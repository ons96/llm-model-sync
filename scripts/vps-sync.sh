#!/usr/bin/env bash
# VPS sync script — pulls latest data from GitHub and applies to VPS config.
# Runs via cron at 04:00 UTC, one hour after the GitHub Actions sync.

set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/llm-model-sync}"
VPS_CONFIG_DIR="${VPS_CONFIG_DIR:-$HOME/llm-provider-manager/vps_config}"
DATA_DIR="${DATA_DIR:-$REPO_DIR/data}"
LOG_FILE="${LOG_FILE:-$HOME/llm-model-sync/sync.log}"

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG_FILE"; }

log "Starting VPS sync..."

cd "$REPO_DIR"

log "Pulling latest data from GitHub..."
git pull --rebase origin main || {
    log "ERROR: git pull failed"
    exit 1
}

if [ ! -f "$DATA_DIR/models.json" ]; then
    log "ERROR: $DATA_DIR/models.json not found — has the GitHub Actions sync run?"
    exit 1
fi

log "Applying sync to VPS config..."
python3 "$REPO_DIR/scripts/apply_sync.py" \
    --config "$VPS_CONFIG_DIR/router_config.yaml" \
    2>&1 | tee -a "$LOG_FILE"

if [ -f "$DATA_DIR/pricing-changes.json" ]; then
    change_count=$(python3 -c "import json; print(len(json.load(open('$DATA_DIR/pricing-changes.json'))))" 2>/dev/null || echo "0")
    if [ "$change_count" -gt 0 ]; then
        log "WARNING: $change_count free-to-paid pricing change(s) detected!"
    fi
fi

log "Syncing DB from updated YAMLs..."
if [ -f "$HOME/llm-provider-manager/scripts/import_vps_yaml_to_db.py" ]; then
    python3 "$HOME/llm-provider-manager/scripts/import_vps_yaml_to_db.py" \
        --vps-config-dir "$VPS_CONFIG_DIR" 2>&1 | tee -a "$LOG_FILE" || true
fi

log "VPS sync complete."
