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
Bitcoin (BTCUSDT) scanner — runs standalone or inside run_all.py.
Sends Telegram alert when score >= MIN_SCORE (65/150).
Can be run by GitHub Actions cron for 24/7 coverage.
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

from btc_strategy import score_btc
from feeds.btc_feed import get_btc_data, get_cme_gap, get_prev_day_high_low
from feeds.fear_greed import get_fear_greed
from feeds.funding_rate import get_funding_rate
from notifier import telegram_send
from shared.smc_engine import get_kill_zone
from signal_logger import log_signal

THRESHOLD = float(os.environ.get("BTC_SCORE", "65"))
BOT_STATE_FILE = "bot_state.json"


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _is_paused() -> bool:
    try:
        with open(BOT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("BTC", {}).get("paused", False)
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"[BTC] bot_state read error: {e}")
        return False


def _format_btc_alert(sig: dict) -> str:
    tp = sig.get("trade_params", {})
    ph = sig.get("phase_scores", {})
    chk = sig.get("must_have_checklist", {})
    cme = sig.get("cme_gap", {})
    bar = "#" * int(sig["score"] // 15) + "." * (10 - int(sig["score"] // 15))

    lines = (
        [
            f"*** BITCOIN SIGNAL — {sig['signal']} ***",
            "",
            "Asset     : Bitcoin (BTCUSDT)",
            f"Score     : {sig['score']}/150  ({sig['score_pct']}%)  [{bar}]",
            f"Strength  : {sig['signal_strength']}",
            f"Kill Zone : {sig['kill_zone']}",
            f"Funding   : {sig.get('funding_rate', '?')}%",
            f"Fear/Greed: {sig.get('fear_greed_index', '?')}",
            "",
            f"Entry  : ${tp.get('entry', '?'):,}",
            f"SL     : ${tp.get('sl', '?'):,}  ({tp.get('sl_pct', '?')}%)",
            f"T1     : ${tp.get('t1', '?'):,}  (RR 1:{tp.get('rr_t1', '?')})",
            f"T2     : ${tp.get('t2', '?'):,}  (RR 1:{tp.get('rr_t2', '?')})",
            "",
            f"CME Gap Below : ${cme.get('nearest_gap_below') or 'None':,}"
            if cme.get("nearest_gap_below")
            else "CME Gap Below : None",
            f"CME Gap Above : ${cme.get('nearest_gap_above') or 'None':,}"
            if cme.get("nearest_gap_above")
            else "CME Gap Above : None",
            "",
            f"SMC Structure    : {ph.get('smc_structure', '?')}/60",
            f"ICT Crypto       : {ph.get('ict_crypto_filters', '?')}/52",
            f"PA + Boosters    : {ph.get('pa_boosters', '?')}/38",
            "",
            f"{'OK' if chk.get('bos_or_choch_4h') else 'XX'}  BOS/CHOCH 4H",
            f"{'OK' if chk.get('order_block_valid') else 'XX'}  Order Block",
            f"{'OK' if chk.get('liquidity_sweep') else 'XX'}  Liquidity Sweep",
            f"{'OK' if chk.get('inside_kill_zone') else 'XX'}  Kill Zone",
            "",
        ]
        + [f"  + {r}" for r in sig.get("reasons", [])]
        + [
            "",
            "Check funding rate before entry. Move SL to breakeven at T1.",
            "Trade BTC at your own risk.",
        ]
    )
    return "\n".join(lines)


def scan_btc_once() -> dict | None:
    """Run one BTC scan. Returns signal dict or None."""
    ist = _now_ist()
    print(f"[BTC] Scanning — {ist.strftime('%H:%M IST')}")

    try:
        data = get_btc_data()
        pdh, pdl = get_prev_day_high_low()
        funding = get_funding_rate("BTCUSDT")
        fg = get_fear_greed()
        cme = get_cme_gap()

        print(f"[BTC] Price=${data['price']:,.0f}  Funding={funding['rate_pct']}%  F&G={fg['value']} ({fg['label']})")

        sig = score_btc(
            df_weekly=data["df_weekly"],
            df_4h=data["df_4h"],
            df_1h=data["df_1h"],
            df_15m=data["df_15m"],
            pdh=pdh,
            pdl=pdl,
            funding=funding,
            fear_greed=fg,
            cme_gap=cme,
            ist_time=ist,
        )

        kz, kz_pts = get_kill_zone("BTC", ist.hour, ist.minute)
        print(f"[BTC] Kill Zone: {kz} (pts={kz_pts})")

        if sig and sig.get("score", 0) >= THRESHOLD:
            tp = sig.get("trade_params", {})
            ent = sig.get("entry", tp.get("entry", "?"))
            t2 = sig.get("t2", tp.get("t2", sig.get("target", "?")))
            print(
                f"[BTC] STRONG: {sig['signal']} "
                f"score={sig['score']}/150 [{sig['signal_strength']}] "
                f"entry=${ent:,} T2=${t2:,}"
            )
            return sig
        if sig and isinstance(sig, dict) and sig.get("score", 0) > 0:
            print(f"[BTC] Signal found but score {sig.get('score', 0)}/150 < threshold {THRESHOLD}")
        elif kz_pts == 0:
            print(f"[BTC] Blocked — not in a kill zone (current: {kz})")
        else:
            print("[BTC] Blocked — BOS/CHOCH on 4H, Order Block, or Liquidity Sweep not confirmed")
    except Exception as e:
        print(f"[BTC] Scan error: {e}")
    return None


def run_btc_watcher():
    """Continuous 15-minute scan loop for BTC (for local run_all.py)."""
    print("[BTC] Watcher started — scanning every 15 min")
    alerted_today = set()
    last_date = None

    while True:
        ist = _now_ist()
        today = ist.date()

        if last_date != today:
            alerted_today = set()
            last_date = today

        if _is_paused():
            print("[BTC] Paused — sleeping 60s")
            time.sleep(60)
            continue

        sig = scan_btc_once()
        if sig:
            key = f"{sig['signal']}_{sig['entry']}"
            if key not in alerted_today:
                alerted_today.add(key)
                log_signal(sig)
                telegram_send(_format_btc_alert(sig))
                print("[BTC] Alert fired and logged")

        time.sleep(15 * 60)


# ── Standalone entry ─────────────────────────────────────────────


def main():
    ist = _now_ist()
    print(f"[BTC] One-shot scan — {ist.strftime('%A %H:%M IST')}")

    sig = scan_btc_once()
    if sig:
        log_signal(sig)
        ok = telegram_send(_format_btc_alert(sig))
        print(f"[BTC] Telegram: {'SENT' if ok else 'FAILED'}")
    else:
        print("[BTC] No strong setup — no alert sent")


if __name__ == "__main__":
    main()
