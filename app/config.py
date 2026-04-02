from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Tuple


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


def _as_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Optional[str], default: float) -> float:
    if value is None or value == "":
        return default
    return float(value)


def _as_int(value: Optional[str], default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    return int(value)


def _as_csv(value: Optional[str]) -> Tuple[str, ...]:
    if not value:
        return tuple()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _as_int_csv(value: Optional[str]) -> Tuple[int, ...]:
    return tuple(int(part) for part in _as_csv(value))


def _default_title_allowlist() -> Tuple[str, ...]:
    return (
        "morning run",
        "afternoon run",
        "evening run",
        "night run",
        "lunch run",
        "morning ride",
        "afternoon ride",
        "evening ride",
        "night ride",
        "lunch ride",
        "run",
        "ride",
    )


@dataclass(frozen=True)
class Settings:
    log_level: str = "INFO"
    db_path: Path = Path("data/service.db")
    webhook_verify_token: str = "change-me"
    allowed_athlete_ids: Tuple[int, ...] = field(default_factory=tuple)
    request_timeout_seconds: float = 10.0
    worker_poll_interval_seconds: float = 2.0
    worker_lease_seconds: int = 90
    max_retry_attempts: int = 5
    retry_backoff_seconds: int = 30
    confidence_threshold: float = 0.75
    overwrite_manual_titles: bool = False
    overwrite_existing_generated_titles: bool = True
    reverse_geocode_enabled: bool = True
    via_place_sample_count: int = 6
    via_place_output_limit: int = 8
    overpass_retry_attempts: int = 3
    overpass_retry_base_delay_seconds: float = 1.0
    overpass_retry_max_delay_seconds: float = 6.0
    nominatim_retry_attempts: int = 3
    nominatim_retry_base_delay_seconds: float = 1.5
    nominatim_retry_max_delay_seconds: float = 8.0
    route_highlight_limit: int = 6
    strava_segment_candidate_limit: int = 8
    geo_cache_only: bool = False
    strava_cache_only: bool = False
    geocode_user_agent: str = "strava-renamer/0.1"
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    overpass_base_url: str = "https://overpass-api.de/api/interpreter"
    strava_client_id: Optional[int] = None
    strava_client_secret: Optional[str] = None
    strava_refresh_token: Optional[str] = None
    strava_athlete_id: Optional[int] = None
    strava_base_url: str = "https://www.strava.com"
    default_title_allowlist: Tuple[str, ...] = field(default_factory=_default_title_allowlist)

    @property
    def can_call_strava(self) -> bool:
        return bool(self.strava_client_id and self.strava_client_secret and self.strava_refresh_token)


def load_settings(env_file: str = ".env") -> Settings:
    _load_dotenv(Path(env_file))

    db_path = Path(os.getenv("DB_PATH", "data/service.db"))
    default_titles = list(_default_title_allowlist())
    extra_titles = [title.lower() for title in _as_csv(os.getenv("DEFAULT_TITLE_ALLOWLIST"))]
    merged_titles = tuple(dict.fromkeys(default_titles + extra_titles))

    return Settings(
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        db_path=db_path,
        webhook_verify_token=os.getenv("WEBHOOK_VERIFY_TOKEN", "change-me"),
        allowed_athlete_ids=_as_int_csv(os.getenv("ALLOWED_ATHLETE_IDS")),
        request_timeout_seconds=_as_float(os.getenv("REQUEST_TIMEOUT_SECONDS"), 10.0),
        worker_poll_interval_seconds=_as_float(os.getenv("WORKER_POLL_INTERVAL_SECONDS"), 2.0),
        worker_lease_seconds=int(_as_float(os.getenv("WORKER_LEASE_SECONDS"), 90)),
        max_retry_attempts=int(_as_float(os.getenv("MAX_RETRY_ATTEMPTS"), 5)),
        retry_backoff_seconds=int(_as_float(os.getenv("RETRY_BACKOFF_SECONDS"), 30)),
        confidence_threshold=_as_float(os.getenv("CONFIDENCE_THRESHOLD"), 0.75),
        overwrite_manual_titles=_as_bool(os.getenv("OVERWRITE_MANUAL_TITLES"), False),
        overwrite_existing_generated_titles=_as_bool(os.getenv("OVERWRITE_EXISTING_GENERATED_TITLES"), True),
        reverse_geocode_enabled=_as_bool(os.getenv("REVERSE_GEOCODE_ENABLED"), True),
        via_place_sample_count=int(_as_float(os.getenv("VIA_PLACE_SAMPLE_COUNT"), 6)),
        via_place_output_limit=int(_as_float(os.getenv("VIA_PLACE_OUTPUT_LIMIT"), 8)),
        overpass_retry_attempts=int(_as_float(os.getenv("OVERPASS_RETRY_ATTEMPTS"), 3)),
        overpass_retry_base_delay_seconds=_as_float(os.getenv("OVERPASS_RETRY_BASE_DELAY_SECONDS"), 1.0),
        overpass_retry_max_delay_seconds=_as_float(os.getenv("OVERPASS_RETRY_MAX_DELAY_SECONDS"), 6.0),
        nominatim_retry_attempts=int(_as_float(os.getenv("NOMINATIM_RETRY_ATTEMPTS"), 3)),
        nominatim_retry_base_delay_seconds=_as_float(os.getenv("NOMINATIM_RETRY_BASE_DELAY_SECONDS"), 1.5),
        nominatim_retry_max_delay_seconds=_as_float(os.getenv("NOMINATIM_RETRY_MAX_DELAY_SECONDS"), 8.0),
        route_highlight_limit=int(_as_float(os.getenv("ROUTE_HIGHLIGHT_LIMIT"), 6)),
        strava_segment_candidate_limit=int(_as_float(os.getenv("STRAVA_SEGMENT_CANDIDATE_LIMIT"), 8)),
        geo_cache_only=_as_bool(os.getenv("GEO_CACHE_ONLY"), False),
        strava_cache_only=_as_bool(os.getenv("STRAVA_CACHE_ONLY"), False),
        geocode_user_agent=os.getenv("GEOCODE_USER_AGENT", "strava-renamer/0.1"),
        nominatim_base_url=os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org"),
        overpass_base_url=os.getenv("OVERPASS_BASE_URL", "https://overpass-api.de/api/interpreter"),
        strava_client_id=_as_int(os.getenv("STRAVA_CLIENT_ID")),
        strava_client_secret=os.getenv("STRAVA_CLIENT_SECRET"),
        strava_refresh_token=os.getenv("STRAVA_REFRESH_TOKEN"),
        strava_athlete_id=_as_int(os.getenv("STRAVA_ATHLETE_ID")),
        strava_base_url=os.getenv("STRAVA_BASE_URL", "https://www.strava.com"),
        default_title_allowlist=merged_titles,
    )


def ensure_directories(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)
