/**
 * BB-Box — Configuration and threshold definitions
 *
 * CRITICAL: Two temperature threshold modes per Article 20 TT 26/2013/TT-BYT
 * - Storage mode: stricter thresholds for blood bank storage
 * - Transport mode: wider thresholds for transit
 *
 * The original project description conflated these. BB-Box differentiates.
 */

#ifndef BBBOX_CONFIG_H
#define BBBOX_CONFIG_H

#include <Arduino.h>

// ── Version ────────────────────────────────────────────────────────
#define BBBOX_VERSION "0.10.0"

// ── WiFi Configuration ─────────────────────────────────────────────
#define BBBOX_WIFI_SSID     "BLOODBLINK-BOX"
#define BBBOX_WIFI_PASSWORD "bbbox2026"
#define BBBOX_API_URL        "http://10.0.2.2:8000/api"
#define BBBOX_UPLOAD_INTERVAL_MS  30000  // Upload readings every 30 seconds

// ── Sensor Pins ─────────────────────────────────────────────────────
#ifndef I2C1_SDA
#define I2C1_SDA   8
#define I2C1_SCL   9
#endif

#ifndef I2C0_SDA
#define I2C0_SDA   18
#define I2C0_SCL   17
#endif

#ifndef REED_PIN
#define REED_PIN   4
#endif

#ifndef LIS3DH_INT1_PIN
#define LIS3DH_INT1_PIN  5
#endif

#ifndef SPI_CS_PIN
#define SPI_CS_PIN   10
#define SPI_CLK_PIN  12
#define SPI_MOSI_PIN 11
#define SPI_MISO_PIN 13
#endif

#ifndef LED_R_PIN
#define LED_R_PIN  2
#define LED_G_PIN  15
#define LED_B_PIN  16
#endif

#ifndef BUZZER_PIN
#define BUZZER_PIN 21
#endif

// ── TMP117 I2C Addresses ───────────────────────────────────────────
#define TMP117_CORE_ADDR   0x48  // A0=GND → 0x48 (core sensor)
#define TMP117_SHELL_ADDR  0x49  // A0=VCC → 0x49 (shell sensor)

// ── LIS3DH Configuration ────────────────────────────────────────────
#define LIS3DH_ADDR        0x18  // SDO=GND
#define LIS3DH_SHOCK_THRESHOLD_G  3.0  // Alert if > 3g shock
#define LIS3DH_SHOCK_DURATION_MS  50  // Must last > 50ms

// ── Reed Switch (Door Open) ────────────────────────────────────────
#define REED_DEBOUNCE_MS   200   // Debounce period

// ── Logging ─────────────────────────────────────────────────────────
#define BBBOX_LOG_INTERVAL_MS   5000   // Log reading every 5 seconds
#define BBBOX_UPLOAD_BATCH_SIZE  50     // Max readings per batch upload

// ── Alert Thresholds ────────────────────────────────────────────────
// Number of consecutive out-of-range readings before alert
#define BBBOX_ALERT_COUNT        3
// Duration (ms) to keep alert LED on
#define BBBOX_ALERT_LED_DURATION_MS  5000

// ── W25Q Flash ──────────────────────────────────────────────────────
#define W25Q_SECTOR_SIZE    4096
#define W25Q_PAGE_SIZE      256
#define W25Q_TOTAL_SECTORS  4096  // 16 MB

// ── Temperature Threshold Mode ─────────────────────────────────────

typedef enum {
    THRESHOLD_MODE_STORAGE = 0,  // Stricter: blood bank storage
    THRESHOLD_MODE_TRANSPORT = 1, // Wider: during transit
} threshold_mode_t;

/**
 * Temperature thresholds per Article 20 TT 26/2013/TT-BYT.
 *
 * STORAGE: strict range for long-term storage in blood bank
 * TRANSPORT: wider range allowing brief excursions during transit
 *
 * The original project description had these conflated. BB-Box separates them.
 */
typedef struct {
    float min_temp;    // Minimum temperature (°C)
    float max_temp;    // Maximum temperature (°C)
    const char* component;  // Component code
    const char* note;       // Regulatory reference
} temp_threshold_t;

// Storage thresholds — for blood bank refrigerator/freezer
static const temp_threshold_t STORAGE_THRESHOLDS[] = {
    {2.0f,   6.0f,   "WB",  "Whole blood: 2–6°C (Art 24 TT 26)"},
    {2.0f,   6.0f,   "RBC", "Red blood cells: 2–6°C (Art 24.3 TT 26)"},
    {20.0f,  24.0f,  "PLT", "Platelets: 20–24°C with agitation (Art 30 TT 26)"},
    {-25.0f, -18.0f, "FFP", "Fresh frozen plasma: ≤−18°C (Art 33 TT 26)"},
};
#define STORAGE_THRESHOLD_COUNT 4

// Transport thresholds — wider range for transit
static const temp_threshold_t TRANSPORT_THRESHOLDS[] = {
    {1.0f,   10.0f,  "WB",  "Whole blood transport: 1–10°C"},
    {1.0f,   10.0f,  "RBC", "Red blood cell transport: 1–10°C"},
    {20.0f,  24.0f,  "PLT", "Platelet transport: 20–24°C (same as storage)"},
    {-18.0f, -10.0f, "FFP", "Frozen plasma transport: ≤−18°C"},
};
#define TRANSPORT_THRESHOLD_COUNT 4

// ── Shelf Life (Article 24, 30, 33 TT 26/2013/TT-BYT) ──────────────
static const unsigned long SHELF_LIFE_HOURS[] = {
    42 * 24,    // WB: 42 days → hours
    42 * 24,    // RBC: 42 days → hours
    5 * 24,     // PLT: 5 days → hours
    365 * 24,   // FFP: 12 months → hours (conservative)
};
#define SHELF_LIFE_COUNT 4

// ── Component Codes ────────────────────────────────────────────────
#define COMPONENT_WB  "WB"
#define COMPONENT_RBC "RBC"
#define COMPONENT_PLT "PLT"
#define COMPONENT_FFP "FFP"

// ── Alert Level ─────────────────────────────────────────────────────
typedef enum {
    ALERT_NONE = 0,
    ALERT_WARNING,    // Temperature approaching threshold
    ALERT_CRITICAL,   // Temperature outside threshold
    ALERT_DOOR_OPEN,  // Door opened during transport
    ALERT_SHOCK,       // Shock detected above threshold
} alert_level_t;

// ── RGB LED Colors ──────────────────────────────────────────────────
typedef struct {
    uint8_t r, g, b;
} rgb_color_t;

static const rgb_color_t LED_GREEN   = {0, 255, 0};    // Normal
static const rgb_color_t LED_AMBER   = {255, 191, 0};   // Warning
static const rgb_color_t LED_RED     = {255, 0, 0};     // Critical
static const rgb_color_t LED_BLUE   = {0, 100, 255};    // Door open
static const rgb_color_t LED_PURPLE  = {180, 0, 255};    // Shock
static const rgb_color_t LED_OFF     = {0, 0, 0};

#endif // BBBOX_CONFIG_H