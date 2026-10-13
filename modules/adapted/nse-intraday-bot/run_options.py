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
Options Scanner — Nifty / Bank Nifty / Sensex
==============================================
Scans all three indices every 5 minutes during kill zones.
Fires Telegram alert when score >= 70/100 (sure shot only).
Saves to options_log.json.

Run:
  python run_options.py          # one-shot scan
  UPDATE_ONLY=1 python run_options.py   # update status only
"""

import json
import os
import time
from datetime import datetime, timedelta, timezone

from feeds.index_feed import (
    get_index_data,
    get_india_vix,
    get_prev_day_levels,
    next_expiry,
)
from notifier import telegram_send
from options_strategy import MIN_SCORE, score_options

OPTIONS_LOG = "options_log.json"
BOT_STATE_FILE = "bot_state.json"
INDICES = ["NIFTY", "BANKNIFTY", "SENSEX"]

# GitHub raw fallback so the dashboard can read the log even on Render/remote
_OPTIONS_LOG_URL = os.environ.get(
    "OPTIONS_LOG_URL",
    "https://raw.githubusercontent.com/lavakus/nse-intraday-bot/main/options_log.json",
)


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _load_log() -> list:
    # 1) Try local file first
    try:
        with open(OPTIONS_LOG, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[OPTIONS] Failed to load local log: {e}")

    # 2) Fallback: fetch from GitHub (for Render / remote dashboard)
    try:
        import requests as _req

        r = _req.get(_OPTIONS_LOG_URL, timeout=10)
        if r.status_code == 200:
            print("[OPTIONS] Loaded log from GitHub fallback")
            return r.json()
    except Exception as e:
        print(f"[OPTIONS] GitHub fallback failed: {e}")
    return []


def _save_log(data: list):
    with open(OPTIONS_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def _is_paused() -> bool:
    try:
        with open(BOT_STATE_FILE, encoding="utf-8") as f:
            return json.load(f).get("OPTIONS", {}).get("paused", False)
    except FileNotFoundError:
        return False
    except Exception as e:
        print(f"[OPTIONS] bot_state read error: {e}")
        return False


# ── Status updater ────────────────────────────────────────────────


def update_options_statuses() -> list:
    """Update OPEN options calls with current index price."""
    data = _load_log()
    changed = 0

    for rec in data:
        if rec.get("status") != "OPEN":
            continue
        try:
            from feeds.index_feed import get_index_data

            d = get_index_data(rec["index"])
            price = d["price"]
            if price is None:
                continue

            entry = float(rec["entry"])
            t2 = float(rec["t2"])
            sl = float(rec["sl"])
            d_ = rec["direction"]

            rec["exit_price"] = price

            if d_ == "LONG":
                rec["pnl_pts"] = round(price - entry, 1)
                rec["pnl_pct"] = round((price - entry) / entry * 100, 2)
                if price >= t2:
                    rec["status"] = "TARGET HIT"
                    changed += 1
                elif price <= sl:
                    rec["status"] = "SL HIT"
                    changed += 1
            else:
                rec["pnl_pts"] = round(entry - price, 1)
                rec["pnl_pct"] = round((entry - price) / entry * 100, 2)
                if price <= t2:
                    rec["status"] = "TARGET HIT"
                    changed += 1
                elif price >= sl:
                    rec["status"] = "SL HIT"
                    changed += 1
        except Exception as e:
            print(f"[OPTIONS] Status update error for {rec.get('index', '?')}: {e}")

    if changed:
        _save_log(data)
    return data


# ── Telegram formatter ────────────────────────────────────────────


def _format_options_alert(sig: dict, vix_data: dict) -> str:
    chk = sig.get("must_have_checklist", {})
    lines = (
        [
            f"🎯 OPTIONS CALL — {sig['index']} {sig['option_type']}",
            "",
            f"Index     : {sig['index']}  @  {sig['entry']:,.0f}",
            f"Signal    : {'🟢 BUY CALL' if sig['option_type'] == 'CALL' else '🔴 BUY PUT'}",
            f"Score     : {sig['score']}/100  [{sig['signal_strength']}]",
            f"Kill Zone : {sig['kill_zone']}",
            f"India VIX : {sig['vix']}  — {vix_data['label'].split('(')[0].strip()}",
            "",
            "── Index Levels ──",
            f"Entry  : {sig['entry']:,.0f}",
            f"T1     : {sig['t1']:,.0f}  (partial exit)",
            f"T2     : {sig['t2']:,.0f}  (full target)  R:R 1:{sig['rr']}",
            f"SL     : {sig['sl']:,.0f}  (-{sig['sl_pct']}%)",
            "",
            "── Option Details ──",
            f"Expiry : {sig['expiry']}",
            f"Strike : {sig['strike']:,.0f}  {sig['option_type']}",
            f"  {sig['strike_note']}",
            f"  ATM  : {sig['strike_atm']:,.0f}",
            f"  OTM1 : {sig['strike_otm1']:,.0f}",
            "",
            "── Checklist ──",
            f"{'✅' if chk.get('bos_or_choch_15m') else '❌'}  BOS/CHOCH 15min",
            f"{'✅' if chk.get('inside_kill_zone') else '❌'}  Kill Zone active",
            f"{'✅' if chk.get('vix_safe') else '❌'}  VIX safe (<25)",
            f"{'✅' if chk.get('order_block') else '❌'}  Order Block",
            f"{'✅' if chk.get('liquidity_sweep') else '❌'}  Liquidity Sweep",
            "",
        ]
        + [f"  ✦ {r}" for r in sig.get("reasons", [])]
        + [
            "",
            "⚠ This is an INDEX call, not a premium price.",
            f"  Enter the option when index is near {sig['entry']:,.0f}.",
            f"  Max risk: 1% of capital. Exit if index hits SL {sig['sl']:,.0f}.",
        ]
    )
    return "\n".join(lines)


# ── Scanner ───────────────────────────────────────────────────────


def scan_options_once() -> list:
    """Scan all 3 indices for options signals. Returns list of signals."""
    ist = _now_ist()
    print(f"[OPTIONS] Scanning — {ist.strftime('%H:%M IST')}")

    vix_data = get_india_vix()
    print(f"[OPTIONS] India VIX: {vix_data['vix']} — {vix_data['risk']}")

    if vix_data["block"]:
        print("[OPTIONS] VIX ≥ 25 — all options trades blocked")
        return []

    signals = []
    for index in INDICES:
        try:
            data = get_index_data(index)
            pd_lvls = get_prev_day_levels(index)

            print(f"[{index}] Price={data['price']:,.0f}  Change={data['change_pct']:+.2f}%")

            if data["df_15m"] is None:
                print(f"[{index}] No 15min data")
                continue

            sig = score_options(
                index=index,
                df_15m=data["df_15m"],
                df_5m=data["df_5m"],
                vix=vix_data["vix"],
                pdh=pd_lvls["pdh"],
                pdl=pd_lvls["pdl"],
                ist_time=ist,
            )

            if sig and sig.get("score", 0) >= MIN_SCORE:
                sig["vix_label"] = vix_data["label"]
                signals.append(sig)
                print(
                    f"[{index}] ✓ {sig['option_type']} score={sig['score']}/100 "
                    f"[{sig['signal_strength']}]  strike={sig['strike']}  "
                    f"expiry={sig['expiry']}"
                )
            else:
                sc = sig.get("score", 0) if sig else 0
                print(f"[{index}] score={sc}/100 — no signal")

        except Exception as e:
            print(f"[{index}] Error: {e}")

    return signals


def get_options_data() -> dict:
    """Load options log, refresh OPEN statuses, return dashboard dict."""
    data = update_options_statuses()
    wins = [r for r in data if r.get("status") == "TARGET HIT"]
    losses = [r for r in data if r.get("status") == "SL HIT"]
    open_ = [r for r in data if r.get("status") == "OPEN"]
    closed = len(wins) + len(losses)

    try:
        vix_data = get_india_vix()
    except Exception:
        vix_data = {"vix": "—", "label": "—", "risk": "medium", "block": False}

    nifty_price = bnf_price = sensex_price = None
    nifty_chg = bnf_chg = sensex_chg = None
    try:
        nd = get_index_data("NIFTY")
        nifty_price = nd["price"]
        nifty_chg = nd["change_pct"]
        bd = get_index_data("BANKNIFTY")
        bnf_price = bd["price"]
        bnf_chg = bd["change_pct"]
        sd = get_index_data("SENSEX")
        sensex_price = sd["price"]
        sensex_chg = sd["change_pct"]
    except Exception:
        pass

    return {
        "active": [r for r in data if r.get("status") == "OPEN"][:10],
        "history": list(reversed(data))[:30],
        "summary": {
            "total": len(data),
            "wins": len(wins),
            "losses": len(losses),
            "open": len(open_),
            "win_rate": round(len(wins) / closed * 100, 1) if closed > 0 else 0,
        },
        "market": {
            "vix": vix_data["vix"],
            "vix_label": vix_data["label"],
            "vix_risk": vix_data["risk"],
            "vix_block": vix_data["block"],
            "nifty": nifty_price,
            "nifty_chg": nifty_chg,
            "banknifty": bnf_price,
            "banknifty_chg": bnf_chg,
            "sensex": sensex_price,
            "sensex_chg": sensex_chg,
        },
        "expiry": {
            "NIFTY": next_expiry("NIFTY"),
            "BANKNIFTY": next_expiry("BANKNIFTY"),
            "SENSEX": next_expiry("SENSEX"),
        },
    }


# ── Continuous watcher ────────────────────────────────────────────


def run_options_watcher():
    """Continuous 5-minute scan loop (for run_all.py)."""
    print("[OPTIONS] Watcher started — scanning every 5 min")
    alerted = {}  # key → datetime of last alert

    while True:
        ist = _now_ist()

        if _is_paused():
            print("[OPTIONS] Paused — sleeping 60s")
            time.sleep(60)
            continue

        signals = scan_options_once()
        data = _load_log()

        for sig in signals:
            key = f"{sig['index']}_{sig['option_type']}_{sig['strike']}_{sig['expiry']}"
            last = alerted.get(key)

            # De-dup: don't re-alert same call within 30 minutes
            if last and (ist - last).total_seconds() < 1800:
                continue

            alerted[key] = ist
            sig["id"] = len(data) + 1
            data.append(sig)
            _save_log(data)

            vix_data = get_india_vix()
            telegram_send(_format_options_alert(sig, vix_data))
            print(
                f"[OPTIONS] Alert fired: {sig['index']} {sig['option_type']} "
                f"{sig['strike']} {sig['expiry']}"
            )

        time.sleep(5 * 60)


# ── Standalone one-shot ───────────────────────────────────────────


def main():
    ist = _now_ist()
    print(f"[OPTIONS] One-shot scan — {ist.strftime('%A %H:%M IST')}")

    update_only = os.environ.get("UPDATE_ONLY", "0") == "1"
    if update_only:
        update_options_statuses()
        print("[OPTIONS] Status update done")
        return

    signals = scan_options_once()
    if not signals:
        print("[OPTIONS] No sure-shot options call this scan")
        return

    data = _load_log()
    vix_data = get_india_vix()

    for sig in signals:
        sig["id"] = len(data) + 1
        data.append(sig)
        ok = telegram_send(_format_options_alert(sig, vix_data))
        print(
            f"[OPTIONS] {sig['index']} {sig['option_type']} "
            f"strike={sig['strike']} — Telegram: {'SENT' if ok else 'FAILED'}"
        )

    _save_log(data)


if __name__ == "__main__":
    main()
