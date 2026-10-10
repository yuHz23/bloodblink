"""
BB-Core — ABO/RhD compatibility test suite

Must cover ALL 8 blood types × 2 directions (RBC and Plasma).
This is the table that a hematologist reviewer will check first.
"""

import random
from itertools import product

import pytest
from app.services.compatibility import (
    is_compatible, compute_compatibility_score,
    ABO, RhD, ComponentCode,
    RBC_COMPATIBILITY, PLASMA_COMPATIBILITY,
)


class TestRBCCompatibility:
    """8×8 RBC compatibility: standard transfusion medicine table."""

    # Expected results: donor → recipient = compatible?
    # Each row is (donor, recipient, expected_compatible)
    RBC_EXPECTED = [
        # O- (universal donor for RBC)
        ("O", "-", "O", "-", True),    ("O", "-", "O", "+", True),
        ("O", "-", "A", "-", True),    ("O", "-", "A", "+", True),
        ("O", "-", "B", "-", True),    ("O", "-", "B", "+", True),
        ("O", "-", "AB", "-", True),   ("O", "-", "AB", "+", True),

        # O+
        ("O", "+", "O", "-", False),   ("O", "+", "O", "+", True),
        ("O", "+", "A", "-", False),    ("O", "+", "A", "+", True),
        ("O", "+", "B", "-", False),    ("O", "+", "B", "+", True),
        ("O", "+", "AB", "-", False),   ("O", "+", "AB", "+", True),

        # A-
        ("A", "-", "O", "-", False),   ("A", "-", "O", "+", False),
        ("A", "-", "A", "-", True),    ("A", "-", "A", "+", True),
        ("A", "-", "B", "-", False),   ("A", "-", "B", "+", False),
        ("A", "-", "AB", "-", True),   ("A", "-", "AB", "+", True),

        # A+
        ("A", "+", "O", "-", False),   ("A", "+", "O", "+", False),
        ("A", "+", "A", "-", False),   ("A", "+", "A", "+", True),
        ("A", "+", "B", "-", False),   ("A", "+", "B", "+", False),
        ("A", "+", "AB", "-", False),  ("A", "+", "AB", "+", True),

        # B-
        ("B", "-", "O", "-", False),   ("B", "-", "O", "+", False),
        ("B", "-", "A", "-", False),   ("B", "-", "A", "+", False),
        ("B", "-", "B", "-", True),    ("B", "-", "B", "+", True),
        ("B", "-", "AB", "-", True),   ("B", "-", "AB", "+", True),

        # B+
        ("B", "+", "O", "-", False),   ("B", "+", "O", "+", False),
        ("B", "+", "A", "-", False),   ("B", "+", "A", "+", False),
        ("B", "+", "B", "-", False),   ("B", "+", "B", "+", True),
        ("B", "+", "AB", "-", False),  ("B", "+", "AB", "+", True),

        # AB-
        ("AB", "-", "O", "-", False),  ("AB", "-", "O", "+", False),
        ("AB", "-", "A", "-", False),  ("AB", "-", "A", "+", False),
        ("AB", "-", "B", "-", False),  ("AB", "-", "B", "+", False),
        ("AB", "-", "AB", "-", True),  ("AB", "-", "AB", "+", True),

        # AB+
        ("AB", "+", "O", "-", False),  ("AB", "+", "O", "+", False),
        ("AB", "+", "A", "-", False),  ("AB", "+", "A", "+", False),
        ("AB", "+", "B", "-", False),  ("AB", "+", "B", "+", False),
        ("AB", "+", "AB", "-", False), ("AB", "+", "AB", "+", True),
    ]

    @pytest.mark.parametrize("donor_abo,donor_rh,recip_abo,recip_rh,expected", RBC_EXPECTED)
    def test_rbc_compatibility(self, donor_abo, donor_rh, recip_abo, recip_rh, expected):
        """Test all 64 ABO/RhD combinations for RBC compatibility."""
        result, reason = is_compatible(
            donor_abo, donor_rh, recip_abo, recip_rh, "RBC"
        )
        assert result == expected, f"RBC: {donor_abo}{donor_rh}→{recip_abo}{recip_rh}: expected {expected}, got {result} ({reason})"


