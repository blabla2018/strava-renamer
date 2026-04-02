from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, List, Optional

import httpx
import math

from app.activity_filters import FilterDecision, evaluate_activity_filters
from app.config import Settings
from app.db import Database
from app.geocoding import GeoClient
from app.naming import NamingDecision, generate_title, should_rename_activity
from app.route_analysis import (
    OrderedHighlight,
    Point,
    RawRouteSignal,
    RouteEntityCluster,
    RouteHighlight,
    RouteSummary,
    decode_polyline,
    dedupe_places,
    find_turnaround_point,
    is_loop_route,
    limit_clusters,
    limit_highlights,
    limit_ordered_highlights,
    limit_places,
    limit_raw_signals,
    sample_points,
    total_distance_m,
)
from app.strava import StravaClient


@dataclass(frozen=True)
class ActivityProcessingResult:
    activity_id: int
    owner_id: int
    current_name: Optional[str]
    sport_type: str
    filter_decision: FilterDecision
    route_summary: Optional[RouteSummary]
    naming_decision: Optional[NamingDecision]
    should_rename: bool
    rename_reason: str
    updated: bool


class ActivityPipeline:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        strava_client: StravaClient,
        geo_client: GeoClient,
    ) -> None:
        self.settings = settings
        self.db = db
        self.strava_client = strava_client
        self.geo_client = geo_client

    async def process_activity(self, activity_id: int, owner_id: int, apply_update: bool) -> ActivityProcessingResult:
        activity = await self.strava_client.get_activity(activity_id, include_all_efforts=True)
        return await self.process_activity_payload(activity=activity, owner_id=owner_id, apply_update=apply_update)

    async def process_activity_payload(
        self,
        activity: Dict[str, Any],
        owner_id: int,
        apply_update: bool,
    ) -> ActivityProcessingResult:
        activity_id = int(activity["id"])
        current_name = activity.get("name")
        sport_type = str(activity.get("sport_type") or activity.get("type") or "")

        filter_decision = await evaluate_activity_filters(activity)
        if not filter_decision.accepted:
            self.db.record_rename_audit(
                activity_id=activity_id,
                owner_id=owner_id,
                previous_name=current_name,
                generated_name=None,
                confidence=0.0,
                reason=filter_decision.reason,
                outcome="filtered_out",
            )
            return ActivityProcessingResult(
                activity_id=activity_id,
                owner_id=owner_id,
                current_name=current_name,
                sport_type=sport_type,
                filter_decision=filter_decision,
                route_summary=None,
                naming_decision=None,
                should_rename=False,
                rename_reason=filter_decision.reason,
                updated=False,
            )

        summary = await self.build_route_summary(activity)
        segment_details: Dict[int, Dict[str, Any]] = {}
        if sport_type == "Ride":
            segment_details = await self._load_segment_details(activity)
        summary.highlights = rank_activity_highlights(
            activity=activity,
            route_summary=summary,
            segment_details=segment_details,
            limit=self.settings.route_highlight_limit,
        )
        raw_signals = collect_raw_route_signals(
            activity=activity,
            route_summary=summary,
            segment_details=segment_details,
        )
        clusters = cluster_route_signals(raw_signals)
        ordered_highlights = build_ordered_highlights(clusters, limit=self.settings.route_highlight_limit)
        summary.raw_signals = limit_raw_signals(sorted(raw_signals, key=lambda item: (item.position, -item.score)), 50)
        summary.clusters = limit_clusters(clusters, 20)
        summary.ordered_highlights = ordered_highlights
        naming_decision = generate_title(summary)
        previous_audit = self.db.get_last_rename_audit(activity_id)
        should_rename, rename_reason = should_rename_activity(
            current_name=current_name,
            decision=naming_decision,
            sport_type=sport_type,
            settings=self.settings,
        )
        if (
            should_rename
            and previous_audit is not None
            and previous_audit["generated_name"]
            and not self.settings.overwrite_existing_generated_titles
        ):
            should_rename = False
            rename_reason = "existing generated title will not be overwritten by configuration"

        updated = False
        if should_rename and apply_update:
            await self.strava_client.update_activity_name(activity_id, naming_decision.title or "")
            updated = True

        self.db.record_rename_audit(
            activity_id=activity_id,
            owner_id=owner_id,
            previous_name=current_name,
            generated_name=naming_decision.title,
            confidence=naming_decision.confidence,
            reason=f"{naming_decision.reason}; {rename_reason}",
            outcome="renamed" if updated else "skipped",
        )
        return ActivityProcessingResult(
            activity_id=activity_id,
            owner_id=owner_id,
            current_name=current_name,
            sport_type=sport_type,
            filter_decision=filter_decision,
            route_summary=summary,
            naming_decision=naming_decision,
            should_rename=should_rename,
            rename_reason=rename_reason,
            updated=updated,
        )

    async def build_route_summary(self, activity: Dict[str, Any]) -> RouteSummary:
        offline_points = _offline_points_from_activity(activity)
        if offline_points is not None:
            return await self._build_route_summary_from_points(
                points=offline_points,
                distance=float(activity.get("distance") or total_distance_m(offline_points)),
            )

        polyline = (
            activity.get("map", {}).get("summary_polyline")
            or activity.get("map", {}).get("polyline")
            or activity.get("summary_polyline")
        )
        if not polyline:
            return RouteSummary(
                points=[],
                total_distance_m=float(activity.get("distance") or 0.0),
                is_loop=False,
                start_place=None,
                end_place=None,
                warnings=["Activity did not include a route polyline."],
            )

        points = decode_polyline(polyline)
        distance = float(activity.get("distance") or total_distance_m(points))
        return await self._build_route_summary_from_points(points=points, distance=distance)

    async def _build_route_summary_from_points(self, points: List[Point], distance: float) -> RouteSummary:
        route_is_loop = is_loop_route(points, distance)

        start_place = None
        end_place = None
        turnaround_point = None
        turnaround_position = None
        turnaround_place = None
        turnaround_highlight = None
        via_places = []
        landmark = None
        highlights: List[RouteHighlight] = []
        warnings: List[str] = []

        if points:
            try:
                start_place = await self.geo_client.reverse_geocode(points[0])
                end_place = await self.geo_client.reverse_geocode(points[-1])
            except httpx.HTTPError as exc:
                warnings.append(f"Reverse geocoding failed for endpoints: {exc}")

            if route_is_loop:
                turnaround_point, turnaround_position = find_turnaround_point(points)
                if turnaround_point is not None:
                    try:
                        turnaround_place = await self.geo_client.reverse_geocode(turnaround_point)
                    except httpx.HTTPError as exc:
                        warnings.append(f"Reverse geocoding failed for turnaround point: {exc}")
                    try:
                        turnaround_highlight = await self.geo_client.detect_turnaround_poi(turnaround_point)
                    except httpx.HTTPError as exc:
                        warnings.append(f"Turnaround POI lookup failed: {exc}")

            via_sample_count = max(2, min(self.settings.via_place_sample_count, len(points)))
            for via_point in sample_points(points, count=via_sample_count, include_ends=False):
                try:
                    place = await self.geo_client.reverse_geocode(via_point)
                except httpx.HTTPError as exc:
                    warnings.append(f"Reverse geocoding failed for an interior point: {exc}")
                    continue
                if place is not None:
                    via_places.append(place)

            if turnaround_highlight is not None:
                highlights.append(
                    RouteHighlight(
                        name=turnaround_highlight.name,
                        category=turnaround_highlight.category,
                        source=turnaround_highlight.source,
                        score=turnaround_highlight.score + 2.5,
                        distance_m=turnaround_highlight.distance_m,
                        position=turnaround_position,
                    )
                )

        return RouteSummary(
            points=points,
            total_distance_m=distance,
            is_loop=route_is_loop,
            start_place=start_place,
            end_place=end_place,
            turnaround_point=turnaround_point,
            turnaround_position=turnaround_position,
            turnaround_place=turnaround_place,
            turnaround_highlight=turnaround_highlight,
            via_places=limit_places(dedupe_places(via_places), self.settings.via_place_output_limit),
            landmark=landmark,
            highlights=limit_highlights(_dedupe_highlights(sorted(highlights, key=lambda item: (-item.score, item.name.lower()))), self.settings.route_highlight_limit),
            warnings=warnings,
        )

    async def _load_segment_details(self, activity: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen = set()
        for effort in activity.get("segment_efforts", []) or []:
            segment = effort.get("segment") or {}
            segment_id = int(segment.get("id") or 0)
            if segment_id <= 0 or segment_id in seen:
                continue
            seen.add(segment_id)
            candidates.append(segment)
        ranked = sorted(candidates, key=_score_segment_highlight, reverse=True)
        top_ids = [int(segment["id"]) for segment in ranked[: self.settings.strava_segment_candidate_limit] if segment.get("id")]
        if not top_ids:
            return {}
        return await self.strava_client.get_segments(top_ids)


def _offline_points_from_activity(activity: Dict[str, Any]) -> Optional[List[Point]]:
    raw_points = activity.get("_offline_points")
    if not raw_points:
        return None
    points = []
    for item in raw_points:
        lat = item.get("lat")
        lon = item.get("lon")
        if lat is None or lon is None:
            continue
        points.append(Point(lat=float(lat), lon=float(lon)))
    return points


def rank_activity_highlights(
    activity: Dict[str, Any],
    route_summary: RouteSummary,
    segment_details: Optional[Dict[int, Dict[str, Any]]] = None,
    limit: int = 6,
) -> List[RouteHighlight]:
    highlights: List[RouteHighlight] = []
    highlights.extend(_extract_segment_highlights(activity, segment_details or {}))
    highlights.extend(route_summary.highlights)
    ranked = sorted(highlights, key=lambda item: (-item.score, item.distance_m or 0.0, item.name.lower()))
    return limit_highlights(_dedupe_highlights(ranked), limit)


def collect_raw_route_signals(
    activity: Dict[str, Any],
    route_summary: RouteSummary,
    segment_details: Dict[int, Dict[str, Any]],
) -> List[RawRouteSignal]:
    signals: List[RawRouteSignal] = []
    signals.extend(_segment_signals_from_activity(activity, segment_details, route_summary.points))
    signals.extend(_landmark_signals_from_summary(route_summary))
    return signals


def cluster_route_signals(signals: List[RawRouteSignal]) -> List[RouteEntityCluster]:
    if not signals:
        return []

    sorted_signals = sorted(signals, key=lambda item: (item.position, -item.score))
    clusters: List[List[RawRouteSignal]] = []
    for signal in sorted_signals:
        matched_cluster: Optional[List[RawRouteSignal]] = None
        for cluster in clusters:
            if _signals_belong_to_same_cluster(signal, cluster):
                matched_cluster = cluster
                break
        if matched_cluster is None:
            clusters.append([signal])
        else:
            matched_cluster.append(signal)

    result: List[RouteEntityCluster] = []
    for index, cluster_signals in enumerate(clusters, start=1):
        ordered = sorted(cluster_signals, key=lambda item: (item.position, -item.score))
        canonical = _pick_canonical_cluster_name(cluster_signals)
        normalized_name = _normalize_signal_name(canonical)
        score = max(item.score for item in cluster_signals) + math.log10(len(cluster_signals) + 1) * 0.8
        aliases = []
        seen_aliases = set()
        for item in sorted(cluster_signals, key=lambda raw: (-raw.score, raw.name.lower())):
            for alias in [item.name] + list(item.aliases):
                normalized_alias = alias.strip().lower()
                if not normalized_alias or normalized_alias in seen_aliases:
                    continue
                seen_aliases.add(normalized_alias)
                aliases.append(alias)
        sources = sorted({item.source for item in cluster_signals})
        kind = _pick_cluster_kind(cluster_signals)
        metadata = {
            "signal_count": len(cluster_signals),
            "max_score": round(max(item.score for item in cluster_signals), 2),
        }
        result.append(
            RouteEntityCluster(
                cluster_id=f"cluster-{index}",
                canonical_name=canonical,
                normalized_name=normalized_name,
                kind=kind,
                score=score,
                position_start=min(item.position for item in cluster_signals),
                position_end=max(item.position for item in cluster_signals),
                position_centroid=sum(item.position for item in cluster_signals) / len(cluster_signals),
                aliases=aliases,
                sources=sources,
                signals_count=len(cluster_signals),
                metadata=metadata,
            )
        )
    return sorted(result, key=lambda item: item.position_centroid)


def build_ordered_highlights(clusters: List[RouteEntityCluster], limit: int) -> List[OrderedHighlight]:
    selected: List[RouteEntityCluster] = []
    for cluster in sorted(clusters, key=lambda item: item.position_centroid):
        if not _cluster_is_meaningful(cluster):
            continue
        if selected and abs(cluster.position_centroid - selected[-1].position_centroid) < 0.08:
            if cluster.score > selected[-1].score:
                selected[-1] = cluster
            continue
        selected.append(cluster)

    deduped_selected: List[RouteEntityCluster] = []
    for cluster in selected:
        replacement_index: Optional[int] = None
        for index, existing in enumerate(deduped_selected):
            if existing.normalized_name != cluster.normalized_name:
                continue
            if abs(existing.position_centroid - cluster.position_centroid) > 0.35:
                continue
            replacement_index = index
            break
        if replacement_index is None:
            deduped_selected.append(cluster)
            continue
        if cluster.score > deduped_selected[replacement_index].score:
            deduped_selected[replacement_index] = cluster

    ranked = sorted(deduped_selected, key=lambda item: (-item.score, item.position_centroid))
    trimmed = sorted(ranked[:limit], key=lambda item: item.position_centroid)
    return limit_ordered_highlights(
        [
            OrderedHighlight(
                cluster_id=item.cluster_id,
                name=item.canonical_name,
                kind=item.kind,
                score=item.score,
                position=item.position_centroid,
                aliases=item.aliases,
                sources=item.sources,
                metadata=item.metadata,
            )
            for item in trimmed
        ],
        limit,
    )


def _extract_segment_highlights(
    activity: Dict[str, Any],
    segment_details: Dict[int, Dict[str, Any]],
) -> List[RouteHighlight]:
    results: List[RouteHighlight] = []
    seen = set()
    for effort in activity.get("segment_efforts", []) or []:
        segment = effort.get("segment") or {}
        segment_id = int(segment.get("id") or 0)
        if segment_id <= 0 or segment_id in seen:
            continue
        seen.add(segment_id)
        detail = segment_details.get(segment_id, {})
        name = str(detail.get("name") or segment.get("name") or "").strip()
        if not name:
            continue
        score = _score_segment_highlight(detail or segment)
        if score <= 0:
            continue
        results.append(
            RouteHighlight(
                name=name,
                category=_segment_category(detail or segment),
                source="strava_segment",
                score=score,
                distance_m=None,
                position=_segment_position(effort),
            )
        )
    return results


def _segment_signals_from_activity(
    activity: Dict[str, Any],
    segment_details: Dict[int, Dict[str, Any]],
    route_points: List[Point],
) -> List[RawRouteSignal]:
    signals: List[RawRouteSignal] = []
    seen = set()
    for effort in activity.get("segment_efforts", []) or []:
        segment = effort.get("segment") or {}
        segment_id = int(segment.get("id") or 0)
        if segment_id <= 0:
            continue
        detail = segment_details.get(segment_id, {})
        name = str(detail.get("name") or segment.get("name") or "").strip()
        if not name:
            continue
        position = _segment_position(effort)
        score = _score_segment_highlight(detail or segment)
        if score <= 0:
            continue
        kind = _segment_category(detail or segment)
        aliases = _segment_aliases(name)
        dedupe_key = (segment_id, round(position, 3))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        signals.append(
            RawRouteSignal(
                name=name,
                normalized_name=_normalize_signal_name(name),
                kind=kind,
                source="strava_segment",
                score=score,
                position=position,
                aliases=aliases,
                metadata={
                    "segment_id": segment_id,
                    "star_count": detail.get("star_count") or segment.get("star_count"),
                    "athlete_count": detail.get("athlete_count") or segment.get("athlete_count"),
                    "effort_count": detail.get("effort_count") or segment.get("effort_count"),
                    "climb_category": detail.get("climb_category") or segment.get("climb_category"),
                },
            )
        )
    return signals


def _landmark_signals_from_summary(route_summary: RouteSummary) -> List[RawRouteSignal]:
    signals: List[RawRouteSignal] = []
    if (
        route_summary.turnaround_highlight is not None
        and route_summary.turnaround_position is not None
    ):
        signals.append(
            RawRouteSignal(
                name=route_summary.turnaround_highlight.name,
                normalized_name=_normalize_signal_name(route_summary.turnaround_highlight.name),
                kind=route_summary.turnaround_highlight.category,
                source=route_summary.turnaround_highlight.source,
                score=route_summary.turnaround_highlight.score + 3.0,
                position=route_summary.turnaround_position,
                distance_m=route_summary.turnaround_highlight.distance_m,
                aliases=[],
                metadata={"turnaround_boosted": True},
            )
        )
    if (
        route_summary.turnaround_place is not None
        and route_summary.turnaround_position is not None
    ):
        turnaround_name = (
            route_summary.turnaround_place.locality
            or route_summary.turnaround_place.district
            or route_summary.turnaround_place.suburb
        )
        if turnaround_name:
            signals.append(
                RawRouteSignal(
                    name=str(turnaround_name),
                    normalized_name=_normalize_signal_name(str(turnaround_name)),
                    kind="turnaround_place",
                    source="reverse_geocode",
                    score=7.5,
                    position=route_summary.turnaround_position,
                    aliases=[],
                    metadata={"turnaround_place": True},
                )
            )
    for item in route_summary.highlights:
        if item.position is None:
            continue
        signals.append(
            RawRouteSignal(
                name=item.name,
                normalized_name=_normalize_signal_name(item.name),
                kind=item.category,
                source=item.source,
                score=item.score,
                position=item.position,
                distance_m=item.distance_m,
                aliases=list(item.aliases),
                metadata={},
            )
        )
    return signals


def _score_segment_highlight(segment: Dict[str, Any]) -> float:
    climb_category = float(segment.get("climb_category") or 0)
    average_grade = abs(float(segment.get("average_grade") or 0.0))
    distance_km = float(segment.get("distance") or 0.0) / 1000.0
    star_count = float(segment.get("star_count") or 0.0)
    athlete_count = float(segment.get("athlete_count") or 0.0)
    effort_count = float(segment.get("effort_count") or 0.0)

    score = 0.0
    if climb_category > 0:
        score += 6.0 + climb_category * 1.1
    score += min(3.0, average_grade / 2.5)
    score += min(2.5, distance_km / 4.0)
    if star_count > 0:
        score += min(4.0, math.log10(star_count + 1) * 1.8)
    if athlete_count > 0:
        score += min(2.0, math.log10(athlete_count + 1))
    if effort_count > 0:
        score += min(1.5, math.log10(effort_count + 1) * 0.7)
    return score


def _segment_category(segment: Dict[str, Any]) -> str:
    climb_category = int(segment.get("climb_category") or 0)
    if climb_category > 0:
        return "climb_segment"
    if abs(float(segment.get("average_grade") or 0.0)) >= 4.0:
        return "climb_segment"
    return "segment"


def _dedupe_highlights(highlights: List[RouteHighlight]) -> List[RouteHighlight]:
    deduped: List[RouteHighlight] = []
    seen = set()
    for item in highlights:
        key = item.name.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_signal_name(value: str) -> str:
    normalized = _clean_signal_name(value).lower()
    replacements = {
        "alto de ": "",
        "alt de ": "",
        "puerto de ": "",
        "puerto del ": "",
        "port de ": "",
        "mirador de ": "",
        "faro de ": "",
        "el faro de ": "",
        "cap de ": "",
    }
    for prefix, replacement in replacements.items():
        if normalized.startswith(prefix):
            normalized = replacement + normalized[len(prefix):]
    normalized = normalized.replace("'", "").replace("’", "")
    normalized = " ".join(part for part in normalized.replace("-", " ").split() if part)
    return normalized


def _clean_signal_name(value: str) -> str:
    cleaned = value.strip()
    cleaned = cleaned.replace("\\", " ")
    cleaned = cleaned.replace("\"", " ")
    cleaned = cleaned.replace("'", " ")
    cleaned = cleaned.replace("’", " ")
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"\[[^\]]*\]", " ", cleaned)
    cleaned = re.sub(r"(?i)\bcronoescalada\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bcronoescalada\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bpc\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bel\s+rail\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\btot\s+de\s+una\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bde\s+una\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bcruce\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bcartel\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bcanteras\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bchaparral\b", " Chaparral ", cleaned)
    cleaned = re.sub(r"(?i)\bgarbi\b", " Garbi ", cleaned)
    cleaned = re.sub(r"(?i)\boronet\b", " Oronet ", cleaned)
    cleaned = re.sub(r"(?i)\bl[’']?oronet\b", " Oronet ", cleaned)
    cleaned = re.sub(r"(?i)\bel\s+garb[ií]\b", " Garbi ", cleaned)
    cleaned = re.sub(r"(?i)\bserra\b", " ", cleaned)
    cleaned = re.sub(r"(?i)\bhg\b|\bdn\b", " ", cleaned)
    cleaned = re.sub(r"[^A-Za-zÀ-ÿ0-9/+ -]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -/")
    return cleaned


