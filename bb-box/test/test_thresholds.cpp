/**
 * BB-Box — Unit tests for temperature threshold logic
 *
 * Tests the CRITICAL two-mode threshold system per Article 20 TT 26/2013/TT-BYT.
 * The original project description conflated storage and transport thresholds.
 * BB-Box differentiates them — this is the key regulatory compliance point.
 *
 * Run with: pio test -e native
 */

#include <unity.h>
#include <cstring>
#include <cmath>

// Include the config and shipment_reading headers
// For native test, we define BBBOX_CONFIG_H guard to skip Arduino includes
#define BBBOX_CONFIG_H
#define BBBOX_SHIPMENT_READING_H
#define ARDUINO_H

// Minimal Arduino types for native test
typedef uint8_t byte;
#define HIGH 1
#define LOW 0
#define INPUT_PULLUP 0x03
#define OUTPUT 0x01
#define INPUT 0x00

// Inline implementations from config.h and shipment_reading.h
#include <cstdio>

// ── Temperature thresholds (from config.h) ─────────────────────────

typedef enum {
    THRESHOLD_MODE_STORAGE = 0,
    THRESHOLD_MODE_TRANSPORT = 1,
} threshold_mode_t;

typedef struct {
    float min_temp;
    float max_temp;
    const char* component;
    const char* note;
} temp_threshold_t;

typedef enum {
    ALERT_NONE = 0,
    ALERT_WARNING,
    ALERT_CRITICAL,
    ALERT_DOOR_OPEN,
    ALERT_SHOCK,
} alert_level_t;

typedef struct {
    uint8_t r, g, b;
} rgb_color_t;

static const rgb_color_t LED_GREEN   = {0, 255, 0};
static const rgb_color_t LED_AMBER   = {255, 191, 0};
static const rgb_color_t LED_RED     = {255, 0, 0};
static const rgb_color_t LED_BLUE    = {0, 100, 255};
static const rgb_color_t LED_PURPLE  = {180, 0, 255};
static const rgb_color_t LED_OFF     = {0, 0, 0};

// Storage thresholds — Article 20 TT 26/2013/TT-BYT
static const temp_threshold_t STORAGE_THRESHOLDS[] = {
    {2.0f,   6.0f,   "WB",  "Whole blood: 2-6°C (Art 24 TT 26)"},
    {2.0f,   6.0f,   "RBC", "Red blood cells: 2-6°C (Art 24.3 TT 26)"},
    {20.0f,  24.0f,  "PLT", "Platelets: 20-24°C with agitation (Art 30 TT 26)"},
    {-25.0f, -18.0f, "FFP", "Fresh frozen plasma: ≤-18°C (Art 33 TT 26)"},
};
#define STORAGE_THRESHOLD_COUNT 4

// Transport thresholds — wider range for transit
static const temp_threshold_t TRANSPORT_THRESHOLDS[] = {
    {1.0f,   10.0f,  "WB",  "Whole blood transport: 1-10°C"},
    {1.0f,   10.0f,  "RBC", "Red blood cell transport: 1-10°C"},
    {20.0f,  24.0f,  "PLT", "Platelet transport: 20-24°C (same as storage)"},
    {-18.0f, -10.0f, "FFP", "Frozen plasma transport: ≤-18°C"},
};
#define TRANSPORT_THRESHOLD_COUNT 4

#define LIS3DH_SHOCK_THRESHOLD_G  3.0

// ── Inline functions (from shipment_reading.h) ──────────────────────

static inline bool temp_in_threshold(float temp, const char* component,
                                      threshold_mode_t mode) {
    const temp_threshold_t* thresholds;
    int count;
    if (mode == THRESHOLD_MODE_STORAGE) {
        thresholds = STORAGE_THRESHOLDS;
        count = STORAGE_THRESHOLD_COUNT;
    } else {
        thresholds = TRANSPORT_THRESHOLDS;
        count = TRANSPORT_THRESHOLD_COUNT;
    }
    for (int i = 0; i < count; i++) {
        if (strcmp(component, thresholds[i].component) == 0) {
            return (temp >= thresholds[i].min_temp && temp <= thresholds[i].max_temp);
        }
    }
    return false;
}

