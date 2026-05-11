#!/usr/bin/env python3
"""Apply synced model data to VPS LiteLLM config files.

Reads data/models.json from the sync output and updates the VPS
router_config.yaml free_tier_models lists to match what providers
actually serve (vs what was manually specified).

This runs on the VPS via cron, one hour after the GitHub Actions sync.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.stderr.write("PyYAML required: pip install pyyaml\n")
    sys.exit(1)

DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MODELS_FILE = DATA_DIR / "models.json"
PRICING_FILE = DATA_DIR / "pricing.json"
CHANGES_FILE = DATA_DIR / "pricing-changes.json"
DEFAULT_VPS_CONFIG = "/home/ubuntu/llm-provider-manager/vps_config/router_config.yaml"


def load_synced_models() -> dict:
    if not MODELS_FILE.exists():
        sys.stderr.write(f"Missing {MODELS_FILE} — run sync_models.py first\n")
        sys.exit(1)
    return json.loads(MODELS_FILE.read_text())


def load_pricing_changes() -> list[dict]:
    if not CHANGES_FILE.exists():
        return []
    return json.loads(CHANGES_FILE.read_text())


def update_router_config(
    router_path: str,
    synced_models: dict,
    pricing_changes: list[dict],
) -> bool:
    """Update router_config.yaml with fresh model lists. Returns True if changes were made."""
    config_path = Path(router_path)
    if not config_path.exists():
        sys.stderr.write(f"Config not found: {config_path}\n")
        sys.exit(1)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    changed = False

    paid_models = set()
    for change in pricing_changes:
        if change.get("change_type") == "free_to_paid":
            paid_models.add((change.get("provider"), change.get("model")))

    providers = config.get("providers", {})
    for provider_id, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        if not provider_cfg.get("enabled", True):
            continue

        synced = synced_models.get(provider_id, {})
        remote_models = set(synced.get("models", []))

        current_free = set(provider_cfg.get("free_tier_models", []))

        new_free = current_free & remote_models if remote_models else current_free

        for (pid, mid) in paid_models:
            if pid == provider_id and mid in new_free:
                new_free.discard(mid)
                sys.stderr.write(f"  Removing paid model: {provider_id}/{mid}\n")

        if new_free != current_free:
            added = new_free - current_free
            removed = current_free - new_free
            if added:
                sys.stderr.write(f"  [{provider_id}] +{len(added)} models: {sorted(added)[:5]}{'...' if len(added) > 5 else ''}\n")
            if removed:
                sys.stderr.write(f"  [{provider_id}] -{len(removed)} models: {sorted(removed)[:5]}{'...' if len(removed) > 5 else ''}\n")
            provider_cfg["free_tier_models"] = sorted(new_free)
            changed = True

    if changed:
        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        sys.stderr.write(f"Updated {config_path}\n")
    else:
        sys.stderr.write("No changes needed.\n")

    return changed


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Apply synced model data to VPS config")
    parser.add_argument("--config", default=os.environ.get("VPS_CONFIG", DEFAULT_VPS_CONFIG),
                        help="Path to router_config.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    synced_models = load_synced_models()
    pricing_changes = load_pricing_changes()

    if args.dry_run:
        sys.stderr.write("DRY RUN — no files will be modified\n")

    changed = update_router_config(args.config, synced_models, pricing_changes)

    if changed and not args.dry_run:
        sys.stderr.write("Config updated. Restart LiteLLM proxy to apply.\n")
    elif not changed:
        sys.stderr.write("Config is already up to date.\n")


if __name__ == "__main__":
    main()
