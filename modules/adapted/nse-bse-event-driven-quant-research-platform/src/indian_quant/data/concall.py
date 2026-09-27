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


"""Concall.in data access functions.

Source: Concall.in via Playwright API interception.

Functions:
  get_concall_calendar() — Earnings call calendar
  get_concall_details() — Company details from concall
  get_concall_ratios() — Financial ratios
  get_concall_peers() — Peer comparison
"""


import pandas as pd

from indian_quant.config.connections import get_engine


def get_concall_calendar(
    sector: str | None = None,
    days: int | None = None,
) -> pd.DataFrame:
    """Get earnings call calendar from concall.in.

    Returns DataFrame with columns:
        fin_code, company_name, date_time, title, type

    Args:
        sector: Filter by sector. None = all.
        days: Only show next N days. None = all.
    """
    import asyncio

    from indian_quant.ingestion.web.concall_scraper import ConcallScraper

    scraper = ConcallScraper(use_cache=True)
    events = asyncio.get_event_loop().run_until_complete(
        scraper.get_earnings_calendar(size=200, sector=sector or "All")
    )

    if not events:
        return pd.DataFrame()

    df = pd.DataFrame(events)

    if days and "date_time" in df.columns:
        from datetime import datetime, timedelta

        cutoff = datetime.now() + timedelta(days=days)
        df["date_time"] = pd.to_datetime(df["date_time"], errors="coerce")
        df = df[df["date_time"] <= cutoff]

    return df


def get_concall_details(fin_code: int) -> dict | None:
    """Get company details from concall.in.

    Returns dict with:
        company_name, short_name, bse_code, nse_symbol, isin,
        sector, industry, standalone_key_details, consolidated_key_details,
        ttm_data, financial_ratios, peers, events, resources
    """
    import asyncio

    from indian_quant.ingestion.web.concall_scraper import ConcallScraper

    scraper = ConcallScraper(use_cache=True)
    return asyncio.get_event_loop().run_until_complete(scraper.get_company_details(fin_code))


def get_concall_ratios(fin_code: int) -> dict | None:
    """Get financial ratios from concall.in.

    Returns dict with standaloneRatios and consolidatedRatios.
    Each ratio has: name, values (dateEnd, value, unit).
    """
    details = get_concall_details(fin_code)
    if details:
        return details.get("financial_ratios")
    return None


def get_concall_peers(fin_code: int) -> pd.DataFrame | None:
    """Get peer comparison from concall.in.

    Returns DataFrame with peer companies and their metrics.
    """
    details = get_concall_details(fin_code)
    if not details:
        return None

    peers_data = details.get("peers")
    if not peers_data:
        return None

    peers_data.get("columnDefinitions", [])
    rows = peers_data.get("dataRows", [])

    if not rows:
        return pd.DataFrame()

    # Build DataFrame from rows
    df = pd.DataFrame(rows)

    # Add nse_symbol to each row for easier joining
    if "nseSymbol" in df.columns:
        df["symbol"] = df["nseSymbol"]

    return df
