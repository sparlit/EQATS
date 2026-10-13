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


"""Recorded Hull diagnostics without changing its historical accounting."""

from collections import Counter

import pandas as pd

from .replay import metrics


def audit_hull(state: dict, prices: dict[str, pd.DataFrame]) -> dict:
    closed, open_rows, problems = [], [], []
    for original in state.get("positions", []):
        p = dict(original)
        if p.get("state") != "CLOSED":
            open_rows.append(p)
            continue
        risk = (p["entry"] - p["initial_stop"]) * p["quantity"]
        p["net_r"] = p["realised_pnl"] / risk if risk > 0 else None
        p["holding_calendar_days"] = (
            pd.Timestamp(p["exit_date"]) - pd.Timestamp(p["entry_date"])
        ).days
        data = prices.get(p["symbol"])
        if data is not None:
            dates = data.trade_date
            observed = data.loc[dates.gt(p["entry_date"]) & dates.lt(p["exit_date"])]
            # Legacy positions were filled at the signal close. Exclude that
            # candle, and exit-day extrema whose ordering cannot be recovered.
            if not observed.empty and risk > 0:
                unit_risk = risk / p["quantity"]
                p["mfe_r"] = max(0, (observed.high.max() - p["entry"]) / unit_risk)
                p["mae_r"] = min(0, (observed.low.min() - p["entry"]) / unit_risk)
                p["giveback_r"] = max(0, p["mfe_r"] - p["net_r"])
            p["holding_sessions"] = int(
                (dates.gt(p["entry_date"]) & dates.le(p["exit_date"])).sum()
            )
            if not dates.eq(p["entry_date"]).any() or not dates.eq(p["exit_date"]).any():
                p["holding_sessions"] = None
                problems.append(f"{p['trade_id']}: incomplete price coverage")
            entry_row = data.loc[dates.eq(p["entry_date"])]
            if not entry_row.empty:
                p["same_close_entry"] = abs(entry_row.iloc[0].close - p["entry"]) < 0.011
            exit_row = data.loc[dates.eq(p["exit_date"])]
            if (
                not exit_row.empty
                and not exit_row.iloc[0].low <= p["exit_price"] <= exit_row.iloc[0].high
            ):
                problems.append(f"{p['trade_id']}: recorded exit outside daily range")
        closed.append(p)
    capital = state["capital_base"]
    # Recorded end-of-day NAV only if every concurrent holding has a daily mark.
    nav, peak, max_dd, incomplete_days = [], capital, 0.0, []
    first = min((p["entry_date"] for p in state.get("positions", [])), default=None)
    calendar = sorted(
        {
            str(day)
            for d in prices.values()
            for day in d.trade_date
            if first and first <= str(day) <= state["last_run"]
        }
    )
    lookups = {s: dict(zip(d.trade_date, d.close, strict=False)) for s, d in prices.items()}
    for day in calendar:
        equity, complete = capital, True
        for p in state.get("positions", []):
            if (
                p.get("state") not in {"OPEN", "TRAILING", "CLOSED", "CORPORATE_ACTION_REVIEW"}
                or p["entry_date"] > day
            ):
                continue
            if p.get("exit_date") and p["exit_date"] <= day:
                equity += p["realised_pnl"]
            else:
                mark = lookups.get(p["symbol"], {}).get(day)
                if mark is None:
                    complete = False
                    break
                equity += (mark - p["entry"]) * p["quantity"]
        if complete:
            peak = max(peak, equity)
            max_dd = max(max_dd, (peak - equity) / peak * 100)
            nav.append({"date": day, "equity": equity})
        else:
            incomplete_days.append(day)
    rupees = metrics(closed, "realised_pnl")
    rupees["portfolio_max_drawdown"] = max_dd if nav and not incomplete_days else None
    rupees["portfolio_drawdown_status"] = (
        "RECORDED DAILY MARKS, GROSS" if nav and not incomplete_days else "INCOMPLETE MARK COVERAGE"
    )
    return {
        "as_of": state["last_run"],
        "basis": "RECORDED LEGACY FILLS; NOT REPRICED; FEES NOT RECORDED",
        "rupee_metrics": rupees,
        "r_metrics": metrics(closed),
        "closed_trades": closed,
        "open_positions": open_rows,
        "equity_curve": nav,
        "incomplete_mark_dates": incomplete_days,
        "data_issues": problems,
        "same_close_entries": sum(p.get("same_close_entry", False) for p in closed),
        "by_exit": dict(Counter(p.get("exit_reason", "UNKNOWN") for p in closed)),
        "setup_and_regime_at_entry": "NOT RECORDED; DO NOT INVENT LEGACY CLASSIFICATIONS",
        "excursion_note": "Partial daily-bar estimates exclude entry and exit days; not exact intraday MFE/MAE.",
    }
