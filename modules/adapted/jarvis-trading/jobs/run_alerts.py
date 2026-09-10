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


"""
Pre-market Telegram alert push (~08:50 IST via GitHub Actions).

Completes the alert loop alongside the existing 15-min intraday signal scans:
  • Event guard — results/board meetings for watchlist names + high-impact
    macro events (RBI/expiry/CPI) in the next 7 days
  • Top setups — today's Grade-A screener picks (instant from the OHLCV cache)
"""

import warnings

warnings.simplefilter("ignore")

from dotenv import load_dotenv

load_dotenv(override=True)

import csv
from pathlib import Path

from loguru import logger

WATCHLIST = Path("data/watchlist.csv")


def _watchlist_symbols(limit: int = 20) -> list[str]:
    if not WATCHLIST.exists():
        return []
    with WATCHLIST.open() as f:
        return [r["symbol"].replace(".NS", "") for r in csv.DictReader(f) if r.get("symbol")][:limit]


def _event_lines() -> list[str]:
    from data.econ_calendar import fetch_corporate_events, macro_events

    want = {s.upper() for s in _watchlist_symbols()}
    lines = []

    def _playbook(sym: str) -> str:
        try:
            from analytics.earnings import earnings_stats

            st = earnings_stats(sym)
            if st:
                return f" (hist: avg ±{st['avg_abs_move']}% on results, {st['pct_up']:.0f}% up)"
        except Exception:
            pass
        return ""

    try:
        for e in fetch_corporate_events(days_ahead=7, limit=60):
            if e.get("symbol", "").upper() in want:
                sym = e["symbol"].upper()
                lines.append(f"⚠ <b>{sym}</b> — {e.get('purpose', 'event')} · {e.get('date_str', '')}{_playbook(sym)}")
    except Exception as exc:
        logger.warning("corporate events failed: {}", exc)
    try:
        for e in macro_events(days_ahead=7):
            if (e.get("impact") or "").upper() == "HIGH":
                lines.append(f"🔴 {e.get('event', '')} · {e.get('date_str', '')}")
    except Exception as exc:
        logger.warning("macro events failed: {}", exc)
    return lines[:8]


def _setup_lines() -> list[str]:
    from screener.screener import run_screener

    try:
        df = run_screener(None)
    except Exception as exc:
        logger.warning("screener failed: {}", exc)
        return []
    if df.empty:
        return []
    top = df[df["grade"] == "A"].head(5) if "grade" in df.columns else df.head(5)
    return [
        f"▲ <b>{str(r['symbol']).replace('.NS', '')}</b> — score {r['score']:.0f}"
        + (f" · ₹{r['close']:.1f}" if "close" in top.columns else "")
        for _, r in top.iterrows()
    ]


def main() -> None:
    from monitors.telegram_bot import is_configured, send_message

    if not is_configured():
        logger.error("Telegram not configured — set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return

    events = _event_lines()
    setups = _setup_lines()
    parts = ["<b>🌅 AXIOM Pre-Market Alerts</b>"]
    parts.append("\n<b>Event Guard · next 7 days</b>")
    parts.extend(events or ["✓ No watchlist events or high-impact macro ahead."])
    if setups:
        parts.append("\n<b>Top Grade-A Setups</b>")
        parts.extend(setups)
    parts.append("\n<i>Details → axiom-129.vercel.app</i>")

    ok, err = send_message("\n".join(parts))
    logger.info("Pre-market alerts sent: {} {}", ok, err or "")


if __name__ == "__main__":
    main()
