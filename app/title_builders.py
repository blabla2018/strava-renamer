from __future__ import annotations

import re
from dataclasses import dataclass
import unicodedata
from typing import List, Optional, Sequence

from app.route_analysis import OrderedHighlight, RouteHighlight, RouteSummary
from app.title_candidates import TitleCandidate
from app.title_validation import (
    is_specific_highlight,
    is_title_worthy_highlight,
    should_prefer_highlight_over_turnaround_name,
)


@dataclass(frozen=True)
class NamingContext:
    summary: RouteSummary
    start_name: Optional[str]
    end_name: Optional[str]
    turnaround_name: Optional[str]
    turnaround_locality_name: Optional[str]
    destination_locality: Optional[str]
    via_names: List[str]
    landmark: Optional[str]
    highlight: Optional[str]
    ordered_highlight_names: List[str]
    clean_highlight_names: List[str]
    elongated_midpoint_name: Optional[str]
    loop_shape: str


def build_loop_candidates(context: NamingContext) -> List[TitleCandidate]:
    candidates: List[TitleCandidate] = []
    prefer_highlights_over_destination = _should_prefer_highlights_over_destination(
        context.summary,
        context.destination_locality,
    )

    if context.loop_shape == "branched":
        branched_title = _build_branched_loop_title(
            start_name=context.start_name,
            turnaround_name=context.turnaround_name,
            turnaround_locality_name=context.turnaround_locality_name,
            ordered_highlights=context.summary.ordered_highlights,
            route_highlights=context.summary.highlights,
            excluded={context.start_name, context.end_name},
        )
        if branched_title is not None:
            _append_candidate(candidates, TitleCandidate(
                title=branched_title,
                confidence=0.96,
                reason="branched loop route anchored by a turnaround locality and a distinct branch highlight",
            ))
    if context.loop_shape == "ring":
        should_use_loop_points = False
        if context.destination_locality is None and context.clean_highlight_names:
            should_use_loop_points = True
        elif len(context.clean_highlight_names) >= 2 and prefer_highlights_over_destination:
            should_use_loop_points = True
        if should_use_loop_points:
            loop_points = _build_loop_points_title(
                anchor_name=context.start_name,
                highlight_names=context.clean_highlight_names,
                max_highlights=3,
            )
            if loop_points is not None:
                _append_candidate(candidates, TitleCandidate(
                    title=loop_points,
                    confidence=0.96,
                    reason="ring-like loop route with multiple ordered route highlights",
                ))
    if context.loop_shape == "elongated":
        elongated_title = _build_elongated_loop_title(
            start_name=context.start_name,
            turnaround_name=context.turnaround_name,
            midpoint_name=context.elongated_midpoint_name,
            ordered_highlight_names=context.clean_highlight_names,
        )
        if elongated_title is not None:
            _append_candidate(candidates, TitleCandidate(
                title=elongated_title,
                confidence=0.96,
                reason="elongated loop route focused on its farthest destination",
            ))
    long_multi_anchor_title = _build_long_loop_multi_anchor_title(context)
    if long_multi_anchor_title is not None:
        _append_candidate(candidates, TitleCandidate(
            title=long_multi_anchor_title,
            confidence=0.955,
            reason="long loop route with multiple meaningful route anchors",
        ))
    late_secondary_anchor_title = _build_late_secondary_anchor_title(context)
    if late_secondary_anchor_title is not None:
        _append_candidate(candidates, TitleCandidate(
            title=late_secondary_anchor_title,
            confidence=0.955,
            reason="loop route with a late repeated secondary anchor tied to the primary route anchor",
        ))
    skip_destination_for_primary_highlights = (
        _has_primary_turnaround_landmark(context)
        or (context.loop_shape == "ring" and prefer_highlights_over_destination)
    )
    if context.destination_locality and not skip_destination_for_primary_highlights:
        if context.start_name and context.destination_locality != context.start_name:
            _append_candidate(candidates, TitleCandidate(
                title=_trim_title(f"{context.start_name} - {context.destination_locality}"),
                confidence=0.95,
                reason="loop route with a destination locality inferred from mid-route samples",
            ))
        else:
            _append_candidate(candidates, TitleCandidate(
                title=_trim_title(context.destination_locality),
                confidence=0.95,
                reason="loop route with a destination locality inferred from mid-route samples",
            ))
    if context.start_name and context.turnaround_name and context.turnaround_name not in {context.start_name, context.end_name}:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.turnaround_name}"),
            confidence=0.96,
            reason="loop route with a distinct turnaround destination",
        ))
    if context.start_name and len(context.clean_highlight_names) >= 2:
        joined = _trim_title(f"{context.start_name} - {context.clean_highlight_names[0]} - {context.clean_highlight_names[1]}")
        if len(joined) <= 48:
            _append_candidate(candidates, TitleCandidate(
                title=joined,
                confidence=0.95,
                reason="loop route with two ordered high-signal route highlights",
            ))
    if context.start_name and context.highlight and " - " in context.highlight:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.highlight}"),
            confidence=0.94,
            reason="loop route with a composite high-signal route highlight",
        ))
    if context.start_name and context.highlight and context.highlight != context.start_name:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.highlight} Loop"),
            confidence=0.92,
            reason="loop route with a highly ranked route highlight",
        ))
    if context.start_name and context.landmark and context.landmark != context.start_name:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.landmark} Loop"),
            confidence=0.88,
            reason="loop route with recognizable landmark",
        ))
    if context.start_name and context.via_names:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.via_names[0]} Loop"),
            confidence=0.80,
            reason="loop route with distinct via locality",
        ))
    if context.start_name:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} Loop"),
            confidence=0.72,
            reason="loop route with city-level start location only",
        ))
    if len(context.clean_highlight_names) >= 2:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.clean_highlight_names[0]} - {context.clean_highlight_names[1]}"),
            confidence=0.83,
            reason="loop route without locality anchor but with two ordered route highlights",
        ))
    if context.highlight:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(context.highlight),
            confidence=0.79,
            reason="loop route without locality anchor but with a strong route highlight",
        ))
    if not candidates:
        _append_candidate(candidates, TitleCandidate(None, 0.20, "loop route lacked a stable locality anchor"))
    return candidates


