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


import pandas as pd
from v2.corporate_data import calculated_market_cap_cr, market_cap_max_age_days
from v2.eligibility import evaluate_eligibility


def _prices(rows=260):
    return pd.DataFrame(
        {
            "trade_date": pd.date_range("2025-01-01", periods=rows),
            "open": 100.0,
            "high": 105.0,
            "low": 95.0,
            "close": 100.0,
            "volume": 200_000,
            "turnover_lacs": 600.0,
            "delivery_pct": 40.0,
        }
    )


def test_source_aware_market_cap_freshness():
    frame = _prices()
    as_of = str(frame.trade_date.max().date())
    cap_date = str((frame.trade_date.max() - pd.Timedelta(days=100)).date())
    quarterly = evaluate_eligibility(
        "ABC",
        frame,
        metadata={
            "series": "EQ",
            "active": True,
            "market_cap_cr": 2000,
            "market_cap_as_of": cap_date,
            "market_cap_source": "CALCULATED_QUARTERLY_SHARES",
        },
        as_of_date=as_of,
    )
    direct = evaluate_eligibility(
        "ABC",
        frame,
        metadata={
            "series": "EQ",
            "active": True,
            "market_cap_cr": 2000,
            "market_cap_as_of": cap_date,
            "market_cap_source": "NSE_DIRECT_MARKET_CAP",
        },
        as_of_date=as_of,
    )
    assert quarterly.eligible
    assert direct.reason_code == "STALE_MARKET_CAP"
    assert market_cap_max_age_days("NSE_ANNUAL_ALL_COMPANIES") == 0


def test_market_cap_calculation_in_crore():
    assert calculated_market_cap_cr(100, 100_000_000) == 1000
