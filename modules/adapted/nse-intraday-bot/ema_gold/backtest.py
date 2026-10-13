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
EMA trend-following backtest engine — Gold H1.

Usage (from repo root):
    python ema_gold/backtest.py                # uses ema_gold/config.json
    python ema_gold/backtest.py --years 6
    python ema_gold/backtest.py --exit-mode trailing

Outputs (in ema_gold/):
    backtest_trades.csv   full trade log (entry/exit, reason, P/L)
    backtest_summary.json metrics
    equity_curve.png      equity chart (if matplotlib available)
"""
import argparse
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ema_gold.strategy import (
    add_indicators,
    blocked_by_time,
    entry_signal,
    initial_stops,
    load_config,
    position_size,
)

_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Data loading ────────────────────────────────────────────────────


def load_data(cfg: dict) -> pd.DataFrame:
    src = cfg.get("data_source", "mt5")
    bars_per_year = {"M30": 12400, "H1": 6200, "H4": 1560, "D1": 310}.get(
        cfg.get("timeframe", "H1"), 6200
    )
    n_bars = int(cfg.get("backtest_years", 4) * bars_per_year) + cfg["ema_trend"]

    if src == "csv" and cfg.get("csv_path"):
        df = pd.read_csv(cfg["csv_path"])
        df.columns = [c.lower() for c in df.columns]
        tcol = "time" if "time" in df.columns else "date"
        df[tcol] = pd.to_datetime(df[tcol])
        df = df.set_index(tcol)
        return df[["open", "high", "low", "close"]].dropna()

    if src == "mt5":
        import MetaTrader5 as mt5

        root_cfg = {}
        try:
            with open(os.path.join(_DIR, "..", "mt5_config.json"), encoding="utf-8") as f:
                root_cfg = json.load(f)
        except Exception:
            pass
        mt5.initialize(path=root_cfg.get("path") or None)
        tf = getattr(mt5, f"TIMEFRAME_{cfg.get('timeframe', 'H1')}")
        rates = mt5.copy_rates_from_pos(cfg["symbol"], tf, 0, n_bars)
        mt5.shutdown()
        if rates is None or len(rates) < 500:
            raise RuntimeError("MT5 returned insufficient data — is the terminal open?")
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df = df.set_index("time")
        return df[["open", "high", "low", "close"]].astype(float)

    # yfinance fallback (max ~730 days of 1h)
    import yfinance as yf

    df = yf.download("GC=F", period="730d", interval="1h", auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [c.lower() for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df[["open", "high", "low", "close"]].dropna()


# ── Engine ──────────────────────────────────────────────────────────


def run_backtest(cfg: dict, df: pd.DataFrame) -> dict:
    df = add_indicators(df, cfg)
    warmup = cfg["ema_trend"] + 10
    half_spread = cfg["spread_usd"] / 2.0
    slip = cfg["slippage_usd"]

    equity = float(cfg["start_equity"])
    peak = equity
    halted = False
    day_pnl = {}  # date -> realized P/L
    pos = None  # open position dict
    trades = []
    eq_points = []  # (timestamp, equity)

    def day_blocked(ts):
        d = ts.date()
        limit = -cfg["daily_loss_limit_pct"] / 100.0 * equity
        return day_pnl.get(d, 0.0) <= limit

    def close_pos(ts, price, reason):
        nonlocal equity, peak, pos
        # exit costs: half-spread + slippage against us
        px = price - (half_spread + slip) if pos["dir"] == "LONG" else price + (half_spread + slip)
        pnl = (
            (px - pos["entry"]) * pos["units"]
            if pos["dir"] == "LONG"
            else (pos["entry"] - px) * pos["units"]
        )
        equity += pnl
        peak = max(peak, equity)
        day_pnl[ts.date()] = day_pnl.get(ts.date(), 0.0) + pnl
        trades.append(
            {
                "entry_time": pos["time"],
                "exit_time": ts,
                "direction": pos["dir"],
                "entry": round(pos["entry"], 2),
                "exit": round(px, 2),
                "sl": round(pos["sl"], 2),
                "tp": round(pos["tp"], 2),
                "units": round(pos["units"], 4),
                "pnl": round(pnl, 2),
                "r_multiple": round(pnl / pos["risk_amt"], 2),
                "entry_reason": pos["reason"],
                "exit_reason": reason,
                "equity_after": round(equity, 2),
            }
        )
        pos = None

    idx = df.index
    for i in range(warmup, len(df) - 1):
        row = df.iloc[i]
        nxt = df.iloc[i + 1]
        ts, nts = idx[i], idx[i + 1]

        # ── manage open position on the NEXT bar (intrabar, SL first) ──
        if pos is not None:
            hi, lo = float(nxt["high"]), float(nxt["low"])
            # trailing mode: once in profit by trail_trigger_atr, trail at EMA50
            if cfg["exit_mode"] == "trailing":
                trigger = pos["atr"] * cfg["trail_trigger_atr"]
                in_profit = (
                    (float(nxt["close"]) - pos["entry"] >= trigger)
                    if pos["dir"] == "LONG"
                    else (pos["entry"] - float(nxt["close"]) >= trigger)
                )
                if in_profit:
                    e50 = float(nxt["ema_slow"])
                    pos["sl"] = max(pos["sl"], e50) if pos["dir"] == "LONG" else min(pos["sl"], e50)
            if pos["dir"] == "LONG":
                if lo <= pos["sl"]:
                    close_pos(nts, pos["sl"], "stop-loss")
                elif cfg["exit_mode"] == "fixed" and hi >= pos["tp"]:
                    close_pos(nts, pos["tp"], "take-profit")
            else:
                if hi >= pos["sl"]:
                    close_pos(nts, pos["sl"], "stop-loss")
                elif cfg["exit_mode"] == "fixed" and lo <= pos["tp"]:
                    close_pos(nts, pos["tp"], "take-profit")
            # EMA cross-back exit at next bar close
            if pos is not None and cfg.get("exit_on_cross_back", True):
                if (pos["dir"] == "LONG" and nxt["cross_dn"]) or (
                    pos["dir"] == "SHORT" and nxt["cross_up"]
                ):
                    close_pos(nts, float(nxt["close"]), "ema-cross-back")

        eq_points.append((ts, equity))

        # ── circuit breaker ──
        if not halted and equity <= peak * (1 - cfg["max_drawdown_halt_pct"] / 100.0):
            halted = True
            print(
                f"[HALT] max drawdown {cfg['max_drawdown_halt_pct']}% breached "
                f"at {ts}  equity={equity:.2f} peak={peak:.2f}"
            )
        if halted or pos is not None:
            continue

        # ── new entry evaluated on CLOSED bar i, filled at bar i+1 open ──
        if day_blocked(ts):
            continue
        why = blocked_by_time(ts, cfg)
        if why:
            continue
        sig = entry_signal(row, cfg)
        if sig is None:
            continue
        atr_val = float(row["atr"])
        if atr_val <= 0 or np.isnan(atr_val):
            continue
        raw_open = float(nxt["open"])
        entry = (
            raw_open + (half_spread + slip) if sig == "LONG" else raw_open - (half_spread + slip)
        )
        sl_price, tp_price = initial_stops(sig, entry, atr_val, cfg)
        sl_dist = abs(entry - sl_price)
        units = position_size(equity, cfg["risk_pct"], sl_dist)
        if units <= 0:
            continue
        pos = {
            "dir": sig,
            "entry": entry,
            "sl": sl_price,
            "tp": tp_price,
            "units": units,
            "atr": atr_val,
            "time": nts,
            "risk_amt": equity * cfg["risk_pct"] / 100.0,
            "reason": f"EMA{cfg['ema_fast']}x{cfg['ema_slow']} cross "
            f"{'up' if sig == 'LONG' else 'down'}, "
            f"ADX {row['adx']:.0f} > {cfg['adx_min']}, "
            f"price {'>' if sig == 'LONG' else '<'} EMA{cfg['ema_trend']}",
        }

    if pos is not None:
        close_pos(idx[-1], float(df["close"].iloc[-1]), "end-of-data")

    return _report(cfg, trades, eq_points, halted)


# ── Metrics & outputs ───────────────────────────────────────────────


def _report(cfg, trades, eq_points, halted) -> dict:
    tdf = pd.DataFrame(trades)
    eq = pd.Series(dict(eq_points)).sort_index()

    if tdf.empty:
        print("No trades generated.")
        return {}

    wins = tdf[tdf["pnl"] > 0]
    losses = tdf[tdf["pnl"] <= 0]
    gross_w = wins["pnl"].sum()
    gross_l = abs(losses["pnl"].sum())
    dd = eq / eq.cummax() - 1.0
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if daily.std() > 0 else 0.0

    summary = {
        "period": f"{eq.index[0]} -> {eq.index[-1]}",
        "bars": len(eq),
        "total_trades": len(tdf),
        "win_rate_pct": round(len(wins) / len(tdf) * 100, 1),
        "avg_win_usd": round(wins["pnl"].mean(), 2) if len(wins) else 0,
        "avg_loss_usd": round(losses["pnl"].mean(), 2) if len(losses) else 0,
        "avg_realized_RR": round(abs(wins["pnl"].mean() / losses["pnl"].mean()), 2)
        if len(wins) and len(losses)
        else None,
        "avg_r_multiple": round(tdf["r_multiple"].mean(), 3),
        "profit_factor": round(gross_w / gross_l, 2) if gross_l > 0 else None,
        "net_profit_usd": round(tdf["pnl"].sum(), 2),
        "final_equity": round(eq.iloc[-1], 2),
        "return_pct": round((eq.iloc[-1] / cfg["start_equity"] - 1) * 100, 1),
        "max_drawdown_pct": round(dd.min() * 100, 1),
        "sharpe_daily_ann": round(sharpe, 2),
        "halted_by_circuit_breaker": halted,
        "exit_mode": cfg["exit_mode"],
        "exit_reasons": tdf["exit_reason"].value_counts().to_dict(),
    }

    tdf.to_csv(os.path.join(_DIR, "backtest_trades.csv"), index=False)
    with open(os.path.join(_DIR, "backtest_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(11, 5))
        eq.plot(ax=ax, color="tab:blue", lw=1)
        ax.set_title(
            f"EMA trend strategy on {cfg['symbol']} {cfg['timeframe']} — equity curve "
            f"({cfg['exit_mode']} exits)"
        )
        ax.set_ylabel("Equity (USD)")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(_DIR, "equity_curve.png"), dpi=110)
        summary["equity_curve"] = "ema_gold/equity_curve.png"
    except Exception as e:
        print(f"(chart skipped: {e})")
        eq.to_csv(os.path.join(_DIR, "equity_curve.csv"))

    print("\n===== EMA GOLD BACKTEST =====")
    print(json.dumps(summary, indent=2, default=str))
    print(f"\nTrade log: ema_gold/backtest_trades.csv ({len(tdf)} trades)")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=float, default=None)
    ap.add_argument("--exit-mode", choices=["fixed", "trailing"], default=None)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.years:
        cfg["backtest_years"] = args.years
    if args.exit_mode:
        cfg["exit_mode"] = args.exit_mode

    print(
        f"Loading {cfg['backtest_years']}y of {cfg['symbol']} {cfg['timeframe']} "
        f"from {cfg['data_source']}..."
    )
    data = load_data(cfg)
    print(f"{len(data)} bars: {data.index[0]} -> {data.index[-1]}")
    run_backtest(cfg, data)
