#!/usr/bin/env bash
# Set the PROVIDERS_JSON GitHub secret for llm-model-sync repo.
# This script reads providers.json (which contains API keys) and
# uploads it as an encrypted GitHub secret so the workflow can use it.
#
# PREREQUISITES:
#   1. gh CLI must be authenticated: gh auth login
#   2. providers.json must exist in this directory (run build_providers_json.py first)
#
# SECURITY:
#   - providers.json is in .gitignore and must NEVER be committed
#   - The GitHub secret is encrypted at rest and masked in logs
#   - This script does NOT print any API keys

set -euo pipefail

REPO="ons96/llm-model-sync"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROVIDERS_FILE="$REPO_ROOT/providers.json"

if [ ! -f "$PROVIDERS_FILE" ]; then
    echo "ERROR: providers.json not found at $PROVIDERS_FILE"
    echo "Run build_providers_json.py first to generate it."
    exit 1
fi

# Verify the file is valid JSON
if ! python3 -c "import json; json.load(open('$PROVIDERS_FILE'))" 2>/dev/null; then
    echo "ERROR: providers.json is not valid JSON"
    exit 1
fi

provider_count=$(python3 -c "import json; print(len(json.load(open('$PROVIDERS_FILE'))))")
echo "Setting PROVIDERS_JSON secret with $provider_count providers..."

# Set the secret (gh handles encryption)
gh secret set PROVIDERS_JSON --repo "$REPO" < "$PROVIDERS_FILE"

echo "PROVIDERS_JSON secret set successfully."
echo ""
echo "Optional secrets to set:"
echo "  PRIVATE_DATA_PAT  - PAT with access to private data repo"
echo "  PRIVATE_DATA_REPO - org/repo for private data (e.g., yourname/llm-data-private)"
echo "  VPS_SYNC_PAT      - PAT for repository dispatch events"
echo ""
echo "To set optional secrets:"
echo "  gh secret set PRIVATE_DATA_PAT --repo $REPO"
echo "  gh secret set PRIVATE_DATA_REPO --repo $REPO"
