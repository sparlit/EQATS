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


"""Nifty 200 universe construction with point-in-time liquidity filters.

SURVIVORSHIP BIAS WARNING
-------------------------
The constituent list is sourced from ``data/nifty200_constituents.csv``, which
reflects the **current** (today's) Nifty 200 composition.  Any backtest built
on this universe is **survivorship-biased**: stocks that were delisted, merged,
or dropped from the index are excluded from history.

This means:
    - Performance statistics are likely overstated.
    - The true out-of-sample IC and Sharpe are probably lower.
    - Results should be treated as an upper bound, not a realistic estimate.

See ``universe/point_in_time.py`` for the interface to a future bias-free
implementation.
"""


import logging
import warnings
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Survivorship bias warning
# ---------------------------------------------------------------------------
SURVIVORSHIP_BIAS_WARNING = (
    "\n"
    "+----------------------------------------------------------------------+\n"
    "|  [!] SURVIVORSHIP BIAS WARNING                                       |\n"
    "|  Universe is built from today's Nifty 200 constituent list.          |\n"
    "|  All backtest results are survivorship-biased.                       |\n"
    "|  Performance figures are likely overstated.                          |\n"
    "|  See README Limitations for details.                                 |\n"
    "+----------------------------------------------------------------------+\n"
)

# Emit the warning once when this module is imported
warnings.warn(SURVIVORSHIP_BIAS_WARNING, UserWarning, stacklevel=2)


# ---------------------------------------------------------------------------
# Constants for liquidity filters
# ---------------------------------------------------------------------------
MIN_HISTORY_DAYS: int = 252  # minimum trading days of history required
MIN_ADV_VALUE_RS: float = 5_00_00_000  # Rs 5 crore = 50,000,000
ADV_WINDOW: int = 20  # days for median turnover_value
MAX_MISSING_BARS: int = 10  # max NaN in trailing 60 days
MISSING_BAR_WINDOW: int = 60  # trailing window for missing bar check

_RS_5_CRORE: float = 5_00_00_000  # 50,000,000 = 5 crore


def load_constituents(
    csv_path: Path | None = None,
) -> pd.DataFrame:
    """Load the static Nifty 200 constituent list.

    Returns
    -------
    pd.DataFrame
        Columns: ``symbol``, ``company_name``, ``sector``
    """
    if csv_path is None:
        csv_path = Path(__file__).parent.parent.parent / "data" / "nifty200_constituents.csv"
    df = pd.read_csv(csv_path)
    # Deduplicate (CSV may have duplicate symbols from different index revisions)
    df = df.drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    logger.info("Loaded %d unique Nifty 200 constituents from %s", len(df), csv_path)
    return df


def get_symbols(csv_path: Path | None = None) -> list[str]:
    """Return the list of ticker symbols from the constituent CSV."""
    return load_constituents(csv_path)["symbol"].tolist()


def apply_liquidity_filters(
    panel: pd.DataFrame,
    as_of_date: pd.Timestamp | str,
    *,
    min_history_days: int = MIN_HISTORY_DAYS,
    min_adv_value: float = _RS_5_CRORE,
    max_missing_bars: int = MAX_MISSING_BARS,
) -> list[str]:
    """Apply point-in-time liquidity filters to determine the eligible universe.

    Filters applied (in order):
    1. At least ``min_history_days`` trading days of history prior to *as_of_date*.
    2. 20-day median ``turnover_value`` > ``min_adv_value``.
    3. No more than ``max_missing_bars`` NaN closes in the trailing 60 days.

    Parameters
    ----------
    panel:
        Full tidy panel ``MultiIndex(date, symbol)``.
    as_of_date:
        The date at which to evaluate eligibility (uses data strictly ≤ this date).
    min_history_days:
        Minimum days of history required.
    min_adv_value:
        Minimum median turnover value.
    max_missing_bars:
        Maximum missing close prices allowed in the trailing 60-day window.

    Returns
    -------
    list[str]
        Eligible symbols after applying all filters.
    """
    as_of_date = pd.Timestamp(as_of_date)

    # Slice panel to history up to and including as_of_date
    idx = panel.index.get_level_values("date")
    hist = panel.loc[idx <= as_of_date]

    symbols = hist.index.get_level_values("symbol").unique().tolist()
    eligible: list[str] = []

    for sym in symbols:
        sym_data = hist.xs(sym, level="symbol")

        # Filter 1: history length
        if len(sym_data) < min_history_days:
            logger.debug(
                "%s excluded: only %d days of history (need %d)",
                sym,
                len(sym_data),
                min_history_days,
            )
            continue

        # Filter 2: 20-day median turnover_value
        window_size = min(ADV_WINDOW, len(sym_data))
        recent_tv = sym_data["turnover_value"].iloc[-window_size:]
        if recent_tv.median() < min_adv_value:
            logger.debug(
                "%s excluded: 20d median turnover Rs %.0f < Rs %.0f",
                sym,
                recent_tv.median(),
                min_adv_value,
            )
            continue

        # Filter 3: missing bars in trailing 60 days
        missing_window = min(MISSING_BAR_WINDOW, len(sym_data))
        trailing = sym_data["close"].iloc[-missing_window:]
        n_missing = trailing.isna().sum()
        if n_missing > max_missing_bars:
            logger.debug(
                "%s excluded: %d missing bars in last %d days (max %d)",
                sym,
                n_missing,
                missing_window,
                max_missing_bars,
            )
            continue

        eligible.append(sym)

    logger.info(
        "Universe as of %s: %d / %d symbols pass liquidity filters",
        as_of_date.date(),
        len(eligible),
        len(symbols),
    )
    return eligible


def build_rebalance_dates(
    panel: pd.DataFrame,
    frequency: str = "QE",  # quarterly-end
) -> pd.DatetimeIndex:
    """Return rebalance dates — the last trading day of each calendar period.

    Parameters
    ----------
    panel:
        The full tidy panel.
    frequency:
        pandas offset alias for rebalance frequency.  Default ``"QE"``
        (quarter-end). Use ``"ME"`` for monthly.
    """
    all_dates = panel.index.get_level_values("date").unique().sort_values()
    # Resample to frequency and take the last date in each period that appears in trading days
    rebalance = pd.Series(all_dates, index=all_dates).resample(frequency).last().dropna()
    return pd.DatetimeIndex(rebalance.values)


def get_sector_map(csv_path: Path | None = None) -> dict[str, str]:
    """Return ``{symbol: sector}`` from the constituent CSV."""
    df = load_constituents(csv_path)
    return dict(zip(df["symbol"], df["sector"], strict=False))
