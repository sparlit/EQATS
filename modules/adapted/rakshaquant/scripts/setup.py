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

It creates your .env from the template if needed, checks the required free API keys, surfaces
any configuration warnings, and prints a readiness checklist with the exact next command.
ASCII-only output so it works on any terminal.
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

ENV = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
LINE = "=" * 64


def _status(ok: bool) -> str:
    return "[ OK ]" if ok else "[MISSING]"


def main() -> None:
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
        print("[ACTION] Open .env and set your FREE API keys:")
        print("   - GROQ_API_KEY        https://console.groq.com/keys")
        print("   - LANGSMITH_API_KEY   https://smith.langchain.com/settings")
        print()
        print("Then re-run:  uv run python scripts/setup.py")
        print(LINE)
        return

    print("[+] .env present")

    # 2. Load settings (catches missing required keys gracefully).
    try:
        from src.config import get_settings

        settings = get_settings()
    except Exception as exc:
        print(f"[!] Configuration could not load: {exc}")
        print("    Set the required keys (GROQ_API_KEY, LANGSMITH_API_KEY) in .env and re-run.")
        print(LINE)
        return

    # 3. Readiness checklist.
    groq = settings.groq_api_key.get_secret_value()
    groq_ok = bool(groq) and "your_" not in groq
    langsmith = settings.langsmith_api_key.get_secret_value()
    langsmith_ok = bool(langsmith) and "your_" not in langsmith

    print()
    print(f"  Groq API key:     {_status(groq_ok)}")
    print(f"  LangSmith key:    {_status(langsmith_ok)}  (optional - tracing)")
    print(f"  Data source:      {settings.market_data_source}")
    print(f"  Execution mode:   {settings.execution_mode}  (allow_live_orders={settings.allow_live_orders})")
    print(f"  Paper wallet:     Rs.{settings.paper_wallet_balance:,.0f}")
    print(f"  Learning loop:    {'on' if settings.enable_learning else 'off'}")
    print(f"  FinOps:           {'on' if settings.finops_enabled else 'off'}")

    warnings = getattr(settings, "config_warnings", [])
    if warnings:
        print()
        for warning in warnings:
            print(f"  [WARN] {warning}")

    print()
    if groq_ok:
        print("[READY] Start the dashboard:")
        print("        uv run python scripts/run_live_trading.py")
    else:
        print("[ACTION] Set GROQ_API_KEY in .env (https://console.groq.com/keys), then re-run.")
    print(LINE)


if __name__ == "__main__":
    main()
