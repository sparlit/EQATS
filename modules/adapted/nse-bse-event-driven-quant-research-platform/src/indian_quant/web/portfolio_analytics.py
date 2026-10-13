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


"""Portfolio analytics — closed trade analysis for improvement insights."""


import json

import numpy as np
import pandas as pd
import sqlalchemy as sa


def _pg_engine():
    from indian_quant.config.connections import get_engine

    return get_engine()


def _sanitize(obj):
    return json.loads(json.dumps(obj, default=str))


def get_closed_trades(table: str = "paper_signals") -> pd.DataFrame:
    """Fetch all settled trades from PostgreSQL."""
    engine = _pg_engine()
    col_map = {
        "paper_signals": {
            "exit_date": "exit_date",
            "exit_close": "exit_close",
            "realized_net_bps": "realized_net_bps",
            "symbol": "symbol",
            "close_at_signal": "close_at_signal",
            "horizon_label": "horizon_label",
            "horizon_days": "horizon_days",
            "exit_reason": "exit_reason",
            "days_held": "days_held",
            "return_pct": "return_pct",
            "created_at": "created_at",
            "side": "side",
            "position_value": "position_value",
            "risk_amount": "risk_amount",
            "conviction_score": "conviction_score",
            "kelly_fraction": "kelly_fraction",
        },
        "daily_suggestions": {
            "actual_exit_date": "exit_date",
            "actual_exit_close": "exit_close",
            "actual_return_bps": "realized_net_bps",
            "symbol": "symbol",
            "close_at_signal": "close_at_signal",
            "horizon_days": "horizon_days",
            "signal_type": "signal_type",
            "direction": "direction",
            "deliv_z": "deliv_z",
            "suggestion_date": "created_at",
        },
    }
    cols = col_map.get(table, col_map["paper_signals"])
    select_parts = [f"{k} AS {v}" for k, v in cols.items()]
    status_col = "SETTLED" if table == "paper_signals" else "REALIZED"
    date_filter = "exit_date" if table == "paper_signals" else "actual_exit_date"

    with engine.connect() as conn:
        rows = (
            conn.execute(
                sa.text(
                    f"SELECT {', '.join(select_parts)} FROM {table} "
                    f"WHERE status = '{status_col}' AND {date_filter} IS NOT NULL "
                    f"ORDER BY {date_filter}"
                )
            )
            .mappings()
            .all()
        )

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"])
    return df


def compute_equity_curve(df: pd.DataFrame, initial_capital: float = 1_000_000) -> dict:
    """Compute cumulative equity curve from settled trades."""
    if df.empty:
        return {"dates": [], "equity": [], "drawdown": []}

    df = df.sort_values("exit_date").copy()
    df["pnl_pct"] = df["realized_net_bps"] / 10000.0

    equity = [initial_capital]
    dates = [str(df["exit_date"].iloc[0].date())]
    for _, row in df.iterrows():
        new_eq = equity[-1] * (1 + row["pnl_pct"])
        equity.append(round(new_eq, 2))
        dates.append(str(row["exit_date"].date()))

    # Max drawdown
    eq_arr = np.array(equity)
    peak = np.maximum.accumulate(eq_arr)
    dd = (eq_arr - peak) / peak * 100
    dd_list = [round(float(x), 2) for x in dd]

    return {
        "dates": dates,
        "equity": [round(float(x), 2) for x in equity],
        "drawdown": dd_list,
        "final_equity": round(float(eq_arr[-1]), 2),
        "total_return_pct": round(float((eq_arr[-1] / initial_capital - 1) * 100), 2),
    }


