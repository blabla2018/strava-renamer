import asyncio

from app.config import Settings
from app.db import Database
from app.strava import StravaClient


class StubStravaClient(StravaClient):
    def __init__(self, settings, db, responses):
        super().__init__(settings, db)
        self.responses = list(responses)
        self.calls = []

    async def _request_json(self, method, path, json=None, params=None):
        self.calls.append((method, path))
        return self.responses.pop(0)


def test_get_authenticated_athlete_profile_uses_cache_only_db_value(tmp_path):
    db = Database(tmp_path / "service.db")
    db.init()
    db.put_athlete_profile_cache(
        athlete_id=3456798,
        payload={"id": 3456798, "city": "Valencia", "state": "Valencia", "country": "Spain"},
    )
    client = StubStravaClient(
        Settings(webhook_verify_token="token", strava_cache_only=True),
        db,
        responses=[],
    )

    profile = asyncio.run(client.get_authenticated_athlete_profile())
    asyncio.run(client.close())

    assert profile is not None
    assert profile.city == "Valencia"
    assert client.calls == []


def test_get_authenticated_athlete_profile_returns_none_in_cache_only_without_cached_profile(tmp_path):
    db = Database(tmp_path / "service.db")
    db.init()
    client = StubStravaClient(
        Settings(webhook_verify_token="token", strava_cache_only=True),
        db,
        responses=[],
    )

    profile = asyncio.run(client.get_authenticated_athlete_profile())
    asyncio.run(client.close())

    assert profile is None
    assert client.calls == []


def test_get_authenticated_athlete_profile_fetches_and_caches(tmp_path):
    db = Database(tmp_path / "service.db")
    db.init()
    client = StubStravaClient(
        Settings(webhook_verify_token="token"),
        db,
        responses=[
            {"id": 3456798, "city": "Valencia", "state": "Valencia", "country": "Spain"},
        ],
    )

    first = asyncio.run(client.get_authenticated_athlete_profile())
    second = asyncio.run(client.get_authenticated_athlete_profile())
    asyncio.run(client.close())

    assert first is not None
    assert first.city == "Valencia"
    assert second == first
    assert client.calls == [("GET", "/api/v3/athlete")]

    cached = db.get_athlete_profile_cache()
    assert cached is not None
    assert cached["city"] == "Valencia"
