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
Strategy Backtest — walk history, apply strategy at each step, simulate
trades, aggregate.

For each historical date (step=5 bars), we:
  1. Slice data up to that date
  2. Compute features, apply strategy conditions
  3. If passes → entry = next bar's open
     stop = entry * (1 - stop_pct)
     target = entry + target_r * stop_distance
  4. Walk forward up to `hold_bars`:
     - stop hit first → LOSS
     - target hit first → WIN
     - neither → TIMEOUT at last close

Aggregates: n_signals, wins/losses/timeouts, win rate, avg return,
equity curve, max drawdown.

Results cached 7 days in data/backtest_cache.json
"""
import datetime as dt
import hashlib
import json
import os

import db
import pandas as pd
import rule_engine as RE
from log_utils import get_logger

log = get_logger("strategy_backtest")

CACHE_PATH = os.path.join("data", "backtest_cache.json")
CACHE_VERSION = 2
CACHE_TTL_DAYS = 7


# ============================================================
# Cache
# ============================================================
def _load_cache():
    if not os.path.exists(CACHE_PATH):
        return {}
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache):
    os.makedirs("data", exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(cache, f, default=str)


def _strategy_fingerprint(strategy):
    """Stable hash of the complete definition, not just its display name."""
    raw = json.dumps(strategy, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _cache_key(
    name,
    years,
    step,
    universe_limit,
    stop_pct,
    target_r,
    hold_bars,
    strategy=None,
    data_fingerprint="unknown",
):
    sfp = _strategy_fingerprint(strategy or {})
    return (
        f"{name}|y{years}|s{step}|u{universe_limit}|"
        f"sl{stop_pct}|t{target_r}|h{hold_bars}|"
        f"sf{sfp}|df{data_fingerprint}|v{CACHE_VERSION}"
    )


def _get_cached(
    name,
    years,
    step,
    universe_limit,
    stop_pct,
    target_r,
    hold_bars,
    strategy=None,
    data_fingerprint="unknown",
):
    cache = _load_cache()
    key = _cache_key(
        name, years, step, universe_limit, stop_pct, target_r, hold_bars, strategy, data_fingerprint
    )
    entry = cache.get(key)
    if not entry:
        return None
    try:
        d = dt.date.fromisoformat(entry.get("_cached_at", "")[:10])
        if (dt.date.today() - d).days > CACHE_TTL_DAYS:
            return None
        return entry
    except Exception:
        return None


def _put_cached(
    name,
    years,
    step,
    universe_limit,
    stop_pct,
    target_r,
    hold_bars,
    payload,
    strategy=None,
    data_fingerprint="unknown",
):
    cache = _load_cache()
    key = _cache_key(
        name, years, step, universe_limit, stop_pct, target_r, hold_bars, strategy, data_fingerprint
    )
    payload["_cached_at"] = dt.datetime.now().isoformat(timespec="seconds")
    cache[key] = payload
    _save_cache(cache)


def clear_cache(name=None):
    if not os.path.exists(CACHE_PATH):
        return
    if name is None:
        os.remove(CACHE_PATH)
        return
    cache = _load_cache()
    to_del = [k for k in cache if k.startswith(name + "|")]
    for k in to_del:
        del cache[k]
    _save_cache(cache)


# ============================================================
# Trade simulation
# ============================================================
def _simulate(df, entry_i, entry_price, stop, target, hold_bars):
    """Simulate a long entry, including the entry bar.

    Stops are deliberately conservative: a stop gap exits at the bar open,
    and when stop and target are both touched in one bar the stop wins.  If
    the requested window runs past the data, the trade is OPEN (right
    censored), never a fabricated TIMEOUT.
    """
    n = len(df)
    if entry_i < 0 or entry_i >= n or hold_bars <= 0:
        return "OPEN", float(entry_price), max(0, min(entry_i, n - 1)), 0
    end_i = min(entry_i + hold_bars, n)
    complete = (entry_i + hold_bars) <= n
    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
    c = df["Close"].values
    for j in range(entry_i, end_i):
        # Gap-through prices are executable at the open, not the requested
        # stop. Target limits remain fillable at target on an upward gap.
        if float(o[j]) <= stop:
            return "LOSS", float(o[j]), j, j - entry_i + 1
        if l[j] <= stop:
            return "LOSS", float(stop), j, j - entry_i + 1
        if h[j] >= target:
            return "WIN", float(target), j, j - entry_i + 1
    # TIMEOUT at last close in window
    last_i = end_i - 1
    if last_i <= entry_i:
        return "OPEN", float(c[entry_i]), entry_i, 1
    outcome = "TIMEOUT" if complete else "OPEN"
    return outcome, float(c[last_i]), last_i, last_i - entry_i + 1


_PIT_FORBIDDEN_FIELDS = {
    "roce",
    "pe",
    "pb",
    "roe",
    "debt_to_equity",
    "profit_growth_3y",
    "sales_growth_3y",
    "promoter_holding",
    "dividend_yield",
    "cfo_positive",
    "market_cap_cr",
    "operating_margin",
    "net_profit_margin",
    "beta_1y",
    "eps_fy",
    "book_value",
    "ev_ebitda",
    "fcf_fy",
    "net_debt_fy",
    "sector_rs",
}


def _validate_strategy_sandbox(strategy):
    """Reject signals that would leak present-day data into old bars."""
    if not isinstance(strategy, dict):
        return "strategy definition must be an object"
    bad = []
    for c in strategy.get("conditions", []) or []:
        if isinstance(c, dict) and c.get("field") in _PIT_FORBIDDEN_FIELDS:
            bad.append(c.get("field"))
    for field in strategy.get("score_weights", {}) or {}:
        if field in _PIT_FORBIDDEN_FIELDS:
            bad.append(field)
    if bad:
        names = ", ".join(sorted(set(bad)))
        return (
            "historical sandbox rejected current-data field(s): "
            + names
            + "; point-in-time fundamentals/sector_rs are not available"
        )
    return None


def _validate_parameters(years, step, universe_limit, stop_pct, target_r, hold_bars):
    checks = (
        ("years", years, (int, float), 0, 30),
        ("step", step, (int,), 1, 252),
        ("universe_limit", universe_limit, (int,), 1, 5000),
        ("stop_pct", stop_pct, (int, float), 0, 0.99),
        ("target_r", target_r, (int, float), 0, 100),
        ("hold_bars", hold_bars, (int,), 1, 2520),
    )
    for name, value, types, low, high in checks:
        if isinstance(value, bool) or not isinstance(value, types):
            return f"invalid {name}: expected a bounded numeric value"
        if not low < value <= high:
            return f"invalid {name}: must be > {low} and <= {high}"
    return None


def _data_fingerprint(conn):
    """Cheap deterministic version of the price data used by the cache."""
    try:
        row = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date), "
            "ROUND(COALESCE(SUM(close),0),6), "
            "ROUND(COALESCE(SUM(volume),0),2) FROM prices_daily"
        ).fetchone()
        return hashlib.sha256(json.dumps(list(row), default=str).encode()).hexdigest()[:24]
    except Exception:
        return "unavailable"


# ============================================================
# Backtest driver
# ============================================================
def backtest_strategy(
    name,
    years=2,
    step=5,
    universe_limit=150,
    stop_pct=0.05,
    target_r=3.0,
    hold_bars=30,
    use_cache=True,
):
    strategies = RE.load_strategies()
    s = strategies.get(name)
    if not s:
        return {"error": f"strategy '{name}' not found"}
    err = _validate_strategy_sandbox(s)
    if err:
        return {"error": err, "sandbox_rejected": True}
    err = _validate_parameters(years, step, universe_limit, stop_pct, target_r, hold_bars)
    if err:
        return {"error": err}

    conn = db.get_conn()
    syms = RE._universe_symbols(conn, s.get("universe", "active"))
    syms = syms[:universe_limit]
    data_fingerprint = _data_fingerprint(conn)
    # The definition and data fingerprint are part of the key.  This lookup
    # intentionally happens only after validation and fingerprinting.
    if use_cache:
        cached = _get_cached(
            name, years, step, universe_limit, stop_pct, target_r, hold_bars, s, data_fingerprint
        )
        if cached is not None:
            return cached
    funds = RE._load_fundamentals(conn)
    sectors = RE._load_sectors(conn)
    srs = RE._load_sector_rs(conn)

    # Load all history for the selected symbols
    data = {}
    for sym in syms:
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily "
            "WHERE symbol=? ORDER BY date",
            (sym,),
        ).fetchall()
        if len(rows) < 280:
            continue
        df = pd.DataFrame(
            list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"]
        ).set_index("date")
        df.index = pd.to_datetime(df.index)
        data[sym] = df
    conn.close()

    # Date range
    end_dt = dt.date.today()
    start_dt = end_dt - dt.timedelta(days=365 * years)
    start_ts = pd.Timestamp(start_dt)
    end_ts = pd.Timestamp(end_dt)

    signals = []
    n_evaluated = 0
    n_checked_symbols = len(data)

    for sym, df in data.items():
        # Walk history every `step` bars, starting from bar 280
        for i in range(280, len(df) - 1, step):
            dt_i = df.index[i]
            if dt_i < start_ts or dt_i > end_ts:
                continue
            n_evaluated += 1
            slice_df = df.iloc[: i + 1]
            feats = RE._compute_features(
                sym, slice_df, funds.get(sym), sectors.get(sym), srs.get(sym)
            )
            if not feats:
                continue
            r = RE.evaluate(s, feats)
            if not r["passed"]:
                continue
            # Entry at next bar's OPEN
            entry_price = float(df["Open"].iloc[i + 1])
            if entry_price <= 0:
                continue
            stop = entry_price * (1 - stop_pct)
            target = entry_price + target_r * (entry_price - stop)
            outcome, exit_price, exit_i, bars = _simulate(
                df, i + 1, entry_price, stop, target, hold_bars
            )
            ret_pct = (exit_price - entry_price) / entry_price
            signals.append(
                {
                    "symbol": sym,
                    "signal_date": str(dt_i.date()),
                    "entry_date": str(df.index[i + 1].date()),
                    "entry_price": round(entry_price, 2),
                    "stop": round(stop, 2),
                    "target": round(target, 2),
                    "exit_price": round(exit_price, 2),
                    "exit_date": str(df.index[exit_i].date()),
                    "outcome": outcome,
                    "bars_held": int(bars),
                    "return_pct": round(ret_pct * 100, 3),
                }
            )

    # Sort chronologically
    signals.sort(key=lambda x: x["signal_date"])

    # Aggregate
    wins = [x for x in signals if x["outcome"] == "WIN"]
    losses = [x for x in signals if x["outcome"] == "LOSS"]
    timeouts = [x for x in signals if x["outcome"] == "TIMEOUT"]
    opens = [x for x in signals if x["outcome"] == "OPEN"]
    closed = [x for x in signals if x["outcome"] != "OPEN"]

    n = len(signals)
    graded = len(wins) + len(losses)
    win_rate = (len(wins) / graded) if graded else None
    avg_ret = (sum(x["return_pct"] for x in closed) / len(closed)) if closed else 0.0

    # Equity curve
    eq = 1.0
    curve = []
    for x in closed:
        eq *= 1 + x["return_pct"] / 100.0
        curve.append({"date": x["exit_date"], "equity": round(eq, 4)})
    final_equity = round(eq, 4)
    total_return_pct = round((eq - 1) * 100, 2)

    # Max drawdown on curve
    peak = 1.0
    max_dd = 0.0
    for pt in curve:
        e = pt["equity"]
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    result = {
        "strategy": name,
        "years": years,
        "step": step,
        "universe_limit": universe_limit,
        "stop_pct": stop_pct,
        "target_r": target_r,
        "hold_bars": hold_bars,
        "run_at": dt.datetime.now().isoformat(timespec="seconds"),
        "n_symbols": n_checked_symbols,
        "n_evaluated": n_evaluated,
        "n_signals": n,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "n_timeouts": len(timeouts),
        "n_open": len(opens),
        "n_closed": len(closed),
        "win_rate": round(win_rate, 3) if win_rate is not None else None,
        "avg_return_pct": round(avg_ret, 3),
        "total_return_pct": total_return_pct,
        "final_equity": final_equity,
        "max_drawdown_pct": round(max_dd * 100, 2),
        "metric_scope": "research-only synthetic closed-trade sequence; not a portfolio",
        "limitations": [
            "signals may overlap and are not compounded as an executable portfolio",
            "current fundamentals and sector_rs are rejected until PIT data exists",
            "OPEN outcomes are right-censored and excluded from closed-trade sequence metrics",
        ],
        "data_fingerprint": data_fingerprint,
        "equity_curve": curve[-500:],  # cap for size
        "recent_signals": signals[-30:],
    }

    if use_cache:
        try:
            _put_cached(
                name,
                years,
                step,
                universe_limit,
                stop_pct,
                target_r,
                hold_bars,
                result,
                s,
                data_fingerprint,
            )
        except Exception as e:
            log.warning(f"cache write failed: {e}")

    return result


if __name__ == "__main__":
    import sys

    argv = sys.argv[1:]
    if "--clear-cache" in argv:
        clear_cache()
        print("backtest cache cleared")
        sys.exit(0)

    name = None
    for a in argv:
        if not a.startswith("--"):
            name = a
            break
    if not name:
        print("usage: strategy_backtest.py STRATEGY_NAME [years] [step]")
        sys.exit(1)

    years = int(argv[1]) if len(argv) > 1 else 2
    step = int(argv[2]) if len(argv) > 2 else 5

    out = backtest_strategy(name, years=years, step=step)
    if "error" in out:
        print(f"ERROR: {out['error']}")
        sys.exit(1)
    print(f"[{out['strategy']}] years={out['years']} step={out['step']}")
    print(f"  symbols: {out['n_symbols']}  evaluated: {out['n_evaluated']}")
    print(
        f"  signals: {out['n_signals']}  "
        f"(W {out['n_wins']} / L {out['n_losses']} / "
        f"T {out['n_timeouts']} / O {out.get('n_open', 0)})"
    )
    print(f"  win rate: {out['win_rate']}")
    print(f"  avg return / trade: {out['avg_return_pct']}%")
    print(f"  synthetic sequence return (not portfolio): {out['total_return_pct']}%")
    print(f"  synthetic sequence max drawdown: {out['max_drawdown_pct']}%")
    print()
    print("  recent signals:")
    for s in out["recent_signals"][-10:]:
        print(
            f"    {s['signal_date']}  {s['symbol']:<12}  {s['outcome']:<8}  {s['return_pct']:+.2f}%"
        )
