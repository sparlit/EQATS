from __future__ import annotations

import pandas as pd


def generate_weekly_review(trades: pd.DataFrame) -> dict[str, float]:
    """Generate a weekly review summary from trade history."""
    if trades.empty:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "avg_pnl": 0.0,
            "wins": 0,
            "losses": 0,
            "average_holding_period": 0.0,
        }

    trades = trades.copy()
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
    trades["holding_period"] = pd.to_numeric(trades.get("holding_period", pd.Series(dtype="float64")), errors="coerce")
    total_trades = len(trades)
    wins = int((trades["pnl"] > 0).sum())
    losses = int((trades["pnl"] <= 0).sum())
    win_rate = float(wins / total_trades * 100) if total_trades else 0.0
    total_pnl = float(trades["pnl"].sum())
    avg_pnl = float(trades["pnl"].mean()) if total_trades else 0.0
    avg_holding = float(trades["holding_period"].dropna().mean()) if "holding_period" in trades.columns else 0.0

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(avg_pnl, 2),
        "wins": wins,
        "losses": losses,
        "average_holding_period": round(avg_holding, 2),
    }
