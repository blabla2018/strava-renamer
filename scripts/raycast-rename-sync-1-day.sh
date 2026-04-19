#!/bin/bash

# @raycast.schemaVersion 1
# @raycast.title Strava Rename Sync 1 Day
# @raycast.mode compact
# @raycast.packageName Strava Renamer
# @raycast.icon 🔄
# @raycast.description Sync and apply generated Strava activity names for the last 1 day

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

if [ -f ".venv/bin/activate" ]; then
  source ".venv/bin/activate"
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found. Create/activate the project virtualenv first, then run this script again."
  exit 1
fi

if [ -f ".env" ]; then
  set -a
  source ".env"
  set +a
fi

python3 -m app.cli sync-recent-activities --days 1 --apply

echo "Strava rename sync applied for the last 1 day."
