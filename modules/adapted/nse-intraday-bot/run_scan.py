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
Standalone NSE scan script — runs on GitHub Actions every 15 min.
Implements: ORB + VWAP Pullback + Breakout+Retest strategy.
Sends Telegram alert when score >= 80/150.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

# ── CONFIG FROM ENV ─────────────────────────────────────────────
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
THRESHOLD = float(os.environ.get("STRONG_SCORE", "80"))
CAPITAL = float(os.environ.get("CAPITAL", "100000"))
BASE = f"https://api.telegram.org/bot{TOKEN}"

if not TOKEN or not CHAT_ID:
    print("[WARNING] TELEGRAM_TOKEN / TELEGRAM_CHAT_ID not set — alerts will fail")


# ── MARKET HOURS CHECK ──────────────────────────────────────────


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def is_market_open() -> bool:
    ist = _now_ist()
    if ist.weekday() >= 5:  # Saturday / Sunday
        return False
    t = ist.hour * 100 + ist.minute
    return 915 <= t <= 1530


# ── TELEGRAM SEND ───────────────────────────────────────────────


def send(text: str) -> bool:
    try:
        r = requests.post(f"{BASE}/sendMessage", json={"chat_id": CHAT_ID, "text": text}, timeout=10)
        ok = r.json().get("ok", False)
        if not ok:
            print(f"[TG ERROR] {r.json().get('description')}")
        return ok
    except Exception as e:
        print(f"[TG EXCEPTION] {e}")
        return False


# ── ALERT FORMATTER ─────────────────────────────────────────────

_SETUP_LABELS = {
    "BREAKOUT_RETEST": "Breakout + Retest",
    "VWAP_PULLBACK": "VWAP Pullback",
    "ORB": "ORB Breakout",
}