def build_point_to_point_candidates(context: NamingContext) -> List[TitleCandidate]:
    candidates: List[TitleCandidate] = []

    if context.highlight and context.highlight not in {context.start_name, context.end_name}:
        title = _trim_title(f"{context.start_name} - {context.highlight} - {context.end_name}")
        if len(title) <= 48:
            _append_candidate(candidates, TitleCandidate(
                title=title,
                confidence=0.94,
                reason="point-to-point route with a highly ranked route highlight",
            ))
    three_point = _compact_three_point_title(context.start_name or "", context.via_names, context.end_name or "")
    if three_point is not None:
        _append_candidate(candidates, TitleCandidate(
            title=three_point,
            confidence=0.91,
            reason="point-to-point route with two endpoints and one meaningful midpoint",
        ))
    _append_candidate(candidates, TitleCandidate(
        title=_trim_title(f"{context.start_name} - {context.end_name}"),
        confidence=0.93,
        reason="point-to-point route with distinct endpoints",
    ))
    return candidates


def build_single_anchor_candidates(context: NamingContext) -> List[TitleCandidate]:
    candidates: List[TitleCandidate] = []

    if _is_short_intra_city_route(context):
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(context.start_name),
            confidence=0.74,
            reason="short urban route stayed within one city and lacked a stable destination anchor",
        ))
        return candidates

    if context.start_name and context.highlight and context.highlight != context.start_name:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.highlight}"),
            confidence=0.89,
            reason="route anchored by one locality and one highly ranked route highlight",
        ))
    if context.start_name and context.landmark and context.landmark != context.start_name:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.landmark}"),
            confidence=0.84,
            reason="route anchored by one locality and one landmark",
        ))
    if context.start_name and context.via_names:
        _append_candidate(candidates, TitleCandidate(
            title=_trim_title(f"{context.start_name} - {context.via_names[0]}"),
            confidence=0.78,
            reason="route anchored by one locality and one via locality",
        ))
    if not candidates:
        _append_candidate(candidates, TitleCandidate(None, 0.35, "insufficient route context for a compact deterministic title"))
    return candidates


def _is_short_intra_city_route(context: NamingContext) -> bool:
    if not context.start_name:
        return False
    if context.summary.is_loop:
        return False
    if context.summary.total_distance_m > 15_000:
        return False
    if context.end_name and context.end_name != context.start_name:
        return False
    if context.turnaround_name and context.turnaround_name != context.start_name:
        return False
    if context.destination_locality and context.destination_locality != context.start_name:
        return False
    if context.via_names:
        return False
    return True


def _append_candidate(candidates: List[TitleCandidate], candidate: TitleCandidate) -> None:
    candidates.append(candidate)


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


