from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from app.config import Settings
from app.route_analysis import DetectedLandmark, Point, ResolvedPlace, RouteSummary, haversine_m, sample_points


@dataclass(frozen=True)
class NamingDecision:
    title: Optional[str]
    confidence: float
    reason: str


def generate_title(summary: RouteSummary) -> NamingDecision:
    start_name = _best_place_name(summary.start_place)
    end_name = _best_place_name(summary.end_place)
    turnaround_name = _turnaround_name(summary)
    dominant_via_locality = _dominant_via_locality(summary, exclude={start_name, end_name})
    midpoint_via_locality = _midpoint_via_locality(summary, exclude={start_name, end_name})
    destination_locality = midpoint_via_locality or dominant_via_locality
    via_names = [_best_place_name(place) for place in summary.via_places]
    via_names = [name for name in via_names if name and name not in {start_name, end_name}]
    landmark = _clean_landmark(summary.landmark)
    highlight = _best_highlight_name(summary)
    ordered_highlight_names = _ordered_highlight_names(summary)
    clean_highlight_names = _clean_ordered_highlight_names(
        ordered_highlight_names,
        excluded={start_name, end_name, turnaround_name, destination_locality},
    )
    elongated_midpoint_name = _best_elongated_midpoint_name(
        via_names=via_names,
        destination_locality=destination_locality,
        ordered_highlight_names=ordered_highlight_names,
        start_name=start_name,
        end_name=end_name,
        turnaround_name=turnaround_name,
    )
    loop_shape = _classify_loop_shape(summary)

    if summary.is_loop:
        if loop_shape == "ring":
            loop_points = _build_loop_points_title(
                anchor_name=start_name,
                highlight_names=clean_highlight_names,
                max_highlights=3,
            )
            if loop_points is not None:
                return NamingDecision(
                    title=loop_points,
                    confidence=0.96,
                    reason="ring-like loop route with multiple ordered route highlights",
                )
        if loop_shape == "elongated":
            elongated_title = _build_elongated_loop_title(
                start_name=start_name,
                turnaround_name=turnaround_name,
                midpoint_name=elongated_midpoint_name,
                ordered_highlight_names=clean_highlight_names,
            )
            if elongated_title is not None:
                return NamingDecision(
                    title=elongated_title,
                    confidence=0.96,
                    reason="elongated loop route focused on its farthest destination",
                )
        if destination_locality and not _should_prefer_highlights_over_destination(summary, destination_locality):
            return NamingDecision(
                title=_trim_title(destination_locality),
                confidence=0.95,
                reason="loop route with a destination locality inferred from mid-route samples",
            )
        if start_name and turnaround_name and turnaround_name not in {start_name, end_name}:
            return NamingDecision(
                title=_trim_title(f"{start_name} - {turnaround_name}"),
                confidence=0.96,
                reason="loop route with a distinct turnaround destination",
            )
        if start_name and len(clean_highlight_names) >= 2:
            joined = _trim_title(f"{start_name} - {clean_highlight_names[0]} - {clean_highlight_names[1]}")
            if len(joined) <= 48:
                return NamingDecision(
                    title=joined,
                    confidence=0.95,
                    reason="loop route with two ordered high-signal route highlights",
                )
        if start_name and highlight and " - " in highlight:
            return NamingDecision(
                title=_trim_title(f"{start_name} - {highlight}"),
                confidence=0.94,
                reason="loop route with a composite high-signal route highlight",
            )
        if start_name and highlight and highlight != start_name:
            return NamingDecision(
                title=_trim_title(f"{start_name} - {highlight} Loop"),
                confidence=0.92,
                reason="loop route with a highly ranked route highlight",
            )
        if start_name and landmark and landmark != start_name:
            return NamingDecision(
                title=_trim_title(f"{start_name} - {landmark} Loop"),
                confidence=0.88,
                reason="loop route with recognizable landmark",
            )
        if start_name and via_names:
            return NamingDecision(
                title=_trim_title(f"{start_name} - {via_names[0]} Loop"),
                confidence=0.80,
                reason="loop route with distinct via locality",
            )
        if start_name:
            return NamingDecision(
                title=_trim_title(f"{start_name} Loop"),
                confidence=0.72,
                reason="loop route with city-level start location only",
            )
        if len(clean_highlight_names) >= 2:
            return NamingDecision(
                title=_trim_title(f"{clean_highlight_names[0]} - {clean_highlight_names[1]}"),
                confidence=0.83,
                reason="loop route without locality anchor but with two ordered route highlights",
            )
        if highlight:
            return NamingDecision(
                title=_trim_title(highlight),
                confidence=0.79,
                reason="loop route without locality anchor but with a strong route highlight",
            )
        return NamingDecision(None, 0.20, "loop route lacked a stable locality anchor")

    if start_name and end_name and start_name != end_name:
        if highlight and highlight not in {start_name, end_name}:
            title = _trim_title(f"{start_name} - {highlight} - {end_name}")
            if len(title) <= 48:
                return NamingDecision(
                    title=title,
                    confidence=0.94,
                    reason="point-to-point route with a highly ranked route highlight",
                )
        three_point = _compact_three_point_title(start_name, via_names, end_name)
        if three_point is not None:
            return NamingDecision(
                title=three_point,
                confidence=0.91,
                reason="point-to-point route with two endpoints and one meaningful midpoint",
            )
        return NamingDecision(
            title=_trim_title(f"{start_name} - {end_name}"),
            confidence=0.93,
            reason="point-to-point route with distinct endpoints",
        )

    if start_name and highlight and highlight != start_name:
        return NamingDecision(
            title=_trim_title(f"{start_name} - {highlight}"),
            confidence=0.89,
            reason="route anchored by one locality and one highly ranked route highlight",
        )

    if start_name and landmark and landmark != start_name:
        return NamingDecision(
            title=_trim_title(f"{start_name} - {landmark}"),
            confidence=0.84,
            reason="route anchored by one locality and one landmark",
        )

    if start_name and via_names:
        return NamingDecision(
            title=_trim_title(f"{start_name} - {via_names[0]}"),
            confidence=0.78,
            reason="route anchored by one locality and one via locality",
        )

    return NamingDecision(None, 0.35, "insufficient route context for a compact deterministic title")


