from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class StravaWebhookEvent(BaseModel):
    aspect_type: str
    event_time: int
    object_id: int
    object_type: str
    owner_id: int
    subscription_id: int
    updates: Optional[Dict[str, Any]] = None


class WebhookAck(BaseModel):
    status: str
    queued: bool = False
    detail: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = Field(default="ok")