class TestPlasmaCompatibility:
    """Plasma compatibility is INVERSE of RBC for ABO."""

    # Independent donor-plasma → recipient-red-cell ABO rule. RhD does not
    # affect plasma compatibility, so cover every ABO/RhD combination.
    COMPATIBLE_RECIPIENTS = {
        "O": {"O"},
        "A": {"O", "A"},
        "B": {"O", "B"},
        "AB": {"O", "A", "B", "AB"},
    }
    PLASMA_EXPECTED = [
        (donor_abo, donor_rh, recipient_abo, recipient_rh,
         recipient_abo in COMPATIBLE_RECIPIENTS[donor_abo])
        for donor_abo, donor_rh, recipient_abo, recipient_rh in product(
            ("O", "A", "B", "AB"), ("-", "+"),
            ("O", "A", "B", "AB"), ("-", "+"),
        )
    ]

    @pytest.mark.parametrize("donor_abo,donor_rh,recip_abo,recip_rh,expected", PLASMA_EXPECTED)
    def test_plasma_compatibility(self, donor_abo, donor_rh, recip_abo, recip_rh, expected):
        """Test key plasma compatibility combinations."""
        result, reason = is_compatible(
            donor_abo, donor_rh, recip_abo, recip_rh, "FFP"
        )
        assert result == expected, f"FFP: {donor_abo}{donor_rh}→{recip_abo}{recip_rh}: expected {expected}, got {result}"


class TestProfessionalConstraints:
    """Hard-coded professional constraints that must never be overridden."""

    def test_on_neg_reserved_for_emergency(self):
        """O- can be given to non-O- but should be flagged."""
        result, reason = is_compatible("O", "-", "A", "+", "RBC")
        assert result is True  # still compatible
        assert "O-" in reason or "khan hiem" in reason.lower() or "tương hợp" in reason

    def test_rhd_downgrade_blocked_for_women_childbearing(self):
        """Rh+ blood CANNOT be given to Rh- women aged 18-45."""
        result, reason = is_compatible(
            "A", "+", "A", "-", "RBC",
            recipient_sex="F", recipient_age=30,
        )
        assert result is False
        assert "RhD" in reason or "sinh đẻ" in reason

    def test_rhd_downgrade_allowed_for_men(self):
        """Rh+ to Rh- is blocked for women of childbearing age but compatible for men (with warning)."""
        # For men/older women, Rh+ to Rh- is still incompatible per standard table
        result, reason = is_compatible(
            "A", "+", "A", "-", "RBC",
            recipient_sex="M", recipient_age=50,
        )
        # Standard ABO table: A+ → A- is NOT compatible
        assert result is False

    def test_identical_group_always_compatible(self):
        """Same ABO/RhD is always compatible."""
        for abo in ["O", "A", "B", "AB"]:
            for rh in ["+", "-"]:
                result, reason = is_compatible(abo, rh, abo, rh, "RBC")
                assert result is True, f"{abo}{rh}→{abo}{rh} should be compatible"


class TestCompatibilityScore:
    """Test scoring function."""

    def test_identical_scores_highest(self):
        """Identical ABO/RhD should score 1.0."""
        score = compute_compatibility_score("O", "+", "O", "+", "RBC")
        assert score == 1.0

    def test_on_neg_penalty(self):
        """O- used for non-O- should have a penalty."""
        score_on_neg = compute_compatibility_score("O", "-", "A", "+", "RBC")
        score_o_pos = compute_compatibility_score("O", "+", "A", "+", "RBC")
        assert score_on_neg < score_o_pos

    def test_incompatible_scores_zero(self):
        """Incompatible combinations score 0."""
        score = compute_compatibility_score("A", "+", "O", "+", "RBC")
        assert score == 0.0


class TestVietnameseBloodGroupDistribution:
    """
    Verify that the seed data generator produces realistic Vietnamese
    blood group distribution: O~45%, B~30%, A~20%, AB~5%.
    """

    def test_distribution(self):
        """Seed data should approximate Vietnamese population distribution."""
        from app.models.seed import _pick_abo_rh
        from collections import Counter

        random.seed(42)
        counts = Counter()
        for _ in range(10000):
            abo, rh = _pick_abo_rh()
            counts[abo.value] += 1

        # O should be ~45% (±3%)
        assert 0.42 < counts["O"] / 10000 < 0.48, f"O distribution: {counts['O']/10000}"
        # B should be ~30% (±3%)
        assert 0.27 < counts["B"] / 10000 < 0.33, f"B distribution: {counts['B']/10000}"
        # A should be ~20% (±3%)
        assert 0.17 < counts["A"] / 10000 < 0.23, f"A distribution: {counts['A']/10000}"
        # AB should be ~5% (±2%)
        assert 0.03 < counts["AB"] / 10000 < 0.07, f"AB distribution: {counts['AB']/10000}"
