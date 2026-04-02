# Strava Renamer

Production-oriented MVP web service that listens to Strava webhooks, filters eligible activities, derives a compact route summary, and renames the activity in Strava.

## What it does

- verifies Strava webhook subscriptions with `GET /webhooks/strava`
- receives activity creation events with `POST /webhooks/strava`
- acknowledges webhooks immediately and processes them asynchronously from SQLite-backed queue storage
- accepts only outdoor `Ride` activities
- rejects `Run`, `VirtualRide`, `VirtualRun`, trainer / indoor rides, and all other sport types
- fetches full activity details from Strava
- decodes the activity polyline, reverse geocodes route points, optionally detects a landmark, and generates a compact deterministic title
- updates the Strava activity name only when confidence is high enough and the current title does not look manually edited

## Architecture

- `FastAPI` app for health checks and webhook endpoints
- `sqlite3` persistence for webhook queue state, OAuth token storage, and rename audit trail
- background worker loop that leases queued webhook events and retries transient failures
- `httpx` clients for Strava, Nominatim, and Overpass
- deterministic naming pipeline first; no LLM dependency required

## Key design decisions

### Webhook validation

Strava webhook verification is supported through the standard `hub.challenge` flow.

Strava does not provide a request signature for webhook delivery, so the service cannot cryptographically validate `POST /webhooks/strava` payload origin in the same way Stripe or GitHub can. The implemented practical safeguards are:

- strict payload validation
- optional `ALLOWED_ATHLETE_IDS` filtering
- idempotent queueing via a stable event key
- fast acknowledgment with deferred processing

### Activity filtering

Accepted:

- `Ride` when `trainer=false`

Rejected:

- `Run`
- `VirtualRide`
- `VirtualRun`
- `Ride` with `trainer=true`
- all other sport types

The earlier OSM-based cycleway heuristic was removed because it did not contribute to naming quality and added slow external requests.

### Route enrichment and naming

Deterministic title rules:

- simple point-to-point route with distinct endpoints: `City A - City B`
- circular route with a meaningful turnaround destination: `City - Destination`
- circular route without a strong destination: `City Loop`
- route with one stable locality plus one meaningful via locality or climb: `City - Highlight` or `City - District`

Guardrails:

- never list every locality encountered
- include at most 2 to 3 meaningful points
- trim titles to a compact length
- skip rename when route context is too weak

### Manual rename protection

The service does not overwrite a title that appears manually edited unless `OVERWRITE_MANUAL_TITLES=true`.

Current heuristic:

- default Strava auto-titles such as `Morning Ride` and `Morning Run` are considered safe to replace
- anything else is treated as manual

This is also heuristic because Strava default titles may be localized. Use `DEFAULT_TITLE_ALLOWLIST` to add localized defaults for your account.

## Local run

```bash
python3 -m venv .venv
.venv/bin/pip install '.[dev]'
cp .env.example .env
.venv/bin/uvicorn app.main:app --reload
```

The service listens on `http://127.0.0.1:8000`.

## Simplest manual test

Before wiring webhooks, you can test the whole naming pipeline on an existing Strava activity id.

1. Fill in `.env` with at least:
   - `STRAVA_CLIENT_ID`
   - `STRAVA_CLIENT_SECRET`
   - `STRAVA_REFRESH_TOKEN`
   - `STRAVA_ATHLETE_ID`
2. Run a dry-run inspection:

```bash
.venv/bin/python -m app.cli inspect-activity --activity-id 12345678901
```

This fetches the activity from Strava, applies filters, reverse geocoding, turnaround POI lookup, and title generation, then prints a JSON result without modifying Strava.

3. If the generated title looks correct, apply it:

```bash
.venv/bin/python -m app.cli inspect-activity --activity-id 12345678901 --apply
```

That is the fastest way to validate the MVP on real data before setting up public webhooks.

## Offline naming iteration

The supported local iteration workflow is now based on cached Strava activities in `eval/cache/activities` plus the evaluation dataset commands below.

If you want richer route diagnostics while tuning naming rules, increase:

- `VIA_PLACE_SAMPLE_COUNT` - how many interior route samples are reverse-geocoded
- `VIA_PLACE_OUTPUT_LIMIT` - how many deduplicated `via_places` are returned in CLI output

Overpass lookups for turnaround POI detection use targeted retries for transient failures like `429`, `502`, `503`, and `504`. You can tune them with:

- `OVERPASS_RETRY_ATTEMPTS`
- `OVERPASS_RETRY_BASE_DELAY_SECONDS`
- `OVERPASS_RETRY_MAX_DELAY_SECONDS`

Nominatim reverse geocoding also retries on transient failures and rate limits like `429`, `500`, `502`, `503`, and `504`. You can tune it with:

- `NOMINATIM_RETRY_ATTEMPTS`
- `NOMINATIM_RETRY_BASE_DELAY_SECONDS`
- `NOMINATIM_RETRY_MAX_DELAY_SECONDS`

For rides, the service now prefers cyclist-relevant highlights from Strava segments plus a turnaround POI when it is helpful:

- Strava `segment_efforts` from the activity itself, enriched with segment detail data such as `star_count`, `athlete_count`, `effort_count`, climb category, grade, and distance
- OpenStreetMap turnaround POI detection near the farthest point of a loop such as peaks, passes, lighthouses, viewpoints, monuments, and attractions

These are merged into a ranked `highlights` list in CLI output. The top highlight is often a better naming anchor than a generic locality.

## Evaluation Dataset Workflow

You can build a local evaluation dataset from your own Strava rides, cache all detailed activity payloads, and then run naming evaluations offline against that cache.

Fetch rides into cache:

```bash
.venv/bin/python -m app.cli fetch-eval-dataset \
  --start-date 2025-09-01 \
  --end-date 2026-04-01
```

This uses `GET /api/v3/athlete/activities` with `after`, `before`, `page`, and `per_page`, then fetches each selected detailed activity with segment efforts and saves it under `eval/cache/activities/`.

Evaluate locally from cache:

```bash
.venv/bin/python -m app.cli evaluate-dataset
```

The report is written to `eval/latest-report.json`. By default the dataset:

- keeps only `Ride`
- excludes `trainer`
- excludes `commute`
- uses the current Strava title as the expected title baseline

To warm local caches before repeated offline evaluations:

```bash
.venv/bin/python -m app.cli prewarm-dataset
```

Repeated evaluations can run fully from local Strava and geo caches by setting `GEO_CACHE_ONLY=true` and `STRAVA_CACHE_ONLY=true`.

## Configure Strava

1. Create a Strava API application.
2. Put your client credentials and refresh token into `.env`.
3. Expose the service publicly over HTTPS.
4. Register the webhook subscription with Strava using:

```bash
curl -X POST https://www.strava.com/api/v3/push_subscriptions \
  -F client_id="$STRAVA_CLIENT_ID" \
  -F client_secret="$STRAVA_CLIENT_SECRET" \
  -F callback_url="https://your-domain.example/webhooks/strava" \
  -F verify_token="$WEBHOOK_VERIFY_TOKEN"
```

## Run tests

```bash
.venv/bin/pytest
```
