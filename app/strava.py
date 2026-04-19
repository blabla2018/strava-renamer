from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Iterable, List, Optional

import httpx

from app.athlete_profile import AthleteProfile
from app.config import Settings
from app.db import Database


logger = logging.getLogger(__name__)


class StravaApiError(Exception):
    pass


class StravaClient:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db
        self.http_client = httpx.AsyncClient(timeout=settings.request_timeout_seconds)
        self._segment_cache: Dict[int, Dict[str, Any]] = {}
        self._athlete_profile_cache: Optional[AthleteProfile] = None

    async def close(self) -> None:
        await self.http_client.aclose()

    async def get_activity(self, activity_id: int, include_all_efforts: bool = True) -> Dict[str, Any]:
        params = {"include_all_efforts": "true"} if include_all_efforts else None
        return await self._request_json("GET", f"/api/v3/activities/{activity_id}", params=params)

    async def update_activity_name(self, activity_id: int, title: str) -> Dict[str, Any]:
        return await self._request_json("PUT", f"/api/v3/activities/{activity_id}", json={"name": title})

    async def get_segment(self, segment_id: int) -> Dict[str, Any]:
        if segment_id in self._segment_cache:
            return self._segment_cache[segment_id]
        cached = self.db.get_segment_cache(segment_id)
        if cached is not None:
            self._segment_cache[segment_id] = cached
            return cached
        if self.settings.strava_cache_only:
            raise StravaApiError(f"segment {segment_id} not available in local cache")
        payload = await self._request_json("GET", f"/api/v3/segments/{segment_id}")
        self._segment_cache[segment_id] = payload
        self.db.put_segment_cache(segment_id, payload)
        return payload

    async def list_athlete_activities(
        self,
        after: Optional[int] = None,
        before: Optional[int] = None,
        page: int = 1,
        per_page: int = 30,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "page": page,
            "per_page": per_page,
        }
        if after is not None:
            params["after"] = after
        if before is not None:
            params["before"] = before
        return await self._request_json_list("GET", "/api/v3/athlete/activities", params=params)

    async def get_authenticated_athlete_profile(self) -> Optional[AthleteProfile]:
        if self._athlete_profile_cache is not None:
            return self._athlete_profile_cache

        cached_payload = self.db.get_athlete_profile_cache()
        if cached_payload is not None:
            self._athlete_profile_cache = AthleteProfile.from_strava_payload(cached_payload)
            return self._athlete_profile_cache

        if self.settings.strava_cache_only:
            return None

        payload = await self._request_json("GET", "/api/v3/athlete")
        profile = AthleteProfile.from_strava_payload(payload)
        if profile.athlete_id is not None:
            self.db.put_athlete_profile_cache(profile.athlete_id, payload)
        self._athlete_profile_cache = profile
        return profile

    async def get_segments(self, segment_ids: Iterable[int]) -> Dict[int, Dict[str, Any]]:
        ids = [segment_id for segment_id in dict.fromkeys(int(value) for value in segment_ids) if segment_id > 0]
        missing = [segment_id for segment_id in ids if segment_id not in self._segment_cache]
        if missing:
            results = await asyncio.gather(*(self.get_segment(segment_id) for segment_id in missing), return_exceptions=True)
            for segment_id, result in zip(missing, results):
                if isinstance(result, Exception):
                    log = logger.debug if self.settings.strava_cache_only else logger.warning
                    log("segment-detail-fetch-failed segment_id=%s error=%s", segment_id, result)
        return {segment_id: self._segment_cache[segment_id] for segment_id in ids if segment_id in self._segment_cache}

    async def _request_json(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self._request(method, path, json=json, params=params)

    async def _request_json_list(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        payload = await self._request(method, path, json=json, params=params)
        if not isinstance(payload, list):
            raise StravaApiError(f"expected list response from {path}")
        return payload

    async def _request(
        self,
        method: str,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        token = await self._ensure_access_token()
        url = f"{self.settings.strava_base_url}{path}"
        response = await self.http_client.request(
            method,
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=json,
            params=params,
        )
        if response.status_code == 401:
            token = await self._refresh_access_token(force=True)
            response = await self.http_client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=json,
                params=params,
            )
        if response.status_code >= 400:
            raise StravaApiError(f"strava request failed {response.status_code}: {response.text[:500]}")
        return response.json()

    async def _ensure_access_token(self) -> str:
        token_row = self.db.get_tokens()
        now = int(time.time())
        if token_row and token_row["access_token"] and token_row["expires_at"] and token_row["expires_at"] > now + 60:
            return str(token_row["access_token"])
        return await self._refresh_access_token(force=not bool(token_row and token_row["refresh_token"]))

    async def _refresh_access_token(self, force: bool = False) -> str:
        if not self.settings.can_call_strava:
            raise StravaApiError("Strava API credentials are not configured")

        token_row = self.db.get_tokens()
        refresh_token = None
        if token_row and token_row["refresh_token"]:
            refresh_token = str(token_row["refresh_token"])
        elif self.settings.strava_refresh_token:
            refresh_token = self.settings.strava_refresh_token

        if not refresh_token:
            raise StravaApiError("No Strava refresh token available")

        response = await self.http_client.post(
            f"{self.settings.strava_base_url}/oauth/token",
            data={
                "client_id": self.settings.strava_client_id,
                "client_secret": self.settings.strava_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
        )
        if response.status_code >= 400:
            raise StravaApiError(f"token refresh failed {response.status_code}: {response.text[:500]}")
        payload = response.json()
        access_token = str(payload["access_token"])
        next_refresh_token = str(payload["refresh_token"])
        expires_at = int(payload["expires_at"])
        self.db.save_tokens(access_token, next_refresh_token, expires_at)
        logger.info("strava-token-refreshed expires_at=%s force=%s", expires_at, force)
        return access_token
