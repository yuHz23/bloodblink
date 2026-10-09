"""BB-Core — Routing API: ETA comparison and route queries."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.config import settings
from app.services.routing import (
    RoutingService, OSRMRouting,
    HCMC_FACILITIES, ETA_COMPARISON_PAIRS,
)

router = APIRouter()

# Use OSRM road geometry when available; map routes get a marked straight-line fallback.
routing_service = RoutingService(provider=OSRMRouting(base_url=settings.osrm_url))


@router.get("/eta")
async def get_eta(
    from_lat: float = Query(..., description="Origin latitude"),
    from_lon: float = Query(..., description="Origin longitude"),
    to_lat: float = Query(..., description="Destination latitude"),
    to_lon: float = Query(..., description="Destination longitude"),
    mode: str = Query(default="car", description="Transport mode: car, motorcycle, emergency"),
):
    """Get estimated travel time between two coordinates."""
    result = await routing_service.get_route_with_fallback(from_lat, from_lon, to_lat, to_lon, mode)
    return {
        "from": {"lat": from_lat, "lon": from_lon},
        "to": {"lat": to_lat, "lon": to_lon},
        "mode": mode,
        "distance_m": result.distance_m,
        "duration_s": result.duration_s,
        "duration_min": round(result.duration_s / 60, 1),
        "provider": result.provider,
        "routing_mode": result.mode,
        "geometry": [[coordinate[1], coordinate[0]] for coordinate in (result.geometry or [])],
    }


@router.get("/eta/compare")
async def compare_eta(
    from_lat: float = Query(..., description="Origin latitude"),
    from_lon: float = Query(..., description="Origin longitude"),
    to_lat: float = Query(..., description="Destination latitude"),
    to_lon: float = Query(..., description="Destination longitude"),
):
    """Compare straight-line ETA vs road ETA — for validation demo."""
    return await routing_service.compare_eta(from_lat, from_lon, to_lat, to_lon)


@router.get("/eta/hcmc-pairs")
async def compare_hcmc_pairs():
    """
    Compare ETA across 20 real facility pairs in HCMC.
    This is the validation demo — proves that road ETA differs
    from straight-line and that the interface works.
    """
    results = []
    for from_id, to_id in ETA_COMPARISON_PAIRS:
        from_fac = HCMC_FACILITIES[from_id]
        to_fac = HCMC_FACILITIES[to_id]
        comparison = await routing_service.compare_eta(
            from_fac["lat"], from_fac["lon"],
            to_fac["lat"], to_fac["lon"],
        )
        results.append({
            "from": {"id": from_id, "name": from_fac["name"]},
            "to": {"id": to_id, "name": to_fac["name"]},
            "straight_line": comparison["straight_line"],
            "road": comparison["road"],
            "difference": comparison["difference"],
        })

    # Summary statistics
    avg_straight_min = sum(r["straight_line"]["duration_min"] for r in results) / len(results)
    avg_road_min = sum(r["road"]["duration_min"] for r in results) / len(results)
    avg_extra_pct = sum(abs(r["difference"]["percentage"]) for r in results) / len(results)

    return {
        "pairs": results,
        "summary": {
            "total_pairs": len(results),
            "avg_straight_line_min": round(avg_straight_min, 1),
            "avg_road_min": round(avg_road_min, 1),
            "avg_extra_time_pct": round(avg_extra_pct, 1),
            "note": "Road ETA uses OSRM when available, falls back to haversine with urban speed estimate. No real-time traffic data — must state this in demo.",
        },
    }


@router.get("/eta/facility/{facility_id}")
async def get_eta_from_facility(
    facility_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get ETA from one facility to all other HCMC facilities."""
    if facility_id not in HCMC_FACILITIES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Facility {facility_id} not found in HCMC data")

    from_fac = HCMC_FACILITIES[facility_id]
    results = []

    for other_id, other_fac in HCMC_FACILITIES.items():
        if other_id == facility_id:
            continue

        route = await routing_service.get_route(
            from_fac["lat"], from_fac["lon"],
            other_fac["lat"], other_fac["lon"],
            mode="car",
        )
        results.append({
            "to_facility_id": other_id,
            "to_name": other_fac["name"],
            "distance_m": route.distance_m,
            "duration_s": route.duration_s,
            "duration_min": round(route.duration_s / 60, 1),
            "provider": route.provider,
        })

    results.sort(key=lambda r: r["duration_s"])

    return {
        "from_facility_id": facility_id,
        "from_name": from_fac["name"],
        "to_facilities": results,
    }


@router.post("/set-provider")
async def set_routing_provider(
    provider: str = Query(..., description="Road routing provider: 'osrm'"),
    osrm_url: str = Query(default=settings.osrm_url, description="OSRM base URL"),
):
    """Configure road routing; straight-line routes are disabled."""
    if provider != "osrm":
        raise HTTPException(status_code=422, detail="Chỉ hỗ trợ định tuyến đường bộ qua OSRM.")
    routing_service.set_provider(OSRMRouting(base_url=osrm_url))
    return {"provider": "osrm", "url": osrm_url}
