from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Optional

from app.config import Settings, ensure_directories


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Database:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        ensure_directories([db_path.parent])

    @contextmanager
    def connection(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;

                CREATE TABLE IF NOT EXISTS webhook_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    received_at TEXT NOT NULL,
                    available_at TEXT NOT NULL,
                    lease_expires_at TEXT,
                    processed_at TEXT,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS oauth_tokens (
                    token_owner INTEGER PRIMARY KEY CHECK (token_owner = 1),
                    access_token TEXT,
                    refresh_token TEXT,
                    expires_at INTEGER
                );

                CREATE TABLE IF NOT EXISTS rename_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    activity_id INTEGER NOT NULL UNIQUE,
                    owner_id INTEGER NOT NULL,
                    previous_name TEXT,
                    generated_name TEXT,
                    confidence REAL,
                    reason TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS geo_cache (
                    cache_key TEXT PRIMARY KEY,
                    service TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS strava_segment_cache (
                    segment_id INTEGER PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def seed_tokens(self, settings: Settings) -> None:
        if not settings.strava_refresh_token:
            return
        with self.connection() as conn:
            existing = conn.execute(
                "SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE token_owner = 1"
            ).fetchone()
            if existing:
                return
            conn.execute(
                """
                INSERT INTO oauth_tokens (token_owner, access_token, refresh_token, expires_at)
                VALUES (1, ?, ?, ?)
                """,
                (
                    None,
                    settings.strava_refresh_token,
                    None,
                ),
            )

    def enqueue_event(self, external_key: str, payload: Dict[str, Any]) -> bool:
        now = _utcnow().isoformat()
        with self.connection() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO webhook_events
                    (external_key, payload_json, status, attempt_count, received_at, available_at)
                VALUES (?, ?, 'pending', 0, ?, ?)
                """,
                (external_key, json.dumps(payload), now, now),
            )
            return cursor.rowcount > 0

    def claim_next_event(self, lease_seconds: int, max_retry_attempts: int) -> Optional[sqlite3.Row]:
        now = _utcnow()
        now_iso = now.isoformat()
        lease_expires_at = (now + timedelta(seconds=lease_seconds)).isoformat()
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE webhook_events
                SET status = 'retry', lease_expires_at = NULL
                WHERE status = 'processing' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?
                """,
                (now_iso,),
            )
            row = conn.execute(
                """
                SELECT id, payload_json, attempt_count
                FROM webhook_events
                WHERE status IN ('pending', 'retry')
                  AND available_at <= ?
                  AND attempt_count < ?
                ORDER BY received_at ASC
                LIMIT 1
                """,
                (now_iso, max_retry_attempts),
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                """
                UPDATE webhook_events
                SET status = 'processing',
                    lease_expires_at = ?,
                    attempt_count = attempt_count + 1
                WHERE id = ?
                """,
                (lease_expires_at, row["id"]),
            )
            claimed = conn.execute(
                "SELECT id, payload_json, attempt_count FROM webhook_events WHERE id = ?",
                (row["id"],),
            ).fetchone()
            return claimed

    def mark_event_done(self, event_id: int) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE webhook_events
                SET status = 'done',
                    processed_at = ?,
                    lease_expires_at = NULL,
                    last_error = NULL
                WHERE id = ?
                """,
                (_utcnow().isoformat(), event_id),
            )

    def mark_event_retry(self, event_id: int, error: str, base_delay_seconds: int, attempts: int) -> None:
        delay_seconds = base_delay_seconds * max(1, attempts)
        available_at = (_utcnow() + timedelta(seconds=delay_seconds)).isoformat()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE webhook_events
                SET status = 'retry',
                    available_at = ?,
                    lease_expires_at = NULL,
                    last_error = ?
                WHERE id = ?
                """,
                (available_at, error[:1000], event_id),
            )

    def mark_event_failed(self, event_id: int, error: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE webhook_events
                SET status = 'failed',
                    processed_at = ?,
                    lease_expires_at = NULL,
                    last_error = ?
                WHERE id = ?
                """,
                (_utcnow().isoformat(), error[:1000], event_id),
            )

    def get_tokens(self) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                "SELECT access_token, refresh_token, expires_at FROM oauth_tokens WHERE token_owner = 1"
            ).fetchone()

    def save_tokens(self, access_token: str, refresh_token: str, expires_at: int) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO oauth_tokens (token_owner, access_token, refresh_token, expires_at)
                VALUES (1, ?, ?, ?)
                ON CONFLICT(token_owner) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at
                """,
                (access_token, refresh_token, expires_at),
            )

    def get_last_rename_audit(self, activity_id: int) -> Optional[sqlite3.Row]:
        with self.connection() as conn:
            return conn.execute(
                """
                SELECT activity_id, previous_name, generated_name, confidence, reason, outcome
                FROM rename_audit
                WHERE activity_id = ?
                """,
                (activity_id,),
            ).fetchone()

    def record_rename_audit(
        self,
        activity_id: int,
        owner_id: int,
        previous_name: Optional[str],
        generated_name: Optional[str],
        confidence: float,
        reason: str,
        outcome: str,
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO rename_audit
                    (activity_id, owner_id, previous_name, generated_name, confidence, reason, outcome, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                    previous_name = excluded.previous_name,
                    generated_name = excluded.generated_name,
                    confidence = excluded.confidence,
                    reason = excluded.reason,
                    outcome = excluded.outcome,
                    created_at = excluded.created_at
                """,
                (
                    activity_id,
                    owner_id,
                    previous_name,
                    generated_name,
                    confidence,
                    reason,
                    outcome,
                    _utcnow().isoformat(),
                ),
            )

    def get_geo_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM geo_cache
                WHERE cache_key = ?
                """,
                (cache_key,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["payload_json"])

    def put_geo_cache(self, cache_key: str, service: str, payload: Any) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO geo_cache (cache_key, service, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    service = excluded.service,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    cache_key,
                    service,
                    json.dumps(payload),
                    _utcnow().isoformat(),
                ),
            )

    def get_segment_cache(self, segment_id: int) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json
                FROM strava_segment_cache
                WHERE segment_id = ?
                """,
                (segment_id,),
            ).fetchone()
            if row is None:
                return None
            return json.loads(row["payload_json"])

    def put_segment_cache(self, segment_id: int, payload: Any) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO strava_segment_cache (segment_id, payload_json, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(segment_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (
                    segment_id,
                    json.dumps(payload),
                    _utcnow().isoformat(),
                ),
            )
