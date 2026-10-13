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
Notifier — Telegram alerts for NSE + Gold + BTC signals.
Credentials always read from environment variables first,
falling back to config.py for local development.
"""
import os

import requests

# Env vars take priority (GitHub Actions secrets), then config.py for local dev
_TOKEN = os.environ.get("TELEGRAM_TOKEN") or ""
_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or ""

if not _TOKEN or not _CHAT_ID:
    try:
        from config import TELEGRAM_CHAT_ID as _CFG_CHAT
        from config import TELEGRAM_TOKEN as _CFG_TOKEN

        _TOKEN = _TOKEN or _CFG_TOKEN
        _CHAT_ID = _CHAT_ID or _CFG_CHAT
    except Exception:
        pass

if not _TOKEN:
    print("[NOTIFIER] WARNING: TELEGRAM_TOKEN not set — alerts will fail")

TELEGRAM_TOKEN = _TOKEN
TELEGRAM_CHAT_ID = _CHAT_ID
BASE = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ── Setup label map ─────────────────────────────────────────────
_SETUP_LABELS = {
    "BREAKOUT_RETEST": "Breakout + Retest",
    "VWAP_PULLBACK": "VWAP Pullback",
    "ORB": "ORB Breakout",
}


# ── NSE ALERT MESSAGE ───────────────────────────────────────────


def _message(sig: dict) -> str:
    action = sig.get("signal", "BUY" if sig.get("direction") == "LONG" else "SELL")
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
    risk_rs = int(tp.get("risk_amt", 1000))

    bar = "#" * int(score // 15) + "." * (10 - int(score // 15))

    lines = [
        f"*** NSE INTRADAY  --  {action} SIGNAL ***",
        "",
        f"Stock     : {sig.get('symbol', '?')}",
        f"Setup     : {setup_lbl}",
        f"Direction : {action}",
        f"Score     : {score}/150  ({pct}%)  [{bar}]",
        f"Strength  : {strength}",
        f"Kill Zone : {kz}",
        "",
        "--- TRADE PARAMETERS ---",
        f"Entry  : Rs {entry}",
        f"SL     : Rs {sl}  ({sl_pct}%)",
        f"T1     : Rs {t1}  (exit 50% here)",
        f"T2     : Rs {t2}  (RR 1:{rr})",
        "",
        f"Qty    : {shares} shares",
        f"Risk   : Rs {risk_rs} (1% capital)",
        "",
    ]

    # Show OR info if present
    if or_info.get("high"):
        lines += [
            f"Opening Range : {or_info.get('low', '?')} - {or_info.get('high', '?')}",
            "",
        ]

    lines += (
        [
            "--- PHASE SCORES ---",
            f"Setup Quality  : {ph.get('setup_quality', '?')}/60",
            f"Trend Filters  : {ph.get('trend_filters', '?')}/40",
            f"Entry Quality  : {ph.get('entry_quality', '?')}/30",
            f"Boosters       : {ph.get('boosters', '?')}/20",
            "",
            "--- CHECKLIST ---",
            f"{'OK' if chk.get('setup_detected') else 'XX'}  Setup confirmed ({setup_lbl})",
            f"{'OK' if chk.get('vwap_aligned') else 'XX'}  VWAP aligned",
            f"{'OK' if chk.get('volume_confirmed') else 'XX'}  Volume {sig.get('vol_ratio', '?')}x avg",
            f"{'OK' if chk.get('inside_kill_zone') else 'XX'}  Kill Zone active",
            f"{'OK' if chk.get('rr_valid') else 'XX'}  R:R 1:{rr}",
            "",
            "--- SIGNALS ---",
        ]
        + [f"  + {r}" for r in sig.get("reasons", [])]
        + [
            "",
            f"VWAP: {sig.get('vwap', '?')}  RSI: {sig.get('rsi', '?')}  "
            f"Gap: {sig.get('gap_pct', '0')}%",
            "",
            "Exit rules:",
            "  * Hard SL at setup candle low",
            "  * Move SL to breakeven at T1",
            "  * Exit ALL positions by 3:15 PM IST",
            "",
            "Max 3 trades/day. Trade at your own risk.",
        ]
    )
    return "\n".join(lines)


# ── TELEGRAM SEND ──────────────────────────────────────────────


def _send_telegram(sig: dict) -> bool:
    try:
        r = requests.post(
            f"{BASE}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": _message(sig)},
            timeout=10,
        )
        ok = r.json().get("ok", False)
        print(
            f"  [TELEGRAM] {sig.get('symbol', '?')} -> "
            f"{'SENT' if ok else 'FAILED: ' + r.json().get('description', '')}"
        )
        return ok
    except Exception as e:
        print(f"  [TELEGRAM ERROR] {e}")
        return False


# ── PLAIN UTILITY (bot commands, greetings, etc.) ──────────────


def telegram_send(text: str, chat_id: str = None, markup: dict = None) -> bool:
    chat_id = chat_id or TELEGRAM_CHAT_ID
    payload = {"chat_id": chat_id, "text": text}
    if markup:
        payload["reply_markup"] = markup
    try:
        r = requests.post(f"{BASE}/sendMessage", json=payload, timeout=10)
        return r.json().get("ok", False)
    except Exception as e:
        print(f"[TELEGRAM SEND ERROR] {e}")
        return False


# ── FIRE ALERT ─────────────────────────────────────────────────


def fire_alert(sig: dict):
    """Log signal to dashboard + send to Telegram."""
    sym = sig.get("symbol", "?")
    setup = sig.get("setup", "?")
    print(
        f"\n[ALERT] {sym}  {sig.get('signal', '?')}  setup={setup}  "
        f"score={sig.get('score', '?')}/150  "
        f"entry={sig.get('entry', '?')}  "
        f"t1={sig.get('t1', '?')}  t2={sig.get('t2', '?')}  "
        f"sl={sig.get('sl', '?')}"
    )

    # ── Log to dashboard ──────────────────────────────────────
    try:
        from signal_logger import log_signal

        log_signal(sig)
    except Exception as e:
        print(f"  [LOG ERROR] {e}")

    # ── Send to Telegram (with one retry) ─────────────────────
    ok = _send_telegram(sig)
    if not ok:
        import time

        time.sleep(2)
        print(f"  [RETRY] {sym}...")
        ok = _send_telegram(sig)

    print(f"  [ALERT COMPLETE] {sym} — Telegram {'SENT' if ok else 'FAILED'}")
