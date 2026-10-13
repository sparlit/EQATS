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


"""Point-in-time universe interface.

This module defines the ``UniverseProvider`` protocol that any universe
implementation must satisfy.  Two implementations are provided:

``StaticUniverse``
    Uses today's Nifty 200 constituent list for all dates.
    **Survivorship-biased** — for POC use only.

``PointInTimeUniverse``
    Stub that raises ``NotImplementedError``.
    **Future work** — requires a historical index composition data feed.

Future Work
-----------
A bias-free implementation of ``PointInTimeUniverse`` requires a data source
that tracks *historical* NSE index constituents, such as:
    - NSE's own historical index composition files (available via NSE Data APIs)
    - Refinitiv / Bloomberg historical membership data
    - CMIE Prowess constituent history

Implementation would:
    1. load a mapping of {date → list[str]} from that source
    2. For ``get_universe(date)``, return the constituents that were in the
       index at the *start* of that month/quarter, not retrospectively.
    3. Apply the same liquidity filters as ``StaticUniverse.get_universe`` but
       only to instruments that were actually in the index on that date.
"""


from typing import Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class UniverseProvider(Protocol):
    """Protocol that all universe implementations must satisfy."""

    def get_universe(self, date: pd.Timestamp) -> list[str]:
        """Return the eligible symbol list as of *date*.

        Parameters
        ----------
        date:
            The rebalance date.  Implementations MUST NOT use any data
            from after this date.

        Returns
        -------
        list[str]
            Tickers with ``.NS`` suffix.
        """
        ...


class StaticUniverse:
    """Returns the same (today's) Nifty 200 list for every date.

    ⚠️  Survivorship-biased — use only for POC research.
    """

    def __init__(self, panel: pd.DataFrame) -> None:
        from nse_alpha.universe.nifty200 import apply_liquidity_filters

        self._panel = panel
        self._apply_filters = apply_liquidity_filters

    def get_universe(self, date: pd.Timestamp) -> list[str]:
        """Apply liquidity filters to the static constituent list as of *date*."""
        return self._apply_filters(self._panel, date)


class PointInTimeUniverse:
    """True point-in-time universe provider.

    **NOT IMPLEMENTED** — future work.

    Raises ``NotImplementedError`` on any method call.
    See module docstring for implementation requirements.
    """

    def get_universe(self, date: pd.Timestamp) -> list[str]:
        raise NotImplementedError(
            "PointInTimeUniverse is not implemented yet. "
            "It requires historical NSE index composition data. "
            "See universe/point_in_time.py for future work notes."
        )