def _signals_belong_to_same_cluster(signal: RawRouteSignal, cluster: List[RawRouteSignal]) -> bool:
    centroid = sum(item.position for item in cluster) / len(cluster)
    if abs(signal.position - centroid) > 0.12:
        return False
    cluster_names = {_normalize_signal_name(item.name) for item in cluster}
    if signal.normalized_name in cluster_names:
        return True
    if any(_name_overlap(signal.normalized_name, existing) for existing in cluster_names):
        return True
    return False


def _name_overlap(a: str, b: str) -> bool:
    tokens_a = set(a.split())
    tokens_b = set(b.split())
    if not tokens_a or not tokens_b:
        return False
    intersection = tokens_a & tokens_b
    return len(intersection) >= max(1, min(len(tokens_a), len(tokens_b)) // 2)


def _pick_canonical_cluster_name(signals: List[RawRouteSignal]) -> str:
    preferred_label = _preferred_known_cluster_label(signals)
    if preferred_label is not None:
        return preferred_label

    candidates: List[tuple] = []
    for signal in signals:
        cleaned = _clean_signal_name(signal.name)
        for alias in [cleaned] + [_clean_signal_name(alias) for alias in signal.aliases]:
            normalized = _normalize_signal_name(alias)
            if not normalized:
                continue
            penalty = _noisy_name_penalty(alias)
            meaningful_tokens = _meaningful_tokens(alias)
            if not meaningful_tokens:
                continue
            display = _display_name_from_tokens(meaningful_tokens)
            score = signal.score - penalty + min(1.2, len(meaningful_tokens) * 0.25)
            if len(display) <= 2:
                score -= 2.0
            candidates.append((score, len(display), display))

    if not candidates:
        fallback = max(signals, key=lambda item: (item.score, len(item.name))).name
        return _clean_signal_name(fallback) or fallback

    candidates.sort(key=lambda item: (-item[0], item[1], item[2].lower()))
    top_names = [item[2] for item in candidates[:12]]

    if any("Oronet" == name for name in top_names) and any("Garbi" == name for name in top_names):
        return "Oronet - Garbi"
    return top_names[0]


def _preferred_known_cluster_label(signals: List[RawRouteSignal]) -> Optional[str]:
    bag = " ".join(
        _normalize_signal_name(part)
        for signal in signals
        for part in [signal.name] + list(signal.aliases)
        if part
    )
    if not bag:
        return None

    tokens = set(bag.split())
    if {"oronet", "garbi"} <= tokens:
        return "Oronet - Garbi"
    if {"sa", "calobra"} <= tokens or "calobra" in tokens:
        return "Sa Calobra"
    if "formentor" in tokens:
        return "Formentor"
    if "oronet" in tokens:
        return "Oronet"
    if "garbi" in tokens:
        return "Garbi"
    if "cullera" in tokens:
        return "Cullera"
    return None


def _noisy_name_penalty(value: str) -> float:
    penalty = 0.0
    lower = value.lower()
    if "\"" in value or "(" in value or ")" in value:
        penalty += 1.2
    if "\\" in value or "/" in value:
        penalty += 0.5
    if any(token in lower for token in ("cronoescalada", "cronoescalada", "pc ", "tot de una", "el rail")):
        penalty += 2.5
    if len(value) > 28:
        penalty += 0.8
    return penalty


def _meaningful_tokens(value: str) -> List[str]:
    raw_tokens = [token for token in re.split(r"[\s/+,-]+", value) if token]
    stopwords = {
        "de", "del", "la", "el", "l", "les", "los", "las", "y", "i",
        "hasta", "todo", "tot", "una", "en", "al", "a",
        "port", "puerto", "coll", "mirador", "faro",
    }
    result = []
    for token in raw_tokens:
        clean = token.strip()
        if not clean:
            continue
        if clean.lower() in stopwords:
            continue
        if len(clean) <= 2 and clean.lower() not in {"or", "sa"}:
            continue
        result.append(clean)
    return result


def _display_name_from_tokens(tokens: List[str]) -> str:
    normalized = []
    seen = set()
    for token in tokens:
        text = token[:1].upper() + token[1:].lower()
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    if not normalized:
        return ""
    if "Oronet" in normalized and "Garbi" in normalized:
        return "Oronet - Garbi"
    if len(normalized) >= 2 and normalized[0] != normalized[1]:
        joined = " - ".join(normalized[:2])
        if len(joined) <= 22:
            return joined
    return normalized[0]


def _pick_cluster_kind(signals: List[RawRouteSignal]) -> str:
    priority = {
        "climb_segment": 5,
        "mountain_pass": 5,
        "turnaround_place": 5,
        "peak": 4,
        "lighthouse": 4,
        "viewpoint": 3,
        "attraction": 3,
        "monument": 2,
        "segment": 1,
    }
    return max(signals, key=lambda item: priority.get(item.kind, 0)).kind


def _cluster_is_meaningful(cluster: RouteEntityCluster) -> bool:
    if cluster.kind in {"climb_segment", "mountain_pass", "peak", "lighthouse", "viewpoint", "turnaround_place"}:
        return True
    return cluster.score >= 4.5


def _segment_position(effort: Dict[str, Any]) -> float:
    start_index = effort.get("start_index")
    end_index = effort.get("end_index")
    if isinstance(start_index, int) and isinstance(end_index, int) and end_index >= start_index:
        midpoint = (start_index + end_index) / 2.0
        return min(1.0, max(0.0, midpoint / max(1.0, float(end_index + 1))))
    elapsed = effort.get("elapsed_time")
    moving = effort.get("moving_time") or elapsed
    if isinstance(elapsed, (int, float)) and isinstance(moving, (int, float)) and moving > 0:
        return min(1.0, max(0.0, float(elapsed) / float(moving)))
    return 0.5


def _segment_aliases(name: str) -> List[str]:
    aliases = [name]
    normalized = _normalize_signal_name(name)
    if normalized and normalized != name.lower():
        aliases.append(normalized.title())
    return aliases
