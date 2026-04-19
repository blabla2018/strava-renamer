from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class AthleteProfile:
    athlete_id: Optional[int]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]

    @classmethod
    def from_strava_payload(cls, payload: Dict[str, Any]) -> "AthleteProfile":
        raw_id = payload.get("id")
        athlete_id: Optional[int]
        try:
            athlete_id = int(raw_id) if raw_id is not None else None
        except (TypeError, ValueError):
            athlete_id = None
        return cls(
            athlete_id=athlete_id,
            city=_clean_text(payload.get("city")),
            state=_clean_text(payload.get("state")),
            country=_clean_text(payload.get("country")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.athlete_id,
            "city": self.city,
            "state": self.state,
            "country": self.country,
        }


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
