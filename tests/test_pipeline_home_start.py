import asyncio

from app.athlete_profile import AthleteProfile
from app.config import Settings
from app.db import Database
from app.pipeline import ActivityPipeline
from app.route_analysis import Point, ResolvedPlace


class FakeStravaClient:
    def __init__(self):
        self.profile_calls = 0

    async def get_authenticated_athlete_profile(self):
        self.profile_calls += 1
        return AthleteProfile(athlete_id=1, city="València", state="Valencia", country="Spain")

    async def get_segments(self, segment_ids):
        return {}

    async def update_activity_name(self, activity_id, title):
        return {"id": activity_id, "name": title}


class FakeGeoClient:
    async def reverse_geocode(self, point: Point):
        if point.lat == 0:
            return ResolvedPlace(locality="València", district=None, suburb=None, country="ES", road=None)
        return ResolvedPlace(locality="Serra", district=None, suburb=None, country="ES", road=None)

    async def detect_turnaround_poi(self, point: Point):
        return None


def test_pipeline_always_omits_home_city_start(tmp_path):
    db = Database(tmp_path / "service.db")
    db.init()
    strava_client = FakeStravaClient()
    pipeline = ActivityPipeline(
        settings=Settings(webhook_verify_token="token", db_path=tmp_path / "service.db"),
        db=db,
        strava_client=strava_client,
        geo_client=FakeGeoClient(),
    )
    activity = {
        "id": 1,
        "name": "Morning Ride",
        "sport_type": "Ride",
        "distance": 30000,
        "_offline_points": [
            {"lat": 0, "lon": 0},
            {"lat": 1, "lon": 0},
            {"lat": 0, "lon": 0},
        ],
        "segment_efforts": [],
    }

    result = asyncio.run(pipeline.process_activity_payload(activity, owner_id=1, apply_update=False))

    assert strava_client.profile_calls == 1
    assert result.naming_decision.title == "Serra"
