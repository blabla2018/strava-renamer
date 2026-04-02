from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import load_settings
from app.db import Database
from app.eval_tools import evaluate_dataset, fetch_eval_dataset, parse_iso_date, prewarm_dataset, write_json
from app.geocoding import GeoClient
from app.pipeline import ActivityPipeline
from app.strava import StravaClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manual tools for the Strava renamer service.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect-activity",
        help="Fetch one Strava activity, generate a title, and optionally apply the rename.",
    )
    inspect_parser.add_argument("--activity-id", type=int, required=True, help="Strava activity id")
    inspect_parser.add_argument(
        "--owner-id",
        type=int,
        default=None,
        help="Athlete id for audit records; defaults to STRAVA_ATHLETE_ID if configured",
    )
    inspect_parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually send the generated title back to Strava. Without this flag the command is dry-run only.",
    )
    inspect_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include full route diagnostics such as raw signals and clusters.",
    )

    fetch_eval_parser = subparsers.add_parser(
        "fetch-eval-dataset",
        help="Fetch ride activities from Strava into a local eval cache and dataset file.",
    )
    fetch_eval_parser.add_argument("--start-date", type=parse_iso_date, default=date(2025, 9, 1))
    fetch_eval_parser.add_argument("--end-date", type=parse_iso_date, default=date.today())
    fetch_eval_parser.add_argument("--dataset-path", type=Path, default=Path("eval/dataset.json"))
    fetch_eval_parser.add_argument("--cache-dir", type=Path, default=Path("eval/cache/activities"))
    fetch_eval_parser.add_argument("--per-page", type=int, default=100)

    eval_parser = subparsers.add_parser(
        "evaluate-dataset",
        help="Evaluate cached activities against expected titles without calling Strava for each test.",
    )
    eval_parser.add_argument("--dataset-path", type=Path, default=Path("eval/dataset.json"))
    eval_parser.add_argument("--output-path", type=Path, default=Path("eval/latest-report.json"))

    prewarm_parser = subparsers.add_parser(
        "prewarm-dataset",
        help="Prewarm geo and segment caches for the local dataset.",
    )
    prewarm_parser.add_argument("--dataset-path", type=Path, default=Path("eval/dataset.json"))
    return parser


