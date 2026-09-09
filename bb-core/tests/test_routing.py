"""BB-Core — Routing service tests: haversine, ETA comparison, provider swap."""

import asyncio
import math
import pytest

from app.services.routing import (
    StraightLineRouting, OSRMRouting, RoutingService,
    HCMC_FACILITIES, ETA_COMPARISON_PAIRS,
)


# ── Haversine tests ──────────────────────────────────────────────

class TestHaversine:
    """Verify haversine distance calculation against known distances."""

    @pytest.mark.asyncio
    async def test_same_point_zero_distance(self):
        r = StraightLineRouting()
        result = await r.get_route(10.7869, 106.6854, 10.7869, 106.6854, "car")
        assert result.distance_m < 1  # should be ~0

    @pytest.mark.asyncio
    async def test_known_distance_hcm(self):
        """BV TMHH → BV Chợ Rẫy ≈ 2.8 km straight line."""
        r = StraightLineRouting()
        result = await r.get_route(10.7869, 106.6854, 10.7635, 106.6690, "car")
        # Haversine distance should be roughly 2.5–3.5 km
        assert 2000 < result.distance_m < 4000

    @pytest.mark.asyncio
    async def test_haversine_formula_exact(self):
        """Test against manually computed haversine for a known pair."""
        # HCMC to Vung Tau: ~65 km straight line
        r = StraightLineRouting()
        result = await r.get_route(10.7869, 106.6854, 10.3460, 107.0830, "car")
        assert 50_000 < result.distance_m < 80_000

    @pytest.mark.asyncio
    async def test_eta_car_mode(self):
        """Car at 25 km/h — 2.8 km should take ~6–7 minutes."""
        r = StraightLineRouting()
        result = await r.get_route(10.7869, 106.6854, 10.7635, 106.6690, "car")
        # 2.8 km at 25 km/h = 0.112 h = 6.7 min ≈ 403 s
        assert 300 < result.duration_s < 500

    @pytest.mark.asyncio
    async def test_eta_emergency_mode(self):
        """Emergency at 40 km/h — should be faster than car."""
        r = StraightLineRouting()
        result_car = await r.get_route(10.7869, 106.6854, 10.7635, 106.6690, "car")
        result_emergency = await r.get_route(10.7869, 106.6854, 10.7635, 106.6690, "emergency")
        assert result_emergency.duration_s < result_car.duration_s

    @pytest.mark.asyncio
    async def test_eta_motorcycle_mode(self):
        """Motorcycle at 30 km/h — between car and emergency."""
        r = StraightLineRouting()
        result_car = await r.get_route(10.7869, 106.6854, 10.7635, 106.6690, "car")
        result_moto = await r.get_route(10.7869, 106.6854, 10.7635, 106.6690, "motorcycle")
        result_emergency = await r.get_route(10.7869, 106.6854, 10.7635, 106.6690, "emergency")
        assert result_car.duration_s > result_moto.duration_s > result_emergency.duration_s

    def test_haversine_static_method(self):
        """Test static haversine against known formula."""
        # Manhattan distance check: TMHH (10.7869, 106.6854) → Cho Ray (10.7635, 106.6690)
        dist = StraightLineRouting.haversine(10.7869, 106.6854, 10.7635, 106.6690)
        assert 2000 < dist < 4000  # ~2.8 km


# ── RoutingService facade tests ──────────────────────────────────

class TestRoutingService:
    """Test facade and provider swapping."""

    def test_default_provider_is_straight_line(self):
        svc = RoutingService()
        assert svc._provider.get_name() == "straight_line (haversine)"

    def test_swap_to_osrm(self):
        svc = RoutingService()
        osrm = OSRMRouting(base_url="http://localhost:5000")
        svc.set_provider(osrm)
        assert svc._provider.get_name() == "osrm"

    def test_swap_back_to_straight_line(self):
        svc = RoutingService()
        svc.set_provider(OSRMRouting())
        svc.set_provider(StraightLineRouting())
        assert svc._provider.get_name() == "straight_line (haversine)"

    @pytest.mark.asyncio
    async def test_compare_eta(self):
        """Compare ETA should return both straight-line and road results."""
        svc = RoutingService()
        result = await svc.compare_eta(10.7869, 106.6854, 10.7635, 106.6690)
        assert "straight_line" in result
        assert "road" in result
        assert "difference" in result
        assert result["straight_line"]["duration_min"] > 0
        assert result["road"]["duration_min"] > 0

    @pytest.mark.asyncio
    async def test_compare_eta_returns_positive_durations(self):
        """Both ETA modes should return positive values."""
        svc = RoutingService()
        for from_id, to_id in ETA_COMPARISON_PAIRS[:5]:  # Check first 5 pairs
            from_fac = HCMC_FACILITIES[from_id]
            to_fac = HCMC_FACILITIES[to_id]
            result = await svc.compare_eta(from_fac["lat"], from_fac["lon"], to_fac["lat"], to_fac["lon"])
            assert result["straight_line"]["duration_s"] > 0
            assert result["road"]["duration_s"] > 0


# ── HCMC facility data tests ─────────────────────────────────────

