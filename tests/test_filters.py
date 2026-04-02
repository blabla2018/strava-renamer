import asyncio

from app.activity_filters import evaluate_activity_filters


def test_run_is_rejected():
    decision = asyncio.run(evaluate_activity_filters({"sport_type": "Run"}))
    assert not decision.accepted
    assert "only outdoor rides are supported" in decision.reason


def test_trainer_ride_is_rejected():
    decision = asyncio.run(evaluate_activity_filters({"sport_type": "Ride", "trainer": True}))
    assert not decision.accepted
    assert "trainer" in decision.reason


def test_outdoor_ride_is_accepted():
    decision = asyncio.run(evaluate_activity_filters({"sport_type": "Ride", "trainer": False}))
    assert decision.accepted
    assert decision.reason == "outdoor ride accepted"