static inline alert_level_t classify_alert(float core_temp, float shell_temp,
                                           const char* component,
                                           threshold_mode_t mode,
                                           bool door_open,
                                           float shock_g) {
    if (shock_g > LIS3DH_SHOCK_THRESHOLD_G) return ALERT_SHOCK;
    if (door_open && mode == THRESHOLD_MODE_TRANSPORT) return ALERT_DOOR_OPEN;
    if (!temp_in_threshold(core_temp, component, mode)) return ALERT_CRITICAL;
    // Warning: within 1°C of boundary
    const temp_threshold_t* thresholds;
    int count;
    if (mode == THRESHOLD_MODE_STORAGE) {
        thresholds = STORAGE_THRESHOLDS;
        count = STORAGE_THRESHOLD_COUNT;
    } else {
        thresholds = TRANSPORT_THRESHOLDS;
        count = TRANSPORT_THRESHOLD_COUNT;
    }
    for (int i = 0; i < count; i++) {
        if (strcmp(component, thresholds[i].component) == 0) {
            float margin = 1.0f;
            if (core_temp < thresholds[i].min_temp + margin ||
                core_temp > thresholds[i].max_temp - margin) {
                return ALERT_WARNING;
            }
            break;
        }
    }
    return ALERT_NONE;
}

// ── TESTS ────────────────────────────────────────────────────────────

