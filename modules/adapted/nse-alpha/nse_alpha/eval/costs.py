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


"""Transaction cost model and strategy capacity estimation.

Cost decomposition (round-trip, in basis points)
------------------------------------------------
Each component is a separate named constant so that assumptions are visible
and can be adjusted individually:

    BROKERAGE_BPS   ~2 bps  Brokerage + exchange transaction charges
    STT_SELL_BPS    ~10 bps Securities Transaction Tax on sell-side only
    IMPACT_BPS      ~3 bps  Market impact for large-cap stocks

    DEFAULT_ROUND_TRIP_BPS = 15 bps  (sum of above)

The cost is expressed as a round-trip cost and applied proportionally to
turnover.  This is a linear cost model — it does not capture nonlinear
impact for large orders.

Sensitivity runs: 5 bps (low cost), 15 bps (baseline), 30 bps (high cost).
All three are included in the output table.
"""


import pandas as pd

# ---------------------------------------------------------------------------
# Cost model constants (round-trip, in basis points)
# ---------------------------------------------------------------------------
BROKERAGE_BPS: float = 2.0  # Brokerage + NSE/BSE transaction charges
STT_SELL_BPS: float = 10.0  # STT (Securities Transaction Tax) on sell leg only
IMPACT_BPS: float = 3.0  # Estimated market impact for large-cap names

DEFAULT_ROUND_TRIP_BPS: float = BROKERAGE_BPS + STT_SELL_BPS + IMPACT_BPS  # = 15.0

SENSITIVITY_COST_BPS: list[float] = [5.0, 15.0, 30.0]

# Participation cap: max fraction of a stock's ADV we trade in one day
ADV_PARTICIPATION_CAP: float = 0.05  # 5% of ADV per name per day

# ---------------------------------------------------------------------------
# Cost application
# ---------------------------------------------------------------------------


def compute_net_returns(
    gross_returns: pd.Series,
    turnover: float,
    cost_bps: float = DEFAULT_ROUND_TRIP_BPS,
) -> pd.Series:
    """Apply transaction costs to gross returns.

    Net return per period = gross return - turnover * cost_bps / 10_000

    Parameters
    ----------
    gross_returns:
        Daily gross L/S spread returns.
    turnover:
        Average one-way turnover per period (from ``compute_turnover``).
    cost_bps:
        Round-trip transaction cost in basis points.

    Returns
    -------
    pd.Series
        Net returns after cost.

    Notes
    -----
    This is a linear cost model.  It assumes cost scales linearly with
    turnover and does not model nonlinear market impact or borrow costs
    for the short leg.  See README Limitations for details.
    """
    cost_per_period = turnover * cost_bps / 10_000.0
    return (gross_returns - cost_per_period).rename("net_return")


def compute_capacity(
    panel: pd.DataFrame,
    weights: pd.DataFrame,
    participation_cap: float = ADV_PARTICIPATION_CAP,
) -> float:
    """Estimate strategy capacity in Rs crore.

    The capacity is the AUM at which the required daily trading in any
    constituent exceeds ``participation_cap`` × 20-day ADV of that stock.

    Methodology:
        1. For each date, compute the per-stock 20-day median ``turnover_value``
           (20d ADV in Rs).
        2. The maximum tradeable daily AUM per stock = ADV * participation_cap.
        3. For the long-short portfolio at unit AUM, the required trade in stock i
           is ``|Δw_i| * AUM``.
        4. Capacity = min over stocks of (max_tradeable_Rs / |Δw_i|) when |Δw_i| > 0.
        5. Report in Rs crore.

    Parameters
    ----------
    panel:
        Full tidy panel with ``turnover_value``.
    weights:
        Per-date per-symbol weights from ``compute_weights_from_deciles``.
    participation_cap:
        Fraction of ADV the strategy can trade per stock per day.

    Returns
    -------
    float
        Estimated capacity in Rs crore.
    """
    import numpy as np

    rs_per_crore: float = 1e7

    # 20-day median turnover_value per symbol per date
    tv = panel["turnover_value"].unstack("symbol")  # date × symbol
    adv20 = tv.rolling(20, min_periods=5).median()

    w = weights["weight"].unstack("symbol").fillna(0.0)
    dw = w.diff().abs()  # |Δw_i| on each date

    capacities: list[float] = []
    for date in dw.index:
        dw_row = dw.loc[date]
        adv_row = adv20.loc[date] if date in adv20.index else None
        if adv_row is None:
            continue
        active = dw_row[dw_row > 1e-8]
        if active.empty:
            continue
        max_trade_rs = adv_row[active.index] * participation_cap
        cap_per_stock = max_trade_rs / active
        cap_rs = float(cap_per_stock.min())
        if not np.isnan(cap_rs) and cap_rs > 0:
            capacities.append(cap_rs)

    if not capacities:
        return float("nan")

    # Use median capacity across dates (more robust than minimum)
    median_cap_rs = float(np.median(capacities))
    return median_cap_rs / rs_per_crore