def format_alert(sig: dict) -> str:
    action = sig.get("signal", "BUY")
    score = sig.get("score", 0)
    pct = sig.get("score_pct", round(score / 150 * 100, 1))
    strength = sig.get("signal_strength", "GOOD")
    kz = sig.get("kill_zone", "?")
    setup_raw = sig.get("setup", "?")
    setup_lbl = _SETUP_LABELS.get(setup_raw, setup_raw)
    ph = sig.get("phase_scores", {})
    tp = sig.get("trade_params", {})
    chk = sig.get("must_have_checklist", {})
    or_info = sig.get("opening_range", {})

    entry = tp.get("entry", sig.get("entry", "?"))
    sl = tp.get("sl", sig.get("sl", "?"))
    t1 = tp.get("t1", sig.get("t1", "?"))
    t2 = tp.get("t2", sig.get("t2", sig.get("target", "?")))
    rr = tp.get("rr_ratio", sig.get("rr", "?"))
    sl_pct = tp.get("sl_pct", "?")
    shares = tp.get("shares", sig.get("shares", "?"))
    risk_rs = tp.get("risk_amt", round(CAPITAL * 0.01, 0))
    bar = "#" * int(score // 15) + "." * (10 - int(score // 15))

    lines = (
        [
            f"*** NSE INTRADAY  —  {action} SIGNAL ***",
            "",
            f"Stock     : {sig['symbol']}",
            f"Setup     : {setup_lbl}",
            f"Direction : {action}",
            f"Score     : {score}/150  ({pct}%)  [{bar}]",
            f"Strength  : {strength}",
            f"Kill Zone : {kz}",
            "",
            "--- TRADE PARAMETERS ---",
            f"Entry  : Rs {entry}",
            f"SL     : Rs {sl}  ({sl_pct}%)",
            f"T1     : Rs {t1}  (exit 50% of position)",
            f"T2     : Rs {t2}  (full target, RR 1:{rr})",
            "",
            f"Qty    : {shares} shares",
            f"Risk   : Rs {int(risk_rs)} (1% capital)",
            "",
            "--- OPENING RANGE ---",
            f"OR High : Rs {or_info.get('high', '?')}",
            f"OR Low  : Rs {or_info.get('low', '?')}",
            f"OR Range: Rs {or_info.get('range', '?')}",
            "",
            "--- PHASE SCORES ---",
            f"Setup Quality  : {ph.get('setup_quality', '?')}/60",
            f"Trend Filters  : {ph.get('trend_filters', '?')}/40",
            f"Entry Quality  : {ph.get('entry_quality', '?')}/30",
            f"Boosters       : {ph.get('boosters', '?')}/20",
            "",
            "--- CHECKLIST ---",
            f"{'OK' if chk.get('setup_detected') else 'XX'}  Setup confirmed",
            f"{'OK' if chk.get('vwap_aligned') else 'XX'}  VWAP aligned",
            f"{'OK' if chk.get('volume_confirmed') else 'XX'}  Volume {sig.get('vol_ratio', '?')}x",
            f"{'OK' if chk.get('inside_kill_zone') else 'XX'}  Kill Zone active",
            f"{'OK' if chk.get('rr_valid') else 'XX'}  R:R >= 1.5:1",
            "",
            "--- SIGNALS ---",
        ]
        + [f"  + {r}" for r in sig.get("reasons", [])]
        + [
            "",
            (f"VWAP: Rs{sig.get('vwap', '?')}  RSI:{sig.get('rsi', '?')}  Gap:{sig.get('gap_pct', '?')}%"),
            "",
            "Exit Rules:",
            "  - Hard SL at setup candle low",
            "  - Move SL to breakeven after T1",
            "  - MANDATORY exit by 3:15 PM IST",
            "  - False breakout: exit if price reverses inside OR within 2 bars",
            "",
            "Max 3 trades/day | 2% daily loss limit",
            "Trade NSE at your own risk.",
        ]
    )
    return "\n".join(lines)


# ── MAIN SCAN ───────────────────────────────────────────────────


def main():
    ist = _now_ist()
    print(f"NSE Intraday Scan — threshold={THRESHOLD}/150  time={ist.strftime('%H:%M IST %A')}")

    if not is_market_open():
        print(f"Market closed ({ist.strftime('%A %H:%M IST')}). Skipping scan.")
        sys.exit(0)

    from concurrent.futures import ThreadPoolExecutor, as_completed

    from data_fetcher import get_intraday_data, get_prev_day_high_low
    from nse_stocks import get_nse_stocks
    from strategy import score_stock

    stocks = get_nse_stocks()[:250]
    print(f"Scanning {len(stocks)} stocks...")

    def scan_one(sym):
        try:
            df5 = get_intraday_data(sym, "5m")
            df15 = get_intraday_data(sym, "15m")
            if df5.empty or df15.empty:
                return None
            pdh, pdl = get_prev_day_high_low(sym)
            sig = score_stock(df5, df15, sym, pdh, pdl, ist, capital=CAPITAL)
            if sig and sig.get("score", 0) >= THRESHOLD:
                return sig
        except Exception as e:
            print(f"[SCAN] {sym}: {e}")
        return None

    strong = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for fut in as_completed({pool.submit(scan_one, s): s for s in stocks}):
            r = fut.result()
            if r:
                strong.append(r)
                print(
                    f"  STRONG: {r['symbol']:12s} {r['signal']:4s} "
                    f"setup={r.get('setup', '?'):18s} "
                    f"score={r['score']}/150 [{r['signal_strength']}]"
                )

    strong.sort(key=lambda x: x["score"], reverse=True)
    print(f"\nResult: {len(strong)} strong signal(s)")

    # ── Log signals ─────────────────────────────────────────────
    try:
        from signal_logger import log_signal, update_statuses

        update_statuses()
        for s in strong[:10]:
            log_signal(s)
        print(f"[LOG] {len(strong[:10])} signal(s) written to signals_log.json")
    except Exception as e:
        print(f"[LOG ERROR] {e}")

    # ── Send to Telegram ─────────────────────────────────────────
    if strong:
        send(
            f"NSE Intraday Scan — {len(strong)} setup(s) found "
            f"(score {THRESHOLD:.0f}+/150)  "
            f"{ist.strftime('%H:%M IST')}"
        )
        time.sleep(1)
        for s in strong[:5]:  # cap at 5 alerts per scan
            send(format_alert(s))
            time.sleep(0.5)
    else:
        print("No strong setups this scan. No Telegram message sent.")


if __name__ == "__main__":
    main()
