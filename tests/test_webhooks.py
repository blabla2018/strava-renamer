from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_webhook_verification_success(tmp_path):
    settings = Settings(
        webhook_verify_token="secret-token",
        db_path=tmp_path / "test.db",
    )
    client = TestClient(create_app(settings))

    response = client.get(
        "/webhooks/strava",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "secret-token",
            "hub.challenge": "abc123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"hub.challenge": "abc123"}


def test_webhook_event_is_enqueued(tmp_path):
    settings = Settings(
        webhook_verify_token="secret-token",
        db_path=tmp_path / "test.db",
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/webhooks/strava",
            json={
                "aspect_type": "create",
                "event_time": 1711900000,
                "object_id": 42,
                "object_type": "activity",
                "owner_id": 123,
                "subscription_id": 999,
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "accepted"
        assert response.json()["queued"] is True
