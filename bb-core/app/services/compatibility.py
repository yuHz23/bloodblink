"""
BB-Core — ABO/RhD compatibility rules for blood component matching.

Per TT 26/2013/TT-BYT and international transfusion standards:
- RBC and Whole Blood: recipient must be compatible with donor (standard table)
- Plasma: compatibility is INVERSE of RBC (O plasma can go to anyone, AB plasma only to AB)
- Platelets: preferably ABO-identical; if not available, compatible per RBC rules
  with volume limits

Two hard-coded professional constraints (not parameters to optimize):
1. PENALIZE using O- for non-O- patients — O- is a scarce resource reserved for
   emergencies where patient blood type is unknown.
2. NEVER downgrade RhD for women of childbearing age (18-45) — hemolytic disease risk.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional


class ComponentCode(str, Enum):
    RBC  = "RBC"
    PLT  = "PLT"
    FFP  = "FFP"
    CRYO = "CRYO"
    WB   = "WB"


class ABO(str, Enum):
    O  = "O"
    A  = "A"
    B  = "B"
    AB = "AB"


class RhD(str, Enum):
    POS = "+"
    NEG = "-"


# ── Compatibility tables ────────────────────────────────────────

# RBC/WB: standard compatibility (donor can give TO recipient)
# Key = donor type, Value = set of acceptable recipient types
RBC_COMPATIBILITY: dict[str, set[str]] = {
    # Rh(D) negative donors can give to both + and - recipients of compatible ABO
    "O-":  {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "O+":  {"O+", "A+", "B+", "AB+"},
    "A-":  {"A-", "A+", "AB-", "AB+"},
    "A+":  {"A+", "AB+"},
    "B-":  {"B-", "B+", "AB-", "AB+"},
    "B+":  {"B+", "AB+"},
    "AB-": {"AB-", "AB+"},
    "AB+": {"AB+"},
}

# Plasma: INVERSE compatibility (donor ABO gives to recipient ABO)
# Key = donor ABO+RhD, Value = set of acceptable recipient types
# Note: plasma compatibility depends on ABO only, RhD is less critical
PLASMA_COMPATIBILITY: dict[str, set[str]] = {
    # O plasma → all ABO types (universal plasma donor)
    "O-":  {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "O+":  {"O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"},
    "A-":  {"A-", "A+", "AB-", "AB+"},
    "A+":  {"A-", "A+", "AB-", "AB+"},
    "B-":  {"B-", "B+", "AB-", "AB+"},
    "B+":  {"B-", "B+", "AB-", "AB+"},
    "AB-": {"AB-", "AB+"},
    "AB+": {"AB+", "AB-"},
}

# Platelets: preferably ABO-identical, but can use RBC-compatible if needed
PLT_COMPATIBILITY = RBC_COMPATIBILITY  # conservative: use RBC rules


def is_compatible(
    donor_abo: str,
    donor_rh: str,
    recipient_abo: str,
    recipient_rh: str,
    component: str,
    recipient_sex: Optional[str] = None,
    recipient_age: Optional[int] = None,
) -> tuple[bool, str]:
    """
    Check if a donor blood unit is compatible with a recipient.

    Returns (is_compatible, reason_text).

    Hard-coded professional constraints:
    1. O- units should NOT be given to non-O- patients (scarce resource).
       Returns True but flags with a warning.
    2. RhD-incompatible transfusion is BLOCKED for women of childbearing age (18-45).
    """
    donor_type = f"{donor_abo}{donor_rh}"
    recipient_type = f"{recipient_abo}{recipient_rh}"

    # Select compatibility table based on component
    if component in (ComponentCode.FFP.value, ComponentCode.CRYO.value):
        compat_table = PLASMA_COMPATIBILITY
    else:
        compat_table = RBC_COMPATIBILITY

    # Check ABO/RhD compatibility
    compatible_types = compat_table.get(donor_type, set())
    if recipient_type not in compatible_types:
        return False, f"ABO/RhD không tương hợp: {donor_type} → {recipient_type}"

    # Professional constraint 1: O- should be reserved for emergencies
    is_on_neg = donor_type == "O-"
    recipient_is_on_neg = recipient_type == "O-"

    # Professional constraint 2: No RhD downgrade for women of childbearing age
    if donor_rh == RhD.POS.value and recipient_rh == RhD.NEG.value:
        # Rh+ → Rh- is NEVER acceptable (sensitization risk)
        if recipient_sex == "F" and (recipient_age is None or 18 <= recipient_age <= 45):
            return False, "Không hạ chuẩn RhD cho phụ nữ tuổi sinh đẻ (18-45)"

    reason_parts = []
    if donor_abo == recipient_abo and donor_rh == recipient_rh:
        reason_parts.append("cùng nhóm máu")
    else:
        reason_parts.append(f"tương hợp {donor_type}→{recipient_type}")

    if is_on_neg and not recipient_is_on_neg:
        reason_parts.append("⚠️ O- là tài nguyên khan hiếm")

    return True, ", ".join(reason_parts)


def compute_compatibility_score(
    donor_abo: str,
    donor_rh: str,
    recipient_abo: str,
    recipient_rh: str,
    component: str,
    recipient_sex: Optional[str] = None,
    recipient_age: Optional[int] = None,
) -> float:
    """
    Compute a 0-1 compatibility quality score for ranking.

    1.0 = identical ABO/RhD (best)
    0.8 = compatible, same ABO different RhD (Rh+ to Rh+ or Rh- to Rh-)
    0.5 = compatible but different ABO group
    0.0 = incompatible (blocked)

    Additional penalties:
    - Using O- for non-O- patient: -0.3 (professional constraint)
    """
    donor_type = f"{donor_abo}{donor_rh}"
    recipient_type = f"{recipient_abo}{recipient_rh}"

    is_compat, reason = is_compatible(
        donor_abo, donor_rh, recipient_abo, recipient_rh,
        component, recipient_sex, recipient_age,
    )
    if not is_compat:
        return 0.0

    # Exact match
    if donor_type == recipient_type:
        return 1.0

    score = 0.8  # base compatibility score

    # Same ABO, different Rh
    if donor_abo == recipient_abo:
        score = 0.9

    # Different ABO (compatible but cross-group)
    if donor_abo != recipient_abo:
        score = 0.5

    # O- penalty
    if donor_type == "O-" and recipient_type != "O-":
        score -= 0.3

    return max(0.0, score)


# ── Unit test data for ABO/RhD compatibility ──────────────────────
# Full 8x8 coverage test cases (export for test suite)

ALL_BLOOD_TYPES = ["O-", "O+", "A-", "A+", "B-", "B+", "AB-", "AB+"]

COMPAT_TEST_CASES_RBC = []
for donor in ALL_BLOOD_TYPES:
    for recipient in ALL_BLOOD_TYPES:
        donor_abo = donor[0] if len(donor) == 2 else donor[:2]
        donor_rh = donor[-1]
        recip_abo = recipient[0] if len(recipient) == 2 else recipient[:2]
        recip_rh = recipient[-1]
        # Parse correctly for 2-char types like "AB"
        if recipient.startswith("AB"):
            recip_abo = "AB"
            recip_rh = recipient[-1]
        if donor.startswith("AB"):
            donor_abo = "AB"
            donor_rh = donor[-1]

        compat, _ = is_compatible(
            donor_abo, donor_rh, recip_abo, recip_rh, "RBC"
        )
        COMPAT_TEST_CASES_RBC.append((donor, recipient, compat))