from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any, Dict, List, Optional

from app.config import Settings
from app.pipeline import ActivityPipeline, ActivityProcessingResult
from app.strava import StravaClient


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SyncedActivity:
    activity_id: int
    owner_id: int
    sport_type: str
    current_name: Optional[str]
    generated_title: Optional[str]
    accepted: bool
    filter_reason: str
    should_rename: bool
    rename_reason: str
    updated: bool

    @classmethod
    def from_result(cls, result: ActivityProcessingResult) -> "SyncedActivity":
        return cls(
            activity_id=result.activity_id,
            owner_id=result.owner_id,
            sport_type=result.sport_type,
            current_name=result.current_name,
            generated_title=result.naming_decision.title if result.naming_decision else None,
            accepted=result.filter_decision.accepted,
            filter_reason=result.filter_decision.reason,
            should_rename=result.should_rename,
            rename_reason=result.rename_reason,
            updated=result.updated,
        )


@dataclass(frozen=True)
class RecentActivitySyncReport:
    days: int
    apply_update: bool
    after: str
    before: str
    total_listed: int
    processed: int
    renamed: int
    skipped: int
    activities: List[SyncedActivity]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "days": self.days,
            "apply_update": self.apply_update,
            "after": self.after,
            "before": self.before,
            "total_listed": self.total_listed,
            "processed": self.processed,
            "renamed": self.renamed,
            "skipped": self.skipped,
            "activities": [asdict(item) for item in self.activities],
        }


class RecentActivitySync:
    def __init__(
        self,
        settings: Settings,
        strava_client: StravaClient,
        pipeline: ActivityPipeline,
    ) -> None:
        self.settings = settings
        self.strava_client = strava_client
        self.pipeline = pipeline

    async def sync_recent_activities(
        self,
        days: int,
        apply_update: bool,
        per_page: int = 100,
    ) -> RecentActivitySyncReport:
        if days < 1:
            raise ValueError("days must be >= 1")
        if per_page < 1:
            raise ValueError("per_page must be >= 1")

        before_dt = datetime.now(timezone.utc)
        after_dt = before_dt - timedelta(days=days)
        summaries = await self._list_recent_activities(
            after=int(after_dt.timestamp()),
            before=int(before_dt.timestamp()),
            per_page=per_page,
        )

        processed_results: List[SyncedActivity] = []
        default_owner_id = self.settings.strava_athlete_id or 0
        for summary in sorted(summaries, key=_activity_sort_key):
            activity_id = _parse_activity_id(summary)
            if activity_id is None:
                logger.warning("recent-activity-sync skipped summary without valid id: %s", summary)
                continue

            owner_id = int(summary.get("athlete", {}).get("id") or default_owner_id)
            result = await self.pipeline.process_activity(
                activity_id=activity_id,
                owner_id=owner_id,
                apply_update=apply_update,
            )
            processed_results.append(SyncedActivity.from_result(result))

        renamed = sum(1 for item in processed_results if item.updated)
        return RecentActivitySyncReport(
            days=days,
            apply_update=apply_update,
            after=after_dt.isoformat(),
            before=before_dt.isoformat(),
            total_listed=len(summaries),
            processed=len(processed_results),
            renamed=renamed,
            skipped=len(processed_results) - renamed,
            activities=processed_results,
        )

    async def _list_recent_activities(self, after: int, before: int, per_page: int) -> List[Dict[str, Any]]:
        activities: List[Dict[str, Any]] = []
        page = 1

        while True:
            batch = await self.strava_client.list_athlete_activities(
                after=after,
                before=before,
                page=page,
                per_page=per_page,
            )
            if not batch:
                break

            activities.extend(batch)
            if len(batch) < per_page:
                break

            page += 1

        return activities


def _parse_activity_id(summary: Dict[str, Any]) -> Optional[int]:
    raw_id = summary.get("id")
    if raw_id is None:
        return None
    try:
        return int(raw_id)
    except (TypeError, ValueError):
        return None


def _activity_sort_key(summary: Dict[str, Any]) -> tuple[str, int]:
    activity_id = _parse_activity_id(summary) or 0
    return (
        str(summary.get("start_date") or summary.get("start_date_local") or ""),
        activity_id,
    )