def _build_long_loop_multi_anchor_title(context: NamingContext) -> Optional[str]:
    if not context.summary.is_loop or context.summary.total_distance_m < 70_000:
        return None
    if _has_primary_turnaround_landmark(context):
        return None

    destination = _primary_loop_destination(context)
    if destination is None:
        return None

    excluded = {context.start_name, context.end_name, destination, context.turnaround_name}
    highlight = _best_strong_loop_anchor_highlight(context.summary.ordered_highlights, excluded=excluded)
    if highlight is None:
        return None
    parts: List[str] = []
    parts.append(highlight)
    parts.append(destination)

    via_after_destination = _next_distinct_via_after(
        context.via_names,
        destination,
        excluded=set(parts) | {context.start_name, context.end_name, context.turnaround_name},
    )
    if via_after_destination is not None:
        parts.append(via_after_destination)

    parts = _dedupe_title_parts(parts)
    if len(parts) < 2:
        return None
    title_parts = ([context.start_name] if context.start_name else []) + parts[:3]
    title = _trim_title(" - ".join(part for part in title_parts if part))
    return title or None


def _has_primary_turnaround_landmark(context: NamingContext) -> bool:
    if not context.turnaround_name or not context.summary.ordered_highlights:
        return False
    first = context.summary.ordered_highlights[0]
    if first.kind not in {"mountain_pass", "peak", "lighthouse"}:
        return False
    return _normalize_text(first.name) == _normalize_text(context.turnaround_name)


def _primary_loop_destination(context: NamingContext) -> Optional[str]:
    for candidate in (context.destination_locality, context.turnaround_name):
        if not candidate:
            continue
        if candidate in {context.start_name, context.end_name}:
            continue
        return candidate
    return None


def _build_late_secondary_anchor_title(context: NamingContext) -> Optional[str]:
    if not context.summary.is_loop:
        return None
    primary = _primary_anchor_for_late_secondary(context)
    if primary is None:
        return None
    secondary = _late_secondary_anchor_from_primary_cluster(context, primary)
    if secondary is None:
        return None
    parts = _dedupe_title_parts([part for part in (primary, secondary) if part])
    if len(parts) < 2:
        return None
    title_parts = ([context.start_name] if context.start_name else []) + parts
    title = _trim_title(" - ".join(title_parts))
    if len(title) <= 48:
        return title
    return None


def _primary_anchor_for_late_secondary(context: NamingContext) -> Optional[str]:
    if not _has_primary_turnaround_landmark(context):
        return None
    if context.turnaround_name in {context.start_name, context.end_name}:
        return None
    return context.turnaround_name


def _late_secondary_anchor_from_primary_cluster(context: NamingContext, primary: str) -> Optional[str]:
    primary_key = _normalize_token_key(primary)
    if not primary_key:
        return None
    excluded = _excluded_secondary_anchor_tokens(context, primary)
    records: dict[str, dict] = {}
    for cluster in context.summary.clusters:
        if cluster.position_centroid < 0.70:
            continue
        if _normalize_token_key(cluster.canonical_name) != primary_key:
            continue
        if cluster.score < 12.0:
            continue
        aliases = [cluster.canonical_name] + list(cluster.aliases)
        if not any(primary_key in _secondary_anchor_tokens(alias) for alias in aliases):
            continue
        for alias in aliases:
            tokens = _secondary_anchor_tokens(alias)
            if not tokens:
                continue
            mentions_primary = primary_key in tokens
            for token in set(tokens):
                if token == primary_key or token in excluded:
                    continue
                record = records.setdefault(
                    token,
                    {
                        "display": _title_case(token),
                        "cooccurrence_support": 0,
                        "before_primary_support": 0,
                        "after_primary_support": 0,
                        "total_support": 0,
                        "best_score": 0.0,
                        "max_position": 0.0,
                    },
                )
                record["total_support"] += 1
                record["best_score"] = max(record["best_score"], cluster.score)
                record["max_position"] = max(record["max_position"], cluster.position_centroid)
                if mentions_primary:
                    record["cooccurrence_support"] += 1
                    primary_index = tokens.index(primary_key)
                    token_index = tokens.index(token)
                    if token_index < primary_index:
                        record["before_primary_support"] += 1
                    elif token_index > primary_index:
                        record["after_primary_support"] += 1
    candidates = [
        record
        for record in records.values()
        if (
            record["before_primary_support"] >= 1
            and record["after_primary_support"] >= 1
            and record["cooccurrence_support"] >= 2
            and record["total_support"] >= 3
        )
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            -item["cooccurrence_support"],
            -min(item["before_primary_support"], item["after_primary_support"]),
            -item["total_support"],
            -item["best_score"],
            -item["max_position"],
            item["display"].lower(),
        )
    )
    return candidates[0]["display"]


