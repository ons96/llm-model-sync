#!/usr/bin/env bash
# Add a provider (default: blazeai) to llm-model-sync via the existing
# build_providers_json.py pipeline. Reads the API key from the process
# env or from --env-file, then exports BLAZEAI_API_KEY (or the
# --provider-specific env var) and regenerates providers.json.
#
# Usage:
#   ./update_blazeai_provider.sh                     # uses ~/.config/opencode/.env
#   ./update_blazeai_provider.sh --env-file ./my.env
#   BLAZEAI_API_KEY=sk-... ./update_blazeai_provider.sh   # read from process env
#
# The key is passed through the env, never written to providers.json
# in plaintext: build_providers_json.py emits "$BLAZEAI_API_KEY" by
# default (see its --write-env-refs option), and providers.json is in
# .gitignore anyway.

set -euo pipefail

ENV_FILE="${HOME}/.config/opencode/.env"
PROVIDER_KEY_NAME="BLAZEAI_API_KEY"
PROVIDER_ID="blazeai"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --env-file) ENV_FILE="$2"; shift 2 ;;
        --provider) PROVIDER_ID="$2"; PROVIDER_KEY_NAME="$(echo "$2" | tr '[:lower:]' '[:upper:]')_API_KEY"; shift 2 ;;
        -h|--help)
            sed -n '2,18p' "$0"
            exit 0
            ;;
        *) echo "Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "${!PROVIDER_KEY_NAME:-}" && -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
fi

if [[ -z "${!PROVIDER_KEY_NAME:-}" ]]; then
    echo "ERROR: $PROVIDER_KEY_NAME not set in env or $ENV_FILE" >&2
    exit 1
fi

cd "$(dirname "$0")"

echo "Regenerating providers.json via build_providers_json.py ..."
python3 scripts/build_providers_json.py --output providers.json
echo "Done. providers.json (gitignored) reflects current env-var state."
echo ""
echo "To test:"
echo "  cd $(pwd)"
echo "  DATA_DIR=\$(pwd)/data PROVIDERS_JSON=\$(pwd)/providers.json python3 scripts/sync_models.py"
