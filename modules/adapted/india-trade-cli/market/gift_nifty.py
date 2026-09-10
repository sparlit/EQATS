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


"""
market/gift_nifty.py
────────────────────
GIFT NIFTY (NSE IFSC futures) pre-market indicator (#106).

GIFT NIFTY (formerly SGX NIFTY) trades when NSE is closed and is the
primary predictor of gap-up / gap-down opens on NSE.

Data sources (tried in order):
  1. yfinance ^NSEIFSC  — real-time GIFT NIFTY price
  2. yfinance NIFTY50.NS — NSE NIFTY 50 futures (weaker proxy)
  3. None               — returns GiftNiftySnapshot with 0 values

Usage:
    from market.gift_nifty import get_gift_nifty

    g = get_gift_nifty()
    if g and g.ltp:
        print(f"GIFT NIFTY: {g.ltp:.0f} ({g.change_pct:+.2f}%)")
        if g.premium_pts is not None:
            print(f"  Premium vs NIFTY spot: {g.premium_pts:+.0f} pts ({g.premium_pct:+.2f}%)")
"""


from dataclasses import dataclass
from typing import Optional


@dataclass
class GiftNiftySnapshot:
    """GIFT NIFTY / NIFTY IFSC futures snapshot."""

    ltp: float  # Last traded price
    change: float  # Point change
    change_pct: float  # % change
    high: float = 0.0
    low: float = 0.0
    # vs NIFTY spot (set by get_gift_nifty if nifty_spot provided)
    premium_pts: float | None = None  # positive = trades above spot
    premium_pct: float | None = None
    source: str = ""  # "yfinance" | "unavailable"

    @property
    def implied_gap_pct(self) -> float | None:
        """Expected NSE gap-open percentage (premium_pct)."""
        return self.premium_pct

    def as_text(self, nifty_spot: float | None = None) -> str:
        """One-liner for terminal output."""
        direction = "+" if self.change >= 0 else ""
        gap_text = ""
        if self.premium_pts is not None:
            direction2 = "+" if self.premium_pct >= 0 else ""
            gap_text = (
                f" — {direction2}{self.premium_pct:.2f}% gap {'up' if self.premium_pct >= 0 else 'down'} open implied"
            )
        return (
            f"GIFT NIFTY: {self.ltp:,.0f}  "
            f"({direction}{self.change:+.0f} pts, {direction}{self.change_pct:.2f}%)"
            f"{gap_text}"
        )


# yfinance tickers to try in order
_YF_TICKERS = ["^NSEIFSC", "NIFTY50.NS"]


def get_gift_nifty(nifty_spot: float | None = None) -> GiftNiftySnapshot | None:
    """
    Fetch GIFT NIFTY (NSE IFSC) futures price.

    Args:
        nifty_spot: Current NIFTY 50 spot price (to compute premium/discount).
                    If None, premium_pts and premium_pct will be None.

    Returns:
        GiftNiftySnapshot or None if all sources fail.
    """
    snap = _from_yfinance(nifty_spot)
    if snap is not None:
        return snap
    return None


def _from_yfinance(nifty_spot: float | None) -> GiftNiftySnapshot | None:
    """Fetch from yfinance using ^NSEIFSC or NIFTY50.NS fallback."""
    try:
        import yfinance as yf
    except ImportError:
        return None

    for ticker_sym in _YF_TICKERS:
        try:
            t = yf.Ticker(ticker_sym)
            info = t.fast_info  # faster than full .info

            # fast_info has: last_price, previous_close, day_high, day_low
            ltp = getattr(info, "last_price", None)
            prev = getattr(info, "previous_close", None)

            if ltp is None or ltp == 0:
                continue

            change = (ltp - prev) if prev else 0.0
            change_pct = (change / prev * 100) if prev else 0.0
            high = getattr(info, "day_high", 0.0) or 0.0
            low = getattr(info, "day_low", 0.0) or 0.0

            premium_pts: float | None = None
            premium_pct: float | None = None
            if nifty_spot and nifty_spot > 0:
                premium_pts = round(ltp - nifty_spot, 1)
                premium_pct = round(premium_pts / nifty_spot * 100, 3)

            return GiftNiftySnapshot(
                ltp=round(ltp, 1),
                change=round(change, 1),
                change_pct=round(change_pct, 3),
                high=round(high, 1),
                low=round(low, 1),
                premium_pts=premium_pts,
                premium_pct=premium_pct,
                source="yfinance",
            )
        except Exception:
            continue

    return None
