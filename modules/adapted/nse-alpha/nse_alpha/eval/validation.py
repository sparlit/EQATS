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


"""Walk-forward cross-validation for signal evaluation.

Walk-Forward Expanding Window
------------------------------
The default validator uses an expanding training window:

    ┌──────────────────────────┬──────────┬───────────────────┐
    │  Train (min 252 days)    │ Embargo  │  Test (63 days)   │
    │  expanding               │ (5 days) │                   │
    └──────────────────────────┴──────────┴───────────────────┘

Embargo: 5-day gap between train end and test start prevents any subtle
cross-contamination from events that span the boundary (e.g. earnings
effects that linger for a few days).

``CrossValidator`` Protocol
----------------------------
The ``CrossValidator`` protocol defines a clean interface so that future
implementations (PurgedKFold, CombinatorialPurgedCV) can be swapped in
without modifying call sites.  Those implementations are NOT built in this
phase — see Future Work.
"""


from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import pandas as pd

# ---------------------------------------------------------------------------
# Named constants — do not hardcode these inline anywhere
# ---------------------------------------------------------------------------
MIN_TRAIN_DAYS: int = 252  # minimum trading days in the training window
TEST_BLOCK_DAYS: int = 63  # number of trading days in each test block
EMBARGO_DAYS: int = 5  # buffer between train and test to prevent leakage

DateRange = tuple[pd.DatetimeIndex, pd.DatetimeIndex]


@runtime_checkable
class CrossValidator(Protocol):
    """Protocol for all cross-validation schemes.

    Any implementation that satisfies this protocol can be dropped into
    ``eval/runner.py`` without changing call sites.
    """

    def split(self, dates: pd.DatetimeIndex) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        """Yield ``(train_dates, test_dates)`` tuples.

        Parameters
        ----------
        dates:
            All trading dates in the panel, sorted ascending.

        Yields
        ------
        tuple[pd.DatetimeIndex, pd.DatetimeIndex]
            ``train_dates`` contains dates for training.
            ``test_dates`` contains dates for testing.
            The sets are non-overlapping; embargo dates are excluded from both.
        """
        ...


@dataclass
class WalkForwardEmbargo:
    """Expanding-window walk-forward cross-validator with embargo gap.

    Parameters
    ----------
    min_train_days:
        Minimum number of trading days required in the training window.
    test_block_days:
        Size of each test block in trading days.
    embargo_days:
        Number of days to exclude between train and test.
    """

    min_train_days: int = MIN_TRAIN_DAYS
    test_block_days: int = TEST_BLOCK_DAYS
    embargo_days: int = EMBARGO_DAYS

    def split(self, dates: pd.DatetimeIndex) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        """Yield expanding-window ``(train_dates, test_dates)`` pairs."""
        dates = dates.sort_values()
        n = len(dates)

        test_start_idx = self.min_train_days + self.embargo_days
        if test_start_idx >= n:
            return

        idx = test_start_idx
        while idx < n:
            # Training: all dates from 0 to train_end (expanding)
            train_end_idx = idx - self.embargo_days - 1
            train_dates = dates[: train_end_idx + 1]

            # Test: next test_block_days from idx
            test_end_idx = min(idx + self.test_block_days - 1, n - 1)
            test_dates = dates[idx : test_end_idx + 1]

            if len(train_dates) >= self.min_train_days and len(test_dates) > 0:
                yield train_dates, test_dates

            idx = test_end_idx + 1


class PurgedKFold:
    """Purged K-Fold cross-validator — NOT IMPLEMENTED.

    Future work: implement purged K-fold as described in
    López de Prado (2018), "Advances in Financial Machine Learning", Chapter 7.

    When implemented, it should satisfy the ``CrossValidator`` protocol so it
    can replace ``WalkForwardEmbargo`` at call sites without further changes.
    """

    def split(self, dates: pd.DatetimeIndex) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        raise NotImplementedError(
            "PurgedKFold is not implemented in this phase. See Future Work in README."
        )


class CombinatorialPurgedCV:
    """Combinatorial purged cross-validation — NOT IMPLEMENTED.

    Future work: see López de Prado (2018), Chapter 12.
    Satisfies ``CrossValidator`` protocol once implemented.
    """

    def split(self, dates: pd.DatetimeIndex) -> Iterator[tuple[pd.DatetimeIndex, pd.DatetimeIndex]]:
        raise NotImplementedError(
            "CombinatorialPurgedCV is not implemented in this phase. See Future Work in README."
        )
