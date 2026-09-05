"""
AXIOM Preflight — go-live readiness check.

Validates that every required secret is present and that the critical external
services respond, BEFORE you trust the automation. Run locally:
    python -m tools.preflight
Or as a one-off GitHub Actions job (workflow_dispatch) to verify Secrets.

Exit code 0 = ready; non-zero = something needs fixing.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

REQUIRED = [
    "GROQ_API_KEY",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
]


def check_env() -> list[str]:
    missing = [k for k in REQUIRED if not os.getenv(k, "").strip()]
    for k in REQUIRED:
        status = "OK " if os.getenv(k, "").strip() else "MISSING"
        logger.info("  [{}] {}", status, k)
    return missing


def check_telegram() -> bool:
    try:
        from monitors.telegram_bot import send_message
        ok, info = send_message("🔧 <b>AXIOM preflight</b> — Telegram reachable.")
        logger.info("Telegram: {} ({})", "OK" if ok else "FAIL", info)
        return ok
    except Exception as exc:
        logger.error("Telegram check failed: {}", exc)
        return False


def check_groq() -> bool:
    try:
        from ai.brain import _call_groq
        out = _call_groq("You are a test.", "Reply with the single word OK.", max_tokens=5)
        ok = bool(out)
        logger.info("Groq AI: {} ({})", "OK" if ok else "FAIL", out[:40])
        return ok
    except Exception as exc:
        logger.error("Groq check failed: {}", exc)
        return False


def check_fii_dii() -> bool:
    try:
        from data.fii_dii import fetch_fii_dii
        d = fetch_fii_dii()
        if d.get("available"):
            fii = d.get("fii", {}).get("net")
            dii = d.get("dii", {}).get("net")
            logger.info("FII/DII ({}): OK  FII net {} | DII net {}", d.get("date"), fii, dii)
            return True
        logger.warning("FII/DII: unavailable — {}", d.get("note"))
        return False
    except Exception as exc:
        logger.error("FII/DII check failed: {}", exc)
        return False


def check_data() -> bool:
    try:
        from data.fetcher import load_universe
        n = len(load_universe())
        logger.info("Universe load: OK ({} symbols)", n)
        return n > 0
    except Exception as exc:
        logger.error("Universe load failed: {}", exc)
        return False


def main() -> None:
    logger.info("=== AXIOM PREFLIGHT ===")
    logger.info("-- 1. Environment variables --")
    missing = check_env()

    logger.info("-- 2. Data universe --")
    data_ok = check_data()

    logger.info("-- 3. Telegram --")
    tg_ok = check_telegram() if "TELEGRAM_BOT_TOKEN" not in missing else False

    logger.info("-- 4. Groq AI --")
    groq_ok = check_groq() if "GROQ_API_KEY" not in missing else False

    # Informational (non-fatal): NSE may block datacenter IPs; briefing degrades gracefully
    logger.info("-- 5. FII/DII (NSE, informational) --")
    fii_ok = check_fii_dii()
    logger.info("  {} fii/dii (non-fatal)", "✅" if fii_ok else "⚠️")

    logger.info("=== SUMMARY ===")
    results = {
        "env vars": not missing,
        "data": data_ok,
        "telegram": tg_ok,
        "groq": groq_ok,
    }
    for name, ok in results.items():
        logger.info("  {} {}", "✅" if ok else "❌", name)

    if missing:
        logger.error("Missing secrets: {}", ", ".join(missing))

    if all(results.values()):
        logger.success("ALL CHECKS PASSED — ready to go live.")
        sys.exit(0)
    else:
        logger.error("Preflight FAILED — fix the ❌ items above before relying on automation.")
        sys.exit(1)


if __name__ == "__main__":
    main()
