from __future__ import annotations

from typing import Optional


def is_specific_highlight(name: str, destination_locality: Optional[str]) -> bool:
    normalized = _normalize_text(name).replace("-", " ")
    if destination_locality and _normalize_text(destination_locality) in normalized:
        return False
    generic_tokens = {
        "calle", "camino", "desde", "climb", "full", "ftp", "gcm", "rot", "rotonda",
        "sedavi", "saler", "parte", "muro", "delfines", "via", "este", "juto", "sep",
        "ultimos", "lookout", "corner", "tramo", "libre", "tunel", "túnel",
        "nort", "norte", "sud", "sur", "cron0", "crono", "barco", "cv",
    }
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    meaningful = [token for token in tokens if token not in generic_tokens]
    return len(meaningful) >= 1 and len(meaningful) >= len(tokens) / 2


def is_title_worthy_highlight(name: str) -> bool:
    normalized = _normalize_text(name).replace("-", " ")
    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False
    generic_tokens = {
        "331", "500", "barraca", "btt", "calle", "camino", "carrefour", "castillo",
        "climb", "conos", "corner", "corral", "cuarteles", "cumbre", "delfines",
        "desde", "este", "juto", "lookout", "parte", "poligono", "rotonda",
        "rot", "saler", "sep", "slalom", "subida", "ultimos", "vallesa", "vamos",
        "via", "vía", "tramo", "libre", "tunel", "túnel", "nort", "norte",
        "sur", "sud", "cron0", "crono", "barco",
        "cv",
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


def should_prefer_highlight_over_turnaround_name(highlight_name: str, turnaround_name: Optional[str]) -> bool:
    if not turnaround_name:
        return False
    normalized_turnaround = _normalize_text(turnaround_name).replace("-", " ")
    normalized_highlight = _normalize_text(highlight_name).replace("-", " ")
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


def is_generic_locality_highlight(name: str) -> bool:
    normalized = _normalize_text(name).replace("-", " ")
    tokens = [token for token in normalized.split() if token]
    if len(tokens) != 1:
        return False
    return tokens[0] in {"serra", "sueca", "escorca", "raiguer", "naquera", "náquera"}


def _normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())
