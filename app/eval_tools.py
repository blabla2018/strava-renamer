from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.config import ensure_directories
from app.pipeline import ActivityPipeline
from app.strava import StravaClient


@dataclass(frozen=True)
class EvalEntry:
    activity_id: int
    expected_title: str
    cache_path: str
    current_name: str
    sport_type: str
    start_date: Optional[str]


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def to_epoch_bounds(start: date, end: date) -> tuple[int, int]:
    start_dt = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(end, time.max, tzinfo=timezone.utc)
    return int(start_dt.timestamp()), int(end_dt.timestamp())


def write_json(path: Path, payload: Any) -> None:
    ensure_directories([path.parent])
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


async def fetch_eval_dataset(
    dataset_path: Path,
    cache_dir: Path,
    strava_client: StravaClient,
    start_date: date,
    end_date: date,
    per_page: int = 100,
) -> Dict[str, Any]:
    ensure_directories([dataset_path.parent, cache_dir])
    after_ts, before_ts = to_epoch_bounds(start_date, end_date)

    summaries: List[Dict[str, Any]] = []
    page = 1
    while True:
        batch = await strava_client.list_athlete_activities(
            after=after_ts,
            before=before_ts,
            page=page,
            per_page=per_page,
        )
        if not batch:
            break
        summaries.extend(batch)
        if len(batch) < per_page:
            break
        page += 1

    filtered = [item for item in summaries if _is_eval_candidate(item)]
    entries: List[EvalEntry] = []
    for item in filtered:
        activity_id = int(item["id"])
        detailed = await strava_client.get_activity(activity_id, include_all_efforts=True)
        cache_path = cache_dir / f"{activity_id}.json"
        write_json(cache_path, detailed)
        entries.append(
            EvalEntry(
                activity_id=activity_id,
                expected_title=str(item.get("name") or ""),
                cache_path=str(cache_path),
                current_name=str(item.get("name") or ""),
                sport_type=str(item.get("sport_type") or item.get("type") or ""),
                start_date=item.get("start_date_local"),
            )
        )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date_range": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
        },
        "activities": [entry.__dict__ for entry in entries],
    }
    write_json(dataset_path, payload)
    return payload


async def evaluate_dataset(
    dataset_path: Path,
    pipeline: ActivityPipeline,
) -> Dict[str, Any]:
    dataset = read_json(dataset_path)
    rows = []
    exact = 0
    normalized_exact = 0
    total = 0
    for item in dataset.get("activities", []):
        activity = read_json(Path(item["cache_path"]))
        result = await pipeline.process_activity_payload(
            activity=activity,
            owner_id=int(activity.get("athlete", {}).get("id") or 0),
            apply_update=False,
        )
        expected = str(item.get("expected_title") or "")
        generated = str(result.naming_decision.title or "")
        row = build_eval_row(
            activity_id=int(item["activity_id"]),
            expected_title=expected,
            generated_title=generated,
            current_name=str(activity.get("name") or ""),
            route_summary=result.route_summary,
        )
        total += 1
        if row["exact_match"]:
            exact += 1
        if row["normalized_exact_match"]:
            normalized_exact += 1
        rows.append(row)

    rows.sort(key=lambda row: (row["normalized_exact_match"], row["similarity"]), reverse=False)
    return {
        "dataset_path": str(dataset_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "activities": total,
            "exact_match_count": exact,
            "normalized_exact_match_count": normalized_exact,
            "exact_match_rate": round(exact / total, 4) if total else 0.0,
            "normalized_exact_match_rate": round(normalized_exact / total, 4) if total else 0.0,
            "average_similarity": round(sum(row["similarity"] for row in rows) / total, 4) if total else 0.0,
            "average_token_jaccard": round(sum(row["token_jaccard"] for row in rows) / total, 4) if total else 0.0,
        },
        "rows": rows,
    }


async def prewarm_dataset(
    dataset_path: Path,
    pipeline: ActivityPipeline,
    strava_client: StravaClient,
) -> Dict[str, Any]:
    dataset = read_json(dataset_path)
    warmed = 0
    failures = []
    for item in dataset.get("activities", []):
        activity = read_json(Path(item["cache_path"]))
        try:
            if str(activity.get("sport_type") or activity.get("type") or "") == "Ride":
                await pipeline._load_segment_details(activity)
            await pipeline.build_route_summary(activity)
            warmed += 1
        except Exception as exc:
            failures.append({"activity_id": item["activity_id"], "error": str(exc)})
    return {
        "dataset_path": str(dataset_path),
        "activities_total": len(dataset.get("activities", [])),
        "activities_warmed": warmed,
        "failures": failures[:20],
    }


def build_eval_row(
    activity_id: int,
    expected_title: str,
    generated_title: str,
    current_name: str,
    route_summary,
) -> Dict[str, Any]:
    normalized_expected = normalize_title(expected_title)
    normalized_generated = normalize_title(generated_title)
    expected_tokens = set(normalized_expected.split())
    generated_tokens = set(normalized_generated.split())
    union = expected_tokens | generated_tokens
    token_jaccard = len(expected_tokens & generated_tokens) / len(union) if union else 1.0
    similarity = SequenceMatcher(a=normalized_expected, b=normalized_generated).ratio()
    return {
        "activity_id": activity_id,
        "expected_title": expected_title,
        "generated_title": generated_title,
        "current_name": current_name,
        "exact_match": expected_title == generated_title,
        "normalized_exact_match": normalized_expected == normalized_generated,
        "similarity": round(similarity, 4),
        "token_jaccard": round(token_jaccard, 4),
        "ordered_highlights": [
            {
                "name": item.name,
                "kind": item.kind,
                "score": round(item.score, 2),
                "position": round(item.position, 3),
            }
            for item in (route_summary.ordered_highlights if route_summary else [])
        ][:4],
    }


def normalize_title(value: str) -> str:
    collapsed = " ".join(value.strip().lower().replace("’", "'").replace("-", " ").split())
    return collapsed


def _is_eval_candidate(activity: Dict[str, Any]) -> bool:
    sport_type = str(activity.get("sport_type") or activity.get("type") or "")
    if sport_type != "Ride":
        return False
    if bool(activity.get("trainer")):
        return False
    if bool(activity.get("commute")):
        return False
    if sport_type in {"VirtualRide", "EBikeRide"}:
        return False
    return True
