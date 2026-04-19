from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from typing import Any, Dict, List, Optional, Sequence

import httpx

from app.config import Settings
from app.db import Database
from app.route_analysis import DetectedLandmark, Point, ResolvedPlace, haversine_m


logger = logging.getLogger(__name__)


class GeoClient:
    def __init__(self, settings: Settings, db: Optional[Database] = None) -> None:
        self.settings = settings
        self.db = db
        self.http_client = httpx.AsyncClient(
            timeout=settings.request_timeout_seconds,
            headers={"User-Agent": settings.geocode_user_agent},
        )

    async def close(self) -> None:
        await self.http_client.aclose()

    async def reverse_geocode(self, point: Point) -> Optional[ResolvedPlace]:
        if not self.settings.reverse_geocode_enabled:
            return None

        params = {
            "format": "jsonv2",
            "lat": point.lat,
            "lon": point.lon,
            "zoom": 14,
            "addressdetails": 1,
        }
        cache_key = self._cache_key("nominatim-reverse", params)
        data = self._cache_get(cache_key)
        if data is None and self.settings.geo_cache_only:
            return None
        if data is None:
            data = await self._get_nominatim_reverse(params=params)
            self._cache_put(cache_key, "nominatim", data)
        address = data.get("address", {})

        locality = _pick_locality(data, address)
        district = address.get("city_district") or address.get("district") or address.get("county")
        suburb = address.get("suburb") or address.get("neighbourhood") or address.get("quarter")
        road = address.get("road") or address.get("pedestrian") or address.get("path")

        raw_rank = 0
        if address.get("city"):
            raw_rank = 4
        elif address.get("town") or address.get("municipality"):
            raw_rank = 3
        elif address.get("county"):
            raw_rank = 2
        elif address.get("village"):
            raw_rank = 1

        return ResolvedPlace(
            locality=locality,
            district=district,
            suburb=suburb,
            country=address.get("country"),
            road=road,
            raw_rank=raw_rank,
        )
    async def detect_turnaround_poi(self, point: Point, radius_m: int = 1200) -> Optional[DetectedLandmark]:
        query = f"""
        [out:json][timeout:18];
        (
          nwr(around:{radius_m},{point.lat},{point.lon})["name"]["man_made"="lighthouse"];
          nwr(around:{radius_m},{point.lat},{point.lon})["name"]["natural"~"peak|saddle"];
          nwr(around:{radius_m},{point.lat},{point.lon})["name"]["mountain_pass"="yes"];
          nwr(around:{radius_m},{point.lat},{point.lon})["name"]["tourism"~"viewpoint|attraction"];
          nwr(around:{radius_m},{point.lat},{point.lon})["name"]["historic"~"monument|castle|memorial|archaeological_site"];
        );
        out center tags;
        """
        payload = await self._post_overpass(query, cache_namespace="overpass-turnaround-poi")
        if payload is None:
            return None
        best: Optional[DetectedLandmark] = None
        for element in payload.get("elements", []):
            tags = element.get("tags", {})
            name = (tags.get("name") or "").strip()
            if not name:
                continue
            lat = element.get("lat", element.get("center", {}).get("lat"))
            lon = element.get("lon", element.get("center", {}).get("lon"))
            if lat is None or lon is None:
                continue
            candidate_point = Point(lat=float(lat), lon=float(lon))
            distance_m = haversine_m(point, candidate_point)
            if distance_m > radius_m:
                continue
            category = self._landmark_category(tags)
            score = self._landmark_score_from_parts(category=category, distance_m=distance_m) + 2.0
            if tags.get("wikidata"):
                score += 0.8
            if tags.get("wikipedia"):
                score += 0.5
            candidate = DetectedLandmark(
                name=name,
                category=category,
                distance_m=distance_m,
                source="turnaround_poi",
                score=score,
            )
            if best is None or candidate.score > best.score:
                best = candidate
        return best

    async def _post_overpass(self, query: str, cache_namespace: str) -> Optional[Dict[str, Any]]:
        cache_key = self._cache_key(cache_namespace, {"query": query})
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        if self.settings.geo_cache_only:
            return None

        last_error: Optional[Exception] = None
        attempts = max(1, self.settings.overpass_retry_attempts)
        base_delay = max(0.1, self.settings.overpass_retry_base_delay_seconds)
        max_delay = max(base_delay, self.settings.overpass_retry_max_delay_seconds)

        for attempt in range(1, attempts + 1):
            try:
                response = await self.http_client.post(self.settings.overpass_base_url, content=query)
                response.raise_for_status()
                payload = response.json()
                self._cache_put(cache_key, "overpass", payload)
                return payload
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                await self._sleep_before_retry(
                    service="overpass",
                    attempt=attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    reason=exc.__class__.__name__,
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code not in {429, 502, 503, 504} or attempt >= attempts:
                    raise
                await self._sleep_before_retry(
                    service="overpass",
                    attempt=attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    reason=f"http-{status_code}",
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError("Overpass request failed without a captured exception")

    async def _get_nominatim_reverse(self, params: Dict[str, Any]) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        attempts = max(1, self.settings.nominatim_retry_attempts)
        base_delay = max(0.1, self.settings.nominatim_retry_base_delay_seconds)
        max_delay = max(base_delay, self.settings.nominatim_retry_max_delay_seconds)

        for attempt in range(1, attempts + 1):
            try:
                response = await self.http_client.get(
                    f"{self.settings.nominatim_base_url}/reverse",
                    params=params,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= attempts:
                    raise
                await self._sleep_before_retry(
                    service="nominatim",
                    attempt=attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    reason=exc.__class__.__name__,
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code not in {408, 425, 429, 500, 502, 503, 504} or attempt >= attempts:
                    raise
                await self._sleep_before_retry(
                    service="nominatim",
                    attempt=attempt,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    reason=f"http-{status_code}",
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError("Nominatim reverse geocoding failed without a captured exception")

    async def _sleep_before_retry(
        self,
        service: str,
        attempt: int,
        base_delay: float,
        max_delay: float,
        reason: str,
    ) -> None:
        delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
        jitter = random.uniform(0.0, min(0.5, delay * 0.25))
        sleep_for = delay + jitter
        logger.warning(
            "%s-retry attempt=%s next_sleep=%.2fs reason=%s",
            service,
            attempt,
            sleep_for,
            reason,
        )
        await asyncio.sleep(sleep_for)

    @staticmethod
    def _landmark_category(tags: Dict[str, Any]) -> str:
        if tags.get("mountain_pass") == "yes":
            return "mountain_pass"
        for key in ("natural", "leisure", "tourism", "historic", "waterway"):
            if key in tags:
                return str(tags[key])
        return "landmark"

    @staticmethod
    def _landmark_score_from_parts(category: str, distance_m: float) -> float:
        category_boost = {
            "mountain_pass": 4.5,
            "peak": 4.0,
            "saddle": 3.8,
            "park": 3.5,
            "nature_reserve": 3.4,
            "water": 3.3,
            "bay": 3.0,
            "viewpoint": 2.8,
            "attraction": 2.7,
            "beach": 2.6,
            "wood": 2.2,
            "river": 2.2,
            "lighthouse": 3.9,
            "monument": 3.0,
            "castle": 3.3,
        }.get(category, 2.0)
        return category_boost - (distance_m / 1000.0)

    def _cache_key(self, namespace: str, payload: Dict[str, Any]) -> str:
        raw = json_dumps_stable(payload)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return f"{namespace}:{digest}"

    def _cache_get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if self.db is None:
            return None
        return self.db.get_geo_cache(cache_key)

    def _cache_put(self, cache_key: str, service: str, payload: Dict[str, Any]) -> None:
        if self.db is None:
            return
        self.db.put_geo_cache(cache_key, service, payload)


def json_dumps_stable(payload: Dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _pick_locality(data: Dict[str, Any], address: Dict[str, Any]) -> Optional[str]:
    addresstype = str(data.get("addresstype") or "").lower()
    name = str(data.get("name") or "").strip() or None

    if addresstype == "village":
        return address.get("village") or name or address.get("town") or address.get("city")

    if addresstype in {"hamlet", "isolated_dwelling"}:
        return (
            address.get("town")
            or address.get("municipality")
            or address.get("city")
            or address.get(addresstype)
            or address.get("village")
            or address.get("hamlet")
            or name
        )

    return (
        address.get("city")
        or address.get("town")
        or address.get("municipality")
        or address.get("village")
        or address.get("hamlet")
        or address.get("isolated_dwelling")
        or address.get("suburb")
        or address.get("county")
    )
