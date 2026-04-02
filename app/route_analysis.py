from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence


EARTH_RADIUS_M = 6_371_000


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


@dataclass(frozen=True)
class ResolvedPlace:
    locality: Optional[str]
    district: Optional[str]
    suburb: Optional[str]
    country: Optional[str]
    road: Optional[str]
    raw_rank: int = 0


@dataclass(frozen=True)
class DetectedLandmark:
    name: str
    category: str
    distance_m: float
    source: str = "osm"
    score: float = 0.0
    position: Optional[float] = None


@dataclass(frozen=True)
class RouteHighlight:
    name: str
    category: str
    source: str
    score: float
    distance_m: Optional[float] = None
    position: Optional[float] = None
    aliases: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class RawRouteSignal:
    name: str
    normalized_name: str
    kind: str
    source: str
    score: float
    position: float
    distance_m: Optional[float] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    aliases: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RouteEntityCluster:
    cluster_id: str
    canonical_name: str
    normalized_name: str
    kind: str
    score: float
    position_start: float
    position_end: float
    position_centroid: float
    aliases: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    signals_count: int = 0
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class OrderedHighlight:
    cluster_id: str
    name: str
    kind: str
    score: float
    position: float
    aliases: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class RouteSummary:
    points: List[Point]
    total_distance_m: float
    is_loop: bool
    start_place: Optional[ResolvedPlace]
    end_place: Optional[ResolvedPlace]
    turnaround_point: Optional[Point] = None
    turnaround_position: Optional[float] = None
    turnaround_place: Optional[ResolvedPlace] = None
    turnaround_highlight: Optional[DetectedLandmark] = None
    via_places: List[ResolvedPlace] = field(default_factory=list)
    landmark: Optional[DetectedLandmark] = None
    highlights: List[RouteHighlight] = field(default_factory=list)
    raw_signals: List[RawRouteSignal] = field(default_factory=list)
    clusters: List[RouteEntityCluster] = field(default_factory=list)
    ordered_highlights: List[OrderedHighlight] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def decode_polyline(encoded: str) -> List[Point]:
    index = 0
    lat = 0
    lon = 0
    points = []

    while index < len(encoded):
        shift = 0
        result = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lat += ~(result >> 1) if result & 1 else result >> 1

        shift = 0
        result = 0
        while True:
            byte = ord(encoded[index]) - 63
            index += 1
            result |= (byte & 0x1F) << shift
            shift += 5
            if byte < 0x20:
                break
        lon += ~(result >> 1) if result & 1 else result >> 1

        points.append(Point(lat=lat / 1e5, lon=lon / 1e5))

    return points


def haversine_m(a: Point, b: Point) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    d_lat = lat2 - lat1
    d_lon = math.radians(b.lon - a.lon)

    sin_lat = math.sin(d_lat / 2.0)
    sin_lon = math.sin(d_lon / 2.0)
    h = sin_lat ** 2 + math.cos(lat1) * math.cos(lat2) * sin_lon ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def total_distance_m(points: Sequence[Point]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(haversine_m(points[idx - 1], points[idx]) for idx in range(1, len(points)))


def is_loop_route(points: Sequence[Point], total_distance: float) -> bool:
    if len(points) < 2:
        return False
    start_end_gap = haversine_m(points[0], points[-1])
    threshold = max(1000.0, total_distance * 0.12)
    return start_end_gap <= threshold


def sample_points(points: Sequence[Point], count: int, include_ends: bool = True) -> List[Point]:
    if not points:
        return []
    if count >= len(points):
        return list(points)
    indices = []
    if include_ends:
        indices = [round(i * (len(points) - 1) / (count - 1)) for i in range(count)]
    else:
        indices = [round((i + 1) * (len(points) - 1) / (count + 1)) for i in range(count)]
    deduped = []
    seen = set()
    for index in indices:
        if index in seen:
            continue
        seen.add(index)
        deduped.append(points[index])
    return deduped


def find_turnaround_point(points: Sequence[Point]) -> tuple[Optional[Point], Optional[float]]:
    if len(points) < 3:
        return None, None
    origin = points[0]
    start_index = max(1, len(points) // 10)
    end_index = max(start_index + 1, len(points) - len(points) // 10)
    if end_index <= start_index:
        start_index = 1
        end_index = len(points) - 1
    best_index = None
    best_distance = -1.0
    for idx in range(start_index, end_index):
        distance = haversine_m(origin, points[idx])
        if distance > best_distance:
            best_distance = distance
            best_index = idx
    if best_index is None:
        return None, None
    position = best_index / max(1, len(points) - 1)
    return points[best_index], position


def dedupe_places(places: Iterable[ResolvedPlace]) -> List[ResolvedPlace]:
    seen = set()
    result = []
    for place in places:
        key = (
            (place.locality or "").strip().lower(),
            (place.district or "").strip().lower(),
            (place.suburb or "").strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(place)
    return result


def limit_places(places: Sequence[ResolvedPlace], limit: int) -> List[ResolvedPlace]:
    if limit <= 0:
        return []
    return list(places[:limit])


def limit_highlights(highlights: Sequence[RouteHighlight], limit: int) -> List[RouteHighlight]:
    if limit <= 0:
        return []
    return list(highlights[:limit])


def limit_raw_signals(signals: Sequence[RawRouteSignal], limit: int) -> List[RawRouteSignal]:
    if limit <= 0:
        return []
    return list(signals[:limit])


def limit_clusters(clusters: Sequence[RouteEntityCluster], limit: int) -> List[RouteEntityCluster]:
    if limit <= 0:
        return []
    return list(clusters[:limit])


def limit_ordered_highlights(highlights: Sequence[OrderedHighlight], limit: int) -> List[OrderedHighlight]:
    if limit <= 0:
        return []
    return list(highlights[:limit])
