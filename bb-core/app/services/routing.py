"""
BB-Core — Routing Provider interface and OSRM implementation.

Architecture decision per planning doc:
  - OSRM self-hosted on OpenStreetMap Vietnam extract
  - Runs offline, no query limits, demo不怕 mất mạng
  - NO real-time traffic data — must state this in demo
  - RoutingProvider interface allows swapping to commercial provider later

Two ETA modes:
  1. Straight-line (haversine) — fallback, always available
  2. OSRM road routing — realistic travel times
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx
from fastapi import HTTPException


# ── Data classes ────────────────────────────────────────────────

@dataclass
class RouteResult:
    """Result from a routing query."""
    distance_m: float           # total distance in meters
    duration_s: float            # estimated travel time in seconds
    geometry: Optional[list[list[float]]] = None  # GeoJSON coordinates [longitude, latitude]
    provider: str = "unknown"   # which provider computed this
    mode: str = "road"          # "road" or "straight_line"


class RoutingUnavailableError(HTTPException):
    """Road routing could not provide a real route."""

    def __init__(self, detail: str):
        super().__init__(status_code=503, detail=detail)


# ── Abstract interface ──────────────────────────────────────────

class RoutingProvider(ABC):
    """
    Abstract routing provider — swap OSRM for commercial service later.

    Commercial candidates for Vietnam:
    - Google Maps Platform (Directions API)
    - Mapbox Directions API
    - GrabMart / Gojek internal APIs (if available)
    - OpenRouteService (hosted, with traffic)
    """

    @abstractmethod
    async def get_route(
        self,
        from_lat: float, from_lon: float,
        to_lat: float, to_lon: float,
        mode: str = "car",  # "car" | "motorcycle" | "emergency"
    ) -> RouteResult:
        """Get route between two coordinates."""
        ...

    @abstractmethod
    async def get_eta(
        self,
        from_lat: float, from_lon: float,
        to_lat: float, to_lon: float,
        mode: str = "car",
    ) -> int:
        """Get estimated travel time in seconds."""
        ...

    @abstractmethod
    def get_name(self) -> str:
        """Human-readable provider name."""
        ...


# ── Haversine (straight-line) fallback ──────────────────────────

class StraightLineRouting(RoutingProvider):
    """
    Haversine distance-based ETA. Always available.

    Uses average urban speed to estimate time:
    - Car: 25 km/h in HCMC traffic (empirical average)
    - Motorcycle: 30 km/h (common transport for blood delivery)
    - Emergency: 40 km/h (with sirens / emergency priority)
    """

    SPEED_KMH = {
        "car": 25.0,
        "motorcycle": 30.0,
        "emergency": 40.0,
    }

    @staticmethod
    def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate haversine distance in meters."""
        R = 6_371_000  # Earth radius in meters
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    async def get_route(
        self, from_lat: float, from_lon: float, to_lat: float, to_lon: float, mode: str = "car"
    ) -> RouteResult:
        dist = self.haversine(from_lat, from_lon, to_lat, to_lon)
        speed_mps = self.SPEED_KMH.get(mode, 25.0) * 1000 / 3600
        duration = dist / speed_mps
        return RouteResult(
            distance_m=round(dist, 1),
            duration_s=round(duration, 1),
            provider="straight_line",
            mode="straight_line",
        )

    async def get_eta(
        self, from_lat: float, from_lon: float, to_lat: float, to_lon: float, mode: str = "car"
    ) -> int:
        route = await self.get_route(from_lat, from_lon, to_lat, to_lon, mode)
        return int(route.duration_s)

    def get_name(self) -> str:
        return "straight_line (haversine)"


# ── OSRM routing ────────────────────────────────────────────────

class OSRMRouting(RoutingProvider):
    """
    Open Source Routing Machine — self-hosted on OSM Vietnam extract.

    Setup:
      1. Download Vietnam OSM extract from geofabrik.de
      2. Process with osrm-backend: osrm-extract, osrm-partition, osrm-customize
      3. Run: osrm-routed --algorithm mld vietnam-latest.osrm

    This runs offline, no API limits, no network dependency for demo.
    """

    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(timeout=10.0)

    async def get_route(
        self, from_lat: float, from_lon: float, to_lat: float, to_lon: float, mode: str = "car"
    ) -> RouteResult:
        """Query OSRM for road route between two points."""
        # OSRM route API: /route/v1/{profile}/{coordinates}?overview=simplified
        url = f"{self.base_url}/route/v1/driving/{from_lon},{from_lat};{to_lon},{to_lat}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "false",
            "alternatives": "false",
        }
        try:
            resp = await self.client.get(url, params=params)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RoutingUnavailableError(
                "Không kết nối được dịch vụ chỉ đường OSRM; không thể tạo tuyến đường bộ."
            ) from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise RoutingUnavailableError("OSRM trả về dữ liệu tuyến đường không hợp lệ.") from exc

        if data.get("code") != "Ok" or not data.get("routes"):
            raise RoutingUnavailableError("OSRM không tìm thấy tuyến đường bộ phù hợp.")

        route = data["routes"][0]
        geometry = (route.get("geometry") or {}).get("coordinates")
        if not geometry or len(geometry) < 2:
            raise RoutingUnavailableError("OSRM không trả về hình học tuyến đường bộ.")

        return RouteResult(
            distance_m=route["distance"],
            duration_s=route["duration"],
            geometry=geometry,
            provider="osrm",
            mode="road",
        )

    async def get_eta(
        self, from_lat: float, from_lon: float, to_lat: float, to_lon: float, mode: str = "car"
    ) -> int:
        route = await self.get_route(from_lat, from_lon, to_lat, to_lon, mode)
        return int(route.duration_s)

    def get_name(self) -> str:
        return "osrm"


