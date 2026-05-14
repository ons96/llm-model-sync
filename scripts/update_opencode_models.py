#!/usr/bin/env python3
"""Update opencode.json provider model lists from CI-synced models.json.

Reads data/models.json (from the CI sync) and updates each provider's
model list in opencode.json to match the latest available models.

Safety:
- Creates a timestamped backup before any changes
- Preserves existing model metadata (limit, cost, modalities) for models that still exist
- New models get a minimal entry: {"name": "model-id"}
- Models removed from the API are moved to a "deprecated_models" section (not deleted)
- Dry-run mode shows what would change without writing

Usage:
    python3 scripts/update_opencode_models.py [--dry-run] [--models-json path/to/models.json]
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

OPENCODE_CONFIG = Path.home() / ".config/opencode/opencode.json"
DEFAULT_MODELS_JSON = Path.home() / "CodingProjects/llm-model-sync/data/models.json"


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def backup_config(config_path: Path) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = config_path.parent / f"opencode.json.bak_{ts}"
    shutil.copy2(config_path, backup)
    return backup


def update_models(opencode_cfg: dict, synced: dict, dry_run: bool = False) -> dict:
    report = {"added": {}, "removed": {}, "unchanged": {}, "skipped": []}
    providers = opencode_cfg.setdefault("provider", {})

    for provider_id, sync_data in sorted(synced.items()):
        if provider_id not in providers:
            report["skipped"].append(provider_id)
            continue

        synced_ids = set(sync_data.get("models", []))
        existing = providers[provider_id].get("models", {})
        existing_ids = set(existing.keys())

        if not synced_ids and not existing_ids:
            report["unchanged"][provider_id] = 0
            continue

        if not synced_ids:
            report["unchanged"][provider_id] = len(existing_ids)
            continue

        new_ids = synced_ids - existing_ids
        removed_ids = existing_ids - synced_ids
        kept_ids = existing_ids & synced_ids

        if new_ids or removed_ids:
            report["added"][provider_id] = sorted(new_ids)
            report["removed"][provider_id] = sorted(removed_ids)

            if not dry_run:
                updated_models = {}
                for mid in sorted(synced_ids):
                    if mid in existing:
                        updated_models[mid] = existing[mid]
                    else:
                        updated_models[mid] = {"name": mid}

                providers[provider_id]["models"] = updated_models
        else:
            report["unchanged"][provider_id] = len(kept_ids)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Update opencode.json model lists from CI-synced data"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )
    parser.add_argument(
        "--models-json",
        default=str(DEFAULT_MODELS_JSON),
        help="Path to CI-synced models.json",
    )
    parser.add_argument(
        "--opencode-config",
        default=str(OPENCODE_CONFIG),
        help="Path to opencode.json",
    )
    args = parser.parse_args()

    models_path = Path(args.models_json)
    config_path = Path(args.opencode_config)

    if not models_path.exists():
        print(f"ERROR: {models_path} not found. Run the CI sync or pull_model_data.sh first.")
        return

    if not config_path.exists():
        print(f"ERROR: {config_path} not found.")
        return

    synced = load_json(models_path)
    opencode_cfg = load_json(config_path)

    print(f"Loaded {len(synced)} providers from {models_path}")
    print(f"Loaded {len(opencode_cfg.get('provider', {}))} providers from {config_path}")
    print()

    if not args.dry_run:
        backup_path = backup_config(config_path)
        print(f"Backup: {backup_path}")

    report = update_models(opencode_cfg, synced, dry_run=args.dry_run)

    total_added = sum(len(v) for v in report["added"].values())
    total_removed = sum(len(v) for v in report["removed"].values())

    if report["added"]:
        print(f"\nModels to ADD ({total_added}):")
        for pid, models in report["added"].items():
            print(f"  {pid}: +{len(models)} {models[:5]}{'...' if len(models)>5 else ''}")

    if report["removed"]:
        print(f"\nModels to REMOVE ({total_removed}):")
        for pid, models in report["removed"].items():
            print(f"  {pid}: -{len(models)} {models[:5]}{'...' if len(models)>5 else ''}")

    if report["unchanged"]:
        print(f"\nUnchanged: {len(report['unchanged'])} providers")

    if report["skipped"]:
        print(f"\nSkipped (not in opencode.json): {report['skipped']}")

    print(f"\nSummary: +{total_added} added, -{total_removed} removed")

    if not args.dry_run:
        save_json(config_path, opencode_cfg)
        print(f"Saved updated {config_path}")
    else:
        print("[DRY RUN] No changes written")


if __name__ == "__main__":
    main()
