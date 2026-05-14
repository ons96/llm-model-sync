#!/usr/bin/env bash
# Pull latest model sync data from private repo and update local opencode config.
# Designed to run on the VPS or local machine via cron or manual trigger.
#
# SECURITY:
# - PRIVATE_DATA_PAT is read from env or .env file, never logged
# - No API keys are printed or committed
# - Only model names and counts are synced (no provider keys)
#
# USAGE:
#   bash scripts/pull_model_data.sh [--dry-run]

set -euo pipefail

DRY_RUN=false
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
OPENCODE_DIR="${OPENCODE_DIR:-$HOME/.config/opencode}"

# Load PAT from env or .env
PRIVATE_DATA_PAT="${PRIVATE_DATA_PAT:-}"
PRIVATE_DATA_REPO="${PRIVATE_DATA_REPO:-}"

if [ -z "$PRIVATE_DATA_PAT" ] && [ -f "$OPENCODE_DIR/.env" ]; then
    PRIVATE_DATA_PAT="$(grep '^PRIVATE_DATA_PAT=' "$OPENCODE_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
fi
if [ -z "$PRIVATE_DATA_REPO" ] && [ -f "$OPENCODE_DIR/.env" ]; then
    PRIVATE_DATA_REPO="$(grep '^PRIVATE_DATA_REPO=' "$OPENCODE_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2-)"
fi

if [ -z "$PRIVATE_DATA_PAT" ] || [ -z "$PRIVATE_DATA_REPO" ]; then
    echo "ERROR: PRIVATE_DATA_PAT and PRIVATE_DATA_REPO must be set (env or $OPENCODE_DIR/.env)"
    exit 1
fi

CLONE_URL="https://x-access-token:${PRIVATE_DATA_PAT}@github.com/${PRIVATE_DATA_REPO}.git"
TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

echo "Cloning $PRIVATE_DATA_REPO..."
git clone "$CLONE_URL" "$TMPDIR/repo" --depth 1 2>/dev/null

if [ ! -d "$TMPDIR/repo/data" ]; then
    echo "ERROR: No data/ directory in private repo"
    exit 1
fi

# Verify no secrets in pulled data before copying
for f in "$TMPDIR/repo/data/models.json" "$TMPDIR/repo/data/pricing.json" "$TMPDIR/repo/data/pricing-changes.json"; do
    if [ -f "$f" ] && grep -qE '(sk-|gsk_|nvapi-|blz_|AIza|lfu_|sta_|vc-|csk-)' "$f" 2>/dev/null; then
        echo "ERROR: Secret key pattern found in $(basename "$f") - aborting"
        exit 1
    fi
done
echo "Verified: no secrets in pulled data"

mkdir -p "$DATA_DIR"
for f in models.json pricing.json pricing-changes.json; do
    if [ -f "$TMPDIR/repo/data/$f" ]; then
        if $DRY_RUN; then
            echo "[DRY RUN] Would copy $f to $DATA_DIR/"
        else
            cp "$TMPDIR/repo/data/$f" "$DATA_DIR/"
            echo "Copied $f"
        fi
    fi
done

# Run local sync pipeline if available
SYNC_SCRIPT="$REPO_ROOT/scripts/sync_to_opencode.py"
if [ -f "$SYNC_SCRIPT" ] && ! $DRY_RUN; then
    echo "Running sync_to_opencode.py..."
    python3 "$SYNC_SCRIPT" || echo "WARNING: sync_to_opencode.py failed (non-fatal)"
fi

echo "Pull complete."