# ── Routing service facade ─────────────────────────────────────

class RoutingService:
    """
    Facade that manages routing providers and provides a unified interface.
    Defaults to road routing through OSRM.
    """

    def __init__(self, provider: Optional[RoutingProvider] = None):
        self._provider = provider if provider is not None else OSRMRouting()
        self._straight_line = StraightLineRouting()  # always available as fallback

    def set_provider(self, provider: RoutingProvider):
        """Swap routing provider at runtime."""
        self._provider = provider

    async def get_route(
        self, from_lat: float, from_lon: float, to_lat: float, to_lon: float, mode: str = "car"
    ) -> RouteResult:
        return await self._provider.get_route(from_lat, from_lon, to_lat, to_lon, mode)

    async def get_eta(
        self, from_lat: float, from_lon: float, to_lat: float, to_lon: float, mode: str = "car"
    ) -> int:
        return await self._provider.get_eta(from_lat, from_lon, to_lat, to_lon, mode)

    async def compare_eta(
        self, from_lat: float, from_lon: float, to_lat: float, to_lon: float
    ) -> dict:
        """Compare straight-line ETA vs road ETA — for validation demo."""
        road = await self._provider.get_route(from_lat, from_lon, to_lat, to_lon, "car")
        straight = await self._straight_line.get_route(from_lat, from_lon, to_lat, to_lon, "car")

        diff_s = road.duration_s - straight.duration_s
        diff_pct = (diff_s / straight.duration_s * 100) if straight.duration_s > 0 else 0

        return {
            "straight_line": {
                "distance_m": round(straight.distance_m, 1),
                "duration_s": round(straight.duration_s, 1),
                "duration_min": round(straight.duration_s / 60, 1),
                "provider": straight.provider,
            },
            "road": {
                "distance_m": round(road.distance_m, 1),
                "duration_s": round(road.duration_s, 1),
                "duration_min": round(road.duration_s / 60, 1),
                "provider": road.provider,
            },
            "difference": {
                "extra_seconds": round(diff_s, 1),
                "extra_minutes": round(diff_s / 60, 1),
                "percentage": round(diff_pct, 1),
            },
        }


# ── HCMC facility coordinates (from seed data) ─────────────────

HCMC_FACILITIES = {
    "fac-bv-tmhh":        {"name": "Bệnh viện Truyền máu Huyết học TP.HCM", "lat": 10.7869, "lon": 106.6854},
    "fac-bv-cho-ray":     {"name": "Bệnh viện Chợ Rẫy",               "lat": 10.7635, "lon": 106.6690},
    "fac-bv-ung-buou":    {"name": "Bệnh viện Ung Bướu TP.HCM",       "lat": 10.7736, "lon": 106.6973},
    "fac-bv-nhi-dong":    {"name": "Bệnh viện Nhi Đồng 1",             "lat": 10.7905, "lon": 106.6940},
    "fac-bv-pham-ngoc-thach": {"name": "Bệnh viện Phạm Ngọc Thạch",   "lat": 10.7811, "lon": 106.6728},
}

# 20 pairs of facilities for ETA comparison
ETA_COMPARISON_PAIRS = [
    ("fac-bv-tmhh", "fac-bv-cho-ray"),
    ("fac-bv-tmhh", "fac-bv-ung-buou"),
    ("fac-bv-tmhh", "fac-bv-nhi-dong"),
    ("fac-bv-tmhh", "fac-bv-pham-ngoc-thach"),
    ("fac-bv-cho-ray", "fac-bv-ung-buou"),
    ("fac-bv-cho-ray", "fac-bv-nhi-dong"),
    ("fac-bv-cho-ray", "fac-bv-pham-ngoc-thach"),
    ("fac-bv-ung-buou", "fac-bv-nhi-dong"),
    ("fac-bv-ung-buou", "fac-bv-pham-ngoc-thach"),
    ("fac-bv-nhi-dong", "fac-bv-pham-ngoc-thach"),
    # Repeat with reverse direction (ETA can differ)
    ("fac-bv-cho-ray", "fac-bv-tmhh"),
    ("fac-bv-ung-buou", "fac-bv-tmhh"),
    ("fac-bv-nhi-dong", "fac-bv-tmhh"),
    ("fac-bv-pham-ngoc-thach", "fac-bv-tmhh"),
    ("fac-bv-ung-buou", "fac-bv-cho-ray"),
    ("fac-bv-nhi-dong", "fac-bv-cho-ray"),
    ("fac-bv-pham-ngoc-thach", "fac-bv-cho-ray"),
    ("fac-bv-nhi-dong", "fac-bv-ung-buou"),
    ("fac-bv-pham-ngoc-thach", "fac-bv-ung-buou"),
    ("fac-bv-pham-ngoc-thach", "fac-bv-nhi-dong"),
]
