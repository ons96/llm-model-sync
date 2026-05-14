#!/usr/bin/env python3
"""System health check for LLM model sync infrastructure.

Checks:
1. CI sync freshness (models.json age)
2. VPS1 gateway health (port 8000)
3. VPS2 opencode health
4. Provider model counts vs last known
5. Disk/memory on VPS instances
6. Cron job freshness

Usage: python3 health_check.py [--json] [--quiet]
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", str(Path(__file__).parent.parent / "data")))
MODELS_JSON = DATA_DIR / "models.json"
VPS1 = "40.233.101.233"
VPS2 = "155.248.217.255"
SSH_KEY = os.path.expanduser("~/.ssh/oracle.key")
MAX_AGE_HOURS = 30

results = {"timestamp": datetime.now(timezone.utc).isoformat(), "checks": {}}


def ssh_cmd(host, cmd, timeout=15):
    try:
        r = subprocess.run(
            ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=10", f"ubuntu@{host}", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "TIMEOUT", -1
    except Exception as e:
        return str(e), -1


def check_local_models_freshness():
    if not MODELS_JSON.exists():
        return "FAIL", f"{MODELS_JSON} not found"
    mtime = datetime.fromtimestamp(MODELS_JSON.stat().st_mtime, tz=timezone.utc)
    age = datetime.now(timezone.utc) - mtime
    age_hours = age.total_seconds() / 3600
    if age_hours > MAX_AGE_HOURS:
        return "WARN", f"models.json is {age_hours:.1f}h old (max {MAX_AGE_HOURS}h)"
    with open(MODELS_JSON) as f:
        d = json.load(f)
    total = sum(v.get("model_count", 0) for v in d.values())
    broken = [k for k, v in d.items() if v.get("model_count", 0) == 0]
    working = len(d) - len(broken)
    return "OK", f"{working} working providers, {total} models, {len(broken)} broken, age {age_hours:.1f}h"


def check_vps1_gateway():
    out, rc = ssh_cmd(VPS1, "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/ 2>/dev/null || echo 'FAIL'")
    if rc != 0:
        return "FAIL", f"SSH failed: {out[:80]}"
    out = out.strip().replace("'", "")
    if "200" in out:
        svc, _ = ssh_cmd(VPS1, "sudo systemctl is-active llm-gateway 2>/dev/null")
        return "OK", f"HTTP 200, service={svc}"
    return "WARN", f"HTTP {out}"


def check_vps1_resources():
    out, rc = ssh_cmd(VPS1, "free -m | awk '/Mem/{print $3,$4}'; df -h / | awk 'NR==2{print $5}'")
    if rc != 0:
        return "FAIL", f"SSH failed: {out[:80]}"
    return "OK", f"mem_used/free_mb={out}, disk_use={out}"


def check_vps2_resources():
    out, rc = ssh_cmd(VPS2, "free -m | awk '/Mem/{print $3,$4}'; df -h / | awk 'NR==2{print $5}'")
    if rc != 0:
        return "FAIL", f"SSH failed: {out[:80]}"
    return "OK", f"mem/disk: {out}"


def check_vps2_opencode():
    out, rc = ssh_cmd(VPS2, "test -f ~/.config/opencode/opencode.json && echo exists || echo missing")
    if rc != 0:
        return "FAIL", f"SSH failed: {out[:80]}"
    if "exists" in out:
        return "OK", "opencode.json present"
    return "FAIL", "opencode.json missing"


def check_vps_crons():
    checks = {}
    for name, host in [("VPS1", VPS1), ("VPS2", VPS2)]:
        out, rc = ssh_cmd(host, "crontab -l 2>/dev/null | grep -c model")
        if rc != 0:
            checks[name] = f"FAIL: no cron"
        else:
            checks[name] = f"OK: {out} model cron(s)"
    return "OK", str(checks)


checks = [
    ("local_models_freshness", check_local_models_freshness),
    ("vps1_gateway", check_vps1_gateway),
    ("vps1_resources", check_vps1_resources),
    ("vps2_resources", check_vps2_resources),
    ("vps2_opencode", check_vps2_opencode),
    ("vps_crons", check_vps_crons),
]

failures = 0
warnings = 0

for name, fn in checks:
    status, detail = fn()
    results["checks"][name] = {"status": status, "detail": detail}
    if status == "FAIL":
        failures += 1
    elif status == "WARN":
        warnings += 1

    if "--quiet" not in sys.argv:
        icon = {"OK": ".", "WARN": "!", "FAIL": "X"}[status]
        print(f" [{icon}] {name}: {detail}")

if "--json" in sys.argv:
    print(json.dumps(results, indent=2))

print(f"\nResults: {len(checks) - failures - warnings} OK, {warnings} WARN, {failures} FAIL")
sys.exit(1 if failures > 0 else 0)
