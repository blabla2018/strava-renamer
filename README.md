# Strava Renamer

Local scheduled Strava renamer that polls recent activities, analyzes the route, and updates the title only when the current name still looks like a default Strava auto-title.

## What it does

- runs locally on a schedule instead of depending on a public webhook endpoint
- fetches recent activities for the authenticated athlete from Strava
- renames only outdoor bike rides that pass the current deterministic naming pipeline
- leaves manually edited titles untouched unless `OVERWRITE_MANUAL_TITLES=true`
- stores OAuth tokens, geo cache, segment cache, and rename audit history in SQLite

## Current activity filter

Rejected:

- `Run`
- `VirtualRide`
- `VirtualRun`
- `Ride` with `trainer=true`
- `Ride` with `commute=true`
- all other sport types

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install '.[dev]'
cp .env.example .env
```

Fill `.env` with at least:

- `STRAVA_CLIENT_ID`
- `STRAVA_CLIENT_SECRET`
- `STRAVA_REFRESH_TOKEN`
- `STRAVA_ATHLETE_ID`

## Main scheduled command

Dry run for the last 3 days:

```bash
.venv/bin/python -m app.cli sync-recent-activities --days 3
```

Real rename run for the last 3 days:

```bash
.venv/bin/python -m app.cli sync-recent-activities --days 3 --apply
```

The command lists recent athlete activities via `GET /api/v3/athlete/activities`, fetches each activity in detail, and then:

- skips everything except outdoor `Ride`
- generates a route-based title
- renames only when confidence is high enough
- skips activities whose current title already looks manually edited

## One-off inspection

Dry run for a single activity:

```bash
.venv/bin/python -m app.cli inspect-activity --activity-id 12345678901
```

Apply rename for one activity:

```bash
.venv/bin/python -m app.cli inspect-activity --activity-id 12345678901 --apply
```

## launchd on macOS

The repository now includes:

- `launchd/com.example.strava-renamer.plist.template` - an anonymized XML template without personal paths or labels
- `scripts/install-launch-agent.sh` - an installer that fills the template with your local paths and registers it in `~/Library/LaunchAgents`

Default install:

```bash
./scripts/install-launch-agent.sh
```

This generates a local plist and installs it with:

- label `com.example.strava-renamer.daily`
- schedule every day at `15:00`
- command `.venv/bin/python -m app.cli sync-recent-activities --days 3 --apply`
- logs in `~/Library/Logs/strava-renamer/`

Custom install example:

```bash
LABEL=com.yourname.strava-renamer.daily HOUR=15 MINUTE=0 DAYS=3 ./scripts/install-launch-agent.sh
```

Useful options:

- `LABEL` - launchd label and generated plist filename
- `HOUR` - hour of the daily run, `0..23`
- `MINUTE` - minute of the daily run, `0..59`
- `DAYS` - how many recent days to inspect on each run
- `PYTHON_BIN` - Python interpreter to use instead of `.venv/bin/python`
- `RUN_AT_LOAD=true` - also execute once immediately after the agent is loaded
- `BOOTSTRAP=false` - only generate the plist without calling `launchctl`
- `PLIST_PATH` - custom output plist path
- `LOG_DIR`, `STDOUT_PATH`, `STDERR_PATH` - log destinations

Preview-only example without installing into launchd:

```bash
BOOTSTRAP=false PLIST_PATH=/tmp/strava-renamer.plist ./scripts/install-launch-agent.sh
```

## Offline evaluation workflow

You can still build and score a local evaluation dataset from cached Strava rides.

Fetch rides into cache:

```bash
.venv/bin/python -m app.cli fetch-eval-dataset \
  --start-date 2025-09-01 \
  --end-date 2026-04-01
```

Evaluate locally from cache:

```bash
.venv/bin/python -m app.cli evaluate-dataset
```

Prewarm geo and segment caches:

```bash
.venv/bin/python -m app.cli prewarm-dataset
```

Repeated evaluations can run fully from cache with `GEO_CACHE_ONLY=true` and `STRAVA_CACHE_ONLY=true`.

## Notes

- Default-title detection is heuristic. Add localized Strava defaults via `DEFAULT_TITLE_ALLOWLIST`.
- Legacy webhook-related code remains in the repository, but the primary workflow is now local scheduled execution.

## Run tests

```bash
.venv/bin/pytest
```
