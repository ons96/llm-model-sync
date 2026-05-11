# LLM Model Sync

Automated model list and pricing sync for LLM providers. Runs daily via GitHub Actions, updating model catalogs and detecting free→paid changes.

## System Components

1. **GitHub Actions workflow** (`.github/workflows/sync-models.yml`) - Runs daily at 03:00 UTC
2. **Sync script** (`scripts/sync_models.py`) - Fetches `/v1/models` and `/api/pricing` from all providers
3. **VPS apply script** (`scripts/apply_sync.py`) - Updates LiteLLM router config with fresh model lists
4. **VPS cron script** (`scripts/vps-sync.sh`) - Wrapper for VPS deployment

## Setup

### 1. Configure GitHub Secret

Create `PROVIDERS_JSON` secret in your repository settings with format:

```json
[
  {"id": "provider1", "base_url": "https://api.example.com", "api_key": "sk-...", "type": "openai"},
  {"id": "provider2", "base_url": "https://new-api.example.com", "api_key": "sk-...", "type": "newapi"}
]
```

Fields:
- `id` - Unique identifier for the provider
- `base_url` - Provider's base URL (for `/v1/models`)
- `api_key` - API key for authentication
- `type` - Either `"openai"` or `"newapi"` (auto-detected by hostname if omitted)

### 2. Create VPS Sync PAT

Create a Personal Access Token with `repo` scope for `VPS_SYNC_PAT` secret. This allows the VPS to pull the latest data.

### 3. Deploy to VPS

```bash
git clone <repo-url>
cd llm-model-sync
pip install pyyaml aiohttp
```

Add cron entry for 04:00 UTC (one hour after GitHub Actions):
```bash
0 4 * * * cd /path/to/llm-model-sync && ./scripts/vps-sync.sh >> /var/log/llm-sync.log 2>&1
```

## Usage

### Manual Sync (Dry Run)
```bash
DATA_DIR=data PROVIDERS_JSON='[{"id":"test","base_url":"...","api_key":"..."}]' python scripts/sync_models.py
python scripts/apply_sync.py --dry-run
```

### Output Files

- `data/models.json` - Current model lists per provider
- `data/pricing.json` - Pricing data from providers
- `data/pricing-changes.json` - Free→paid transitions since last run

## Provider Types

- **openai** - Standard OpenAI-compatible `/v1/models` endpoint
- **newapi** - New-API format with `/api/pricing` endpoint (Chinese proxy)

Detection by hostname: Providers with `new-api`, `nvm`, or `one-api` in hostname are auto-detected as newapi type.

## Security

All provider credentials come from GitHub Secrets only. The workflow YAML contains no hardcoded URLs or keys. Never logs API keys or model lists.