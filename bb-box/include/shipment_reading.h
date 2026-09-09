/**
 * BB-Box — Shipment Reading Model
 *
 * Matches BB-Core database schema (ShipmentReading in models/database.py):
 *   - t_core: core compartment temperature (TMP117 #1)
 *   - t_shell: shell/transport environment temperature (TMP117 #2)
 *   - lid_open: reed switch state
 *   - shock_g: LIS3DH peak acceleration
 *   - timestamp: RTC DS3231 accurate time
 */

#ifndef BBBOX_SHIPMENT_READING_H
#define BBBOX_SHIPMENT_READING_H

#include <Arduino.h>
#include "config.h"

// Maximum readings that fit in a batch upload
#define MAX_READING_BATCH BBBOX_UPLOAD_BATCH_SIZE

typedef struct {
    char shipment_id[37];    // UUID string
    char reading_id[37];     // UUID string (generated on device)
    float t_core;            // Core compartment temp (°C) from TMP117 #1
    float t_shell;           // Shell environment temp (°C) from TMP117 #2
    bool  lid_open;           // Reed switch: true = door open
    float shock_g;           // LIS3DH peak shock in g
    unsigned long timestamp; // Unix timestamp from DS3231
    threshold_mode_t mode;   // STORAGE or TRANSPORT thresholds
    alert_level_t alert;     // Current alert level
    char component_code[4];  // WB, RBC, PLT, FFP
} shipment_reading_t;

/**
 * Check if a temperature reading is within threshold.
 * Uses the correct threshold table based on mode (storage vs transport).
 *
 * This is the CRITICAL function that implements Article 20's
 * two-mode threshold system.
 */
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

    // Unknown component — fail safe (out of range)
    return false;
}

/**
 * Classify alert level based on temperature and thresholds.
 */
static inline alert_level_t classify_alert(float core_temp, float shell_temp,
                                           const char* component,
                                           threshold_mode_t mode,
                                           bool door_open,
                                           float shock_g) {
    // Shock detection
    if (shock_g > LIS3DH_SHOCK_THRESHOLD_G) {
        return ALERT_SHOCK;
    }

    // Door open during transport is an alert
    if (door_open && mode == THRESHOLD_MODE_TRANSPORT) {
        return ALERT_DOOR_OPEN;
    }

    // Temperature classification
    if (!temp_in_threshold(core_temp, component, mode)) {
        return ALERT_CRITICAL;
    }

    // Warning: approaching threshold (within 1°C of boundary)
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
            float margin = 1.0f;  // 1°C warning margin
            if (core_temp < thresholds[i].min_temp + margin ||
                core_temp > thresholds[i].max_temp - margin) {
                return ALERT_WARNING;
            }
            break;
        }
    }

    return ALERT_NONE;
}

/**
 * Convert alert level to human-readable string.
 */
static inline const char* alert_level_str(alert_level_t level) {
    switch (level) {
        case ALERT_NONE:     return "OK";
        case ALERT_WARNING:  return "CẢNH BÁO";
        case ALERT_CRITICAL: return "NGUY HIỂM";
        case ALERT_DOOR_OPEN: return "MỞ CỬA";
        case ALERT_SHOCK:    return "SỐC";
        default:             return "???";
    }
}

/**
 * Get RGB color for alert level.
 */
static inline rgb_color_t alert_led_color(alert_level_t level) {
    switch (level) {
        case ALERT_NONE:      return LED_GREEN;
        case ALERT_WARNING:   return LED_AMBER;
        case ALERT_CRITICAL:  return LED_RED;
        case ALERT_DOOR_OPEN: return LED_BLUE;
        case ALERT_SHOCK:     return LED_PURPLE;
        default:               return LED_OFF;
    }
}

#endif // BBBOX_SHIPMENT_READING_H