from __future__ import annotations

import re
from dataclasses import dataclass
import unicodedata
from typing import Iterable, List, Optional, Sequence, Tuple

from app.athlete_profile import AthleteProfile
from app.route_analysis import DetectedLandmark, OrderedHighlight, Point, ResolvedPlace, RouteSummary, haversine_m, sample_points
from app.title_candidates import TitleCandidate
from app.title_builders import NamingContext, build_loop_candidates, build_point_to_point_candidates, build_single_anchor_candidates
from app.title_validation import (
    is_generic_locality_highlight,
    is_specific_highlight,
    is_title_worthy_highlight,
    should_prefer_highlight_over_turnaround_name,
)


@dataclass(frozen=True)
class NamingDecision:
    title: Optional[str]
    confidence: float
    reason: str


def generate_title(summary: RouteSummary, athlete_profile: Optional[AthleteProfile] = None) -> NamingDecision:
    candidates = generate_title_candidates(summary, athlete_profile=athlete_profile)
    best = candidates[0]
    return NamingDecision(title=best.title, confidence=best.confidence, reason=best.reason)


def generate_title_candidates(
    summary: RouteSummary,
    athlete_profile: Optional[AthleteProfile] = None,
) -> List[TitleCandidate]:
    context = _build_naming_context(summary)
    if summary.is_loop:
        candidates = build_loop_candidates(context)
    elif context.start_name and context.end_name and context.start_name != context.end_name:
        candidates = build_point_to_point_candidates(context)
    else:
        candidates = build_single_anchor_candidates(context)
    return _apply_home_start_suppression(candidates, summary, athlete_profile)


def _build_naming_context(summary: RouteSummary) -> _NamingContext:
    start_name = _best_place_name(summary.start_place)
    end_name = _best_place_name(summary.end_place)
    turnaround_name = _turnaround_name(summary)
    turnaround_locality_name = _best_place_name(summary.turnaround_place)
    dominant_via_locality = _dominant_via_locality(summary, exclude={start_name, end_name})
    midpoint_via_locality = _midpoint_via_locality(summary, exclude={start_name, end_name})
    via_names = [_best_place_name(place) for place in summary.via_places]
    via_names = [name for name in via_names if name and name not in {start_name, end_name}]
    destination_locality = _pick_destination_locality(
        turnaround_locality_name=turnaround_locality_name,
        via_names=via_names,
        midpoint_via_locality=midpoint_via_locality,
        dominant_via_locality=dominant_via_locality,
        start_name=start_name,
        end_name=end_name,
    )
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
    return NamingContext(
        summary=summary,
        start_name=start_name,
        end_name=end_name,
        turnaround_name=turnaround_name,
        turnaround_locality_name=turnaround_locality_name,
        destination_locality=destination_locality,
        via_names=via_names,
        landmark=landmark,
        highlight=highlight,
        ordered_highlight_names=ordered_highlight_names,
        clean_highlight_names=clean_highlight_names,
        elongated_midpoint_name=elongated_midpoint_name,
        loop_shape=_classify_loop_shape(summary),
    )


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_place_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalize_text(ascii_only)


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
    return _canonical_anchor_name(name)


def _best_highlight_name(summary: RouteSummary) -> Optional[str]:
    if summary.ordered_highlights:
        name = summary.ordered_highlights[0].name.strip()
        if name:
            return _canonical_anchor_name(name)
    if not summary.highlights:
        return None
    name = summary.highlights[0].name.strip()
    if not name:
        return None
    return _canonical_anchor_name(name)


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
        if has_composite and is_generic_locality_highlight(name):
            continue
        if not is_title_worthy_highlight(name):
            continue
        seen.add(normalized)
        cleaned.append(name)
    return cleaned


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
        name = _canonical_anchor_name(cleaned)
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
    if turnaround_position is not None and compactness >= 2.65 and not 0.43 <= turnaround_position <= 0.57:
        return "branched"
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


def _pick_destination_locality(
    turnaround_locality_name: Optional[str],
    via_names: Sequence[str],
    midpoint_via_locality: Optional[str],
    dominant_via_locality: Optional[str],
    start_name: Optional[str],
    end_name: Optional[str],
) -> Optional[str]:
    if (
        turnaround_locality_name
        and turnaround_locality_name not in {start_name, end_name}
        and len(via_names) >= 2
        and normalize_text(via_names[-1]) == normalize_text(turnaround_locality_name)
    ):
        return turnaround_locality_name
    return midpoint_via_locality or dominant_via_locality


def _apply_home_start_suppression(
    candidates: Sequence[TitleCandidate],
    summary: RouteSummary,
    athlete_profile: Optional[AthleteProfile],
) -> List[TitleCandidate]:
    if not candidates:
        return list(candidates)
    if not _should_omit_home_start(summary.start_place, athlete_profile):
        return list(candidates)

    start_name = _best_place_name(summary.start_place)
    if not start_name:
        return list(candidates)

    rewritten: List[TitleCandidate] = []
    for candidate in candidates:
        rewritten.append(_candidate_without_start(candidate, start_name))
    return rewritten


def _should_omit_home_start(
    start_place: Optional[ResolvedPlace],
    athlete_profile: Optional[AthleteProfile],
) -> bool:
    if start_place is None or athlete_profile is None or not athlete_profile.city:
        return False

    start_candidates = [value for value in (start_place.locality, start_place.district, start_place.suburb) if value]
    if not start_candidates:
        return False

    home_key = normalize_place_key(athlete_profile.city)
    return any(normalize_place_key(value) == home_key for value in start_candidates)


def _candidate_without_start(candidate: TitleCandidate, start_name: str) -> TitleCandidate:
    if not candidate.title:
        return candidate

    title = candidate.title.strip()
    parts = [part.strip() for part in title.split(" - ") if part.strip()]
    if len(parts) >= 2 and normalize_place_key(parts[0]) == normalize_place_key(start_name):
        remainder = " - ".join(parts[1:]).strip()
        if remainder and normalize_place_key(remainder) not in {"loop"}:
            return TitleCandidate(
                title=remainder,
                confidence=candidate.confidence,
                reason=f"{candidate.reason}; omitted home-city start",
            )
    return candidate


def _should_prefer_highlights_over_destination(summary: RouteSummary, destination_locality: Optional[str]) -> bool:
    if len(summary.ordered_highlights) >= 2:
        if all(is_specific_highlight(item.name, destination_locality) for item in summary.ordered_highlights[:2]):
            return True
    if summary.ordered_highlights:
        best = summary.ordered_highlights[0]
        if (
            best.kind in {"climb_segment", "mountain_pass", "peak", "lighthouse"}
            and best.score >= 12.0
            and is_specific_highlight(best.name, destination_locality)
        ):
            return True
    return False


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
        if is_generic_locality_highlight(name):
            continue
        if not is_title_worthy_highlight(name):
            continue
        return name
    return None


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
    if category in {"attraction", "viewpoint", "archaeological_site"}:
        if turnaround_locality.lower() not in highlight_name.lower():
            return True
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


def _canonical_anchor_name(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    lowered = normalized.lower()
    prefixes = (
        "alto de ",
        "alt de ",
        "puerto de ",
        "puerto del ",
        "puerto d'",
        "port de ",
        "port del ",
        "port d'",
        "mirador de ",
        "faro de ",
        "el faro de ",
        "cap de ",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            normalized = normalized[len(prefix):].strip()
            break
    normalized = re.sub(r"^(l|d)[’']", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"^(l|el|la|les|los)\s+", "", normalized, flags=re.IGNORECASE)
    return _title_case(normalized)