def _excluded_secondary_anchor_tokens(context: NamingContext, primary: str) -> set[str]:
    excluded_values = [
        context.start_name,
        context.end_name,
        context.turnaround_name,
        context.turnaround_locality_name,
        context.destination_locality,
        primary,
        *context.via_names,
    ]
    excluded: set[str] = set()
    for value in excluded_values:
        if not value:
            continue
        excluded.update(_secondary_anchor_tokens(value))
        excluded.add(_normalize_token_key(value))
    return {token for token in excluded if token}


def _secondary_anchor_tokens(value: str) -> List[str]:
    normalized = _normalize_token_key(value)
    raw_tokens = [token for token in re.split(r"[\s/+,-]+", normalized) if token]
    stopwords = {
        "alto", "alt", "aso", "atw", "bajada", "base", "byjps", "calle", "camino",
        "carrer", "carretera", "climb", "crono", "cronoescalada", "cruce", "desde",
        "descanso", "descenso", "duro", "ele", "entrada", "final", "font", "fuente",
        "hasta", "ida", "inicio", "jp", "las", "los", "mas", "mejor", "mirador",
        "mtb", "parking", "pc", "pico", "pm", "por", "primera", "puerto", "rampa",
        "rampas", "real", "repecho", "repechos", "roadbikers", "salida", "serie",
        "servici", "servicio", "sprint", "subida", "team", "test", "total", "tramo",
        "tribox", "ultimo", "ultima", "unlimited", "velocidad", "vuelta",
        "via", "vía",
    }
    tokens: List[str] = []
    for token in raw_tokens:
        if len(token) <= 3:
            continue
        if token.isdigit():
            continue
        if token in stopwords:
            continue
        if token.startswith("cv") and any(char.isdigit() for char in token):
            continue
        tokens.append(token)
    return tokens


def _best_strong_loop_anchor_highlight(
    ordered_highlights: Sequence[OrderedHighlight],
    excluded: set[Optional[str]],
) -> Optional[str]:
    excluded_keys = {_normalize_text(value) for value in excluded if value}
    candidates: List[tuple[float, str]] = []
    for item in ordered_highlights:
        if item.kind == "turnaround_place":
            continue
        if item.kind not in {"climb_segment", "mountain_pass", "peak", "lighthouse"}:
            continue
        if item.score < 18.0:
            continue
        name = _title_case(item.name.strip())
        normalized = _normalize_text(name)
        if not name or not normalized:
            continue
        if normalized in excluded_keys:
            continue
        if any(excluded_key in normalized or normalized in excluded_key for excluded_key in excluded_keys):
            continue
        if not is_title_worthy_highlight(name):
            continue
        score = item.score
        if item.kind in {"climb_segment", "mountain_pass", "peak", "lighthouse"}:
            score += 0.4
        candidates.append((score, name))
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (-entry[0], len(entry[1]), entry[1].lower()))
    return candidates[0][1]


def _next_distinct_via_after(
    via_names: Sequence[str],
    anchor: str,
    excluded: set[Optional[str]],
) -> Optional[str]:
    anchor_key = _normalize_text(anchor)
    excluded_keys = {_normalize_text(value) for value in excluded if value}
    seen_anchor = False
    for name in via_names:
        key = _normalize_text(name)
        if not key:
            continue
        if key == anchor_key:
            seen_anchor = True
            continue
        if not seen_anchor:
            continue
        if key in excluded_keys:
            continue
        return name
    return None


def _dedupe_title_parts(parts: Sequence[str]) -> List[str]:
    result: List[str] = []
    seen = set()
    for part in parts:
        key = _normalize_text(part)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(part)
    return result