async def _inspect_activity(activity_id: int, owner_id: Optional[int], apply_update: bool, verbose: bool) -> int:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    db.seed_tokens(settings)

    strava_client = StravaClient(settings, db)
    geo_client = GeoClient(settings, db)
    pipeline = ActivityPipeline(settings, db, strava_client, geo_client)

    try:
        result = await pipeline.process_activity(
            activity_id=activity_id,
            owner_id=owner_id or settings.strava_athlete_id or 0,
            apply_update=apply_update,
        )
    finally:
        await strava_client.close()
        await geo_client.close()

    print(
        json.dumps(
            _activity_result_payload(result, verbose=verbose),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def _fetch_eval_dataset(
    start_date: date,
    end_date: date,
    dataset_path: Path,
    cache_dir: Path,
    per_page: int,
) -> int:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    db.seed_tokens(settings)
    strava_client = StravaClient(settings, db)
    try:
        payload = await fetch_eval_dataset(
            dataset_path=dataset_path,
            cache_dir=cache_dir,
            strava_client=strava_client,
            start_date=start_date,
            end_date=end_date,
            per_page=per_page,
        )
    finally:
        await strava_client.close()

    print(
        json.dumps(
            {
                "dataset_path": str(dataset_path),
                "cache_dir": str(cache_dir),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "activities_cached": len(payload.get("activities", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def _evaluate_dataset(dataset_path: Path, output_path: Path) -> int:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    geo_client = GeoClient(settings, db)
    strava_client = StravaClient(settings, db)
    pipeline = ActivityPipeline(settings, db, strava_client, geo_client)
    try:
        report = await evaluate_dataset(dataset_path=dataset_path, pipeline=pipeline)
    finally:
        await strava_client.close()
        await geo_client.close()

    write_json(output_path, report)
    compact_rows = [
        {
            "activity_id": row["activity_id"],
            "expected_title": row["expected_title"],
            "generated_title": row["generated_title"],
            "normalized_exact_match": row["normalized_exact_match"],
            "similarity": row["similarity"],
            "token_jaccard": row["token_jaccard"],
        }
        for row in report["rows"][:20]
    ]
    print(
        json.dumps(
            {
                "dataset_path": str(dataset_path),
                "output_path": str(output_path),
                "summary": report["summary"],
                "top_mismatches": compact_rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


async def _prewarm_dataset(dataset_path: Path) -> int:
    settings = load_settings()
    db = Database(settings.db_path)
    db.init()
    geo_client = GeoClient(settings, db)
    strava_client = StravaClient(settings, db)
    pipeline = ActivityPipeline(settings, db, strava_client, geo_client)
    try:
        report = await prewarm_dataset(dataset_path=dataset_path, pipeline=pipeline, strava_client=strava_client)
    finally:
        await strava_client.close()
        await geo_client.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _route_payload(summary) -> Optional[Dict[str, Any]]:
    if summary is None:
        return None
    return {
        "distance_m": round(summary.total_distance_m, 1),
        "is_loop": summary.is_loop,
        "start_place": _place_payload(summary.start_place),
        "end_place": _place_payload(summary.end_place),
        "via_places": [_place_payload(place) for place in summary.via_places],
        "highlights": [_highlight_payload(item) for item in summary.highlights],
        "landmark": _landmark_payload(summary.landmark),
        "warnings": summary.warnings,
    }


def _route_payload_verbose(summary) -> Optional[Dict[str, Any]]:
    payload = _route_payload(summary)
    if payload is None or summary is None:
        return payload
    payload["ordered_highlights"] = [_ordered_highlight_payload(item) for item in summary.ordered_highlights]
    payload["clusters"] = [_cluster_payload(item) for item in summary.clusters]
    payload["raw_signals"] = [_raw_signal_payload(item) for item in summary.raw_signals]
    return payload


def _activity_result_payload(result, verbose: bool) -> Dict[str, Any]:
    route = _route_payload_verbose(result.route_summary) if verbose else _route_payload(result.route_summary)
    payload = {
        "activity_id": result.activity_id,
        "owner_id": result.owner_id,
        "sport_type": result.sport_type,
        "current_name": result.current_name,
        "accepted": result.filter_decision.accepted,
        "filter_reason": result.filter_decision.reason,
        "filter_warnings": result.filter_decision.warnings,
        "generated_title": result.naming_decision.title if result.naming_decision else None,
        "confidence": result.naming_decision.confidence if result.naming_decision else None,
        "naming_reason": result.naming_decision.reason if result.naming_decision else None,
        "should_rename": result.should_rename,
        "rename_reason": result.rename_reason,
        "updated": result.updated,
        "route": route,
    }
    if not verbose and result.route_summary is not None:
        payload["diagnostics"] = {
            "raw_signal_count": len(result.route_summary.raw_signals),
            "cluster_count": len(result.route_summary.clusters),
            "ordered_highlight_count": len(result.route_summary.ordered_highlights),
            "use_verbose_flag": "Run with --verbose to inspect raw_signals, clusters, and ordered_highlights.",
        }
    return payload


def _place_payload(place) -> Optional[Dict[str, Any]]:
    if place is None:
        return None
    return {
        "locality": place.locality,
        "district": place.district,
        "suburb": place.suburb,
        "country": place.country,
        "road": place.road,
    }


def _landmark_payload(landmark) -> Optional[Dict[str, Any]]:
    if landmark is None:
        return None
    return {
        "name": landmark.name,
        "category": landmark.category,
        "source": landmark.source,
        "score": round(landmark.score, 2),
        "distance_m": round(landmark.distance_m, 1),
    }


def _highlight_payload(item) -> Dict[str, Any]:
    payload = {
        "name": item.name,
        "category": item.category,
        "source": item.source,
        "score": round(item.score, 2),
    }
    if item.distance_m is not None:
        payload["distance_m"] = round(item.distance_m, 1)
    if item.position is not None:
        payload["position"] = round(item.position, 3)
    if item.aliases:
        payload["aliases"] = item.aliases
    return payload


def _ordered_highlight_payload(item) -> Dict[str, Any]:
    payload = {
        "cluster_id": item.cluster_id,
        "name": item.name,
        "kind": item.kind,
        "score": round(item.score, 2),
        "position": round(item.position, 3),
        "sources": item.sources,
    }
    if item.aliases:
        payload["aliases"] = item.aliases
    if item.metadata:
        payload["metadata"] = item.metadata
    return payload


def _cluster_payload(item) -> Dict[str, Any]:
    return {
        "cluster_id": item.cluster_id,
        "canonical_name": item.canonical_name,
        "normalized_name": item.normalized_name,
        "kind": item.kind,
        "score": round(item.score, 2),
        "position_start": round(item.position_start, 3),
        "position_end": round(item.position_end, 3),
        "position_centroid": round(item.position_centroid, 3),
        "aliases": item.aliases,
        "sources": item.sources,
        "signals_count": item.signals_count,
        "metadata": item.metadata,
    }


def _raw_signal_payload(item) -> Dict[str, Any]:
    payload = {
        "name": item.name,
        "normalized_name": item.normalized_name,
        "kind": item.kind,
        "source": item.source,
        "score": round(item.score, 2),
        "position": round(item.position, 3),
        "aliases": item.aliases,
    }
    if item.distance_m is not None:
        payload["distance_m"] = round(item.distance_m, 1)
    if item.lat is not None:
        payload["lat"] = item.lat
    if item.lon is not None:
        payload["lon"] = item.lon
    if item.metadata:
        payload["metadata"] = item.metadata
    return payload


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "inspect-activity":
        return asyncio.run(_inspect_activity(args.activity_id, args.owner_id, args.apply, args.verbose))
    if args.command == "fetch-eval-dataset":
        return asyncio.run(
            _fetch_eval_dataset(
                start_date=args.start_date,
                end_date=args.end_date,
                dataset_path=args.dataset_path,
                cache_dir=args.cache_dir,
                per_page=args.per_page,
            )
        )
    if args.command == "evaluate-dataset":
        return asyncio.run(_evaluate_dataset(args.dataset_path, args.output_path))
    if args.command == "prewarm-dataset":
        return asyncio.run(_prewarm_dataset(args.dataset_path))
    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
