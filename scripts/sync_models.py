#!/usr/bin/env python3
"""LLM Provider Model Sync & Pricing Monitor

Queries /v1/models on all providers, fetches pricing from new-api /api/pricing
endpoints, and detects free→paid changes. Outputs:
  - data/models.json       — latest model catalog per provider
  - data/pricing.json      — pricing info per model
  - data/pricing-changes.json — diff of pricing changes since last run

Designed to run in GitHub Actions with secrets for API keys.
Compatible with Python 3.10+ using only stdlib + aiohttp.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import aiohttp
except ImportError:
    print("aiohttp is required: pip install aiohttp", file=sys.stderr)
    sys.exit(1)

log = logging.getLogger("sync_models")

DEFAULT_TIMEOUT = 10
DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
MODELS_FILE = DATA_DIR / "models.json"
PRICING_FILE = DATA_DIR / "pricing.json"
CHANGES_FILE = DATA_DIR / "pricing-changes.json"

PROVIDER_TYPE_OPENAI = "openai-compatible"
PROVIDER_TYPE_NEWAPI = "new-api"

NEWAPI_HOST_SIGNATURES = [
    "noobrouter", "supacoder", "aihubmix", "iflow", "xinjianya",
    "swiftrouter", "bluesminds", "cliproxyapi", "hapuppy", "logfare",
    "ollama-cloud", "aitools", "ktai", "wiwi",
]


def detect_provider_type(base_url: str) -> str:
    """Heuristic: Chinese aggregator hostnames indicate new-api, everything else is openai-compatible."""
    host = base_url.lower()
    for sig in NEWAPI_HOST_SIGNATURES:
        if sig in host:
            return PROVIDER_TYPE_NEWAPI
    return PROVIDER_TYPE_OPENAI


async def fetch_models(
    session: aiohttp.ClientSession,
    provider_id: str,
    base_url: str,
    api_key: str,
    timeout: int,
) -> list[dict[str, Any]]:
    """Fetch /v1/models from a provider. Returns list of model dicts from the 'data' key."""
    url = f"{base_url.rstrip('/')}/v1/models"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                log.warning("[%s] /v1/models returned %s", provider_id, resp.status)
                return []
            body = await resp.json(content_type=None)
            models = body.get("data", [])
            if isinstance(models, list):
                return models
            log.warning("[%s] Unexpected /v1/models shape: %s", provider_id, type(models).__name__)
            return []
    except asyncio.TimeoutError:
        log.warning("[%s] /v1/models timed out after %ds", provider_id, timeout)
        return []
    except Exception as exc:
        log.warning("[%s] /v1/models error: %s", provider_id, exc)
        return []


async def fetch_pricing_newapi(
    session: aiohttp.ClientSession,
    provider_id: str,
    base_url: str,
    api_key: str,
    timeout: int,
) -> dict[str, Any]:
    """Fetch /api/pricing from a new-api provider. Returns {model_id: pricing_info}."""
    url = f"{base_url.rstrip('/')}/api/pricing"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status != 200:
                log.warning("[%s] /api/pricing returned %s", provider_id, resp.status)
                return {}
            body = await resp.json(content_type=None)
            if isinstance(body, dict) and "data" in body:
                return body["data"] if isinstance(body["data"], dict) else {}
            return body if isinstance(body, dict) else {}
    except asyncio.TimeoutError:
        log.warning("[%s] /api/pricing timed out after %ds", provider_id, timeout)
        return {}
    except Exception as exc:
        log.warning("[%s] /api/pricing error: %s", provider_id, exc)
        return {}


def detect_pricing_changes(
    prev_pricing: dict[str, Any],
    curr_pricing: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compare previous/current pricing to find free→paid transitions.

    Returns list of change records:
      [{"model", "provider", "old_price", "new_price", "change_type": "free_to_paid", "detected_at"}]
    """
    changes: list[dict[str, Any]] = []
    for model_id, curr_info in curr_pricing.items():
        prev_info = prev_pricing.get(model_id)
        if prev_info is None:
            continue
        if _is_free(prev_info) and not _is_free(curr_info):
            changes.append({
                "model": model_id,
                "provider": curr_info.get("provider_id", "unknown"),
                "old_price": _extract_price(prev_info),
                "new_price": _extract_price(curr_info),
                "old_free": True,
                "new_free": False,
                "change_type": "free_to_paid",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            })
    return changes


def _is_free(pricing_info: dict[str, Any]) -> bool:
    price = _extract_price(pricing_info)
    if price is not None:
        return price == 0.0
    return pricing_info.get("free", pricing_info.get("is_free", False))


def _extract_price(pricing_info: dict[str, Any]) -> float | None:
    for key in ("model_price", "prompt_price", "price", "input_price"):
        val = pricing_info.get(key)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                continue
    return None