def compute_risk_metrics(df: pd.DataFrame) -> dict:
    """Compute Sharpe, Sortino, max drawdown, profit factor, etc."""
    if df.empty:
        return {}

    returns = df["realized_net_bps"].values / 10000.0
    n = len(returns)
    avg = float(np.mean(returns))
    std = float(np.std(returns, ddof=1)) if n > 1 else 0.0

    # Annualized (assume ~252 trading days, avg hold ~5 days → ~50 trades/year)
    trades_per_year = (
        max(1, 252 / max(1, df["days_held"].mean())) if "days_held" in df.columns else 50
    )
    ann_ret = avg * trades_per_year
    ann_vol = std * np.sqrt(trades_per_year)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

    # Sortino (downside deviation)
    downside = returns[returns < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0.0
    ann_downside = downside_std * np.sqrt(trades_per_year)
    sortino = ann_ret / ann_downside if ann_downside > 0 else 0.0

    # Max drawdown
    eq = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(eq)
    dd = (eq - peak) / peak
    max_dd = float(np.min(dd)) * 100

    # Profit factor
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    gross_profit = float(np.sum(wins)) if len(wins) > 0 else 0.0
    gross_loss = float(np.abs(np.sum(losses))) if len(losses) > 0 else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Win/loss stats
    win_rate = len(wins) / n * 100 if n > 0 else 0
    avg_win = float(np.mean(wins)) * 10000 if len(wins) > 0 else 0
    avg_loss = float(np.mean(losses)) * 10000 if len(losses) > 0 else 0
    expectancy = avg * 10000  # avg bps per trade

    return _sanitize(
        {
            "total_trades": n,
            "win_rate_pct": round(win_rate, 1),
            "avg_win_bps": round(avg_win, 1),
            "avg_loss_bps": round(avg_loss, 1),
            "expectancy_bps": round(expectancy, 1),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": round(sortino, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "avg_days_held": round(float(df["days_held"].mean()), 1)
            if "days_held" in df.columns
            else 0,
            "annual_return_pct": round(ann_ret * 100, 2),
            "annual_volatility_pct": round(ann_vol * 100, 2),
        }
    )


def compute_monthly_performance(df: pd.DataFrame) -> list[dict]:
    """Monthly breakdown of returns."""
    if df.empty:
        return []
    df = df.copy()
    df["month"] = df["exit_date"].dt.to_period("M")
    monthly = []
    for month, grp in df.groupby("month"):
        avg_bps = float(grp["realized_net_bps"].mean())
        win_rate = (grp["realized_net_bps"] > 0).sum() / len(grp) * 100
        monthly.append(
            {
                "month": str(month),
                "trades": len(grp),
                "avg_bps": round(avg_bps, 1),
                "win_rate": round(win_rate, 1),
                "total_bps": round(float(grp["realized_net_bps"].sum()), 1),
            }
        )
    return monthly


def compute_by_horizon(df: pd.DataFrame) -> list[dict]:
    """Performance breakdown by time horizon."""
    if df.empty or "horizon_label" not in df.columns:
        return []
    result = []
    for hz, grp in df.groupby("horizon_label"):
        avg_bps = float(grp["realized_net_bps"].mean())
        win_rate = (grp["realized_net_bps"] > 0).sum() / len(grp) * 100
        result.append(
            {
                "horizon": hz,
                "trades": len(grp),
                "avg_bps": round(avg_bps, 1),
                "win_rate": round(win_rate, 1),
                "avg_days_held": round(float(grp["days_held"].mean()), 1)
                if "days_held" in grp.columns
                else 0,
            }
        )
    return result


def compute_by_exit_reason(df: pd.DataFrame) -> list[dict]:
    """Performance breakdown by exit reason (STOP vs HORIZON)."""
    if df.empty or "exit_reason" not in df.columns:
        return []
    result = []
    for reason, grp in df.groupby("exit_reason"):
        avg_bps = float(grp["realized_net_bps"].mean())
        win_rate = (grp["realized_net_bps"] > 0).sum() / len(grp) * 100
        result.append(
            {
                "reason": reason,
                "trades": len(grp),
                "avg_bps": round(avg_bps, 1),
                "win_rate": round(win_rate, 1),
            }
        )
    return result


def compute_by_signal_type(df: pd.DataFrame) -> list[dict]:
    """Performance breakdown by signal type (suggestions only)."""
    if df.empty or "signal_type" not in df.columns:
        return []
    result = []
    for sig, grp in df.groupby("signal_type"):
        avg_bps = float(grp["realized_net_bps"].mean())
        win_rate = (grp["realized_net_bps"] > 0).sum() / len(grp) * 100
        result.append(
            {
                "signal_type": sig,
                "trades": len(grp),
                "avg_bps": round(avg_bps, 1),
                "win_rate": round(win_rate, 1),
            }
        )
    return result


def compute_streak_analysis(df: pd.DataFrame) -> dict:
    """Win/loss streak analysis."""
    if df.empty:
        return {
            "max_win_streak": 0,
            "max_loss_streak": 0,
            "current_streak": 0,
            "streak_type": "none",
        }

    wins = (df["realized_net_bps"] > 0).astype(int).values
    max_win = max_loss = 0
    "win" if wins[-1] else "loss"
    current_type = "win" if wins[0] else "loss"
    count = 1

    for i in range(1, len(wins)):
        if (wins[i] and current_type == "win") or (not wins[i] and current_type == "loss"):
            count += 1
        else:
            if current_type == "win":
                max_win = max(max_win, count)
            else:
                max_loss = max(max_loss, count)
            current_type = "win" if wins[i] else "loss"
            count = 1

    if current_type == "win":
        max_win = max(max_win, count)
    else:
        max_loss = max(max_loss, count)

    return _sanitize(
        {
            "max_win_streak": max_win,
            "max_loss_streak": max_loss,
            "current_streak": count,
            "streak_type": current_type,
        }
    )


def compute_full_analytics() -> dict:
    """Compute all analytics for the dashboard."""
    paper_df = get_closed_trades("paper_signals")
    sugg_df = get_closed_trades("daily_suggestions")

    # Merge for combined view
    combined = (
        pd.concat([paper_df, sugg_df], ignore_index=True)
        if not paper_df.empty and not sugg_df.empty
        else (paper_df if not paper_df.empty else sugg_df)
    )

    equity = (
        compute_equity_curve(combined)
        if not combined.empty
        else {"dates": [], "equity": [], "drawdown": []}
    )
    risk = compute_risk_metrics(combined) if not combined.empty else {}
    monthly = compute_monthly_performance(combined)
    by_horizon = compute_by_horizon(combined)
    by_reason = compute_exit_reason(combined) if not combined.empty else []
    by_signal = compute_by_signal_type(sugg_df) if not sugg_df.empty else []
    streaks = compute_streak_analysis(combined) if not combined.empty else {}

    # Best/worst trades
    best = {}
    worst = {}
    if not combined.empty:
        best_idx = combined["realized_net_bps"].idxmax()
        worst_idx = combined["realized_net_bps"].idxmin()
        best = {
            "symbol": combined.loc[best_idx, "symbol"],
            "bps": round(float(combined.loc[best_idx, "realized_net_bps"]), 1),
            "exit_date": str(combined.loc[best_idx, "exit_date"].date()),
        }
        worst = {
            "symbol": combined.loc[worst_idx, "symbol"],
            "bps": round(float(combined.loc[worst_idx, "realized_net_bps"]), 1),
            "exit_date": str(combined.loc[worst_idx, "exit_date"].date()),
        }

    # Recent trades (last 20)
    recent = []
    if not combined.empty:
        recent_df = combined.sort_values("exit_date", ascending=False).head(20)
        for _, row in recent_df.iterrows():
            dh = row.get("days_held", 0)
            if pd.isna(dh):
                dh = 0
            recent.append(
                _sanitize(
                    {
                        "symbol": row["symbol"],
                        "exit_date": str(row["exit_date"].date()),
                        "exit_reason": row.get("exit_reason", ""),
                        "days_held": int(dh),
                        "net_bps": round(float(row["realized_net_bps"]), 1),
                        "entry_px": round(float(row["close_at_signal"]), 2),
                        "exit_px": round(float(row.get("exit_close", 0)), 2),
                    }
                )
            )

    return _sanitize(
        {
            "equity": equity,
            "risk": risk,
            "monthly": monthly,
            "by_horizon": by_horizon,
            "by_exit_reason": by_reason,
            "by_signal_type": by_signal,
            "streaks": streaks,
            "best_trade": best,
            "worst_trade": worst,
            "recent_trades": recent,
            "total_paper": len(paper_df),
            "total_suggestions": len(sugg_df),
            "total_combined": len(combined),
        }
    )


def compute_exit_reason(df: pd.DataFrame) -> list[dict]:
    """Alias for compute_by_exit_reason."""
    return compute_by_exit_reason(df)