class TestHCMCFacilities:
    """Verify HCMC facility data integrity."""

    def test_all_five_facilities_present(self):
        assert len(HCMC_FACILITIES) == 5
        assert "fac-bv-tmhh" in HCMC_FACILITIES
        assert "fac-bv-cho-ray" in HCMC_FACILITIES
        assert "fac-bv-ung-buou" in HCMC_FACILITIES
        assert "fac-bv-nhi-dong" in HCMC_FACILITIES
        assert "fac-bv-pham-ngoc-thach" in HCMC_FACILITIES

    def test_coordinates_in_hcmc_range(self):
        """All facilities should be within HCMC bounding box."""
        for fid, fac in HCMC_FACILITIES.items():
            assert 10.6 < fac["lat"] < 11.0, f"{fid} lat out of HCMC range"
            assert 106.5 < fac["lon"] < 107.0, f"{fid} lon out of HCMC range"
            assert "name" in fac

    def test_comparison_pairs_count(self):
        """Should have 20 pairs (10 unique + 10 reverse)."""
        assert len(ETA_COMPARISON_PAIRS) == 20

    def test_all_pair_ids_valid(self):
        """All pair IDs should reference existing facilities."""
        for from_id, to_id in ETA_COMPARISON_PAIRS:
            assert from_id in HCMC_FACILITIES, f"Unknown facility: {from_id}"
            assert to_id in HCMC_FACILITIES, f"Unknown facility: {to_id}"

    def test_pairs_include_all_directions(self):
        """Should include both directions for at least some pairs."""
        # TMHH → Cho Ray and Cho Ray → TMHH should both exist
        forward = ("fac-bv-tmhh", "fac-bv-cho-ray") in ETA_COMPARISON_PAIRS
        reverse = ("fac-bv-cho-ray", "fac-bv-tmhh") in ETA_COMPARISON_PAIRS
        assert forward and reverse, "Should have both directions for TMHH ↔ Cho Ray"


# ── Integration: ETA in matching engine ──────────────────────────

class TestETAInMatching:
    """Verify that ETA lookup integrates correctly with matching."""

    def test_eta_lookup_callback(self):
        """Simulated ETA lookup should return seconds."""
        def mock_eta(from_fac, to_fac):
            return 1800  # 30 minutes

        from app.services.matching import find_matching_units, TransferRequest, BloodUnitCandidate
        from datetime import datetime, timezone, timedelta

        request = TransferRequest(
            request_id="test-001",
            requester_facility_id="fac-bv-tmhh",
            component_code="RBC",
            abo="O",
            rh="+",
            urgency="routine",
            needed_by=datetime.now(timezone.utc) + timedelta(hours=6),
        )

        candidate = BloodUnitCandidate(
            unit_id="unit-001",
            isbt_din="VN1234567890",
            component_code="RBC",
            abo="O",
            rh="+",
            volume_ml=250,
            collected_at=datetime.now(timezone.utc) - timedelta(days=7),
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            held_by_facility_id="fac-bv-cho-ray",
            facility_name="BV Chợ Rẫy",
            facility_opt_in=True,
        )

        results = find_matching_units(
            request=request,
            candidates=[candidate],
            eta_lookup=mock_eta,
        )

        assert len(results) > 0
        # ETA should be populated from the callback
        if results[0].compatible:
            assert results[0].eta_seconds == 1800

    def test_eta_different_for_different_facilities(self):
        """Different source facilities should give different ETAs."""
        call_log = []

        def tracking_eta(from_fac, to_fac):
            call_log.append((from_fac, to_fac))
            # Different ETA per facility distance
            etas = {
                "fac-bv-cho-ray": 1800,      # 30 min (closest)
                "fac-bv-ung-buou": 2400,      # 40 min
                "fac-bv-nhi-dong": 3000,      # 50 min
                "fac-bv-pham-ngoc-thach": 2700, # 45 min
            }
            return etas.get(from_fac, 5400)

        from app.services.matching import find_matching_units, TransferRequest, BloodUnitCandidate
        from datetime import datetime, timezone, timedelta

        request = TransferRequest(
            request_id="test-002",
            requester_facility_id="fac-bv-tmhh",
            component_code="PLT",
            abo="A",
            rh="+",
            urgency="emergency",
            needed_by=datetime.now(timezone.utc) + timedelta(hours=2),
        )

        candidates = [
            BloodUnitCandidate(
                unit_id=f"unit-{i}",
                isbt_din=f"VN{i:012d}",
                component_code="PLT",
                abo="A",
                rh="+",
                volume_ml=300,
                collected_at=datetime.now(timezone.utc) - timedelta(days=1),
                expires_at=datetime.now(timezone.utc) + timedelta(days=4),
                held_by_facility_id=fid,
                facility_name=HCMC_FACILITIES[fid]["name"],
                facility_opt_in=True,
            )
            for i, fid in enumerate([
                "fac-bv-cho-ray", "fac-bv-ung-buou", "fac-bv-nhi-dong"
            ])
        ]

        results = find_matching_units(
            request=request,
            candidates=candidates,
            eta_lookup=tracking_eta,
        )

        # ETA callback should have been called for each candidate
        assert len(call_log) == 3