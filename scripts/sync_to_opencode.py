#!/usr/bin/env python3
"""Bridge script: push llm-model-sync data to llm-provider-manager DB.

Reads data/models.json from the sync output and updates the llm-provider-manager
SQLite database, which then syncs to opencode.json via sync_db_to_opencode.py.

This allows the scheduled GitHub Actions sync to propagate to local OpenCode.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Configuration - resolve paths relative to this script, not CWD
SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", SCRIPT_DIR.parent / "data"))
MODELS_FILE = DATA_DIR / "models.json"
LLM_PROVIDER_MANAGER_DIR = Path(os.environ.get("LLM_PROVIDER_MANAGER_DIR",
    SCRIPT_DIR.parent.parent / "llm-provider-manager"))
DB_PATH = LLM_PROVIDER_MANAGER_DIR / "llm_providers.db"
OPENCODE_CONFIG = Path(os.environ.get("OPENCODE_CONFIG",
    Path.home() / ".config/opencode/opencode.json"))


def get_db_connection():
    """Connect to the llm-provider-manager database."""
    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}", file=sys.stderr)
        print("Run this on the same machine as llm-provider-manager, or set LLM_PROVIDER_MANAGER_DIR", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def update_models_from_sync(conn: sqlite3.Connection) -> int:
    """Update model lists in DB from synced data. Returns count of updated providers."""
    if not MODELS_FILE.exists():
        print(f"ERROR: {MODELS_FILE} not found — run sync_models.py first", file=sys.stderr)
        sys.exit(1)

    synced_models = json.loads(MODELS_FILE.read_text())

    c = conn.cursor()
    updated = 0

    for provider_id, data in synced_models.items():
        # Find provider in DB by key_name
        c.execute("SELECT id, display_name FROM providers WHERE key_name = ?", (provider_id,))
        row = c.fetchone()

        if not row:
            print(f"  Skipping {provider_id}: not in database (may need import_vps_yaml_to_db)")
            continue

        db_provider_id = row["id"]
        synced_model_ids = set(data.get("models", []))

        # Get existing models for this provider
        c.execute("SELECT model_id FROM models WHERE provider_id = ?", (db_provider_id,))
        existing_models = {r["model_id"] for r in c.fetchall()}

        # Add new models
        new_models = synced_model_ids - existing_models
        for model_id in new_models:
            c.execute("""INSERT OR IGNORE INTO models (provider_id, model_id, display_name, last_verified)
                         VALUES (?, ?, ?, ?)""",
                      (db_provider_id, model_id, model_id, datetime.now(timezone.utc).isoformat()))

        # Mark removed models as fallback_only (soft delete)
        removed_models = existing_models - synced_model_ids
        if removed_models:
            c.execute(f"""UPDATE models SET fallback_only = 1, updated_at = ?
                          WHERE provider_id = ? AND model_id IN ({','.join(['?' for _ in removed_models])})""",
                      (datetime.now(timezone.utc).isoformat(), db_provider_id, *removed_models))
            print(f"  {provider_id}: -{len(removed_models)} models (marked as fallback_only)")

        if new_models:
            print(f"  {provider_id}: +{len(new_models)} new models")
            updated += 1

    conn.commit()
    return updated


def backup_opencode_json(config_path: Path) -> Path | None:
    """Create a timestamped backup of opencode.json. Returns backup path or None on error."""
    if not config_path.exists():
        return None
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = config_path.parent / f"opencode.json.bak_{timestamp}"
    try:
        import shutil
        shutil.copy2(config_path, backup_path)
        print(f"Backup created: {backup_path}")
        return backup_path
    except Exception as e:
        print(f"Warning: Failed to backup {config_path}: {e}", file=sys.stderr)
        return None


def sync_to_opencode(dry_run: bool = False) -> int:
    """Run the full sync: DB update -> opencode.json. Returns updated provider count."""
    conn = get_db_connection()
    updated = update_models_from_sync(conn)
    conn.close()

    # Always sync DB -> opencode.json, even if no new models were inserted,
    # because fallback_only changes or other DB updates need to propagate.
    # Create backup before syncing (skip for dry-run)
    config_path = OPENCODE_CONFIG
    if not dry_run:
        backup_path = backup_opencode_json(config_path)
        if backup_path:
            print(f"   Restore with: cp {backup_path} {config_path}")
        else:
            print("Warning: No backup created — opencode.json may not exist yet")

    # Now run the existing sync script with update-only mode (safer: never adds new providers)
    import subprocess
    cmd = [sys.executable, str(LLM_PROVIDER_MANAGER_DIR / "scripts/sync_db_to_opencode.py"), "--update-only"]
    if dry_run:
        cmd.append("--dry-run")

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    return updated


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Sync llm-model-sync data to OpenCode")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    updated = sync_to_opencode(args.dry_run)
    print(f"Synced {updated} providers.")


if __name__ == "__main__":
    main()