def _build_branched_loop_title(
    start_name: Optional[str],
    turnaround_name: Optional[str],
    turnaround_locality_name: Optional[str],
    ordered_highlights: Sequence[OrderedHighlight],
    route_highlights: Sequence[RouteHighlight],
    excluded: set[Optional[str]],
) -> Optional[str]:
    if not turnaround_name:
        return None

    best_route_highlight = _best_branched_route_highlight(
        route_highlights=route_highlights,
        turnaround_name=turnaround_name,
        excluded=excluded | {turnaround_name},
    )
    best_non_overlap = _best_branched_highlight(
        ordered_highlights=ordered_highlights,
        turnaround_name=turnaround_name,
        excluded=excluded | {turnaround_name},
        require_turnaround_overlap=False,
    )
    best_overlap = _best_branched_highlight(
        ordered_highlights=ordered_highlights,
        turnaround_name=turnaround_name,
        excluded=excluded | {turnaround_name},
        require_turnaround_overlap=True,
    )
    if best_route_highlight is not None and (
        best_non_overlap is None
        or best_route_highlight[0] >= _branched_highlight_score(best_non_overlap) + 0.25
    ):
        best_non_overlap_name = best_route_highlight[1]
    else:
        best_non_overlap_name = best_non_overlap.name if best_non_overlap is not None else None

    if (
        best_overlap is not None
        and _can_overlap_branch_replace_turnaround(best_overlap.name, turnaround_name, turnaround_locality_name)
        and (best_non_overlap is None or _branched_highlight_score(best_overlap) >= _branched_highlight_score(best_non_overlap) + 4.0)
    ):
        title = _trim_title(" - ".join(part for part in (start_name, best_overlap.name) if part))
        if len(title) <= 48:
            return title

    if best_non_overlap_name is not None:
        merged_branch_name = _merge_turnaround_into_composite_branch(best_non_overlap_name, turnaround_name)
        branch_title = merged_branch_name if merged_branch_name is not None else " - ".join(
            part for part in (turnaround_name, best_non_overlap_name) if part
        )
        title = _trim_title(" - ".join(part for part in (start_name, branch_title) if part))
        if len(title) <= 48:
            return title

    if best_overlap is not None and _can_overlap_branch_replace_turnaround(best_overlap.name, turnaround_name, turnaround_locality_name):
        title = _trim_title(" - ".join(part for part in (start_name, best_overlap.name) if part))
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
    if distinct_highlights and should_prefer_highlight_over_turnaround_name(distinct_highlights[0], turnaround_name):
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


def _best_branched_highlight(
    ordered_highlights: Sequence[OrderedHighlight],
    turnaround_name: Optional[str],
    excluded: set[Optional[str]],
    require_turnaround_overlap: bool,
) -> Optional[OrderedHighlight]:
    excluded_keys = {_normalize_text(value) for value in excluded if value}
    candidates: List[tuple[float, OrderedHighlight]] = []
    for item in ordered_highlights:
        name = _title_case(item.name.strip())
        normalized = _normalize_text(name)
        if not name or not normalized:
            continue
        if normalized in excluded_keys:
            continue
        if (
            not require_turnaround_overlap
            and any(excluded_key in normalized or normalized in excluded_key for excluded_key in excluded_keys)
        ):
            continue
        overlaps_turnaround = _shares_meaningful_tokens(name, turnaround_name)
        if overlaps_turnaround != require_turnaround_overlap:
            continue
        if not _is_branch_extension_worthy(item):
            continue
        candidates.append((_branched_highlight_score(item), item))
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (-entry[0], -entry[1].position, entry[1].name.lower()))
    return candidates[0][1]


def _branched_highlight_score(item: OrderedHighlight) -> float:
    score = item.score
    name = _title_case(item.name.strip())
    normalized = _normalize_text(name).replace("-", " ")
    tokens = [token for token in normalized.split() if token]
    if item.kind in {"mountain_pass", "climb_segment"}:
        score += 1.4
    if " - " in name:
        score += 0.9
    if any(token in {"ftp", "series"} for token in tokens):
        score -= 1.8
    if len(tokens) >= 4:
        score -= 0.6
    return score


def _best_branched_route_highlight(
    route_highlights: Sequence[RouteHighlight],
    turnaround_name: Optional[str],
    excluded: set[Optional[str]],
) -> Optional[tuple[float, str]]:
    excluded_keys = {_normalize_text(value) for value in excluded if value}
    candidates: List[tuple[float, str]] = []
    for item in route_highlights:
        if item.position is None:
            continue
        if item.category not in {"segment", "climb_segment", "mountain_pass", "peak", "lighthouse"}:
            continue
        name = _canonical_route_highlight_name(item.name)
        normalized = _normalize_text(name)
        if not name or not normalized:
            continue
        if normalized in excluded_keys:
            continue
        if any(excluded_key in normalized or normalized in excluded_key for excluded_key in excluded_keys):
            continue
        if _shares_meaningful_tokens(name, turnaround_name):
            continue
        if not is_title_worthy_highlight(name):
            continue
        score = item.score
        if item.category in {"climb_segment", "mountain_pass", "peak", "lighthouse"}:
            score += 0.4
        if " - " not in name:
            score += 0.3
        candidates.append((score, name))
    if not candidates:
        return None
    candidates.sort(key=lambda entry: (-entry[0], len(entry[1]), entry[1].lower()))
    return candidates[0]