async def sync_all_providers(
    providers: list[dict[str, Any]],
    timeout: int = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Query all providers for models and pricing concurrently. Returns (models_catalog, pricing_catalog)."""
    models_catalog: dict[str, Any] = {}
    pricing_catalog: dict[str, Any] = {}

    async with aiohttp.ClientSession() as session:
        tasks = []
        for p in providers:
            pid = p["id"]
            base_url = p["base_url"]
            api_key = p.get("api_key", "")
            ptype = p.get("type", detect_provider_type(base_url))
            tasks.append((pid, base_url, "models", fetch_models(session, pid, base_url, api_key, timeout)))
            if ptype == PROVIDER_TYPE_NEWAPI:
                tasks.append((pid, base_url, "pricing", fetch_pricing_newapi(session, pid, base_url, api_key, timeout)))

        results = await asyncio.gather(*[t[3] for t in tasks], return_exceptions=True)

        for task_info, result in zip(tasks, results):
            pid, base_url, kind = task_info[0], task_info[1], task_info[2]
            if isinstance(result, Exception):
                log.error("[%s] %s task failed: %s", pid, kind, result)
                continue
            if kind == "models":
                model_ids = [m.get("id", "unknown") for m in result if isinstance(m, dict)]
                models_catalog[pid] = {
                    "base_url": base_url,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "model_count": len(model_ids),
                    "models": model_ids,
                }
            elif kind == "pricing":
                tagged = {}
                for mid, info in result.items():
                    if isinstance(info, dict):
                        info["provider_id"] = pid
                    tagged[mid] = info
                pricing_catalog.update(tagged)

    return models_catalog, pricing_catalog


def mask_value(value: str) -> None:
    """Register a value as a GitHub Actions secret mask to prevent log leakage."""
    if os.environ.get("GITHUB_ACTIONS") == "true" and value:
        print(f"::add-mask::{value}")


def set_output(name: str, value: str) -> None:
    """Set a GitHub Actions output variable."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        with open(os.environ.get("GITHUB_OUTPUT", "/dev/null"), "a") as f:
            f.write(f"{name}={value}\n")


def load_providers_from_env() -> list[dict[str, Any]]:
    """Load provider definitions from PROVIDERS_JSON env var.

    Expected format:
    [
      {"id": "groq", "base_url": "https://api.groq.com/openai/v1", "api_key": "...", "type": "openai-compatible"},
      {"id": "supacoder", "base_url": "https://supacoder.top/v1", "api_key": "...", "type": "new-api"}
    ]
    """
    raw = os.environ.get("PROVIDERS_JSON", "")
    if not raw:
        log.error("PROVIDERS_JSON env var is empty or not set")
        sys.exit(1)
    try:
        providers = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("PROVIDERS_JSON is not valid JSON: %s", exc)
        sys.exit(1)
    if not isinstance(providers, list):
        log.error("PROVIDERS_JSON must be a JSON array, got %s", type(providers).__name__)
        sys.exit(1)
    for p in providers:
        key = p.get("api_key", "")
        if key:
            mask_value(key)
    return providers


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    providers = load_providers_from_env()
    log.info("Loaded %d providers", len(providers))

    timeout = int(os.environ.get("PROVIDER_TIMEOUT", str(DEFAULT_TIMEOUT)))
    log.info("Per-provider timeout: %ds", timeout)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    prev_pricing: dict[str, Any] = {}
    if PRICING_FILE.exists():
        try:
            prev_pricing = json.loads(PRICING_FILE.read_text())
            log.info("Loaded previous pricing: %d entries", len(prev_pricing))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not load previous pricing: %s", exc)

    models_catalog, pricing_catalog = asyncio.run(sync_all_providers(providers, timeout))

    MODELS_FILE.write_text(json.dumps(models_catalog, indent=2))
    log.info("Wrote %s (%d providers)", MODELS_FILE, len(models_catalog))

    PRICING_FILE.write_text(json.dumps(pricing_catalog, indent=2))
    log.info("Wrote %s (%d entries)", PRICING_FILE, len(pricing_catalog))

    changes = detect_pricing_changes(prev_pricing, pricing_catalog)
    if changes:
        log.warning("Detected %d free->paid change(s)!", len(changes))
        for c in changes:
            log.warning("  - %s (%s): was free, now %s", c["model"], c["provider"], c["new_price"])

    existing_changes: list[dict[str, Any]] = []
    if CHANGES_FILE.exists():
        try:
            existing_changes = json.loads(CHANGES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    existing_keys = {(c["model"], c["provider"]) for c in existing_changes}
    new_changes = [c for c in changes if (c["model"], c["provider"]) not in existing_keys]
    all_changes = existing_changes + new_changes

    CHANGES_FILE.write_text(json.dumps(all_changes, indent=2))
    log.info("Wrote %s (%d total changes, %d new)", CHANGES_FILE, len(all_changes), len(new_changes))

    set_output("providers_queried", str(len(providers)))
    set_output("models_found", str(sum(m.get("model_count", 0) for m in models_catalog.values())))
    set_output("pricing_entries", str(len(pricing_catalog)))
    set_output("pricing_changes", str(len(new_changes)))

    if os.environ.get("GITHUB_ACTIONS") == "true":
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
        if summary_path:
            with open(summary_path, "a") as f:
                f.write("## Model Sync Results\n\n")
                f.write(f"- **Providers queried:** {len(providers)}\n")
                total_models = sum(m.get('model_count', 0) for m in models_catalog.values())
                f.write(f"- **Total models found:** {total_models}\n")
                f.write(f"- **Pricing entries:** {len(pricing_catalog)}\n")
                f.write(f"- **Free to Paid changes:** {len(new_changes)}\n\n")
                if new_changes:
                    f.write("### Free to Paid Changes\n\n")
                    f.write("| Model | Provider | New Price |\n")
                    f.write("|-------|----------|-----------|\n")
                    for c in new_changes:
                        f.write(f"| {c['model']} | {c['provider']} | {c['new_price']} |\n")

    log.info("Sync complete.")


if __name__ == "__main__":
    main()
