#!/usr/bin/env bash
# RETIRED 2026-10-19 — guard stub, refuses to run.
#
# This script chained sync_to_opencode.py -> sync_db_to_opencode.py, whose
# merge wholesale-replaced each provider's models dict in opencode.json with
# bare {"name": id} DB entries — pruning ALL curated metadata (limit,
# tool_call, reasoning, variants) and any model missing from the DB
# (observed: 824 entries across 18 providers).
#
# sync_db_to_opencode.py's merge is now additive-only (DB adds, never
# replaces), but do not re-wire this chain: opencode.json is hand-curated.
# Original script recoverable via git history.
#
# Use instead:
#   python3 ~/CodingProjects/scripts/update-provider-models.py            # SOTA adds (dry-run)
#   python3 ~/CodingProjects/scripts/update-provider-models.py --apply    # adds + boot-gate
#   python3 ~/CodingProjects/scripts/update-provider-models.py --free    # + verified free models
#   python3 ~/CodingProjects/scripts/update-provider-models.py --prune   # archive-only prune

echo "RETIRED: update-models.sh pruned curated opencode.json models. See script header for replacements." >&2
exit 1
