/**
 * BB-Box — Main firmware for ESP32-S3 cold chain monitor
 *
 * Architecture:
 *   - FreeRTOS tasks for concurrent sensor reading, WiFi, and logging
 *   - Two TMP117 sensors: core (inside) + shell (outside)
 *   - Article 20 TT 26/2013/TT-BYT: TWO threshold modes (storage vs transport)
 *   - ShipmentReading struct matches BB-Core database schema
 *   - Batch upload via REST API, local flash buffer when offline
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>

#include "config.h"
#include "shipment_reading.h"

// ── Global State ────────────────────────────────────────────────────

static threshold_mode_t g_threshold_mode = THRESHOLD_MODE_STORAGE;
static char g_component_code[4] = "RBC";  // Default to RBC (most common)
static char g_shipment_id[37] = "";
static bool g_wifi_connected = false;
static bool g_door_open = false;
static float g_last_shock_g = 0.0f;

// Reading buffer for batch upload
static shipment_reading_t g_reading_buffer[MAX_READING_BATCH];
static int g_reading_count = 0;

// Consecutive out-of-range counter for alert
static int g_oob_count = 0;
static alert_level_t g_current_alert = ALERT_NONE;

// ── Sensor Handles ───────────────────────────────────────────────────

// TMP117 (will be replaced with actual library object)
static bool g_tmp117_core_ok = false;
static bool g_tmp117_shell_ok = false;

// LIS3DH (will be replaced with actual library object)
static bool g_lis3dh_ok = false;

// ── Task Handles ────────────────────────────────────────────────────

static TaskHandle_t h_sensor_task = nullptr;
static TaskHandle_t h_upload_task = nullptr;
static TaskHandle_t h_led_task = nullptr;

// ── Mutex for shared reading buffer ─────────────────────────────────

static SemaphoreHandle_t g_reading_mutex = nullptr;

// ── Forward Declarations ────────────────────────────────────────────

void sensor_task(void* param);
void upload_task(void* param);
void led_task(void* param);
void reed_switch_isr();
void init_sensors();
void init_wifi();
float read_tmp117(uint8_t addr);
float read_lis3dh_shock();
void update_alert_level(float t_core, float t_shell, bool door_open, float shock_g);
void set_led_color(rgb_color_t color);
bool upload_readings();
void generate_uuid(char* buffer, size_t len);

// ── Setup ───────────────────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    Serial.println("\n=== BB-Box Cold Chain Monitor v" BBBOX_VERSION " ===");
    Serial.println("Article 20 TT 26/2013/TT-BYT: Two threshold modes (storage vs transport)");

    // Create mutex
    g_reading_mutex = xSemaphoreCreateMutex();

    // Initialize I2C buses
    Wire1.begin(I2C1_SDA, I2C1_SCL, 400000);  // Core sensor + LIS3DH + DS3231
    Wire.begin(I2C0_SDA, I2C0_SCL, 400000);     // Shell sensor

    // Initialize SPI for W25Q flash
    SPI.begin(SPI_CLK_PIN, SPI_MISO_PIN, SPI_MOSI_PIN, SPI_CS_PIN);

    // Initialize sensors
    init_sensors();

    // Initialize reed switch interrupt
    pinMode(REED_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(REED_PIN), reed_switch_isr, CHANGE);

    // Initialize LED and buzzer
    pinMode(LED_R_PIN, OUTPUT);
    pinMode(LED_G_PIN, OUTPUT);
    pinMode(LED_B_PIN, OUTPUT);
    pinMode(BUZZER_PIN, OUTPUT);

    // Initialize WiFi
    init_wifi();

    // Generate shipment ID if empty
    if (strlen(g_shipment_id) == 0) {
        generate_uuid(g_shipment_id, sizeof(g_shipment_id));
    }

    // Print threshold info
    Serial.println("\n--- Temperature Thresholds ---");
    Serial.printf("Mode: %s\n", g_threshold_mode == THRESHOLD_MODE_STORAGE ? "BẢO QUẢN (Storage)" : "VẬN CHUYỂN (Transport)");
    const temp_threshold_t* thresholds = g_threshold_mode == THRESHOLD_MODE_STORAGE ? STORAGE_THRESHOLDS : TRANSPORT_THRESHOLDS;
    int count = g_threshold_mode == THRESHOLD_MODE_STORAGE ? STORAGE_THRESHOLD_COUNT : TRANSPORT_THRESHOLD_COUNT;
    for (int i = 0; i < count; i++) {
        Serial.printf("  %s: %.1f°C to %.1f°C (%s)\n",
            thresholds[i].component, thresholds[i].min_temp, thresholds[i].max_temp, thresholds[i].note);
    }
    Serial.println("-------------------------------");

    // Create FreeRTOS tasks
    xTaskCreatePinnedToCore(sensor_task, "sensor", 4096, NULL, 2, &h_sensor_task, 1);
    xTaskCreatePinnedToCore(upload_task, "upload", 8192, NULL, 1, &h_upload_task, 0);
    xTaskCreatePinnedToCore(led_task, "led", 2048, NULL, 1, &h_led_task, 0);

    Serial.println("BB-Box tasks started. Monitoring...");
}

void loop() {
    // Main loop is idle — all work done in FreeRTOS tasks
    vTaskDelay(pdMS_TO_TICKS(1000));
}

// ── Sensor Task ─────────────────────────────────────────────────────

void sensor_task(void* param) {
    TickType_t last_wake = xTaskGetTickCount();
    const TickType_t interval = pdMS_TO_TICKS(BBBOX_LOG_INTERVAL_MS);

    while (true) {
        vTaskDelayUntil(&last_wake, interval);

        // Read temperatures from both TMP117 sensors
        float t_core = read_tmp117(TMP117_CORE_ADDR);
        float t_shell = read_tmp117(TMP117_SHELL_ADDR);

        // Read shock from LIS3DH
        float shock_g = read_lis3dh_shock();

        // Read door state
        bool door_open = g_door_open;

        // Classify alert level using TWO-MODE thresholds
        alert_level_t alert = classify_alert(
            t_core, t_shell, g_component_code, g_threshold_mode, door_open, shock_g
        );

        // Store reading in buffer
        if (xSemaphoreTake(g_reading_mutex, pdMS_TO_TICKS(100))) {
            if (g_reading_count < MAX_READING_BATCH) {
                shipment_reading_t* r = &g_reading_buffer[g_reading_count++];
                strncpy(r->shipment_id, g_shipment_id, sizeof(r->shipment_id));
                generate_uuid(r->reading_id, sizeof(r->reading_id));
                r->t_core = t_core;
                r->t_shell = t_shell;
                r->lid_open = door_open;
                r->shock_g = shock_g;
                r->timestamp = millis() / 1000;  // Simplified — use DS3231 in production
                r->mode = g_threshold_mode;
                r->alert = alert;
                strncpy(r->component_code, g_component_code, sizeof(r->component_code));
            }
            xSemaphoreGive(g_reading_mutex);
        }

        // Update global alert level
        g_current_alert = alert;
        g_last_shock_g = shock_g;

        // Serial output
        Serial.printf("[SENSOR] Core: %.1f°C | Shell: %.1f°C | Door: %s | Shock: %.1fg | Alert: %s\n",
            t_core, t_shell, door_open ? "MỞ" : "ĐÓNG", shock_g, alert_level_str(alert));
    }
}

// ── Upload Task ──────────────────────────────────────────────────────

void upload_task(void* param) {
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(BBBOX_UPLOAD_INTERVAL_MS));

        if (!g_wifi_connected) {
            // Try to reconnect
            init_wifi();
            continue;
        }

        // Upload buffered readings
        if (xSemaphoreTake(g_reading_mutex, pdMS_TO_TICKS(1000))) {
            if (g_reading_count > 0) {
                Serial.printf("[UPLOAD] Uploading %d readings...\n", g_reading_count);

                if (upload_readings()) {
                    Serial.println("[UPLOAD] Upload successful");
                    g_reading_count = 0;  // Clear buffer on success
                } else {
                    Serial.println("[UPLOAD] Upload failed — keeping buffer");
                    // Keep readings in buffer, try again next cycle
                    // If buffer is full, log to flash as fallback
                    if (g_reading_count >= MAX_READING_BATCH) {
                        Serial.println("[UPLOAD] Buffer full — would log to W25Q flash in production");
                        g_reading_count = 0;  // Clear to prevent overflow
                    }
                }
            }
            xSemaphoreGive(g_reading_mutex);
        }
    }
}

// ── LED Task ─────────────────────────────────────────────────────────

void led_task(void* param) {
    bool buzzer_on = false;

    while (true) {
        rgb_color_t color = alert_led_color(g_current_alert);
        set_led_color(color);

        // Buzzer for critical alerts
        if (g_current_alert == ALERT_CRITICAL || g_current_alert == ALERT_SHOCK) {
            if (!buzzer_on) {
                tone(BUZZER_PIN, 2000, 200);  // 2 kHz for 200ms
                buzzer_on = true;
            }
            vTaskDelay(pdMS_TO_TICKS(BBBOX_ALERT_LED_DURATION_MS));
            set_led_color(LED_OFF);
            tone(BUZZER_PIN, 0, 0);
            buzzer_on = false;
        } else if (g_current_alert == ALERT_WARNING || g_current_alert == ALERT_DOOR_OPEN) {
            // Slow blink for warning
            vTaskDelay(pdMS_TO_TICKS(2000));
            set_led_color(LED_OFF);
            vTaskDelay(pdMS_TO_TICKS(2000));
        } else {
            // Steady green for normal
            vTaskDelay(pdMS_TO_TICKS(5000));
        }
    }
}

// ── Sensor Initialization ────────────────────────────────────────────

void init_sensors() {
    // TMP117 Core (I²C bus 1, address 0x48)
    Wire1.beginTransmission(TMP117_CORE_ADDR);
    g_tmp117_core_ok = (Wire1.endTransmission() == 0);
    Serial.printf("[INIT] TMP117 Core (0x%02X): %s\n", TMP117_CORE_ADDR, g_tmp117_core_ok ? "OK" : "FAIL");

    // TMP117 Shell (I²C bus 0, address 0x49)
    Wire.beginTransmission(TMP117_SHELL_ADDR);
    g_tmp117_shell_ok = (Wire.endTransmission() == 0);
    Serial.printf("[INIT] TMP117 Shell (0x%02X): %s\n", TMP117_SHELL_ADDR, g_tmp117_shell_ok ? "OK" : "FAIL");

    // LIS3DH (I²C bus 1, address 0x18)
    Wire1.beginTransmission(LIS3DH_ADDR);
    g_lis3dh_ok = (Wire1.endTransmission() == 0);
    Serial.printf("[INIT] LIS3DH (0x%02X): %s\n", LIS3DH_ADDR, g_lis3dh_ok ? "OK" : "FAIL");

    // DS3231 RTC would be initialized here (I²C bus 1, address 0x68)
    // W25Q flash would be initialized here (SPI)
}

// ── WiFi Initialization ─────────────────────────────────────────────

void init_wifi() {
    if (WiFi.status() == WL_CONNECTED) {
        g_wifi_connected = true;
        return;
    }

    Serial.printf("[WIFI] Connecting to %s...\n", BBBOX_WIFI_SSID);
    WiFi.begin(BBBOX_WIFI_SSID, BBBOX_WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        vTaskDelay(pdMS_TO_TICKS(500));
        attempts++;
    }

    g_wifi_connected = (WiFi.status() == WL_CONNECTED);
    if (g_wifi_connected) {
        Serial.printf("[WIFI] Connected! IP: %s\n", WiFi.localIP().toString().c_str());
    } else {
        Serial.println("[WIFI] Connection failed — will retry");
    }
}

// ── TMP117 Reading ──────────────────────────────────────────────────

float read_tmp117(uint8_t addr) {
    // Read temperature register (0x00) from TMP117
    // TMP117 returns temperature in 0.0078125°C resolution (7.8125 m°C/LSB)
    // This is a simplified version — production code uses Adafruit_TMP117 library

    float temp = NAN;

    // Select I2C bus based on address
    TwoWire* bus = (addr == TMP117_SHELL_ADDR) ? &Wire : &Wire1;

    bus->beginTransmission(addr);
    bus->write(0x00);  // Temperature register
    if (bus->endTransmission(false) == 0) {
        if (bus->requestFrom(addr, (uint8_t)2) == 2) {
            uint8_t msb = bus->read();
            uint8_t lsb = bus->read();
            int16_t raw = (msb << 8) | lsb;
            temp = raw * 0.0078125f;  // Convert to °C
        }
    }

    return temp;
}

// ── LIS3DH Shock Reading ───────────────────────────────────────────

float read_lis3dh_shock() {
    // Read acceleration from LIS3DH and calculate shock magnitude
    // Returns peak acceleration in g
    // Simplified — production code uses Adafruit_LIS3DH library

    if (!g_lis3dh_ok) return 0.0f;

    float ax = 0.0f, ay = 0.0f, az = 0.0f;

    // Read X, Y, Z from LIS3DH (0x28-0x2D)
    Wire1.beginTransmission(LIS3DH_ADDR);
    Wire1.write(0x28 | 0x80);  // OUT_X_L with auto-increment
    if (Wire1.endTransmission(false) == 0) {
        if (Wire1.requestFrom(LIS3DH_ADDR, (uint8_t)6) == 6) {
            int16_t x = (Wire1.read() | (Wire1.read() << 8)) >> 4;  // 12-bit left justified
            int16_t y = (Wire1.read() | (Wire1.read() << 8)) >> 4;
            int16_t z = (Wire1.read() | (Wire1.read() << 8)) >> 4;

            // Convert to g (±2g range, sensitivity = 1 mg/digit)
            ax = x * 0.001f;
            ay = y * 0.001f;
            az = z * 0.001f;
        }
    }

    // Calculate shock magnitude
    return sqrtf(ax * ax + ay * ay + az * az);
}

// ── Upload Readings ─────────────────────────────────────────────────

bool upload_readings() {
    HTTPClient http;
    http.begin(String(BBBOX_API_URL) + "/shipment/readings");
    http.addHeader("Content-Type", "application/json");

    // Build JSON array of readings
    JsonDocument doc;
    JsonArray readings = doc.to<JsonArray>();

    for (int i = 0; i < g_reading_count; i++) {
        const shipment_reading_t& r = g_reading_buffer[i];
        JsonObject obj = readings.add<JsonObject>();
        obj["shipment_id"] = r.shipment_id;
        obj["reading_id"] = r.reading_id;
        obj["t_core"] = serialized(String(r.t_core, 2));
        obj["t_shell"] = serialized(String(r.t_shell, 2));
        obj["lid_open"] = r.lid_open;
        obj["shock_g"] = serialized(String(r.shock_g, 2));
        obj["timestamp"] = r.timestamp;
        obj["mode"] = (r.mode == THRESHOLD_MODE_STORAGE) ? "storage" : "transport";
        obj["alert"] = (int)r.alert;
        obj["component_code"] = r.component_code;
    }

    String json;
    serializeJson(doc, json);

    int httpCode = http.POST(json);
    http.end();

    return (httpCode == 200 || httpCode == 201);
}

// ── Reed Switch ISR ──────────────────────────────────────────────────

void IRAM_ATTR reed_switch_isr() {
    static unsigned long last_interrupt = 0;
    unsigned long now = millis();

    if (now - last_interrupt > REED_DEBOUNCE_MS) {
        g_door_open = digitalRead(REED_PIN) == HIGH;
        last_interrupt = now;
    }
}

// ── LED Control ─────────────────────────────────────────────────────

void set_led_color(rgb_color_t color) {
    analogWrite(LED_R_PIN, color.r);
    analogWrite(LED_G_PIN, color.g);
    analogWrite(LED_B_PIN, color.b);
}

// ── UUID Generation ──────────────────────────────────────────────────

void generate_uuid(char* buffer, size_t len) {
    // Simplified UUID v4 generation (use proper RNG in production)
    uint32_t r1 = esp_random();
    uint32_t r2 = esp_random();
    uint32_t r3 = esp_random();
    uint32_t r4 = esp_random();
    snprintf(buffer, len, "%08lx-%04x-4%03x-%04x-%08lx%04x",
        r1,
        (uint16_t)(r2 >> 16),
        (uint16_t)(r2 & 0x0FFF),
        (uint16_t)(r3 >> 16) & 0x3FFF | 0x8000,
        r3 & 0xFFFF | (r4 & 0xFFFF0000),
        r4 & 0xFFFF
    );
}

// ── Mode Switching ──────────────────────────────────────────────────

void set_threshold_mode(threshold_mode_t mode) {
    g_threshold_mode = mode;
    Serial.printf("[MODE] Switched to %s thresholds\n",
        mode == THRESHOLD_MODE_STORAGE ? "BẢO QUẢN (Storage)" : "VẬN CHUYỂN (Transport)");

    const temp_threshold_t* thresholds = mode == THRESHOLD_MODE_STORAGE ? STORAGE_THRESHOLDS : TRANSPORT_THRESHOLDS;
    int count = mode == THRESHOLD_MODE_STORAGE ? STORAGE_THRESHOLD_COUNT : TRANSPORT_THRESHOLD_COUNT;
    for (int i = 0; i < count; i++) {
        Serial.printf("  %s: %.1f°C to %.1f°C\n",
            thresholds[i].component, thresholds[i].min_temp, thresholds[i].max_temp);
    }
}

void set_component(const char* component) {
    strncpy(g_component_code, component, sizeof(g_component_code) - 1);
    g_component_code[sizeof(g_component_code) - 1] = '\0';
    Serial.printf("[COMPONENT] Set to %s\n", g_component_code);
}