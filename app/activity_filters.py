from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class FilterDecision:
    accepted: bool
    reason: str
    warnings: List[str] = field(default_factory=list)


async def evaluate_activity_filters(
    activity: Dict[str, Any],
) -> FilterDecision:
    sport_type = str(activity.get("sport_type") or activity.get("type") or "").strip()
    trainer = bool(activity.get("trainer"))

    if sport_type in {"VirtualRide", "VirtualRun"}:
        return FilterDecision(False, "virtual activity is excluded")

    if sport_type != "Ride":
        return FilterDecision(False, f"only outdoor rides are supported; got {sport_type or 'unknown'}")

    if trainer:
        return FilterDecision(False, "trainer / indoor ride is excluded")

    return FilterDecision(True, "outdoor ride accepted")
