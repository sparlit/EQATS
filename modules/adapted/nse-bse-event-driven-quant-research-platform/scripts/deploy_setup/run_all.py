from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Phase 2: Automated service configuration.

Reads credentials from accounts.json (created by create_accounts.py).
Automatically configures all services — no manual steps needed.

Usage:
    python3 run_all.py
"""


import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

RESULTS_FILE = Path(__file__).parent / "deploy_results.json"
ACCOUNTS_FILE = Path(__file__).parent / "accounts.json"


def run_all() -> None:
    """Execute all deployment configuration steps — fully automated."""
    if not ACCOUNTS_FILE.exists():
        print("=" * 60)
        print("  ERROR: accounts.json not found!")
        print()
        print("  Run Phase 1 first:")
        print("  python3 create_accounts.py")
        print("=" * 60)
        raise SystemExit(1)

    print("=" * 60)
    print("  NSE-BSE Quant — Automated Deployment (Phase 2)")
    print("=" * 60)
    print()
    print("  Configuring all services automatically...")
    print("  Estimated time: 5-10 minutes.")
    print()

    results = {}
    start = time.time()

    # ── Step 1: Neon PostgreSQL ──────────────────────────────────────
    print("━" * 60)
    print("  Step 1/5: Neon PostgreSQL")
    print("━" * 60)
    try:
        from setup_neon import setup_neon, verify_neon_connection

        neon_email, neon_pass, neon_dsn = setup_neon()
        results["neon"] = {"email": neon_email, "password": neon_pass, "dsn": neon_dsn}

        if neon_dsn:
            print("  Verifying connection...")
            if verify_neon_connection(neon_dsn):
                print("  [✓] Neon connection verified")
            else:
                print("  [i] Neon connection check skipped")
        print()
    except Exception as e:
        print(f"  [!] Neon setup failed: {e}")
        results["neon"] = {"error": str(e)}
        neon_dsn = ""
        print()

    # ── Step 2: Upstash Redis ───────────────────────────────────────
    print("━" * 60)
    print("  Step 2/5: Upstash Redis")
    print("━" * 60)
    try:
        from setup_upstash import setup_upstash, verify_upstash_connection

        upstash_email, upstash_pass, redis_url = setup_upstash()
        results["upstash"] = {"email": upstash_email, "password": upstash_pass, "url": redis_url}

        if redis_url:
            print("  Verifying connection...")
            if verify_upstash_connection(redis_url):
                print("  [✓] Upstash connection verified")
            else:
                print("  [!] Upstash connection failed")
        print()
    except Exception as e:
        print(f"  [!] Upstash setup failed: {e}")
        results["upstash"] = {"error": str(e)}
        redis_url = ""
        print()

    # ── Step 3: GitHub Secrets ──────────────────────────────────────
    print("━" * 60)
    print("  Step 3/5: GitHub Actions Secrets")
    print("━" * 60)
    try:
        from setup_github_secrets import setup_github_secrets

        if neon_dsn and redis_url:
            gh_email, gh_pass, gh_ok = setup_github_secrets(neon_dsn, redis_url)
            results["github"] = {"email": gh_email, "password": gh_pass, "secrets_set": gh_ok}
        else:
            print("  [!] Skipping: missing Neon DSN or Redis URL")
            results["github"] = {"skipped": True}
        print()
    except Exception as e:
        print(f"  [!] GitHub setup failed: {e}")
        results["github"] = {"error": str(e)}
        print()

    # ── Step 4: Render Web Service ──────────────────────────────────
    print("━" * 60)
    print("  Step 4/5: Render Web Service")
    print("━" * 60)
    try:
        from setup_render import setup_render

        if neon_dsn and redis_url:
            render_email, render_pass, render_url = setup_render(neon_dsn, redis_url)
            results["render"] = {"email": render_email, "password": render_pass, "url": render_url}
        else:
            print("  [!] Skipping: missing Neon DSN or Redis URL")
            render_url = ""
            results["render"] = {"skipped": True}
        print()
    except Exception as e:
        print(f"  [!] Render setup failed: {e}")
        results["render"] = {"error": str(e)}
        render_url = ""
        print()

    # ── Step 5: UptimeRobot ─────────────────────────────────────────
    print("━" * 60)
    print("  Step 5/5: UptimeRobot Monitor")
    print("━" * 60)
    try:
        from setup_uptimerobot import setup_uptimerobot

        if render_url:
            ur_email, ur_pass, ur_ok = setup_uptimerobot(render_url)
            results["uptimerobot"] = {"email": ur_email, "password": ur_pass, "monitor_active": ur_ok}
        else:
            print("  [!] Skipping: no Render URL")
            results["uptimerobot"] = {"skipped": True}
        print()
    except Exception as e:
        print(f"  [!] UptimeRobot setup failed: {e}")
        results["uptimerobot"] = {"error": str(e)}
        print()

    elapsed = time.time() - start

    # ── Summary ─────────────────────────────────────────────────────
    print("=" * 60)
    print("  Deployment Summary")
    print("=" * 60)
    print(f"  Elapsed: {elapsed:.0f}s")
    print()

    neon = results.get("neon", {})
    if neon.get("dsn"):
        print(f"  [✓] Neon PG:      {neon['dsn'][:50]}...")
    else:
        print(f"  [✗] Neon PG:      {neon.get('error', 'not configured')}")
    print()

    ups = results.get("upstash", {})
    if ups.get("url"):
        print(f"  [✓] Upstash:      {ups['url'][:50]}...")
    else:
        print(f"  [✗] Upstash:      {ups.get('error', 'not configured')}")
    print()

    gh = results.get("github", {})
    if gh.get("secrets_set"):
        print("  [✓] GitHub:       secrets added")
    else:
        print(f"  [✗] GitHub:       {gh.get('error', 'not configured')}")
    print()

    rend = results.get("render", {})
    if rend.get("url"):
        print(f"  [✓] Render:       {rend['url']}")
    else:
        print(f"  [✗] Render:       {rend.get('error', 'not configured')}")
    print()

    ur = results.get("uptimerobot", {})
    if ur.get("monitor_active"):
        print("  [✓] UptimeRobot:  monitor active")
    else:
        print(f"  [✗] UptimeRobot:  {ur.get('error', 'not configured')}")
    print()

    RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str))
    print(f"  Results saved to: {RESULTS_FILE}")

    if rend.get("url"):
        print()
        print(f"  Your dashboard: {rend['url']}")

    env_path = PROJECT_ROOT / ".env"
    env_lines = []
    if neon.get("dsn"):
        env_lines.append(f"NSE_QUANT_PG_DSN={neon['dsn']}")
    if ups.get("url"):
        env_lines.append(f"NSE_QUANT_REDIS_URL={ups['url']}")
    env_lines.append("REDIS_TTL=3600")
    env_path.write_text("\n".join(env_lines) + "\n")
    print(f"  .env saved to: {env_path}")


if __name__ == "__main__":
    run_all()