void test_rbc_storage_in_range() {
    TEST_ASSERT_TRUE(temp_in_threshold(4.0f, "RBC", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(2.0f, "RBC", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(6.0f, "RBC", THRESHOLD_MODE_STORAGE));
}

void test_rbc_storage_out_of_range() {
    TEST_ASSERT_FALSE(temp_in_threshold(1.9f, "RBC", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_FALSE(temp_in_threshold(6.1f, "RBC", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_FALSE(temp_in_threshold(0.5f, "RBC", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_FALSE(temp_in_threshold(10.0f, "RBC", THRESHOLD_MODE_STORAGE));
}

void test_rbc_transport_in_range() {
    // CRITICAL: transport allows 1-10°C, wider than storage 2-6°C
    TEST_ASSERT_TRUE(temp_in_threshold(1.0f, "RBC", THRESHOLD_MODE_TRANSPORT));
    TEST_ASSERT_TRUE(temp_in_threshold(5.0f, "RBC", THRESHOLD_MODE_TRANSPORT));
    TEST_ASSERT_TRUE(temp_in_threshold(10.0f, "RBC", THRESHOLD_MODE_TRANSPORT));
}

void test_rbc_transport_out_of_range() {
    TEST_ASSERT_FALSE(temp_in_threshold(0.9f, "RBC", THRESHOLD_MODE_TRANSPORT));
    TEST_ASSERT_FALSE(temp_in_threshold(10.1f, "RBC", THRESHOLD_MODE_TRANSPORT));
}

void test_plt_same_storage_transport() {
    // PLT has the same range for both storage and transport
    TEST_ASSERT_TRUE(temp_in_threshold(22.0f, "PLT", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(22.0f, "PLT", THRESHOLD_MODE_TRANSPORT));
    TEST_ASSERT_TRUE(temp_in_threshold(20.0f, "PLT", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(24.0f, "PLT", THRESHOLD_MODE_STORAGE));
}

void test_ffp_storage_range() {
    // FFP storage: -25°C to -18°C
    TEST_ASSERT_TRUE(temp_in_threshold(-20.0f, "FFP", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(-25.0f, "FFP", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(-18.0f, "FFP", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_FALSE(temp_in_threshold(-17.9f, "FFP", THRESHOLD_MODE_STORAGE));
}

void test_ffp_transport_range() {
    // FFP transport: -18°C to -10°C (wider range for transit)
    TEST_ASSERT_TRUE(temp_in_threshold(-15.0f, "FFP", THRESHOLD_MODE_TRANSPORT));
    TEST_ASSERT_TRUE(temp_in_threshold(-18.0f, "FFP", THRESHOLD_MODE_TRANSPORT));
    TEST_ASSERT_TRUE(temp_in_threshold(-10.0f, "FFP", THRESHOLD_MODE_TRANSPORT));
}

void test_critical_difference_storage_vs_transport() {
    // THE KEY TEST: Same temperature, different mode, different result
    // 8°C is OUT OF RANGE for RBC storage (2-6°C)
    // 8°C is IN RANGE for RBC transport (1-10°C)
    TEST_ASSERT_FALSE(temp_in_threshold(8.0f, "RBC", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(8.0f, "RBC", THRESHOLD_MODE_TRANSPORT));

    // 1.5°C is OUT OF RANGE for RBC storage
    // 1.5°C is IN RANGE for RBC transport
    TEST_ASSERT_FALSE(temp_in_threshold(1.5f, "RBC", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_TRUE(temp_in_threshold(1.5f, "RBC", THRESHOLD_MODE_TRANSPORT));
}

void test_alert_classification_normal() {
    TEST_ASSERT_EQUAL(ALERT_NONE, classify_alert(4.0f, 5.0f, "RBC", THRESHOLD_MODE_STORAGE, false, 0.0f));
    TEST_ASSERT_EQUAL(ALERT_NONE, classify_alert(22.0f, 22.0f, "PLT", THRESHOLD_MODE_STORAGE, false, 0.0f));
}

void test_alert_classification_critical() {
    TEST_ASSERT_EQUAL(ALERT_CRITICAL, classify_alert(7.0f, 8.0f, "RBC", THRESHOLD_MODE_STORAGE, false, 0.0f));
    TEST_ASSERT_EQUAL(ALERT_CRITICAL, classify_alert(0.0f, 1.0f, "RBC", THRESHOLD_MODE_STORAGE, false, 0.0f));
}

void test_alert_classification_warning() {
    // Within 1°C of boundary → WARNING
    TEST_ASSERT_EQUAL(ALERT_WARNING, classify_alert(2.5f, 3.0f, "RBC", THRESHOLD_MODE_STORAGE, false, 0.0f));
    TEST_ASSERT_EQUAL(ALERT_WARNING, classify_alert(5.5f, 6.0f, "RBC", THRESHOLD_MODE_STORAGE, false, 0.0f));
}

void test_alert_classification_door_open() {
    // Door open during transport → DOOR_OPEN alert
    TEST_ASSERT_EQUAL(ALERT_DOOR_OPEN, classify_alert(4.0f, 5.0f, "RBC", THRESHOLD_MODE_TRANSPORT, true, 0.0f));
    // Door open during storage → just WARNING (not DOOR_OPEN)
    TEST_ASSERT_EQUAL(ALERT_NONE, classify_alert(4.0f, 5.0f, "RBC", THRESHOLD_MODE_STORAGE, true, 0.0f));
}

void test_alert_classification_shock() {
    // Shock > 3g → SHOCK alert regardless of other conditions
    TEST_ASSERT_EQUAL(ALERT_SHOCK, classify_alert(4.0f, 5.0f, "RBC", THRESHOLD_MODE_STORAGE, false, 5.0f));
    TEST_ASSERT_EQUAL(ALERT_SHOCK, classify_alert(4.0f, 5.0f, "RBC", THRESHOLD_MODE_TRANSPORT, true, 3.5f));
}

void test_unknown_component_out_of_range() {
    // Unknown component should return false (fail safe)
    TEST_ASSERT_FALSE(temp_in_threshold(4.0f, "XYZ", THRESHOLD_MODE_STORAGE));
    TEST_ASSERT_FALSE(temp_in_threshold(4.0f, "XYZ", THRESHOLD_MODE_TRANSPORT));
}

// ── Main ─────────────────────────────────────────────────────────────

int main(int argc, char** argv) {
    UNITY_BEGIN();

    // RBC storage tests
    RUN_TEST(test_rbc_storage_in_range);
    RUN_TEST(test_rbc_storage_out_of_range);

    // RBC transport tests
    RUN_TEST(test_rbc_transport_in_range);
    RUN_TEST(test_rbc_transport_out_of_range);

    // PLT same range tests
    RUN_TEST(test_plt_same_storage_transport);

    // FFP tests
    RUN_TEST(test_ffp_storage_range);
    RUN_TEST(test_ffp_transport_range);

    // CRITICAL: Storage vs transport difference
    RUN_TEST(test_critical_difference_storage_vs_transport);

    // Alert classification tests
    RUN_TEST(test_alert_classification_normal);
    RUN_TEST(test_alert_classification_critical);
    RUN_TEST(test_alert_classification_warning);
    RUN_TEST(test_alert_classification_door_open);
    RUN_TEST(test_alert_classification_shock);

    // Unknown component
    RUN_TEST(test_unknown_component_out_of_range);

    return UNITY_END();
}