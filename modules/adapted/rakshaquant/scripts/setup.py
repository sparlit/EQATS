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


"""
Guided one-command setup for RakshaQuant.

Run this first:  uv run python scripts/setup.py

It creates your .env from the template if needed, runs the readiness check
(``scripts/check_config.py``) and prints the exact next command. Every key is optional: the
demo needs none. ASCII-only output so it works on any terminal.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

ENV = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
LINE = "=" * 64


def main() -> int:
    print(LINE)
    print(" RakshaQuant - Setup")
    print(LINE)
    print(
        f"[i] Python {sys.version_info.major}.{sys.version_info.minor} "
        f"({'OK' if sys.version_info >= (3, 11) else 'needs 3.11+'})"
    )

    # 1. Ensure a .env exists.
    if not ENV.exists():
        if ENV_EXAMPLE.exists():
            shutil.copy(ENV_EXAMPLE, ENV)
            print("[+] Created .env from .env.example")
        else:
            print("[!] .env.example not found - cannot create .env")
        print()
        print("[ACTION] Every key in .env is optional. Set only what you use:")
        print("   - LLM_ROLE_* and the key of each provider a role names (book C, reviews)")
        print("   - TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID for alerts")
        print()
        print("Then re-run:  uv run python scripts/setup.py")
        print(LINE)
        return 0

    print("[+] .env present")
    print()

    # 2. The readiness check (the same one scripts/check_config.py prints).
    sys.path.insert(0, str(ROOT / "scripts"))
    from check_config import main as check_config

    code = check_config()
    print()
    if code == 0:
        print("[NEXT] Synthetic demo, no keys needed:")
        print("         uv run python scripts/run_live_trading.py --demo")
        print("       Paper session in the web console:")
        print("         uv run python scripts/run_live_trading.py --mode web")
    print(LINE)
    return code


if __name__ == "__main__":
    from src.ops.process import run_entry_point

    run_entry_point("setup", main)
