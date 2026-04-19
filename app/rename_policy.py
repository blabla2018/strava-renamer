from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Tuple

from app.config import Settings
from app.naming import normalize_text

if TYPE_CHECKING:
    from app.naming import NamingDecision


def should_rename_activity(
    current_name: Optional[str],
    decision: "NamingDecision",
    sport_type: str,
    settings: Settings,
    previous_generated_name: Optional[str] = None,
) -> Tuple[bool, str]:
    if not decision.title:
        return False, "no generated title"
    if decision.confidence < settings.confidence_threshold:
        return False, f"confidence {decision.confidence:.2f} below threshold {settings.confidence_threshold:.2f}"
    if current_name and normalize_text(current_name) == normalize_text(decision.title):
        return False, "activity already has the generated title"
    if (
        current_name
        and previous_generated_name
        and normalize_text(current_name) == normalize_text(previous_generated_name)
    ):
        if settings.overwrite_existing_generated_titles:
            return True, "eligible to overwrite previous generated title"
        return False, "existing generated title will not be overwritten by configuration"
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
