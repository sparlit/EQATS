"""
Daily liveness heartbeat — confirms the automation is alive.
If this Telegram ping stops arriving, something is broken. Silence = alarm.
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger

from monitors.telegram_bot import send_message

IST = ZoneInfo("Asia/Kolkata")


def main() -> None:
    now = datetime.now(IST)
    try:
        from screener.regime_classifier import classify_regime
        regime = classify_regime().regime
    except Exception:
        regime = "N/A"

    msg = (
        f"<b>✅ JARVIS HEARTBEAT</b>\n"
        f"{now.strftime('%a %d %b %Y · %H:%M IST')}\n"
        f"Automation online · Regime: <b>{regime}</b>\n"
        f"<i>If this stops arriving, check GitHub Actions.</i>"
    )
    ok, info = send_message(msg)
    logger.info("Heartbeat sent: {} ({})", ok, info)


if __name__ == "__main__":
    main()
