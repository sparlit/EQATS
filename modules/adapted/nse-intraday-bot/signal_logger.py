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
Logs every alert to asset-specific JSON files.
Checks live price to update status: TARGET HIT / SL HIT / OPEN.

Log files:
  signals_log.json      — NSE India
  gold_signals_log.json — Gold (XAUUSD)
  btc_signals_log.json  — Bitcoin (BTCUSDT)
"""
import json
import os
from datetime import datetime

LOG_FILE = "signals_log.json"  # NSE (existing)
GOLD_LOG_FILE = "gold_signals_log.json"
BTC_LOG_FILE = "btc_signals_log.json"
EVAL_FILE = "evaluations_log.jsonl"

# Ticker map for live price lookups
_PRICE_TICKER = {
    "GOLD": "GC=F",
    "BTC": "BTC-USD",
    "BTCUSDT": "BTC-USD",
}


def _log_file_for(asset: str) -> str:
    if asset in ("GOLD", "XAUUSD"):
        return GOLD_LOG_FILE
    if asset in ("BTC", "BTCUSDT"):
        return BTC_LOG_FILE
    return LOG_FILE  # NSE default


# When running on Render (no local file), fetch from GitHub raw URL
_BASE_RAW = "https://raw.githubusercontent.com/lavakus/nse-intraday-bot/main"
GITHUB_RAW = os.environ.get("SIGNALS_JSON_URL", f"{_BASE_RAW}/signals_log.json")
GITHUB_RAW_GOLD = os.environ.get("GOLD_SIGNALS_JSON_URL", f"{_BASE_RAW}/gold_signals_log.json")
GITHUB_RAW_BTC = os.environ.get("BTC_SIGNALS_JSON_URL", f"{_BASE_RAW}/btc_signals_log.json")


def _load(log_file: str = LOG_FILE) -> list:
    # 1) Try local file
    if os.path.exists(log_file):
        try:
            with open(log_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[LOGGER] Failed to read {log_file}: {e}")

    # 2) Fallback: fetch from GitHub (for Render / remote host)
    # All three log files are committed to the repo by GitHub Actions workflows
    url_map = {
        LOG_FILE: GITHUB_RAW,
        GOLD_LOG_FILE: GITHUB_RAW_GOLD,
        BTC_LOG_FILE: GITHUB_RAW_BTC,
    }
    raw_url = url_map.get(log_file)
    if raw_url:
        try:
            import requests as _req

            r = _req.get(raw_url, timeout=10)
            if r.status_code == 200:
                print(f"[LOGGER] Loaded {log_file} from GitHub fallback")
                return r.json()
        except Exception as e:
            print(f"[LOGGER] GitHub fallback failed for {log_file}: {e}")
    return []


def _save(data: list, log_file: str = LOG_FILE):
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


def log_signal(sig: dict):
    """Save a new alert to the correct asset log file."""
    asset = sig.get("asset", sig.get("symbol", "NSE"))
    log_file = _log_file_for(asset)
    data = _load(log_file)
    tp = sig.get("trade_params", {})

    record = {
        "id": len(data) + 1,
        "datetime": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "asset": asset,
        "symbol": sig["symbol"],
        "direction": sig["direction"],
        "signal": sig.get("signal", "BUY" if sig["direction"] == "LONG" else "SELL"),
        "score": sig["score"],
        "score_pct": sig.get("score_pct", round(sig["score"] / 150 * 100, 1)),
        "signal_strength": sig.get("signal_strength", "GOOD"),
        "kill_zone": sig.get("kill_zone", "?"),
        "phase_scores": sig.get("phase_scores", {}),
        "must_have_checklist": sig.get("must_have_checklist", {}),
        "entry": tp.get("entry", sig.get("entry")),
        "t1": tp.get("t1", sig.get("t1")),
        "target": tp.get("t2", sig.get("target", sig.get("t2"))),
        "sl": tp.get("sl", sig.get("sl")),
        "rr": tp.get("rr_ratio", sig.get("rr")),
        "sl_pct": tp.get("sl_pct", sig.get("sl_pct")),
        "rsi": sig.get("rsi", 0),
        "vwap": sig.get("vwap", 0),
        "vol_ratio": sig.get("vol_ratio", 0),
        "reasons": sig.get("reasons", []),
        "status": "OPEN",
        "exit_price": None,
        "pnl_pts": None,
        "pnl_pct": None,
    }
    data.append(record)
    _save(data, log_file)
    print(
        f"[LOG] Saved signal #{record['id']} — {record['symbol']} "
        f"{record['signal']} score={record['score']}/150"
    )


def log_evaluation(sym: str, score: int, blocked_reason: str, phase_scores: dict):
    """
    Log a near-miss evaluation (passed Phase 1 but failed hard rule or score).
    Appended to evaluations_log.jsonl for weekly review.
    """
    try:
        entry = {
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "symbol": sym,
            "score": score,
            "blocked_reason": blocked_reason,
            "phase_scores": phase_scores,
        }
        with open(EVAL_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception as e:
        print(f"[LOGGER] log_evaluation failed: {e}")


def _get_live_price(rec: dict) -> float | None:
    """Return live price for any asset (NSE / Gold / BTC)."""
    import yfinance as yf

    try:
        symbol = rec.get("symbol", "")
        asset = rec.get("asset", symbol)
        yf_sym = _PRICE_TICKER.get(asset) or _PRICE_TICKER.get(symbol)
        if yf_sym is None:
            yf_sym = f"{symbol}.NS"  # default NSE
        tk = yf.Ticker(yf_sym)
        return float(tk.fast_info["last_price"])
    except Exception:
        return None


def _update_file_statuses(log_file: str) -> tuple[list, int]:
    """Load one log file, refresh OPEN signals, return (data, changed_count)."""
    data = _load(log_file)
    changed = 0

    for rec in data:
        if rec["status"] != "OPEN":
            continue
        price = _get_live_price(rec)
        if price is None:
            continue
        try:
            entry = float(rec["entry"])
            target = float(rec["target"])
            sl = float(rec["sl"])
            d = rec["direction"]

            if d == "LONG":
                if price >= target:
                    rec.update(
                        status="TARGET HIT",
                        exit_price=price,
                        pnl_pts=round(price - entry, 2),
                        pnl_pct=round((price - entry) / entry * 100, 2),
                    )
                    changed += 1
                elif price <= sl:
                    rec.update(
                        status="SL HIT",
                        exit_price=price,
                        pnl_pts=round(price - entry, 2),
                        pnl_pct=round((price - entry) / entry * 100, 2),
                    )
                    changed += 1
                else:
                    rec["exit_price"] = price
            else:  # SHORT
                if price <= target:
                    rec.update(
                        status="TARGET HIT",
                        exit_price=price,
                        pnl_pts=round(entry - price, 2),
                        pnl_pct=round((entry - price) / entry * 100, 2),
                    )
                    changed += 1
                elif price >= sl:
                    rec.update(
                        status="SL HIT",
                        exit_price=price,
                        pnl_pts=round(entry - price, 2),
                        pnl_pct=round((entry - price) / entry * 100, 2),
                    )
                    changed += 1
                else:
                    rec["exit_price"] = price
        except Exception as e:
            print(f"[LOGGER] Status update error for record {rec.get('id', '?')}: {e}")

    if changed:
        _save(data, log_file)
    return data, changed


def update_statuses(asset: str = "ALL") -> list:
    """
    Fetch live prices and update status of OPEN signals.
    asset="ALL"  → updates all three log files and returns combined list
    asset="NSE"  → NSE only
    asset="GOLD" → Gold only
    asset="BTC"  → BTC only
    """
    if asset == "ALL":
        nse, _ = _update_file_statuses(LOG_FILE)
        gold, _ = _update_file_statuses(GOLD_LOG_FILE)
        btc, _ = _update_file_statuses(BTC_LOG_FILE)
        return nse + gold + btc
    else:
        log_file = _log_file_for(asset)
        data, _ = _update_file_statuses(log_file)
        return data


def get_all(asset: str = "ALL") -> list:
    return update_statuses(asset)


def get_summary(data: list) -> dict:
    total = len(data)
    if total == 0:
        return {
            "total": 0,
            "wins": 0,
            "losses": 0,
            "open": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "avg_score": 0,
            "excellent": 0,
            "good": 0,
            "weak": 0,
        }

    wins = [r for r in data if r["status"] == "TARGET HIT"]
    losses = [r for r in data if r["status"] == "SL HIT"]
    open_ = [r for r in data if r["status"] == "OPEN"]
    closed = len(wins) + len(losses)
    win_rate = round(len(wins) / closed * 100, 1) if closed > 0 else 0
    total_pnl = round(sum(r["pnl_pts"] or 0 for r in data if r.get("pnl_pts")), 2)
    avg_score = round(sum(r.get("score", 0) for r in data) / total, 1)

    excellent = sum(1 for r in data if r.get("signal_strength") == "EXCELLENT")
    good = sum(1 for r in data if r.get("signal_strength") == "GOOD")
    weak = sum(1 for r in data if r.get("signal_strength") == "WEAK")

    return {
        "total": total,
        "wins": len(wins),
        "losses": len(losses),
        "open": len(open_),
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "avg_score": avg_score,
        "excellent": excellent,
        "good": good,
        "weak": weak,
    }
