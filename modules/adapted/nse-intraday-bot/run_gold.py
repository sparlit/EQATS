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
Gold (XAUUSD) scanner — runs standalone or inside run_all.py.
Sends Telegram alert when score >= MIN_SCORE (65/150).
Can be run by GitHub Actions cron for 24/5 coverage.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

from feeds.dxy_feed import get_dxy_data
from feeds.gold_feed import get_asian_session_range, get_daily_data, get_gold_data, get_m5_data, get_prev_day_high_low
from gold_strategy import score_gold
from notifier import telegram_send
from shared.smc_engine import get_kill_zone
from signal_logger import log_signal

THRESHOLD = float(os.environ.get("GOLD_SCORE", "120"))
BOT_STATE_FILE = "bot_state.json"
GOLD_LOG_FILE = "gold_signals_log.json"


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _is_paused() -> bool:
    try:
        with open(BOT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("GOLD", {}).get("paused", False)
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"[GOLD] bot_state read error: {e}")
        return False


def _format_gold_alert(sig: dict) -> str:
    tp = sig.get("trade_params", {})
    ph = sig.get("phase_scores", {})
    chk = sig.get("must_have_checklist", {})
    conf = sig.get("confluence_str", f"{sig.get('confluence', '?')}/5")
    filled = min(10, int(sig["score"] // 15))
    bar = "#" * filled + "." * (10 - filled)

    def tick(key):
        return "OK" if chk.get(key) else "XX"

    lines = (
        [
            f"*** GOLD SIGNAL — {sig['signal']} ***",
            "",
            "Asset      : Gold (XAUUSD)",
            f"Score      : {sig['score']}/150  ({sig['score_pct']}%)  [{bar}]",
            f"Confluence : {conf} points active",
            f"Strength   : {sig['signal_strength']}",
            f"Kill Zone  : {sig.get('kill_zone', '?')}",
            f"DXY        : {'Confirms' if sig.get('dxy_confirmation') else 'Not confirmed'}",
            "",
            f"Entry  : ${tp.get('entry', '?')}",
            f"SL     : ${tp.get('sl', '?')}  ({tp.get('sl_pct', '?')}%)",
            f"T1     : ${tp.get('t1', '?')}  (RR 1:{tp.get('rr_t1', '?')})",
            f"T2     : ${tp.get('t2', '?')}  (RR 1:{tp.get('rr_t2', '?')})",
            "",
            "--- ICT + SMC Confluence Checklist ---",
            f"{tick('htf_bias_clear')}        HTF Daily Bias Clear",
            f"{tick('premium_discount_zone')} Premium/Discount Zone",
            f"{tick('kill_zone_active')}      Kill Zone Active (London/NY)",
            f"{tick('judas_swing')}           Judas Swing (Asian Range Sweep)",
            f"{tick('ob_or_fvg_present')}     H4 Order Block / FVG",
            "",
            "Phase Breakdown:",
            f"  SMC Structure  : {ph.get('smc_structure', '?')}/60",
            f"  ICT Filters    : {ph.get('ict_gold_filters', '?')}/40",
            f"  PA Boosters    : {ph.get('pa_boosters', '?')}/50",
            "",
        ]
        + [f"  + {r}" for r in sig.get("reasons", [])]
        + [
            "",
            "Move SL to breakeven at T1. Max 0.5% capital risk.",
            "Trade Gold at your own risk.",
        ]
    )
    return "\n".join(lines)


def scan_gold_once() -> dict | None:
    """Run one Gold scan. Returns signal dict or None."""
    ist = _now_ist()
    print(f"[GOLD] Scanning — {ist.strftime('%H:%M IST')}")

    try:
        data = get_gold_data()
        if data["price"] is None:
            print("[GOLD] No price data")
            return None

        pdh, pdl = get_prev_day_high_low()
        dxy = get_dxy_data()
        df_daily = get_daily_data()
        df_5m = get_m5_data()

        sig = score_gold(
            df_4h=data["df_4h"],
            df_1h=data["df_1h"],
            df_15m=data["df_15m"],
            df_daily=df_daily,
            df_5m=df_5m,
            pdh=pdh,
            pdl=pdl,
            dxy_data=dxy,
            ist_time=ist,
        )

        kz, kz_pts = get_kill_zone("GOLD", ist.hour, ist.minute)
        print(f"[GOLD] Kill Zone: {kz} (pts={kz_pts}) | Price={data['price']}")

        if sig and sig.get("score", 0) >= THRESHOLD:
            print(
                f"[GOLD] STRONG: {sig['signal']} "
                f"score={sig['score']}/150 [{sig['signal_strength']}] "
                f"entry={sig['entry']} T1={sig['t1']} T2={sig['t2']}"
            )
            return sig
        if sig and isinstance(sig, dict) and sig.get("score", 0) > 0:
            print(f"[GOLD] Signal found but score {sig.get('score', 0)}/150 < threshold {THRESHOLD}")
        elif kz_pts == 0:
            print(f"[GOLD] Blocked — not in a kill zone (current: {kz})")
        else:
            print("[GOLD] Blocked — BOS/CHOCH, Order Block, or Liquidity Sweep not confirmed")
    except Exception as e:
        print(f"[GOLD] Scan error: {e}")
    return None


def run_gold_watcher():
    """Continuous 15-minute scan loop for Gold (for local run_all.py)."""
    print("[GOLD] Watcher started — scanning every 15 min")
    alerted_today = set()
    last_date = None

    while True:
        ist = _now_ist()
        today = ist.date()

        if last_date != today:
            alerted_today = set()
            last_date = today

        if _is_paused():
            print("[GOLD] Paused — sleeping 60s")
            time.sleep(60)
            continue

        sig = scan_gold_once()
        if sig:
            key = f"{sig['signal']}_{sig['entry']}"
            if key not in alerted_today:
                alerted_today.add(key)
                log_signal(sig)
                telegram_send(_format_gold_alert(sig))
                print("[GOLD] Alert fired and logged")

        time.sleep(15 * 60)  # scan every 15 minutes


# ── Standalone entry (for GitHub Actions or direct run) ─────────


def main():
    ist = _now_ist()
    print(f"[GOLD] One-shot scan — {ist.strftime('%A %H:%M IST')}")

    sig = scan_gold_once()
    if sig:
        log_signal(sig)
        ok = telegram_send(_format_gold_alert(sig))
        print(f"[GOLD] Telegram: {'SENT' if ok else 'FAILED'}")
    else:
        print("[GOLD] No strong setup — no alert sent")


if __name__ == "__main__":
    main()
