#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
TEMPLATE_PATH="$REPO_DIR/launchd/com.example.strava-renamer.plist.template"

LABEL=${LABEL:-com.example.strava-renamer.daily}
DAYS=${DAYS:-3}
HOUR=${HOUR:-15}
MINUTE=${MINUTE:-0}
RUN_AT_LOAD=${RUN_AT_LOAD:-false}
BOOTSTRAP=${BOOTSTRAP:-true}

DEFAULT_PYTHON_BIN="$REPO_DIR/.venv/bin/python"
if [ -z "${PYTHON_BIN:-}" ] && [ -x "$DEFAULT_PYTHON_BIN" ]; then
    PYTHON_BIN="$DEFAULT_PYTHON_BIN"
else
    PYTHON_BIN=${PYTHON_BIN:-$(command -v python3)}
fi

LOG_DIR=${LOG_DIR:-"$HOME/Library/Logs/strava-renamer"}
STDOUT_PATH=${STDOUT_PATH:-"$LOG_DIR/launchd-sync.out.log"}
STDERR_PATH=${STDERR_PATH:-"$LOG_DIR/launchd-sync.err.log"}
PLIST_PATH=${PLIST_PATH:-"$HOME/Library/LaunchAgents/$LABEL.plist"}
DOMAIN="gui/$(id -u)"
SERVICE_TARGET="$DOMAIN/$LABEL"

if [ ! -f "$TEMPLATE_PATH" ]; then
    echo "launchd template not found: $TEMPLATE_PATH" >&2
    exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
    echo "python executable not found: $PYTHON_BIN" >&2
    exit 1
fi

if [ ! -f "$REPO_DIR/app/cli.py" ]; then
    echo "app/cli.py not found: $REPO_DIR/app/cli.py" >&2
    exit 1
fi

if [ ! -f "$REPO_DIR/.env" ]; then
    echo ".env not found: $REPO_DIR/.env" >&2
    echo "Copy .env.example to .env and configure Strava credentials first." >&2
    exit 1
fi

if ! "$PYTHON_BIN" -c "import app.cli" >/dev/null 2>&1; then
    echo "project dependencies are not available in: $PYTHON_BIN" >&2
    echo "Create the project environment and install dependencies first:" >&2
    echo "python3 -m venv .venv && .venv/bin/pip install '.[dev]'" >&2
    exit 1
fi

mkdir -p "$(dirname "$PLIST_PATH")" "$LOG_DIR"

python3 - "$TEMPLATE_PATH" "$PLIST_PATH" "$LABEL" "$PYTHON_BIN" "$REPO_DIR" "$DAYS" "$HOUR" "$MINUTE" "$STDOUT_PATH" "$STDERR_PATH" "$RUN_AT_LOAD" <<'PY'
import sys
from pathlib import Path
from xml.sax.saxutils import escape

template_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
label = sys.argv[3]
python_bin = sys.argv[4]
workdir = sys.argv[5]
days = int(sys.argv[6])
hour = int(sys.argv[7])
minute = int(sys.argv[8])
stdout_path = sys.argv[9]
stderr_path = sys.argv[10]
run_at_load_raw = sys.argv[11].strip().lower()

if days < 1:
    raise SystemExit("DAYS must be >= 1")
if hour < 0 or hour > 23:
    raise SystemExit("HOUR must be between 0 and 23")
if minute < 0 or minute > 59:
    raise SystemExit("MINUTE must be between 0 and 59")
if run_at_load_raw not in {"true", "false"}:
    raise SystemExit("RUN_AT_LOAD must be true or false")

replacements = {
    "__LABEL__": escape(label),
    "__PYTHON_BIN__": escape(python_bin),
    "__WORKDIR__": escape(workdir),
    "__DAYS__": str(days),
    "__HOUR__": str(hour),
    "__MINUTE__": str(minute),
    "__STDOUT_PATH__": escape(stdout_path),
    "__STDERR_PATH__": escape(stderr_path),
    "__RUN_AT_LOAD__": "<true/>" if run_at_load_raw == "true" else "<false/>",
}

content = template_path.read_text(encoding="utf-8")
for old, new in replacements.items():
    content = content.replace(old, new)
output_path.write_text(content, encoding="utf-8")
PY

if [ "$BOOTSTRAP" = "true" ]; then
    launchctl bootout "$DOMAIN" "$PLIST_PATH" >/dev/null 2>&1 || true
    launchctl bootstrap "$DOMAIN" "$PLIST_PATH"
    launchctl enable "$SERVICE_TARGET" >/dev/null 2>&1 || true
    launchctl kickstart -k "$SERVICE_TARGET"
    echo "Installed and started $LABEL"
else
    echo "Generated plist without launchctl bootstrap"
fi

echo "plist:  $PLIST_PATH"
echo "stdout: $STDOUT_PATH"
echo "stderr: $STDERR_PATH"
