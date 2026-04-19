from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TitleCandidate:
    title: Optional[str]
    confidence: float
    reason: str
