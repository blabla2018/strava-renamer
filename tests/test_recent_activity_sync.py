import asyncio

from app.config import Settings
from app.pipeline import ActivityProcessingResult
from app.recent_activity_sync import RecentActivitySync
from app.activity_filters import FilterDecision
from app.naming import NamingDecision


class FakeStravaClient:
    def __init__(self, batches):
        self.batches = batches
        self.calls = []

    async def list_athlete_activities(self, after=None, before=None, page=1, per_page=30):
        self.calls.append(
            {
                "after": after,
                "before": before,
                "page": page,
                "per_page": per_page,
            }
        )
        return list(self.batches.get(page, []))


class FakePipeline:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def process_activity(self, activity_id, owner_id, apply_update):
        self.calls.append(
            {
                "activity_id": activity_id,
                "owner_id": owner_id,
                "apply_update": apply_update,
            }
        )
        return self.results[activity_id]


def make_result(activity_id, owner_id, current_name, updated, accepted=True, sport_type="Ride"):
    return ActivityProcessingResult(
        activity_id=activity_id,
        owner_id=owner_id,
        current_name=current_name,
        sport_type=sport_type,
        filter_decision=FilterDecision(accepted=accepted, reason="outdoor ride accepted" if accepted else "filtered"),
        route_summary=None,
        naming_decision=NamingDecision(title="València - Oronet", confidence=0.95, reason="generated"),
        should_rename=accepted,
        rename_reason="eligible for rename" if accepted else "filtered",
        updated=updated,
    )


def test_sync_recent_activities_paginates_and_processes_oldest_first():
    settings = Settings(webhook_verify_token="token", strava_athlete_id=555)
    strava_client = FakeStravaClient(
        {
            1: [
                {"id": 300, "start_date": "2026-04-04T09:00:00Z", "athlete": {"id": 777}},
                {"id": 200, "start_date": "2026-04-03T09:00:00Z"},
            ],
            2: [
                {"id": 250, "start_date": "2026-04-03T12:00:00Z", "athlete": {"id": 888}},
            ],
        }
    )
    pipeline = FakePipeline(
        {
            200: make_result(200, 555, "Morning Ride", updated=False),
            250: make_result(250, 888, "Morning Ride", updated=True),
            300: make_result(300, 777, "Evening Ride", updated=True),
        }
    )
    sync = RecentActivitySync(settings=settings, strava_client=strava_client, pipeline=pipeline)

    report = asyncio.run(sync.sync_recent_activities(days=3, apply_update=True, per_page=2))

    assert [call["page"] for call in strava_client.calls] == [1, 2]
    assert pipeline.calls == [
        {"activity_id": 200, "owner_id": 555, "apply_update": True},
        {"activity_id": 250, "owner_id": 888, "apply_update": True},
        {"activity_id": 300, "owner_id": 777, "apply_update": True},
    ]
    assert report.total_listed == 3
    assert report.processed == 3
    assert report.renamed == 2
    assert report.skipped == 1


def test_sync_recent_activities_requires_positive_days():
    settings = Settings(webhook_verify_token="token")
    sync = RecentActivitySync(settings=settings, strava_client=FakeStravaClient({}), pipeline=FakePipeline({}))

    try:
        asyncio.run(sync.sync_recent_activities(days=0, apply_update=False))
    except ValueError as exc:
        assert str(exc) == "days must be >= 1"
    else:
        raise AssertionError("Expected ValueError for non-positive days")
