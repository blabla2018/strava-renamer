from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx

from app.config import Settings
from app.db import Database
from app.geocoding import GeoClient
from app.pipeline import ActivityPipeline
from app.schemas import StravaWebhookEvent
from app.strava import StravaApiError, StravaClient


logger = logging.getLogger(__name__)


class EventWorker:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        strava_client: StravaClient,
        geo_client: GeoClient,
    ) -> None:
        self.settings = settings
        self.db = db
        self.strava_client = strava_client
        self.geo_client = geo_client
        self.pipeline = ActivityPipeline(settings, db, strava_client, geo_client)
        self._task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

    def start(self) -> None:
        if self._task is None:
            self._stop_event = asyncio.Event()
            self._task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self._stop_event = None

    async def run_forever(self) -> None:
        while self._stop_event is not None and not self._stop_event.is_set():
            claimed = self.db.claim_next_event(
                lease_seconds=self.settings.worker_lease_seconds,
                max_retry_attempts=self.settings.max_retry_attempts,
            )
            if claimed is None:
                await asyncio.sleep(self.settings.worker_poll_interval_seconds)
                continue

            event_id = int(claimed["id"])
            attempts = int(claimed["attempt_count"])
            try:
                payload = json.loads(claimed["payload_json"])
                event = StravaWebhookEvent(**payload)
                await self.process_event(event)
            except (StravaApiError, httpx.HTTPError) as exc:
                logger.warning("event-processing-retry id=%s error=%s", event_id, exc)
                if attempts >= self.settings.max_retry_attempts:
                    self.db.mark_event_failed(event_id, str(exc))
                else:
                    self.db.mark_event_retry(
                        event_id,
                        str(exc),
                        base_delay_seconds=self.settings.retry_backoff_seconds,
                        attempts=attempts,
                    )
            except Exception as exc:  # pragma: no cover - safety net
                logger.exception("event-processing-failed id=%s", event_id)
                self.db.mark_event_failed(event_id, str(exc))
            else:
                self.db.mark_event_done(event_id)

    async def process_event(self, event: StravaWebhookEvent) -> None:
        if event.object_type != "activity" or event.aspect_type != "create":
            logger.info("event-ignored object_type=%s aspect_type=%s", event.object_type, event.aspect_type)
            return
        if self.settings.allowed_athlete_ids and event.owner_id not in self.settings.allowed_athlete_ids:
            logger.info("event-ignored owner_id=%s reason=owner-not-allowed", event.owner_id)
            return

        result = await self.pipeline.process_activity(
            activity_id=event.object_id,
            owner_id=event.owner_id,
            apply_update=True,
        )
        logger.info(
            "activity-processed activity_id=%s outcome=%s generated_title=%s confidence=%.2f",
            event.object_id,
            "renamed" if result.updated else "skipped",
            result.naming_decision.title if result.naming_decision else None,
            result.naming_decision.confidence if result.naming_decision else 0.0,
        )