def _is_branch_extension_worthy(item: OrderedHighlight) -> bool:
    name = _title_case(item.name.strip())
    if not is_title_worthy_highlight(name):
        return False
    if item.kind in {"mountain_pass", "peak", "lighthouse", "turnaround_place"}:
        return True
    return item.score >= 4.5


def _can_overlap_branch_replace_turnaround(
    branch_name: str,
    turnaround_name: Optional[str],
    turnaround_locality_name: Optional[str],
) -> bool:
    if not turnaround_name or " - " not in branch_name:
        return False
    if turnaround_locality_name and _normalize_text(turnaround_locality_name) == _normalize_text(turnaround_name):
        return False
    if not _shares_meaningful_tokens(branch_name, turnaround_name):
        return False
    if len(_meaningful_highlight_tokens(branch_name)) > len(_meaningful_highlight_tokens(turnaround_name)):
        return True
    return _turnaround_name_is_complex(turnaround_name)


def _merge_turnaround_into_composite_branch(branch_name: str, turnaround_name: Optional[str]) -> Optional[str]:
    if not turnaround_name or " - " not in branch_name:
        return None
    if _shares_meaningful_tokens(branch_name, turnaround_name):
        return None
    if len(_meaningful_highlight_tokens(turnaround_name)) != 1:
        return None

    branch_parts = [part.strip() for part in branch_name.split(" - ") if part.strip()]
    if len(branch_parts) != 2:
        return None
    return " - ".join((branch_parts[0], turnaround_name, branch_parts[1]))


def _turnaround_name_is_complex(value: str) -> bool:
    tokens = _meaningful_highlight_tokens(value)
    if len(tokens) >= 2:
        return True
    normalized = _normalize_text(value).replace("-", " ")
    return any(token in {"port", "puerto", "mirador", "faro", "alto", "coll"} for token in normalized.split())


def _shares_meaningful_tokens(first: Optional[str], second: Optional[str]) -> bool:
    tokens_first = set(_meaningful_highlight_tokens(first))
    tokens_second = set(_meaningful_highlight_tokens(second))
    if not tokens_first or not tokens_second:
        return False
    return bool(tokens_first & tokens_second)


def _meaningful_highlight_tokens(value: Optional[str]) -> List[str]:
    if not value:
        return []
    normalized = _normalize_text(value).replace("-", " ").replace("'", " ").replace("’", " ")
    tokens = [token for token in normalized.split() if token]
    stopwords = {
        "de", "del", "dels", "la", "el", "l", "les", "los", "las", "y", "i",
        "port", "puerto", "mirador", "faro", "alto", "coll",
    }
    return [token for token in tokens if token not in stopwords]


def _should_prefer_highlights_over_destination(summary: RouteSummary, destination_locality: Optional[str]) -> bool:
    meaningful = [
        item
        for item in summary.ordered_highlights
        if item.kind != "turnaround_place"
    ]
    if len(meaningful) >= 2:
        if meaningful[0].kind != "segment" and all(is_specific_highlight(item.name, destination_locality) for item in meaningful[:2]):
            return True
    if meaningful:
        best = meaningful[0]
        if (
            best.kind in {"climb_segment", "mountain_pass", "peak", "lighthouse"}
            and best.score >= 12.0
            and is_specific_highlight(best.name, destination_locality)
        ):
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


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _normalize_token_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    cleaned = re.sub(r"[^A-Za-z0-9/+ -]+", " ", ascii_only)
    return re.sub(r"\s+", " ", cleaned.strip().lower())


def _title_case(value: str) -> str:
    words = value.strip().split()
    if not words:
        return value
    return " ".join(word[:1].upper() + word[1:] for word in words)


def _canonical_route_highlight_name(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)
    cleaned = re.sub(r"\[[^\]]*\]", " ", cleaned)
    cleaned = re.sub(r'["\\]', " ", cleaned)
    cleaned = cleaned.replace("’", " ").replace("'", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -/")
    lowered = cleaned.lower()
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
        "las ",
        "los ",
        "la ",
        "el ",
    )
    for prefix in prefixes:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            lowered = cleaned.lower()
            break
    return _title_case(cleaned)
