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


"""Frictional leakage analytics: how much alpha does trading cost consume?"""


import re

import pandas as pd


def _parse_money(cell: object) -> float:
    """Parse '[13.45 INR]' / '[1.20 INR, 3.40 INR]' / '13.45 INR' cells."""
    total = 0.0
    for match in re.findall(r"-?[\d.]+", str(cell)):
        try:
            total += float(match)
        except ValueError:
            continue
    return total


def compute_friction_metrics(
    fills: pd.DataFrame,
    positions: pd.DataFrame | None = None,
    *,
    starting_balance: float | None = None,
) -> dict[str, float | int | None]:
    """Compute cost-leakage metrics from engine fill/position reports."""
    if fills.empty:
        return {"n_fills": 0, "turnover_notional": 0.0, "total_commissions": 0.0}

    df = fills.copy()
    for col in ("avg_px", "filled_qty"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df["notional"] = df["avg_px"] * df["filled_qty"]
    turnover = float(df["notional"].sum())
    commissions_total = 0.0
    commissions_buy = 0.0
    commissions_sell = 0.0

    if "commissions" in df.columns:
        df["commission_amt"] = df["commissions"].map(_parse_money)
        commissions_total = float(df["commission_amt"].sum())
        side_col = "side" if "side" in df.columns else "order_side"
        if side_col in df.columns:
            sides = df[side_col].astype(str).str.upper()
            commissions_buy = float(df.loc[sides.str.contains("BUY"), "commission_amt"].sum())
            commissions_sell = float(df.loc[sides.str.contains("SELL"), "commission_amt"].sum())

    gross_pnl: float | None = None
    median_holding_days: float | None = None
    if positions is not None and not positions.empty and "realized_pnl" in positions.columns:
        net_realized = float(positions["realized_pnl"].map(_parse_money).dropna().sum())
        # Nautilus realized_pnl is NET of commissions; recover the pre-cost figure.
        gross_pnl = net_realized + commissions_total if commissions_total else net_realized
        if "duration_ns" in positions.columns:
            durations = pd.to_numeric(positions["duration_ns"], errors="coerce").dropna()
            if len(durations):
                median_holding_days = float((durations.median()) / 86_400_000_000_000)

    realized_cost_bps = (commissions_total / turnover * 10_000) if turnover else None

    alpha_leakage_pct: float | None = None
    if gross_pnl is not None and gross_pnl > 0:
        alpha_leakage_pct = commissions_total / gross_pnl * 100
    elif gross_pnl is not None and gross_pnl <= 0:
        alpha_leakage_pct = None

    cost_drag_per_holding_day: float | None = None
    if (
        median_holding_days
        and median_holding_days > 0
        and starting_balance
        and starting_balance > 0
    ):
        n_positions = len(positions) if positions is not None else 0
        if n_positions:
            per_position_cost = commissions_total / n_positions
            cost_drag_per_holding_day = (
                per_position_cost / median_holding_days / starting_balance * 10_000
            )

    return {
        "n_fills": int(len(fills)),
        "turnover_notional": round(turnover, 2),
        "total_commissions": round(commissions_total, 2),
        "commissions_buy": round(commissions_buy, 2),
        "commissions_sell": round(commissions_sell, 2),
        "realized_cost_bps": round(realized_cost_bps, 2) if realized_cost_bps else None,
        "gross_pnl": round(gross_pnl, 2) if gross_pnl is not None else None,
        "alpha_leakage_pct": round(alpha_leakage_pct, 1) if alpha_leakage_pct is not None else None,
        "median_holding_days": round(median_holding_days, 2) if median_holding_days else None,
        "cost_drag_per_holding_day_bps": (
            round(cost_drag_per_holding_day, 3) if cost_drag_per_holding_day else None
        ),
    }
