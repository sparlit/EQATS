from __future__ import annotations

import numpy as np
import pandas as pd


def _empty_metrics() -> dict[str, float]:
    return {
        "total_trades":  0,
        "wins":          0,
        "losses":        0,
        "win_rate":      0.0,
        "avg_rr":        0.0,
        "avg_win":       0.0,
        "avg_loss":      0.0,
        "expectancy":    0.0,    # R per trade
        "total_pnl":     0.0,
        "total_return_pct": 0.0,
        "max_drawdown":  0.0,    # % of peak equity
        "profit_factor": 0.0,
        "sharpe":        0.0,
        "avg_bars_held": 0.0,
    }


def equity_curve(trades: pd.DataFrame, starting_capital: float) -> pd.Series:
    """Build a cumulative equity series indexed by exit_date from closed trades."""
    if trades.empty or "pnl" not in trades.columns:
        return pd.Series([starting_capital])
    ordered = trades.sort_values("exit_date") if "exit_date" in trades.columns else trades
    equity = starting_capital + ordered["pnl"].cumsum()
    if "exit_date" in ordered.columns:
        equity.index = pd.to_datetime(ordered["exit_date"])
    return pd.concat([pd.Series([starting_capital]), equity])


def max_drawdown_pct(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown of an equity curve, as a positive %."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    return float(abs(drawdown.min()) * 100)


def calculate_metrics(trades: pd.DataFrame, starting_capital: float = 1_000_000.0) -> dict[str, float]:
    """
    Compute summary performance metrics from a closed-trade DataFrame.

    Expected columns: pnl, r_multiple, return_pct, bars_held, exit_date.

    Returns a dict of metrics: win_rate, expectancy (R), profit factor, sharpe,
    max drawdown %, avg R:R, etc.
    """
    if trades is None or trades.empty:
        return _empty_metrics()

    pnl = trades["pnl"].astype(float)
    wins_mask = pnl > 0
    losses_mask = pnl < 0
    n = len(trades)
    n_wins = int(wins_mask.sum())
    n_losses = int(losses_mask.sum())

    gross_profit = float(pnl[wins_mask].sum())
    gross_loss = float(abs(pnl[losses_mask].sum()))

    r = trades["r_multiple"].astype(float) if "r_multiple" in trades.columns else pd.Series(dtype=float)

    win_rate = (n_wins / n * 100) if n else 0.0
    avg_win = float(pnl[wins_mask].mean()) if n_wins else 0.0
    avg_loss = float(pnl[losses_mask].mean()) if n_losses else 0.0
    expectancy = float(r.mean()) if not r.empty else 0.0
    avg_rr = float(r[r > 0].mean()) if not r.empty and (r > 0).any() else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Sharpe from per-trade returns (annualized by trade count proxy)
    if "return_pct" in trades.columns:
        rets = trades["return_pct"].astype(float) / 100.0
        sharpe = float(rets.mean() / rets.std() * np.sqrt(len(rets))) if rets.std() > 0 else 0.0
    else:
        sharpe = 0.0

    eq = equity_curve(trades, starting_capital)
    mdd = max_drawdown_pct(eq)
    total_pnl = float(pnl.sum())

    return {
        "total_trades":  n,
        "wins":          n_wins,
        "losses":        n_losses,
        "win_rate":      round(win_rate, 2),
        "avg_rr":        round(avg_rr, 2),
        "avg_win":       round(avg_win, 2),
        "avg_loss":      round(avg_loss, 2),
        "expectancy":    round(expectancy, 3),
        "total_pnl":     round(total_pnl, 2),
        "total_return_pct": round(total_pnl / starting_capital * 100, 2),
        "max_drawdown":  round(mdd, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "sharpe":        round(sharpe, 2),
        "avg_bars_held": round(float(trades["bars_held"].mean()), 1) if "bars_held" in trades.columns else 0.0,
    }
