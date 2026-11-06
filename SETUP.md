# OpenCode Model Sync — Setup Guide

This system keeps your OpenCode model lists automatically updated across all your machines.

## Architecture

```
GitHub Actions (daily 3am UTC)
    ↓ fetches live models from all providers
    ↓ pushes data/models.json
    ↓
Private data repo: github.com/ons96/llm-model-data (private)
    ↓ cloned / pulled by each machine
    ↓
llm-model-sync/ (scripts only, gitignores data/)
    ↓ runs: update-models.sh
    ↓
~/.config/opencode/opencode.json   ← updated in-place with fresh model lists
```

**Key principle:** Model source-of-truth is the **private data repo**. Each machine pulls from there and updates its local OpenCode config. API keys stay local only.

---

## One-Time Setup Per Machine

### 1. Install dependencies
```bash
# Ubuntu/Debian
sudo apt install -y python3 python3-pip
pip3 install aiohttp requests pyyaml

# Or with uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv pip install aiohttp requests pyyaml
```

### 2. Clone repositories
```bash
# llm-model-sync (scripts — public repo)
git clone https://github.com/ons96/llm-model-sync.git ~/llm-model-sync

# llm-model-data (data — private repo, requires GH PAT with repo access)
# Replace <YOUR_GITHUB_PAT> with a Personal Access Token (repo scope)
git clone https://<YOUR_GITHUB_PAT>@github.com/ons96/llm-model-data.git ~/llm-model-data
```

### 3. Link data directory
```bash
cd ~/llm-model-sync
ln -s ~/llm-model-data/data ./data
# Verify: ls data/ should show models.json, pricing.json, etc.
```

### 4. Install OpenCode API keys (machine-specific, NEVER commit)
```bash
mkdir -p ~/.config/opencode
cat > ~/.config/opencode/.env << 'EOF'
# Add your real keys here (these are just examples — paste your actual keys)
BLAZEAI_API_KEY=sk-blaze-...
HUASHANG_API_KEY=sk-...
XINJIANYA_API_KEY=sk-...
GROQ_API_KEY=gsk_...
CEREBRAS_API_KEY=csk_...
# ... add others as needed
EOF

# Secure the file
chmod 600 ~/.config/opencode/.env
```

**Important:** The `.env` file is **local only**. Do NOT commit it to any repo. It's gitignored by default.

### 5. Initial sync
```bash
cd ~/llm-model-sync
./update-models.sh
```
This will:
- Read `data/models.json` (fresh from central repo)
- Update `~/llm-provider-manager/llm_providers.db` (creates it if missing)
- Sync DB → `~/.config/opencode/opencode.json`
- Create a backup: `opencode.json.bak.YYYYMMDD_HHMMSS`

---

## Daily / Weekly Updates

### Manual update (anytime)
```bash
cd ~/llm-model-sync
git pull origin main          # get latest scripts
git -C ~/llm-model-data pull   # get latest model lists
./update-models.sh
```

### Automated with cron (recommended)
```bash
crontab -e
# Add: update model lists every Sunday at 6am
0 6 * * 0 cd /home/youruser/llm-model-sync && ./update-models.sh >> /var/log/opencode-sync.log 2>&1
```

---

## VPS Deployment (Oracle / AWS / etc.)

On your VPS, the setup is identical to above. Additionally:

### Service setup (so it stays running)
```bash
# OpenCode agent runs as a service
# See: /home/ubuntu/get-shit-done/ or your existing service files
```

### Increase sync frequency (optional)
The VPS already has a cron at 4am UTC (`~/llm-model-sync/scripts/vps-sync.sh`). To make it more frequent:
```bash
crontab -l
# Edit to add more runs, e.g. every 6 hours:
0 */6 * * * cd /home/ubuntu/llm-model-sync && ./update-models.sh
```

---

## Troubleshooting

