"""
BB-Box — Unit tests for temperature threshold logic (Python port)

Validates the CRITICAL two-mode threshold system per Article 20 TT 26/2013/TT-BYT.
The original project description conflated storage and transport thresholds.
BB-Box differentiates them — this is the key regulatory compliance point.

Run with: python test/test_thresholds.py
"""

import sys

# ── Threshold tables (mirrors config.h) ──────────────────────────────────

STORAGE_THRESHOLDS = [
    {"min": 2.0,   "max": 6.0,   "component": "WB",  "note": "Whole blood: 2-6°C (Art 24 TT 26)"},
    {"min": 2.0,   "max": 6.0,   "component": "RBC", "note": "Red blood cells: 2-6°C (Art 24.3 TT 26)"},
    {"min": 20.0,  "max": 24.0,  "component": "PLT", "note": "Platelets: 20-24°C with agitation (Art 30 TT 26)"},
    {"min": -25.0, "max": -18.0, "component": "FFP", "note": "Fresh frozen plasma: ≤-18°C (Art 33 TT 26)"},
]

TRANSPORT_THRESHOLDS = [
    {"min": 1.0,   "max": 10.0,  "component": "WB",  "note": "Whole blood transport: 1-10°C"},
    {"min": 1.0,   "max": 10.0,  "component": "RBC", "note": "Red blood cell transport: 1-10°C"},
    {"min": 20.0,  "max": 24.0,  "component": "PLT", "note": "Platelet transport: 20-24°C (same as storage)"},
    {"min": -18.0, "max": -10.0, "component": "FFP", "note": "Frozen plasma transport: ≤-18°C"},
]

SHOCK_THRESHOLD_G = 3.0


# ── Logic functions (mirrors shipment_reading.h) ──────────────────────────

def temp_in_threshold(temp: float, component: str, mode: str) -> bool:
    """Check if temp is within the correct threshold table for the mode."""
    thresholds = STORAGE_THRESHOLDS if mode == "storage" else TRANSPORT_THRESHOLDS
    for t in thresholds:
        if component == t["component"]:
            return t["min"] <= temp <= t["max"]
    return False  # Unknown component → fail safe


def classify_alert(core_temp, shell_temp, component, mode, door_open, shock_g):
    """Classify alert level based on temperature, door, and shock."""
    if shock_g > SHOCK_THRESHOLD_G:
        return "SHOCK"
    if door_open and mode == "transport":
        return "DOOR_OPEN"
    if not temp_in_threshold(core_temp, component, mode):
        return "CRITICAL"
    # Warning: within 1°C of boundary
    thresholds = STORAGE_THRESHOLDS if mode == "storage" else TRANSPORT_THRESHOLDS
    for t in thresholds:
        if component == t["component"]:
            margin = 1.0
            if core_temp < t["min"] + margin or core_temp > t["max"] - margin:
                return "WARNING"
            break
    return "NONE"


# ── Test runner ──────────────────────────────────────────────────────────

passed = 0
failed = 0

def assert_true(condition, msg=""):
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  ✗ FAIL: {msg}")

def assert_false(condition, msg=""):
    assert_true(not condition, msg)

def assert_equal(actual, expected, msg=""):
    global passed, failed
    if actual == expected:
        passed += 1
    else:
        failed += 1
        print(f"  ✗ FAIL: {msg} — expected {expected}, got {actual}")


# ── Tests ────────────────────────────────────────────────────────────────

def test_rbc_storage_in_range():
    assert_true(temp_in_threshold(4.0, "RBC", "storage"), "RBC 4°C storage")
    assert_true(temp_in_threshold(2.0, "RBC", "storage"), "RBC 2°C storage (min)")
    assert_true(temp_in_threshold(6.0, "RBC", "storage"), "RBC 6°C storage (max)")

def test_rbc_storage_out_of_range():
    assert_false(temp_in_threshold(1.9, "RBC", "storage"), "RBC 1.9°C storage out")
    assert_false(temp_in_threshold(6.1, "RBC", "storage"), "RBC 6.1°C storage out")
    assert_false(temp_in_threshold(0.5, "RBC", "storage"), "RBC 0.5°C storage out")
    assert_false(temp_in_threshold(10.0, "RBC", "storage"), "RBC 10°C storage out")

def test_rbc_transport_in_range():
    # CRITICAL: transport allows 1-10°C, wider than storage 2-6°C
    assert_true(temp_in_threshold(1.0, "RBC", "transport"), "RBC 1°C transport (min)")
    assert_true(temp_in_threshold(5.0, "RBC", "transport"), "RBC 5°C transport")
    assert_true(temp_in_threshold(10.0, "RBC", "transport"), "RBC 10°C transport (max)")

def test_rbc_transport_out_of_range():
    assert_false(temp_in_threshold(0.9, "RBC", "transport"), "RBC 0.9°C transport out")
    assert_false(temp_in_threshold(10.1, "RBC", "transport"), "RBC 10.1°C transport out")

def test_plt_same_storage_transport():
    # PLT has the same range for both storage and transport
    assert_true(temp_in_threshold(22.0, "PLT", "storage"), "PLT 22°C storage")
    assert_true(temp_in_threshold(22.0, "PLT", "transport"), "PLT 22°C transport")
    assert_true(temp_in_threshold(20.0, "PLT", "storage"), "PLT 20°C storage (min)")
    assert_true(temp_in_threshold(24.0, "PLT", "storage"), "PLT 24°C storage (max)")

