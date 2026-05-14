#!/usr/bin/env python3
"""Build providers.json for llm-model-sync from all available API key sources.

Sources checked (in priority order):
1. Shell environment variables (runtime values)
2. ~/.bashrc (exported vars)
3. ~/.config/opencode/.env (opencode config)
4. ~/.profile

Usage:
    python3 scripts/build_providers_json.py [--output providers.json]

The output file contains real API keys - NEVER commit it.
It is listed in .gitignore.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

NEWAPI_SIGS = [
    "noobrouter", "supacoder", "aihubmix", "iflow", "xinjianya",
    "swiftrouter", "bluesminds", "cliproxyapi", "hapuppy", "logfare",
    "ollama-cloud", "aitools", "ktai", "wiwi", "blazeai",
    "lotte-library", "huashang", "mydamoxing", "jiekou", "freetheai",
    "zanity", "zenmux", "iflowcn", "llmgateway", "meganova",
    "kilocloud", "kilo",
]

SKIP_PROVIDERS = {
    "google", "aihubmix", "custom", "cursor-proxy", "cliproxyapi",
    "brave_search", "tavily", "duckduckgo", "exa", "jina",
    "vps-gateway", "iflow",
    "router/best-coding", "router/best-reasoning", "router/best-research",
    "router/best-chat", "router/best-coding-moe",
    "coding-smart", "coding-fast", "chat-smart", "chat-fast",
    # No tool call support, broken or missing /v1/chat/completions endpoint
    "g4f", "g4f_nvidia", "g4f_groq", "g4f_gemini", "g4f_ollama",
    "g4f_pollinations", "zenllm", "antigravity",
    # DNS dead or requires key but none configured
    "noobrouter", "openai",
    # DNS dead (domain no longer resolves)
    "kilocloud", "xinjianya",
    # Dead endpoints (404, app removed, or 0 models)
    "claude-carter", "kilo", "wiwi", "supacoder",
    # Auth broken (key does not grant models access)
    "ktai",
    # Duplicate of blazeai (same base URL, fails)
    "blazeai-glm",
    # Service down (503 for 3+ days)
    "swiftrouter",
}

# Providers that do not require an API key (public or no-auth endpoints)
# Note: opencode/opencode_zen are NOT no-auth; they have keys in .env and
# are included via the standard key resolution path.
NO_AUTH_PROVIDERS = {
    # g4f variants do not support tool calls and lack a working chat endpoint
    # zenllm and antigravity return 404/405 on /v1/chat/completions
    # They are excluded from providers.json for OpenCode compatibility.
}

CUSTOM_MODELS_PATH = {
    "blazeai": "/api/models",
}

CUSTOM_BASE_URL = {
    "blazeai": "https://blazeai.boxu.dev",
}


def load_env_file(path: Path) -> dict[str, str]:
    result = {}
    if not path.exists():
        return result
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                result[k] = v
    return result


def load_bashrc(path: Path) -> dict[str, str]:
    result = {}
    if not path.exists():
        return result
    with open(path) as f:
        for line in f:
            m = re.match(r"export\s+(\w+)\s*=\s*[\"']?(.+?)[\"']?\s*$", line.strip())
            if m:
                result[m.group(1)] = m.group(2)
    return result


def resolve_all(vars_dict: dict[str, str], max_depth: int = 10) -> dict[str, str]:
    resolved = {}
    for key, val in vars_dict.items():
        current = val
        depth = 0
        visited: set[str] = set()
        while depth < max_depth and current.startswith("$"):
            ref = current.lstrip("$").strip("{}")
            if ref in visited:
                break
            visited.add(ref)
            current = vars_dict.get(ref, current)
            depth += 1
        if not current.startswith("$") and current:
            resolved[key] = current
    return resolved


def detect_type(name: str, base_url: str) -> str:
    host = (base_url + name).lower()
    for sig in NEWAPI_SIGS:
        if sig in host:
            return "new-api"
    return "openai-compatible"


def normalize_base_url(provider_id: str, url: str) -> str:
    if provider_id in CUSTOM_BASE_URL:
        return CUSTOM_BASE_URL[provider_id]
    if url.endswith("/v1"):
        return url[:-3]
    return url


def build_providers(opencode_json_path: Path) -> list[dict]:
    with open(opencode_json_path) as f:
        cfg = json.load(f)

    all_vars: dict[str, str] = {}
    all_vars.update(load_env_file(Path.home() / ".config/opencode/.env"))
    all_vars.update(load_bashrc(Path.home() / ".bashrc"))
    all_vars.update(load_env_file(Path.home() / ".profile"))
    all_vars.update(os.environ)

    resolved = resolve_all(all_vars)

    providers_cfg = cfg.get("provider", {})
    entries = []
    unresolved = []

    for name, pdata in sorted(providers_cfg.items()):
        if name in SKIP_PROVIDERS:
            continue
        opts = pdata.get("options", {})
        base_url = opts.get("baseURL", "")
        if not base_url or base_url == "N/A":
            continue
        if "127.0.0.1" in base_url or "localhost" in base_url:
            continue

        api_key_ref = opts.get("apiKey", "")
        resolved_key = None
        if api_key_ref and api_key_ref != "N/A":
            if api_key_ref.startswith("$"):
                var_name = api_key_ref.lstrip("$").strip("{}")
                resolved_key = resolved.get(var_name)
            else:
                resolved_key = api_key_ref

        ptype = detect_type(name, base_url)
        entry: dict = {
            "id": name,
            "base_url": normalize_base_url(name, base_url.rstrip("/")),
            "type": ptype,
        }

        if name in CUSTOM_MODELS_PATH:
            entry["models_path"] = CUSTOM_MODELS_PATH[name]

        if resolved_key:
            entry["api_key"] = resolved_key
            entries.append(entry)
        elif name in NO_AUTH_PROVIDERS or api_key_ref == "":
            # No authentication required for this provider
            entries.append(entry)
        else:
            unresolved.append(name)

    return entries, unresolved


def main() -> None:
    parser = argparse.ArgumentParser(description="Build providers.json for llm-model-sync")
    parser.add_argument("--output", "-o", default="providers.json", help="Output file path")
    parser.add_argument("--opencode-config", default=str(Path.home() / ".config/opencode/opencode.json"),
                        help="Path to opencode.json")
    args = parser.parse_args()

    entries, unresolved = build_providers(Path(args.opencode_config))

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(entries, f, indent=2)

    print(f"Written {len(entries)} providers to {output_path}")
    if unresolved:
        print(f"\n{len(unresolved)} providers skipped (no resolvable API key):")
        for n in unresolved:
            print(f"  - {n}")
    print(f"\nWARNING: {output_path} contains real API keys. Never commit it.")


if __name__ == "__main__":
    main()