def should_rename_activity(
    current_name: Optional[str],
    decision: NamingDecision,
    sport_type: str,
    settings: Settings,
) -> Tuple[bool, str]:
    if not decision.title:
        return False, "no generated title"
    if decision.confidence < settings.confidence_threshold:
        return False, f"confidence {decision.confidence:.2f} below threshold {settings.confidence_threshold:.2f}"
    if current_name and normalize_text(current_name) == normalize_text(decision.title):
        return False, "activity already has the generated title"
    if current_name and not settings.overwrite_manual_titles and is_manual_title(current_name, sport_type, settings):
        return False, "activity appears to have been manually renamed already"
    return True, "eligible for rename"


def is_manual_title(current_name: str, sport_type: str, settings: Settings) -> bool:
    normalized = normalize_text(current_name)
    if not normalized:
        return False
    if normalized in settings.default_title_allowlist:
        return False
    generic_kind = "run" if sport_type == "Run" else "ride"
    if normalized == generic_kind:
        return False
    return True


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _best_place_name(place: Optional[ResolvedPlace]) -> Optional[str]:
    if place is None:
        return None
    for candidate in (place.locality, place.district, place.suburb):
        if candidate:
            return _title_case(candidate)
    return None


def _clean_landmark(landmark: Optional[DetectedLandmark]) -> Optional[str]:
    if landmark is None:
        return None
    name = re.sub(r"\s+", " ", landmark.name).strip()
    if not name:
        return None
    return _title_case(name)


def _best_highlight_name(summary: RouteSummary) -> Optional[str]:
    if summary.ordered_highlights:
        name = summary.ordered_highlights[0].name.strip()
        if name:
            return _title_case(name)
    if not summary.highlights:
        return None
    name = summary.highlights[0].name.strip()
    if not name:
        return None
    return _title_case(name)


