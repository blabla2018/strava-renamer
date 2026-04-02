from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Query, Request

from app.config import Settings, load_settings
from app.db import Database
from app.geocoding import GeoClient
from app.logging_utils import configure_logging
from app.schemas import HealthResponse, StravaWebhookEvent, WebhookAck
from app.strava import StravaClient
from app.worker import EventWorker


logger = logging.getLogger(__name__)


def _model_to_dict(model: StravaWebhookEvent) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    service_settings = settings or load_settings()
    configure_logging(service_settings.log_level)
    db = Database(service_settings.db_path)
    strava_client = StravaClient(service_settings, db)
    geo_client = GeoClient(service_settings, db)
    worker = EventWorker(service_settings, db, strava_client, geo_client)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        db.init()
        db.seed_tokens(service_settings)
        worker.start()
        try:
            yield
        finally:
            await worker.stop()
            await strava_client.close()
            await geo_client.close()

    app = FastAPI(
        title="Strava Renamer",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = service_settings
    app.state.db = db
    app.state.worker = worker

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        return HealthResponse()

    @app.get("/webhooks/strava")
    async def verify_webhook(
        hub_mode: str = Query(alias="hub.mode"),
        hub_verify_token: str = Query(alias="hub.verify_token"),
        hub_challenge: str = Query(alias="hub.challenge"),
    ) -> dict:
        if hub_mode != "subscribe" or hub_verify_token != service_settings.webhook_verify_token:
            raise HTTPException(status_code=403, detail="invalid verification request")
        return {"hub.challenge": hub_challenge}

    @app.post("/webhooks/strava", response_model=WebhookAck)
    async def receive_webhook(event: StravaWebhookEvent, request: Request) -> WebhookAck:
        if service_settings.allowed_athlete_ids and event.owner_id not in service_settings.allowed_athlete_ids:
            return WebhookAck(status="ignored", detail="owner_id not allowed")
        if event.object_type != "activity" or event.aspect_type != "create":
            return WebhookAck(status="ignored", detail="event is not a new activity")

        external_key = (
            f"{event.subscription_id}:{event.owner_id}:{event.object_type}:"
            f"{event.object_id}:{event.aspect_type}:{event.event_time}"
        )
        queued = app.state.db.enqueue_event(external_key=external_key, payload=_model_to_dict(event))
        client_host = request.client.host if request.client else "unknown"
        logger.info("webhook-received activity_id=%s queued=%s client=%s", event.object_id, queued, client_host)
        return WebhookAck(status="accepted", queued=queued)

    return app


app = create_app()