### "data/models.json not found"
- Ensure `~/llm-model-data/data/` exists and contains `models.json`
- Check symlink: `ls -la ~/llm-model-sync/data/` should point to `../llm-model-data/data`

### "No provider models updated" but models are stale
The DB already has all synced models. Force a full refresh:
```bash
# On the machine with the DB
python3 ~/llm-provider-manager/scripts/import_vps_yaml_to_db.py --vps-config-dir ~/LLM-API-Key-Proxy/config
# Then re-run update-models.sh
```

### "Huashang/blazeai skipped: not in database"
The provider needs to exist in the DB first. Import from local gateway config:
```bash
python3 ~/llm-provider-manager/scripts/import_vps_yaml_to_db.py --vps-config-dir ~/LLM-API-Key-Proxy/config
```
Or manually insert as shown in the initial setup script.

### API rate limits
If you hit rate limits during fetch (unlikely, 27 providers), increase `PROVIDER_TIMEOUT` env var:
```bash
PROVIDER_TIMEOUT=30 ./update-models.sh
```

### Restore from backup
```bash
# List backups
ls -1 ~/.config/opencode/opencode.json.bak.*

# Restore (replace with most recent good backup)
cp ~/.config/opencode/opencode.json.bak.20250513_120000 ~/.config/opencode/opencode.json
```

---

## Security Notes

- **API keys**: stored in `~/.config/opencode/.env` — this file should have `chmod 600`
- **Never commit `.env`** — it's in `.gitignore` of both repos
- **Private data repo** (`llm-model-data`) contains **no secrets**, only public model IDs
- **Backups**: `update-models.sh` auto-creates timestamped backups before each run
- **VPS security**: Ensure `~/.config/opencode/.env` is readable only by your user

---

## How It Works (Technical)

1. **GitHub Actions** (`.github/workflows/sync-models.yml`) runs daily at 3am UTC:
   - Reads `PROVIDERS_JSON` secret (contains API keys, **only in CI**)
   - Queries `/v1/models` and `/api/pricing` for all providers
   - Writes `data/models.json` + `data/pricing.json`
   - Pushes to `ons96/llm-model-data` (private)

2. **Each machine** runs `update-models.sh`:
   - `DATA_DIR` points to `~/llm-model-data/data`
   - `sync_to_opencode.py` loads `data/models.json`
   - Updates SQLite DB (`~/llm-provider-manager/llm_providers.db`)
   - `sync_db_to_opencode.py` merges DB → `~/.config/opencode/opencode.json`
   - Backup created automatically

3. **OpenCode** reads the updated `opencode.json` on next session.

---

## FAQ

**Q: Do I need API keys on every machine?**
A: Yes. The `.env` file provides keys for actual API calls. Model lists only tell OpenCode what IDs exist.

**Q: Will this work on a 1GB RAM VPS?**
A: Yes. The sync uses ~50–100MB peak. OpenCode itself uses ~200MB. Fits comfortably.

**Q: Can I run this on Windows?**
A: Yes, with WSL2 or native Python. The scripts are cross-platform.

**Q: What if a provider goes offline?**
A: The model remains in opencode.json (no automatic removal). You'll get errors when using it — manually remove if needed.

**Q: How do I disable a provider?**
A: Edit `~/.config/opencode/opencode.json` and set `"enabled": false` or remove its `models` section.

**Q: Where are backups stored?**
A: `~/.config/opencode/opencode.json.bak.YYYYMMDD_HHMMSS`

**Q: Can I customize fallback chains automatically?**
A: Not yet. Fallback chains are in `oh-my-openagent.json` and require manual adjustment or separate tooling.

---

## Files

- `~/llm-model-sync/` — scripts repository (public)
- `~/llm-model-data/` — model list cache (private, your source of truth)
- `~/llm-provider-manager/` — SQLite DB (local state, can be regenerated)
- `~/.config/opencode/` — OpenCode config (API keys + model lists)

---

**Last updated:** 2026-05-13  
**Maintainer:** You (osees)  
**Status:** Working ✅