def _ordered_highlight_names(summary: RouteSummary) -> List[str]:
    names: List[str] = []
    seen = set()
    for item in summary.ordered_highlights:
        name = _title_case(item.name.strip())
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def _clean_ordered_highlight_names(names: Sequence[str], excluded: set[Optional[str]]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    excluded_keys = {normalize_text(value) for value in excluded if value}
    has_composite = any(" - " in name for name in names if name)
    for name in names:
        normalized = normalize_text(name)
        if not normalized or normalized in seen:
            continue
        if normalized in excluded_keys:
            continue
        if any(excluded_key in normalized or normalized in excluded_key for excluded_key in excluded_keys):
            continue
        if has_composite and _is_generic_locality_highlight(name):
            continue
        if not _is_title_worthy_highlight(name):
            continue
        seen.add(normalized)
        cleaned.append(name)
    return cleaned


def _build_loop_points_title(anchor_name: Optional[str], highlight_names: Sequence[str], max_highlights: int) -> Optional[str]:
    candidates = [name for name in highlight_names if name and name != anchor_name]
    if not candidates:
        return None

    for highlight_count in range(min(max_highlights, len(candidates)), 1, -1):
        parts = ([anchor_name] if anchor_name else []) + list(candidates[:highlight_count])
        title = _trim_title(" - ".join(part for part in parts if part))
        if len(title) <= 48:
            return title

    if anchor_name:
        title = _trim_title(f"{anchor_name} - {candidates[0]}")
        if len(title) <= 48:
            return title
    single = _trim_title(candidates[0])
    if len(single) <= 48:
        return single
    return None


def _build_elongated_loop_title(
    start_name: Optional[str],
    turnaround_name: Optional[str],
    midpoint_name: Optional[str],
    ordered_highlight_names: Sequence[str],
) -> Optional[str]:
    if not turnaround_name:
        return None

    if midpoint_name and midpoint_name not in {start_name, turnaround_name}:
        parts = [part for part in (start_name, midpoint_name, turnaround_name) if part]
        title = _trim_title(" - ".join(parts))
        if len(title) <= 48:
            return title

    distinct_highlights = [
        name
        for name in ordered_highlight_names
        if name and name not in {start_name, turnaround_name}
    ]
    if distinct_highlights and _should_prefer_highlight_over_turnaround_name(distinct_highlights[0], turnaround_name):
        if start_name:
            title = _trim_title(f"{start_name} - {distinct_highlights[0]}")
            if len(title) <= 48:
                return title
        title = _trim_title(distinct_highlights[0])
        if len(title) <= 48:
            return title
    for candidate in distinct_highlights[:1]:
        parts = [part for part in (start_name, candidate, turnaround_name) if part]
        title = _trim_title(" - ".join(parts))
        if len(title) <= 48:
            return title

    if start_name and turnaround_name != start_name:
        title = _trim_title(f"{start_name} - {turnaround_name}")
        if len(title) <= 48:
            return title
    title = _trim_title(turnaround_name)
    if len(title) <= 48:
        return title
    return None


def _turnaround_name(summary: RouteSummary) -> Optional[str]:
    turnaround_locality = None
    if summary.turnaround_place is not None:
        for candidate in (
            summary.turnaround_place.locality,
            summary.turnaround_place.district,
            summary.turnaround_place.suburb,
        ):
            if candidate:
                turnaround_locality = _title_case(candidate)
                break

    if summary.turnaround_highlight is not None:
        cleaned = re.sub(r"\s+", " ", summary.turnaround_highlight.name.replace('"', " ").strip())
        name = _title_case(cleaned)
        if name:
            if turnaround_locality and _should_prefer_turnaround_locality(summary, turnaround_locality):
                return turnaround_locality
            return name
    return turnaround_locality


def _classify_loop_shape(summary: RouteSummary) -> str:
    if not summary.is_loop or len(summary.points) < 4:
        return "mixed"

    diameter = _route_diameter_m(summary.points)
    if diameter <= 0:
        return "mixed"

    compactness = summary.total_distance_m / diameter
    turnaround_position = summary.turnaround_position
    if compactness >= 2.65:
        return "ring"
    if compactness <= 2.25:
        return "elongated"
    if turnaround_position is not None and 0.43 <= turnaround_position <= 0.57 and compactness <= 2.45:
        return "elongated"
    return "mixed"


def _route_diameter_m(points: Sequence[Point]) -> float:
    sampled = sample_points(points, count=min(12, len(points)), include_ends=True)
    best = 0.0
    for idx, first in enumerate(sampled):
        for second in sampled[idx + 1 :]:
            best = max(best, haversine_m(first, second))
    return best


def _dominant_via_locality(summary: RouteSummary, exclude: set) -> Optional[str]:
    counts = {}
    canonical = {}
    for place in summary.via_places:
        name = _best_place_name(place)
        if not name or name in exclude:
            continue
        key = name.lower()
        counts[key] = counts.get(key, 0) + 1
        canonical[key] = name
    if not counts:
        return None
    top_key, top_count = max(counts.items(), key=lambda item: (item[1], len(item[0])))
    if top_count >= 2:
        return canonical[top_key]
    return None


def _midpoint_via_locality(summary: RouteSummary, exclude: set) -> Optional[str]:
    names = []
    for place in summary.via_places:
        name = _best_place_name(place)
        if not name or name in exclude:
            continue
        names.append(name)
    if len(names) < 2:
        return None
    return names[len(names) // 2]


def _should_prefer_highlights_over_destination(summary: RouteSummary, destination_locality: Optional[str]) -> bool:
    if len(summary.ordered_highlights) >= 2:
        if all(_is_specific_highlight(item.name, destination_locality) for item in summary.ordered_highlights[:2]):
            return True
    if summary.ordered_highlights:
        best = summary.ordered_highlights[0]
        if (
            best.kind in {"climb_segment", "mountain_pass", "peak", "lighthouse"}
            and best.score >= 12.0
            and _is_specific_highlight(best.name, destination_locality)
        ):
            return True
    return False


def _is_specific_highlight(name: str, destination_locality: Optional[str]) -> bool:
    normalized = normalize_text(name).replace("-", " ")
    if destination_locality and normalize_text(destination_locality) in normalized:
        return False
    generic_tokens = {
        "calle", "camino", "desde", "climb", "full", "ftp", "gcm", "rot", "rotonda",
        "sedavi", "saler", "parte", "muro", "delfines", "via", "este", "juto", "sep",
        "ultimos", "lookout", "corner",
    }
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    meaningful = [token for token in tokens if token not in generic_tokens]
    return len(meaningful) >= 1 and len(meaningful) >= len(tokens) / 2


def _is_title_worthy_highlight(name: str) -> bool:
    normalized = normalize_text(name).replace("-", " ")
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    generic_tokens = {
        "331", "500", "barraca", "btt", "calle", "camino", "carrefour", "castillo",
        "climb", "conos", "corner", "corral", "cuarteles", "cumbre", "delfines",
        "desde", "este", "juto", "lookout", "parte", "poligono", "rotonda",
        "rot", "saler", "sep", "slalom", "subida", "ultimos", "vallesa", "vamos",
        "via", "vía",
    }
    meaningful = [token for token in tokens if token not in generic_tokens and not token.isdigit()]
    if not meaningful:
        return False
    if len(tokens) >= 5:
        return False
    if len(tokens) >= 4 and len(meaningful) < 2:
        return False
    if any(token in {"lookout", "corner", "carrefour", "rotonda", "rot"} for token in tokens):
        return False
    return True


def _best_elongated_midpoint_name(
    via_names: Sequence[str],
    destination_locality: Optional[str],
    ordered_highlight_names: Sequence[str],
    start_name: Optional[str],
    end_name: Optional[str],
    turnaround_name: Optional[str],
) -> Optional[str]:
    if destination_locality and destination_locality not in {start_name, end_name, turnaround_name}:
        return destination_locality
    for name in ordered_highlight_names:
        if not name or name in {start_name, end_name, turnaround_name}:
            continue
        if turnaround_name:
            normalized_turnaround = normalize_text(turnaround_name)
            normalized_name = normalize_text(name)
            if normalized_turnaround in normalized_name or normalized_name in normalized_turnaround:
                continue
        if _is_generic_locality_highlight(name):
            continue
        if not _is_title_worthy_highlight(name):
            continue
        return name
    return None


def _should_prefer_highlight_over_turnaround_name(highlight_name: str, turnaround_name: Optional[str]) -> bool:
    if not turnaround_name:
        return False
    normalized_turnaround = normalize_text(turnaround_name).replace("-", " ")
    normalized_highlight = normalize_text(highlight_name).replace("-", " ")
    if not normalized_highlight or normalized_turnaround in normalized_highlight:
        return False
    turnaround_tokens = [token for token in normalized_turnaround.split() if token]
    if len(turnaround_tokens) != 1:
        return False
    if " - " not in highlight_name:
        return False
    generic_turnarounds = {
        "serra", "naquera", "náquera", "sueca", "escorca", "raiguer",
    }
    return turnaround_tokens[0] in generic_turnarounds


def _is_generic_locality_highlight(name: str) -> bool:
    normalized = normalize_text(name).replace("-", " ")
    tokens = [token for token in normalized.split() if token]
    if len(tokens) != 1:
        return False
    return tokens[0] in {"serra", "sueca", "escorca", "raiguer", "naquera", "náquera"}


def _should_prefer_turnaround_locality(summary: RouteSummary, turnaround_locality: str) -> bool:
    highlight = summary.turnaround_highlight
    if highlight is None:
        return False
    category = (highlight.category or "").lower()
    distance_m = highlight.distance_m or 0.0
    highlight_name = highlight.name.strip()
    clean_highlight = _title_case(re.sub(r"\s+", " ", highlight_name.replace('"', "")).strip())

    if category in {"climb_segment", "mountain_pass", "peak", "lighthouse"}:
        return False
    if clean_highlight and clean_highlight.lower() not in turnaround_locality.lower():
        if len(clean_highlight) <= 24 and category not in {"castle", "monument", "attraction", "viewpoint"}:
            return False
    if turnaround_locality.lower() in highlight.name.strip().lower():
        return True
    if category in {"castle", "monument", "attraction", "viewpoint"}:
        return True
    if distance_m >= 800 and category not in {"lighthouse", "peak", "mountain_pass"}:
        return True
    return False


def _compact_three_point_title(start_name: str, via_names: Sequence[str], end_name: str) -> Optional[str]:
    for candidate in via_names[:2]:
        title = _trim_title(f"{start_name} - {candidate} - {end_name}")
        if len(title) <= 44:
            return title
    return None


def _trim_title(title: str, max_length: int = 48) -> str:
    compact = re.sub(r"\s+", " ", title).strip(" -")
    if len(compact) <= max_length:
        return compact
    return compact[: max_length - 3].rstrip(" -") + "..."


def _title_case(value: str) -> str:
    words = value.strip().split()
    if not words:
        return value
    return " ".join(word[:1].upper() + word[1:] for word in words)