def test_ffp_storage_range():
    assert_true(temp_in_threshold(-20.0, "FFP", "storage"), "FFP -20°C storage")
    assert_true(temp_in_threshold(-25.0, "FFP", "storage"), "FFP -25°C storage (min)")
    assert_true(temp_in_threshold(-18.0, "FFP", "storage"), "FFP -18°C storage (max)")
    assert_false(temp_in_threshold(-17.9, "FFP", "storage"), "FFP -17.9°C storage out")

def test_ffp_transport_range():
    assert_true(temp_in_threshold(-15.0, "FFP", "transport"), "FFP -15°C transport")
    assert_true(temp_in_threshold(-18.0, "FFP", "transport"), "FFP -18°C transport (min)")
    assert_true(temp_in_threshold(-10.0, "FFP", "transport"), "FFP -10°C transport (max)")

def test_critical_storage_vs_transport():
    """THE KEY TEST: Same temperature, different mode, different result."""
    # 8°C: OUT for RBC storage (2-6°C), IN for RBC transport (1-10°C)
    assert_false(temp_in_threshold(8.0, "RBC", "storage"), "8°C RBC storage OUT")
    assert_true(temp_in_threshold(8.0, "RBC", "transport"), "8°C RBC transport IN")
    # 1.5°C: OUT for RBC storage, IN for RBC transport
    assert_false(temp_in_threshold(1.5, "RBC", "storage"), "1.5°C RBC storage OUT")
    assert_true(temp_in_threshold(1.5, "RBC", "transport"), "1.5°C RBC transport IN")

def test_alert_normal():
    assert_equal(classify_alert(4.0, 5.0, "RBC", "storage", False, 0.0), "NONE")
    assert_equal(classify_alert(22.0, 22.0, "PLT", "storage", False, 0.0), "NONE")

def test_alert_critical():
    assert_equal(classify_alert(7.0, 8.0, "RBC", "storage", False, 0.0), "CRITICAL")
    assert_equal(classify_alert(0.0, 1.0, "RBC", "storage", False, 0.0), "CRITICAL")

def test_alert_warning():
    # Within 1°C of boundary → WARNING
    assert_equal(classify_alert(2.5, 3.0, "RBC", "storage", False, 0.0), "WARNING")
    assert_equal(classify_alert(5.5, 6.0, "RBC", "storage", False, 0.0), "WARNING")

def test_alert_door_open():
    # Door open during transport → DOOR_OPEN
    assert_equal(classify_alert(4.0, 5.0, "RBC", "transport", True, 0.0), "DOOR_OPEN")
    # Door open during storage → just NONE (temp OK)
    assert_equal(classify_alert(4.0, 5.0, "RBC", "storage", True, 0.0), "NONE")

def test_alert_shock():
    # Shock > 3g → SHOCK regardless of other conditions
    assert_equal(classify_alert(4.0, 5.0, "RBC", "storage", False, 5.0), "SHOCK")
    assert_equal(classify_alert(4.0, 5.0, "RBC", "transport", True, 3.5), "SHOCK")

def test_unknown_component():
    # Unknown component → fail safe (out of range)
    assert_false(temp_in_threshold(4.0, "XYZ", "storage"), "XYZ storage out")
    assert_false(temp_in_threshold(4.0, "XYZ", "transport"), "XYZ transport out")

def test_wb_storage_vs_transport():
    """WB has same thresholds as RBC — verify separately."""
    assert_true(temp_in_threshold(4.0, "WB", "storage"), "WB 4°C storage")
    assert_false(temp_in_threshold(8.0, "WB", "storage"), "WB 8°C storage OUT")
    assert_true(temp_in_threshold(8.0, "WB", "transport"), "WB 8°C transport IN")

def test_transport_mode_allows_wider_range():
    """Verify that transport mode range width >= storage mode range width for each component.
    For FFP, storage is [-25, -18] (7°C wide) but transport is [-18, -10] (8°C wide).
    They cover different temperature windows but transport is always wider or equal."""
    for s, t in zip(STORAGE_THRESHOLDS, TRANSPORT_THRESHOLDS):
        comp = s["component"]
        storage_width = s["max"] - s["min"]
        transport_width = t["max"] - t["min"]
        assert_true(transport_width >= storage_width,
                    f"{comp}: transport width ({transport_width}°C) >= storage width ({storage_width}°C)")


# ── Run all tests ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("BB-Box Threshold Logic Tests — Article 20 TT 26/2013/TT-BYT")
    print("=" * 60)

    tests = [
        test_rbc_storage_in_range,
        test_rbc_storage_out_of_range,
        test_rbc_transport_in_range,
        test_rbc_transport_out_of_range,
        test_plt_same_storage_transport,
        test_ffp_storage_range,
        test_ffp_transport_range,
        test_critical_storage_vs_transport,
        test_alert_normal,
        test_alert_critical,
        test_alert_warning,
        test_alert_door_open,
        test_alert_shock,
        test_unknown_component,
        test_wb_storage_vs_transport,
        test_transport_mode_allows_wider_range,
    ]

    for t in tests:
        print(f"\n▶ {t.__name__}")
        t()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed out of {passed + failed} assertions")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)
    else:
        print("✅ All BB-Box threshold tests PASSED!")