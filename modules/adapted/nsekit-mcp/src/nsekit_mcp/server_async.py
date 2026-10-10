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
NseKit-MCP Server — Async Version
========================================
"""

import asyncio
import json
import time
from typing import Annotated, Literal

import pandas as pd
from mcp.server import MCPServer
from NseKit import Moneycontrol, NseKit

# ================================================================
#                   ASYNC RATE LIMIT CONTROL (NSE Safe)
# ================================================================

RATE_LIMIT_SECONDS = 0.35  # NSE safe: ~3 requests/sec
_last_call_time: float = 0.0
_async_lock = asyncio.Lock()


async def rate_limit():
    """Async-safe minimum delay between NSE API calls."""
    global _last_call_time
    async with _async_lock:
        now = time.monotonic()
        elapsed = now - _last_call_time
        if elapsed < RATE_LIMIT_SECONDS:
            await asyncio.sleep(RATE_LIMIT_SECONDS - elapsed)
        _last_call_time = time.monotonic()


# ================================================================
#                   MCP + NseKit Initialization
# ================================================================

mcp = MCPServer("NseKit-MCP")

get = NseKit.Nse()
mc = Moneycontrol.MC()

# ================================================================
#                   Helper: DF → JSON
# ================================================================


def df_to_json(data):
    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient="records")
    return data


def compact_args(*args):
    return [a for a in args if a is not None]


def compact_kwargs(**kwargs):
    return {k: v for k, v in kwargs.items() if v is not None}


async def run_sync(func, *args, **kwargs):
    """
    Run a blocking NseKit call in a thread-pool executor so it
    does not block the async event loop.
    """
    # loop = asyncio.get_event_loop()
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


# =====================================================================
# MARKET STATUS & TRADING INFO
# =====================================================================


@mcp.tool()
async def market_live_status(
    mode: Literal["Market Status", "Nifty50", "Mcap", "Gift Nifty"] = "Market Status",
):
    """Get current market status, Nifty50, total mcap, or Gift Nifty value."""
    await rate_limit()
    return df_to_json(await run_sync(get.nse_market_status, mode))


@mcp.tool()
async def market_is_open(
    segment: Literal[
        "Capital Market", "Currency", "Commodity", "Debt", "currencyfuture"
    ] = "Capital Market",
):
    """Check if Capital Market, Currency, Commodity or Debt segment is open."""
    await rate_limit()
    return await run_sync(get.nse_is_market_open, segment)


@mcp.tool()
async def market_trading_holidays_list(
    list_only: Annotated[bool, "Return only date list if True"] = False,
):
    """Get all NSE trading holidays for current year."""
    await rate_limit()
    return df_to_json(await run_sync(get.nse_trading_holidays, list_only=list_only))


@mcp.tool()
async def market_clearing_holidays_list(
    list_only: Annotated[bool, "Return only dates if True"] = False,
):
    """Get all NSE clearing/settlement holidays."""
    await rate_limit()
    return df_to_json(await run_sync(get.nse_clearing_holidays, list_only=list_only))


@mcp.tool()
async def market_is_trading_holiday(date: Annotated[str, 'Optional "DD-MMM-YYYY"'] = None):
    """Check if today or given date is trading holiday."""
    await rate_limit()
    return await run_sync(get.is_nse_trading_holiday, date)


@mcp.tool()
async def market_is_clearing_holiday(date: Annotated[str, 'Optional "DD-MMM-YYYY"'] = None):
    """Check if today or given date is clearing holiday."""
    await rate_limit()
    return await run_sync(get.is_nse_clearing_holiday, date)


# =====================================================================
# LIVE MARKET & REFERENCE DATA
# =====================================================================


@mcp.tool()
async def market_live_turnover():
    """Real-time turnover across Equity, F&O, Currency, Commodity segments."""
    await rate_limit()
    return df_to_json(await run_sync(get.nse_live_market_turnover))


@mcp.tool()
async def currency_reference_rates():
    """Official NSE USD, EUR, GBP, JPY reference rates."""
    await rate_limit()
    return df_to_json(await run_sync(get.nse_reference_rates))


@mcp.tool()
async def gift_nifty_live():
    """Current Gift Nifty futures price and USDINR rate."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_gifty_nifty))


@mcp.tool()
async def market_live_statistics():
    """Live capital market stats: Count of Advances, Declines, Unchanged, 52W High, 52W Low,
    Upper Circuit, Lower Circuit, Market Cap ₹ Lac Crs."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_market_statistics))


@mcp.tool()
async def avg_order_ack_latency():
    """NSE's current average order acknowledgement latency in nanoseconds."""
    await rate_limit()
    return df_to_json(await run_sync(get.latency_nanosec))


@mcp.tool()
async def all_nse_traded_stocks(
    series: Literal["EQ", "BE", "BZ", "SM", "ST", "SZ", "IV", "ID", "GB", "GS", "RR", "RT", "BO"]
    | None = None,
    mkt_cap_gte: Annotated[int | None, "Minimum market cap in ₹ Cr e.g., 1000"] = None,
    mkt_cap_lte: Annotated[int | None, "Maximum market cap in ₹ Cr e.g., 500"] = None,
):
    """
    Fetch live traded securities from NSE Cash Market.

    Parameters
    ----------
    series : str, optional
        Filter by NSE series code.

        Supported values:
        - EQ : Fully paid equity shares / ETFs
        - BE : Trade-for-trade equity shares
        - BZ : Trade-for-trade equity shares
        - SM : SME equity shares
        - ST : SME trade-for-trade shares
        - SZ : SME trade-for-trade shares
        - IV : InvIT units
        - ID : InvIT trade-for-trade units
        - GB : Sovereign Gold Bonds
        - GS : Government Securities
        - RR : REIT units
        - RT : REIT trade-for-trade units
        - BO : Buyback of equity shares

    mkt_cap_gte : int, optional
        Return only securities with Market Cap greater than or equal to
        the specified value (₹ Crores).

    mkt_cap_lte : int, optional
        Return only securities with Market Cap less than or equal to
        the specified value (₹ Crores).

    Returns
    -------
    JSON
        List of traded NSE securities with:
        - Symbol
        - Series
        - Last Price (₹)
        - Change (₹)
        - % Change
        - Volume (Lakhs)
        - Value (₹ Cr.)
        - Mkt Cap (₹ Cr.)

    Examples
    --------
    Get all traded securities:
        all_nse_traded_stocks()

    EQ stocks only:
        all_nse_traded_stocks(series="EQ")

    Market cap >= ₹1,000 Cr:
        all_nse_traded_stocks(mkt_cap_gte=1000)

    Market cap <= ₹500 Cr:
        all_nse_traded_stocks(mkt_cap_lte=500)

    EQ stocks with market cap between ₹500 Cr and ₹5,000 Cr:
        all_nse_traded_stocks(
            series="EQ",
            mkt_cap_gte=500,
            mkt_cap_lte=5000
        )
    """

    await rate_limit()
    kwargs = compact_kwargs(series=series, mkt_cap_gte=mkt_cap_gte, mkt_cap_lte=mkt_cap_lte)
    return df_to_json(await run_sync(get.cm_live_stocks_traded, **kwargs))


from typing import Annotated, Literal


@mcp.tool()
async def all_nse_price_band_hitters(
    band: Literal["all", "upper", "lower", "both"] | None = "all",
    sec_type: Literal["AllSec", "SecGtr20", "SecLwr20"] | None = "AllSec",
    series: Literal["EQ", "BE", "BZ", "SM", "ST", "SZ", "IV", "ID", "GB", "GS", "RR", "RT", "BO"]
    | None = None,
    turnover_gte: Annotated[float | None, "Minimum turnover in ₹ Crores"] = None,
    turnover_lte: Annotated[float | None, "Maximum turnover in ₹ Crores"] = None,
):
    """
    Fetch live NSE Price Band Hitters data.

    Parameters
    ----------
    band : str, optional
        Price band category.

        Supported values:
        - all   : Upper + Lower + Both (default)
        - upper : Upper circuit stocks
        - lower : Lower circuit stocks
        - both  : Stocks that hit both circuits

    sec_type : str, optional
        Security category.

        Supported values:
        - AllSec   : All securities
        - SecGtr20 : Securities with price > ₹20
        - SecLwr20 : Securities with price ≤ ₹20

    series : str, optional
        Filter by NSE series.

        Supported values:
        - EQ : Fully paid equity shares / ETFs
        - BE : Trade-for-trade equity shares
        - BZ : Trade-for-trade equity shares
        - SM : SME equity shares
        - ST : SME trade-for-trade shares
        - SZ : SME trade-for-trade shares
        - IV : InvIT units
        - ID : InvIT trade-for-trade units
        - GB : Sovereign Gold Bonds
        - GS : Government Securities
        - RR : REIT units
        - RT : REIT trade-for-trade units
        - BO : Buyback of equity shares

    turnover_gte : float, optional
        Return only securities with turnover greater than
        or equal to the specified value (₹ Crores).

    turnover_lte : float, optional
        Return only securities with turnover less than
        or equal to the specified value (₹ Crores).

    Returns
    -------
    JSON
        Price band hitter securities with:

        - Symbol
        - Series
        - LTP (₹)
        - Change (₹)
        - % Change
        - Price Band (%)
        - High Price
        - Low Price
        - 52W High
        - 52W Low
        - Volume (Lakhs)
        - Turnover (₹ Cr.)
        - Band

    Examples
    --------
    All price band hitters:
        all_nse_price_band_hitters()

    Upper circuit stocks:
        all_nse_price_band_hitters(band="upper")

    Lower circuit EQ stocks:
        all_nse_price_band_hitters(
            band="lower",
            series="EQ"
        )

    Upper circuit stocks with price > ₹20:
        all_nse_price_band_hitters(
            band="upper",
            sec_type="SecGtr20"
        )

    Upper circuit stocks with turnover ≥ ₹5 Cr:
        all_nse_price_band_hitters(
            band="upper",
            turnover_gte=5
        )

    Turnover between ₹1 Cr and ₹10 Cr:
        all_nse_price_band_hitters(
            turnover_gte=1,
            turnover_lte=10
        )
    """

    await rate_limit()
    kwargs = compact_kwargs(
        band=band,
        sec_type=sec_type,
        series=series,
        turnover_gte=turnover_gte,
        turnover_lte=turnover_lte,
    )
    return df_to_json(await run_sync(get.cm_live_price_band_hitters, **kwargs))


# =====================================================================
# PRE-OPEN & INDEX LIVE
# =====================================================================


@mcp.tool()
async def preopen_index_summary(
    index_name: Literal[
        "NIFTY 50", "Nifty Bank", "Emerge", "Securities in F&O", "Others", "All"
    ] = "NIFTY 50",
):
    """Pre-open advance/decline for Nifty 50, Bank, Emerge, F&O, Others."""
    await rate_limit()
    return df_to_json(await run_sync(get.pre_market_nifty_info, index_name))


@mcp.tool()
async def preopen_market_breadth():
    """Full NSE pre-open advance/decline across all segments."""
    await rate_limit()
    return df_to_json(await run_sync(get.pre_market_all_nse_adv_dec_info))


@mcp.tool()
async def preopen_stocks_data(
    category: Literal["All", "NIFTY 50", "Nifty Bank", "Emerge", "Securities in F&O"] = "NIFTY 50",
):
    """All stocks in pre-open with final price, change %."""
    await rate_limit()
    return df_to_json(await run_sync(get.pre_market_info, category))


@mcp.tool()
async def preopen_futures_data(
    category: Literal["Index Futures", "Stock Futures"] = "Index Futures",
):
    """Index Futures or Stock Futures in pre-open with final price, change %."""
    await rate_limit()
    return df_to_json(await run_sync(get.pre_market_derivatives_info, category))


@mcp.tool()
async def closing_auction_session(symbol: str | None = None):
    """
    Closing Auction Session (CAS) — final-minutes call-auction snapshot.

    Returns per-symbol IEP/order-book-derived fields (or final matched
    price/qty once the auction settles). Pass `symbol = None`(default) show all symbol data.
    Pass `symbol` to filter to a single stock. Pass `symbol="status"` to get a combined session
    state string (e.g. "Open — Closing Auction Session Market Open")
    instead of the data table.
    """
    await rate_limit()
    return df_to_json(await run_sync(get.nse_closing_auction_session, symbol))


@mcp.tool()
async def list_of_indices():
    """All 150+ NSE indices. ("Indices Eligible In Derivatives", "Broad Market Indices",
    "Sectoral Market Indices", "Thematic Market Indices", "Strategy Market Indices", "Others")"""
    await rate_limit()
    return await run_sync(get.list_of_indices)


@mcp.tool()
async def indices_live_data():
    """Live values (open, high, low, close, variation, percentChange, yearHigh, yearLow, pe, pb,
    dy, declines, advances, unchanged) of all 150+ NSE indices."""
    await rate_limit()
    return df_to_json(await run_sync(get.index_live_all_indices_data))


@mcp.tool()
async def index_live_constituents(
    index_name: Annotated[
        str,
        'e.g. "NIFTY 50", "SECURITIES IN F&O", "NIFTY BANK" (use list_of_indices() for full list)',
    ],
    list_only: Annotated[bool, "Return only symbols if True"] = False,
):
    """Get stocks in any NSE index with live or current data."""
    await rate_limit()
    return df_to_json(
        await run_sync(get.index_live_indices_stocks_data, index_name, list_only=list_only)
    )


# =====================================================================
# LISTS & MASTER DATA
# =====================================================================


@mcp.tool()
async def list_of_nifty50_stocks(list_only: Annotated[bool, "Only symbols if True"] = False):
    """Latest Nifty 50 stocks with sector & weight."""
    await rate_limit()
    data = await run_sync(get.nse_6m_nifty_50, list_only=list_only)
    if list_only:
        return {"index": "NIFTY 50", "count": len(data), "symbols": list(data)}
    return df_to_json(data)


@mcp.tool()
async def list_of_nifty500_stocks(list_only: Annotated[bool, "Only symbols if True"] = False):
    """Full Nifty 500 stock list."""
    await rate_limit()
    data = await run_sync(get.nse_6m_nifty_500, list_only=list_only)
    if list_only:
        return {"index": "NIFTY 500", "count": len(data), "symbols": list(data)}
    return df_to_json(data)


@mcp.tool()
async def list_of_fno_stocks(
    mode: Literal["stocks", "index"] = "stocks",
    list_only: Annotated[bool, "Only symbols if True"] = False,
):
    """All F&O eligible stocks or indices."""
    await rate_limit()
    data = await run_sync(get.nse_eom_fno_full_list, mode=mode, list_only=list_only)
    if list_only:
        return {"name": f"F&O {mode.upper()}", "count": len(data), "symbols": list(data)}
    return df_to_json(data)


@mcp.tool()
async def list_of_All_NSE_stocks(list_only: Annotated[bool, "Only symbols if True"] = False):
    """Complete list of all NSE listed equities."""
    await rate_limit()
    data = await run_sync(get.nse_eod_equity_full_list, list_only=list_only)
    if list_only:
        return json.dumps(list(data))
    return df_to_json(data)


# =====================================================================
# OPTION CHAIN & F&O LIVE
# =====================================================================


@mcp.tool()
async def fno_live_option_chain(
    symbol: Annotated[str, "'RELIANCE', 'NIFTY', 'BANKNIFTY'. Must be uppercase."],
    expiry: Annotated[str | None, 'Expiry date "DD-MMM-YYYY", or None for nearest expiry'] = None,
    strike: Annotated[
        str | None,
        "Fetch this strike across all expiries e.g. '23500'. Mutually exclusive with expiry.",
    ] = None,
    compact: Annotated[bool, "Omit bid/ask columns"] = False,
):
    """
    Full live option chain with OI, volume, IV.

    Provide either expiry (single-expiry full chain) or strike (one strike across all expiries), not both.
    use "fno_expiry_dates_and_strikePrice" tool for find Expiry Dates and Strike Price
    Omitting both returns the nearest expiry chain.
    """
    if expiry and strike:
        raise ValueError("Provide either 'expiry' or 'strike', not both.")
    await rate_limit()
    return df_to_json(
        await run_sync(
            get.fno_live_option_chain,
            symbol,
            expiry_date=expiry,
            oi_mode="compact" if compact else "full",
            strike_price=strike,
        )
    )


@mcp.tool()
async def fno_expiry_dates(
    symbol: Annotated[str, "Stock or index. e.g., NIFTY, RELIANCE. Must be uppercase."] = "NIFTY",
    filter_type: Literal["Current", "Next Week", "Month", "All"] = None,
):
    """Get All expiry dates or find particularly current, weekly, monthly expiry dates."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_expiry_dates, symbol, filter_type))


@mcp.tool()
async def fno_expiry_dates_and_strikePrice(symbol: Annotated[str, "Stock or index"] = "NIFTY"):
    """Get All expiry dates & strikePrice for given symbol."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_expiry_dates_raw, symbol))


@mcp.tool()
async def most_active_options(
    contract_type: Literal["Stock", "Index"] = "Stock",
    option_type: Literal["Call", "Put"] = "Call",
    sort_by: Literal["Volume", "Value"] = "Volume",
):
    """Most active Call/Put by volume or value."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_most_active, contract_type, option_type, sort_by))


# =====================================================================
# EQUITY LIVE DATA
# =====================================================================

# @mcp.tool()
# async def most_active_equities(by: Literal["value", "volume"] = "value"):
#     """Top stocks by traded value or volume."""
#     await rate_limit()
#     func = get.cm_live_most_active_equity_by_value if by == "value" else get.cm_live_most_active_equity_by_vol
#     return df_to_json(await run_sync(func))


@mcp.tool()
async def most_active_equities(index: Literal["value", "volume"] = "value"):
    """Top stocks by traded value or volume."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_most_active_equity, index))


@mcp.tool()
async def equity_volume_surge():
    """Stocks with sudden volume surge or spurts vs average."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_volume_spurts))


@mcp.tool()
async def equity_52week_high_live():
    """Live market stocks hitting 52-week high today."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_52week_high))


@mcp.tool()
async def equity_52week_low_live():
    """Live market stocks hitting 52-week low today."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_52week_low))


# =====================================================================
# CORPORATE ACTIONS & EVENTS
# =====================================================================


@mcp.tool()
async def corporate_insider_trading(
    symbol: Annotated[
        str | None, "The NSE stock or index symbol (e.g., RELIANCE). Optional."
    ] = None,
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] | None = None,
    start_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    end_date: Annotated[str | None, "DD-MM-YYYY"] = None,
):
    """Latest insider buying/selling (SAST)."""
    await rate_limit()
    args = compact_args(symbol, period, start_date, end_date)
    return df_to_json(await run_sync(get.cm_live_hist_insider_trading, *args))


@mcp.tool()
async def corporate_actions(
    symbol: Annotated[
        str | None, "The NSE stock or index symbol (e.g., RELIANCE). Optional filter."
    ] = None,
    period: Literal["1M", "3M", "6M", "1Y"] | None = None,
    start_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    end_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    purpose: Annotated[str | None, "Optional filter"] = None,
):
    """Dividends, bonus, splits, rights, buyback."""
    await rate_limit()
    args = compact_args(symbol, period, start_date, end_date, purpose)
    return df_to_json(await run_sync(get.cm_live_hist_corporate_action, *args))


@mcp.tool()
async def corporate_board_meetings(
    symbol: Annotated[str, "Optional filter. Must be uppercase."] = None,
    start_date: Annotated[str, "DD-MM-YYYY"] = None,
    end_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Upcoming & past board meetings."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_hist_board_meetings, symbol, start_date, end_date))


# =====================================================================
# IPO & LISTINGS
# =====================================================================


@mcp.tool()
async def ipo_current_list():
    """All open Mainboard & SME IPOs with subscription status."""
    await rate_limit()
    return df_to_json(await run_sync(get.ipo_current))


@mcp.tool()
async def ipo_preopen_today():
    """Newly listed IPOs in special pre-open session."""
    await rate_limit()
    return df_to_json(await run_sync(get.ipo_preopen))


@mcp.tool()
async def ipo_performance_tracker(board: Literal["Mainboard", "SME"] | None = "Mainboard"):
    """YTD IPO listing performance & gains."""
    await rate_limit()
    return df_to_json(await run_sync(get.ipo_tracker_summary, board))


# =====================================================================
# HISTORICAL & EOD DATA
# =====================================================================


@mcp.tool()
async def index_price_history(
    index: Annotated[str, 'Name of the index (e.g., "NIFTY 50", "NIFTY BANK")'],
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "YTD", "MAX"]
    | None = None,
    from_date: Annotated[str | None, "Start date DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "End date DD-MM-YYYY"] = None,
):
    """Fetch historical OHLC + turnover for any index."""
    await rate_limit()
    kwargs = compact_kwargs(index=index, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.index_historical_data, **kwargs))


@mcp.tool()
async def equity_price_history(
    symbol: Annotated[str, 'Name of the stock (e.g., "TCS", "ITC"). Must be uppercase.'],
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "YTD", "MAX"]
    | None = None,
    from_date: Annotated[str | None, "Start date DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "End date DD-MM-YYYY"] = None,
):
    """Fetch historical price OHLC + turnover + delivery data for any stock."""
    await rate_limit()
    kwargs = compact_kwargs(symbol=symbol, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.cm_hist_security_wise_data, **kwargs))


# =====================================================================
#                          NSE Data - Historical
# =====================================================================


@mcp.tool()
async def nse_circulars(
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
    department: Annotated[str, 'Optional filter, e.g., "NSE Listing"'] = None,
):
    """Historical NSE circulars (default: yesterday → today)."""
    await rate_limit()
    return df_to_json(await run_sync(get.nse_live_hist_circulars, from_date, to_date, department))


@mcp.tool()
async def nse_press_releases(
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
    department: Annotated[
        str,
        "e.g. Corporate Communications, Investor Services Cell, Member Compliance, NSE Clearing, etc.",
    ] = None,
):
    """Historical NSE press releases."""
    await rate_limit()
    return df_to_json(
        await run_sync(get.nse_live_hist_press_releases, from_date, to_date, department)
    )


# =====================================================================
#                          Index Live Data
# =====================================================================


@mcp.tool()
async def nifty50_past_returns():
    """Nifty 50 returns summary (1W to 5Y)."""
    await rate_limit()
    return df_to_json(await run_sync(get.index_live_nifty_50_returns))


@mcp.tool()
async def index_live_contribution(
    Index: Annotated[str, 'e.g., "NIFTY 50", "NIFTY BANK"'] = "NIFTY 50",
    Mode: Literal["First Five", "Full"] = None,
):
    """Stock-wise how many points (changePoints) contribution to NIFTY 50 or given index movement."""
    await rate_limit()
    return df_to_json(await run_sync(get.index_live_contribution, Index, Mode))


# =====================================================================
#                          Index EOD & Historical
# =====================================================================


@mcp.tool()
async def index_eod_bhavcopy(date: Annotated[str, "DD-MM-YYYY"]):
    """All indices EOD bhavcopy for a specific date (uses last trading date if none given)."""
    await rate_limit()
    return df_to_json(await run_sync(get.index_eod_bhav_copy, date))


@mcp.tool()
async def index_pe_pb_div_historical_data(
    index: Annotated[str, 'e.g., "NIFTY 50", "NIFTY BANK"'],
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "YTD", "MAX"]
    | None = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
):
    """Historical P/E, P/B, Dividend Yield for any index."""
    await rate_limit()
    kwargs = compact_kwargs(index=index, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.index_pe_pb_div_historical_data, **kwargs))


@mcp.tool()
async def india_vix(
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "YTD", "MAX"]
    | None = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
):
    """Historical India VIX data."""
    await rate_limit()
    kwargs = compact_kwargs(period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.india_vix_historical_data, **kwargs))


# =====================================================================
#                       Capital Market Live Data
# =====================================================================


@mcp.tool()
async def equity_live_stock_info(
    symbol: Annotated[str, "The NSE stock or index symbol (e.g., RELIANCE). Must be uppercase."],
):
    """Full live quote: Meta Data, Trade Information, Price Information, Securities Information, Order Book, etc."""
    await rate_limit()
    return await run_sync(get.cm_live_equity_info, symbol)


@mcp.tool()
async def equity_block_deals_live():
    """Latest block deals (live)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_block_deal))


@mcp.tool()
async def corporate_announcement(
    symbol: Annotated[str, "Optional filter. Must be uppercase."] = None,
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Corporate announcements (all or symbol-specific)."""
    await rate_limit()
    return df_to_json(
        await run_sync(get.cm_live_hist_corporate_announcement, symbol, from_date, to_date)
    )


@mcp.tool()
async def corporate_today_event_calendar(
    date_from: Annotated[str, "DD-MM-YYYY"] = None,
    date_to: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Today's or date-range corporate events (AGM, results etc.)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_today_event_calendar, date_from, date_to))


@mcp.tool()
async def corporate_upcoming_event_calendar():
    """Upcoming corporate events."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_upcoming_event_calendar))


@mcp.tool()
async def corporate_shareholder_meetings(
    symbol: Annotated[str, "Optional filter. Must be uppercase."] = None,
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Shareholder meetings (AGM/EGM) history."""
    await rate_limit()
    return df_to_json(
        await run_sync(get.cm_live_hist_Shareholder_meetings, symbol, from_date, to_date)
    )


@mcp.tool()
async def equity_QIP_history(
    stage: Literal["In-Principle", "Listing Stage"] = None,
    period_or_symbol: Annotated[
        str, '"1D", "1W", "1M", "3M", "6M", "1Y" or symbol "RELIANCE" etc.'
    ] = None,
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Qualified Institutional Placement (QIP) data by stage, period, symbol."""
    await rate_limit()
    return df_to_json(
        await run_sync(
            get.cm_live_hist_qualified_institutional_placement,
            stage,
            period_or_symbol,
            from_date,
            to_date,
        )
    )


@mcp.tool()
async def equity_preferential_issues(
    stage: Literal["In-Principle", "Listing Stage"] = None,
    period_or_symbol: Annotated[
        str, '"1D", "1W", "1M", "3M", "6M", "1Y" or symbol "RELIANCE" etc.'
    ] = None,
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Preferential issue data."""
    await rate_limit()
    return df_to_json(
        await run_sync(
            get.cm_live_hist_preferential_issue, stage, period_or_symbol, from_date, to_date
        )
    )


@mcp.tool()
async def equity_rights_issues(
    stage: Literal["In-Principle", "Listing Stage"] = None,
    period_or_symbol: Annotated[
        str, '"1D", "1W", "1M", "3M", "6M", "1Y" or symbol "RELIANCE" etc.'
    ] = None,
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Rights issue data."""
    await rate_limit()
    return df_to_json(
        await run_sync(get.cm_live_hist_right_issue, stage, period_or_symbol, from_date, to_date)
    )


@mcp.tool()
async def corporate_voting_results():
    """Latest voting results."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_voting_results))


@mcp.tool()
async def corporate_qtly_shareholding_patterns():
    """Latest quarterly shareholding patterns."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_qtly_shareholding_patterns))


@mcp.tool()
async def corporate_annual_reports():
    """Latest 20 Annual reports with pdf links."""
    await rate_limit()
    return df_to_json(await run_sync(get.recent_annual_reports))


@mcp.tool()
async def corporate_bsr_reports(
    symbol: Annotated[str, "Optional filter. Must be uppercase."] = None,
    from_date: Annotated[str, "DD-MM-YYYY"] = None,
    to_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Business Responsibility and Sustainability Reports (all or symbol-specific)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_live_hist_br_sr, symbol, from_date, to_date))


# =====================================================================
#                         FnO Live Data
# =====================================================================


@mcp.tool()
async def fno_live_futures_data(
    symbol: Annotated[
        str, "The NSE stock or index symbol (e.g., RELIANCE, NIFTY). Must be uppercase."
    ],
):
    """Live futures data for stock or index."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_futures_data, symbol))


@mcp.tool()
async def fno_live_top_20_stocks_contracts(category: Literal["Stock Futures", "Stock Options"]):
    """Live Top 20 Stocks Futures or Stocks Options data."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_top_20_derivatives_contracts, category))


@mcp.tool()
async def fno_live_most_active_futures_contracts(by: Literal["Volume", "Value"] = "Volume"):
    """Most active futures by Volume or Value."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_most_active_futures_contracts, by))


@mcp.tool()
async def fno_live_most_active_contracts_by_oi():
    """Most active contracts by Open Interest."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_most_active_contracts_by_oi))


@mcp.tool()
async def fno_live_most_active_contracts_by_volume():
    """Most active by volume."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_most_active_contracts_by_volume))


@mcp.tool()
async def fno_live_most_active_options_contracts_by_volume():
    """Top options contracts by volume."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_most_active_options_contracts_by_volume))


@mcp.tool()
async def fno_live_most_active_underlying():
    """Most active underlying stocks/indices."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_most_active_underlying))


@mcp.tool()
async def fno_live_change_in_oi():
    """Change in Open Interest across contracts."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_change_in_oi))


@mcp.tool()
async def fno_live_oi_vs_price():
    """Open Interest Vs Price across contracts."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_live_oi_vs_price))


@mcp.tool()
async def fno_live_active_contracts(
    symbol: Annotated[str, "e.g., NIFTY, BANKNIFTY, RELIANCE. Must be uppercase."] = "NIFTY",
    expiry_date: Annotated[str, "DD-MM-YYYY"] = None,
):
    """Active NIFTY/BANKNIFTY & stock option contracts."""
    await rate_limit()
    return df_to_json(
        await run_sync(get.fno_live_active_contracts, symbol, expiry_date=expiry_date)
    )


# =====================================================================
#                         EQUITY EOD DATA
# =====================================================================


@mcp.tool()
async def fii_dii_activity(
    exchange: Annotated[str, "None for All exchange (NSE+BSE). 'Nse' for NSE only."] = None,
):
    """Latest FII/DII net buying/selling activity."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_fii_dii_activity, exchange))


@mcp.tool()
async def market_eod_activity_report(
    date: Annotated[
        str, "Trade date in DD-MM-YY (2-digit year). Uses last trading date if None given."
    ],
):
    """Daily market turnover, advances/declines, top gainers/losers."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_market_activity_report, date))


@mcp.tool()
async def equity_eod_bhavcopy_delivery(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Full NSE equity bhavcopy including delivery percentage & value."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_bhavcopy_with_delivery, date))


@mcp.tool()
async def equity_eod_bhavcopy(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Standard equity closing prices, volume, trades (without delivery)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_equity_bhavcopy, date))


@mcp.tool()
async def equity_52week_high_low_eod(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Stocks hitting 52-week high or low on given date."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_52_week_high_low, date))


@mcp.tool()
async def equity_bulk_deals_eod():
    """End of day based bulk deals across NSE/BSE (client-level)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_bulk_deal))


@mcp.tool()
async def equity_block_deals_eod():
    """End of day based block deals (large negotiated trades)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_block_deal))


@mcp.tool()
async def equity_short_selling(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Stocks disclosed for short selling."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_shortselling, date))


@mcp.tool()
async def surveillance_indicator(
    date: Annotated[str, "DD-MM-YY (2-digit year). Uses last trading date if None given."],
):
    """Stocks under ASM/GSM/Z-category surveillance."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_surveillance_indicator, date))


@mcp.tool()
async def equity_series_changes():
    """Recent changes in trading series (EQ → BE, BE → BZ etc.)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_series_change))


@mcp.tool()
async def equity_price_band_changes(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Stocks moved to/from price bands (2%, 5%, 10%, 20%)."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_eq_band_changes, date))


@mcp.tool()
async def equity_price_bands(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Applicable price bands for all stocks on a given EOD."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_eq_price_band, date))


@mcp.tool()
async def equity_price_band_history(
    symbol: Annotated[str | None, "Optional filter. Must be uppercase."] = None,
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] | None = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
):
    """Historical price band changes for a stock or all stocks."""
    await rate_limit()
    kwargs = compact_kwargs(symbol=symbol, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.cm_hist_eq_price_band, **kwargs))


@mcp.tool()
async def equity_pe_ratio(
    date: Annotated[str, "DD-MM-YY (2-digit year). Uses last trading date if None given."],
):
    """PE, PB, Dividend Yield for all listed companies."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_pe_ratio, date))


@mcp.tool()
async def market_cap(
    date: Annotated[str, "DD-MM-YY (2-digit year). Uses last trading date if None given."],
):
    """Market capitalization (Market Cap Rs.) and Total No of Shares Issued of all companies."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_mcap, date))


@mcp.tool()
async def equity_name_changes():
    """Recent corporate name changes."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_eq_name_change))


@mcp.tool()
async def equity_symbol_changes():
    """Recent symbol changes."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_eod_eq_symbol_change))


@mcp.tool()
async def equity_bulk_deals_history(
    symbol: Annotated[str | None, "Optional filter. Must be uppercase."] = None,
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] | None = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
):
    """Bulk deals history – by symbol, date range or period."""
    await rate_limit()
    kwargs = compact_kwargs(symbol=symbol, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.cm_hist_bulk_deals, **kwargs))


@mcp.tool()
async def equity_block_deals_history(
    symbol: Annotated[str | None, "Optional filter. Must be uppercase."] = None,
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] | None = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
):
    """Block deals history – by symbol or date range."""
    await rate_limit()
    kwargs = compact_kwargs(symbol=symbol, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.cm_hist_block_deals, **kwargs))


@mcp.tool()
async def equity_short_selling_history(
    symbol: Annotated[str | None, "Optional filter. Must be uppercase."] = None,
    period: Literal["1D", "1W", "1M", "3M", "6M", "1Y"] | None = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
):
    """Historical short selling disclosures."""
    await rate_limit()
    kwargs = compact_kwargs(symbol=symbol, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.cm_hist_short_selling, **kwargs))


@mcp.tool()
async def equity_market_business_growth(
    mode: Literal["daily", "monthly", "yearly"] = "daily",
    month: Literal[
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"
    ]
    | None = None,
    year: Annotated[int | None, "FY year, e.g. 2025"] = None,
):
    """NSE daily/monthly/yearly business growth (cash segment)."""
    await rate_limit()
    args = compact_args(mode, month, year)
    return df_to_json(await run_sync(get.cm_dmy_biz_growth, *args))


@mcp.tool()
async def equity_market_monthly_settlement(
    period: Literal["1Y", "2M", "3Y"] | None = None,
    from_year: Annotated[int | None, "e.g., 2024"] = None,
    to_year: Annotated[int | None, "e.g., 2026"] = None,
):
    """Fetch NSE Monthly Settlement Statistics (Cash Market) for multiple financial years (Apr–Mar)."""
    await rate_limit()
    kwargs = compact_kwargs(period=period, from_year=from_year, to_year=to_year)
    return df_to_json(await run_sync(get.cm_monthly_settlement_report, **kwargs))


@mcp.tool()
async def monthly_most_active_equity():
    """Most active stocks by volume/value in latest month."""
    await rate_limit()
    return df_to_json(await run_sync(get.cm_monthly_most_active_equity))


@mcp.tool()
async def market_advances_declines(
    mode: Literal["Day_wise", "Month_wise"] = "Month_wise",
    month: Literal[
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"
    ]
    | None = None,
    year: Annotated[int | None, "e.g., 2025"] = None,
):
    """Historical advances vs declines (daily or monthly)."""
    await rate_limit()
    args = compact_args(mode, month, year)
    return df_to_json(await run_sync(get.historical_advances_decline, *args))


# =====================================================================
#                         F&O EOD & HISTORICAL DATA
# =====================================================================


@mcp.tool()
async def fno_bhavcopy(date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."]):
    """Full F&O bhavcopy (futures + options)."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_bhav_copy, date))


@mcp.tool()
async def fno_fii_stats(date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."]):
    """FII activity in F&O segment (Index/Stock, Long/Short)."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_fii_stats, date))


@mcp.tool()
async def fno_eod_top10_futures(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Top 10 most active futures contracts by volume/OI."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_top10_fut, date))


@mcp.tool()
async def fno_eod_top20_options(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Top 20 most active options contracts."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_top20_opt, date))


@mcp.tool()
async def fno_ban_list(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."] = None,
):
    """Stocks under F&O ban period."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_sec_ban, date))


@mcp.tool()
async def fno_mwpl_data(date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."]):
    """Market Wide Position Limits (MWPL) and usage %."""
    await rate_limit()
    df = await run_sync(get.fno_eod_mwpl_3, date)

    df = df.dropna(axis=1, how="all")

    records = []
    for row in df.to_dict(orient="records"):
        meta = {
            k: v
            for k, v in row.items()
            if not k.startswith("Client") and k != "Sr No."  # ← exclude Sr No.
        }
        clients = {k: v for k, v in row.items() if k.startswith("Client") and pd.notna(v)}
        sorted_vals = sorted(clients.values(), reverse=True)
        sorted_clients = {f"Client {i + 1}": v for i, v in enumerate(sorted_vals)}

        records.append({**meta, **sorted_clients})

    return json.dumps(records, ensure_ascii=False)


@mcp.tool()
async def fno_combined_oi(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """Combined futures & options open interest."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_combine_oi, date))


@mcp.tool()
async def fno_participant_wise_oi(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """FII, DII, Pro, Client wise open interest."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_participant_wise_oi, date))


@mcp.tool()
async def fno_participant_wise_volume(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."],
):
    """FII, DII, Pro, Client wise trading volume in F&O."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_participant_wise_vol, date))


@mcp.tool()
async def futures_price_history(
    symbol: Annotated[str, "Symbol e.g., RELIANCE, NIFTY. Must be uppercase."],
    instrument: Literal["Index Futures", "Stock Futures"],
    expiry: Annotated[str | None, "DD-MMM-YYYY format (e.g. 28-OCT-2025)"] = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    period: Literal["1M", "3M", "1Y"] | None = None,
):
    """Historical futures price, volume, OI."""
    await rate_limit()
    kwargs = compact_kwargs(expiry=expiry, period=period, from_date=from_date, to_date=to_date)
    return df_to_json(await run_sync(get.future_price_volume_data, symbol, instrument, **kwargs))


@mcp.tool()
async def options_price_history(
    symbol: Annotated[str, "Symbol e.g., RELIANCE, NIFTY. Must be uppercase."],
    instrument: Literal["Index Options", "Stock Options"],
    strike: Annotated[int | None, "e.g. 47000"] = None,
    option_type: Literal["CE", "PE"] | None = None,
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    expiry: Annotated[str | None, "DD-MMM-YYYY"] = None,
    period: Literal["3M", "1Y"] | None = None,
):
    """Historical options price, volume, OI, IV."""
    await rate_limit()
    kwargs = compact_kwargs(
        strike=strike,
        option_type=option_type,
        period=period,
        from_date=from_date,
        to_date=to_date,
        expiry=expiry,
    )
    return df_to_json(await run_sync(get.option_price_volume_data, symbol, instrument, **kwargs))


@mcp.tool()
async def fno_lot_sizes(symbol: Annotated[str, "Optional filter. Must be uppercase."] = None):
    """Current F&O lot sizes (all or specific symbol)."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eom_lot_size, symbol))


@mcp.tool()
async def fno_business_growth(
    mode: Literal["daily", "monthly", "yearly"] = "daily",
    month: Literal[
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"
    ]
    | None = None,
    year: Annotated[int | None, "FY year, e.g. 2025"] = None,
):
    """F&O segment daily/monthly/yearly turnover growth."""
    await rate_limit()
    args = compact_args(mode, month, year)
    return df_to_json(await run_sync(get.fno_dmy_biz_growth, *args))


@mcp.tool()
async def fno_settlement_report(
    period: Literal["1Y", "2Y3Y"] | None = None,
    from_year: Annotated[int | None, "e.g., 2024"] = None,
    to_year: Annotated[int | None, "e.g., 2026"] = None,
):
    """NSE Monthly Settlement Statistics (F&O) for given financial years or period."""
    await rate_limit()
    kwargs = compact_kwargs(period=period, from_year=from_year, to_year=to_year)
    return df_to_json(await run_sync(get.fno_monthly_settlement_report, **kwargs))


@mcp.tool()
async def fno_top_10_clearing_members(
    date: Annotated[str, "DD-MM-YYYY. Uses last trading date if None given."] = None,
):
    """Volume and Turnover data of top 10 Clearing Members (no. of contracts) in Equity Derivatives."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_top_10_clearing_members, date))


@mcp.tool()
async def fno_client_category_wise_turnover(
    date: Annotated[str, "Date in DD-MM-YYYY format. Uses last trading date if None is given."],
    raw_data: Annotated[bool, "Return raw NSE response if True."] = False,
):
    """Client Category Wise Turnover(Mutual Funds, AIF, PMS, FPI, Retail, Insurance Companies, Others)."""
    await rate_limit()
    return df_to_json(await run_sync(get.fno_eod_client_wise_turnover, date, raw_data=raw_data))


# =====================================================================
#                         SEBI DATA
# =====================================================================


@mcp.tool()
async def sebi_circulars(
    from_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    to_date: Annotated[str | None, "DD-MM-YYYY"] = None,
    period: Literal["1W", "1M", "3M", "1Y"] | None = None,
):
    """Latest or historical SEBI circulars."""
    await rate_limit()
    args = compact_args(from_date, to_date, period)
    return df_to_json(await run_sync(get.sebi_circulars, *args))


@mcp.tool()
async def sebi_data_pages(page: Annotated[int, "Page number"] = 1):
    """Paginated SEBI circulars and orders."""
    await rate_limit()
    return df_to_json(await run_sync(get.sebi_data, page))


@mcp.tool()
async def price_chart_index(
    index: Annotated[str, "e.g., NIFTY 50, SECURITIES IN F&O"] = "NIFTY 50",
    timeframe: Literal["1D", "1M", "3M", "6M", "1Y"] = "1D",
):
    """Retrieves intraday or historical price chart data for the NIFTY Indices."""
    await rate_limit()
    return df_to_json(await run_sync(get.index_chart, index, timeframe))


@mcp.tool()
async def price_chart_stock(
    symbol: Annotated[str, "Symbol e.g., RELIANCE. Must be uppercase."],
    timeframe: Literal["1D", "1W", "1M", "1Y"] = "1D",
):
    """Retrieves intraday or historical price chart data for the stock."""
    await rate_limit()
    return df_to_json(await run_sync(get.stock_chart, symbol, timeframe))


@mcp.tool()
async def fno_intraday_chart(
    symbol: Annotated[str, "Symbol e.g., RELIANCE, NIFTY. Must be uppercase."],
    inst_type: Literal["FUTSTK", "OPTSTK", "FUTIDX", "OPTIDX"],
    expiry: Annotated[str, "DD-MM-YYYY format"],
    strike: Annotated[str | None, "CE/PE + price (options need CE/PE)"] = None,
):
    """Retrieves intraday chart data for the futures/options contracts (Stock + Index).

    Examples:
        get.fno_chart("TCS", "FUTSTK", "24-02-2026")
        get.fno_chart("NIFTY", "OPTIDX", "24-02-2026", "PE25700")
    """
    await rate_limit()
    args = compact_args(symbol, inst_type, expiry, strike)
    return df_to_json(await run_sync(get.fno_chart, *args))


# @mcp.tool()
# async def price_chart_india_vix():
#     """Retrieves intraday chart data for the India VIX Index."""
#     await rate_limit()
#     return df_to_json(await run_sync(get.india_vix_chart))


@mcp.tool()
async def price_chart_india_vix(
    interval: Annotated[
        Literal["sec", "min"],
        "Data granularity: 'sec' for per-second data, 'min' for per-minute data.",
    ] = "min",
):
    """Retrieves intraday chart data for the India VIX Index.
    Use interval='sec' for raw per-second ticks, or interval='min' to
    get one aggregated row per minute (last price/flag in that minute).
    """
    await rate_limit()
    return df_to_json(await run_sync(get.india_vix_chart, interval))


@mcp.tool()
async def symbol_full_fno_live_data(
    symbol: Annotated[str, "e.g., NIFTY, BANKNIFTY, RELIANCE, TCS. Must be uppercase."],
):
    """Fetches complete live FnO data for the specified stock or index."""
    await rate_limit()
    return await run_sync(get.symbol_full_fno_live_data, symbol)


@mcp.tool()
async def symbol_specific_most_active_Calls_or_Puts_or_Contracts_by_OI(
    symbol: Annotated[str, "Symbol e.g., NIFTY, RELIANCE. Must be uppercase."],
    type_mode: Literal["CALLS", "PUTS", "CONTRACTS"],
):
    """Fetches the Top 5 Most Active CALLS, PUTS, or CONTRACTS based on Open Interest."""
    await rate_limit()
    return await run_sync(
        get.symbol_specific_most_active_Calls_or_Puts_or_Contracts_by_OI, symbol, type_mode
    )


@mcp.tool()
async def price_chart_fno_contracts(
    identifier: Annotated[str, 'Examples: "OPTSTKTCS30-12-2025CE3300.00"'],
):
    """Fetches intraday price chart data (timestamp, price, flag)."""
    await rate_limit()
    return await run_sync(get.identifier_based_fno_contracts_live_chart_data, identifier)


@mcp.tool()
async def investors_statewise():
    """Fetches NSE Registered Investors by State."""
    await rate_limit()
    return await run_sync(get.state_wise_registered_investors)


@mcp.tool()
async def quarterly_financial_results(
    symbol: Annotated[str, "The NSE stock symbol (e.g., TCS). Must be uppercase."],
):
    """Quarterly Results (Amount in Lakhs)."""
    await rate_limit()
    return await run_sync(get.quarterly_financial_results, symbol)


@mcp.tool()
async def quarterly_financial_results_full_data(url: Annotated[str, "NSE HTML URL"]):
    """Quarterly Results from URL."""
    await rate_limit()
    return await run_sync(get.html_tables, url)


@mcp.tool()
async def equity_peer_comparison(
    symbol: Annotated[str, "NSE equity symbol, e.g. 'TCS', 'RELIANCE'. Must be uppercase."],
    quarter: Annotated[str, 'Quarter end-month. e.g. "Mar 2026", "Dec 2025", or "2025-09".'],
    report_type: Annotated[
        Literal["Consolidated", "Standalone"], '"Consolidated" (default) or "Standalone".'
    ] = "Consolidated",
):
    """
    Fetch peer-comparison data for a stock from the NSE.
    Returns one row per peer company with columns: Symbol, LTP (₹), % Chng,
    Volume (Lakhs), Value (₹ Cr.), Mkt Cap (₹ Cr.), P/E, Total Income (₹ Cr.),
    Net Profit (₹ Cr.), EPS (₹), Debt/Equity, Promoter %.
    Common quarter-end months: Mar, Jun, Sep, Dec.
    """
    await rate_limit()
    return df_to_json(await run_sync(get.peer_comparison, symbol, quarter, report_type))


# =====================================================================
# MCP PROMPTS  (pure string generators — no I/O, no async needed)
# =====================================================================


@mcp.prompt()
def pre_market_analysis() -> str:
    """Generate NSE pre-market analysis prompt."""
    return (
        "Generate an NSE PRE-MARKET ANALYSIS.\n\n"
        "Steps:\n"
        "1. Check whether today is a trading holiday.\n"
        "2. Analyze Gift Nifty trend and global cues.\n"
        "3. Review pre-open advance and decline data.\n"
        "4. Identify major gap-up and gap-down stocks.\n"
        "5. Summarize NIFTY 50 and BANKNIFTY directional bias.\n\n"
        "Output Format:\n"
        "- Market Status\n"
        "- Gift Nifty / Global Cues\n"
        "- Market Breadth\n"
        "- Key Movers\n"
        "- Intraday Bias\n"
        "- Risk Notes\n\n"
        "Rules:\n"
        "- Use only NseKit-MCP tools\n"
        "- Do not assume prices or direction\n"
    )


@mcp.prompt()
def market_overview() -> str:
    """Get comprehensive market overview."""
    return (
        "Provide a comprehensive NSE market overview:\n\n"
        "1. Current market status and time\n"
        "2. Nifty 50 and Bank Nifty levels\n"
        "3. Market statistics (advances, declines, 52W highs/lows)\n"
        "4. Top gainers and losers\n"
        "5. Most active stocks by value\n"
        "6. FII/DII activity\n"
        "7. India VIX level\n\n"
        "Present in a clean, organized format."
    )


@mcp.prompt()
def analyze_option_chain() -> str:
    """Analyze option chain for given symbol."""
    return (
        "Analyze the option chain for a given stock/index:\n\n"
        "Steps:\n"
        "1. Get the current expiry dates\n"
        "2. Fetch the option chain for current expiry\n"
        "3. Calculate Put-Call Ratio (PCR)\n"
        "4. Identify max pain level\n"
        "5. Find highest OI strikes for calls and puts\n"
        "6. Analyze OI changes\n"
        "7. Provide directional bias\n\n"
        "Symbol will be provided by user (e.g., NIFTY, RELIANCE)\n"
        "Present in a clean, organized format."
    )


@mcp.prompt()
def stock_deep_dive() -> str:
    """Perform deep analysis of a stock."""
    return (
        "Perform comprehensive stock analysis:\n\n"
        "1. Live Quote (price, volume, circuit limits)\n"
        "2. Historical performance (1W, 1M, 3M, 1Y)\n"
        "3. Delivery percentage analysis\n"
        "4. Bulk/Block deals (if any)\n"
        "5. F&O data (if applicable)\n"
        "6. Corporate actions/announcements\n"
        "7. Insider trading activity\n"
        "8. Valuation metrics (PE, PB, Div Yield)\n\n"
        "Stock symbol will be provided by user.\n"
        "Present in a clean, organized format."
    )


@mcp.prompt()
def fno_expiry_analysis() -> str:
    """Analyze F&O positions before expiry."""
    return (
        "Generate F&O EXPIRY DAY analysis:\n\n"
        "1. Check if today is an expiry day\n"
        "2. Get most active options by OI and volume\n"
        "3. Analyze max pain levels for Nifty and BankNifty\n"
        "4. Review F&O ban stocks\n"
        "5. Check participant-wise OI (FII/DII positioning)\n"
        "6. Identify key support and resistance from OI\n"
        "7. Provide expiry day strategy notes\n\n"
        "Focus on: NIFTY, BANKNIFTY, and top F&O stocks\n"
        "Present in a clean, organized format."
    )


@mcp.prompt()
def market_sentiment() -> str:
    """Gauge overall market sentiment."""
    return (
        "Analyze current market sentiment:\n\n"
        "Data to collect:\n"
        "1. Advance/Decline ratio\n"
        "2. India VIX trend\n"
        "3. FII/DII net positions\n"
        "4. Put-Call Ratio for indices\n"
        "5. Stocks hitting circuits\n"
        "6. Volume analysis\n"
        "7. Sector performance\n\n"
        "Provide sentiment as: Bullish/Bearish/Neutral\n"
        "Include confidence level and key factors.\n"
        "Present in a clean, organized format."
    )


@mcp.prompt()
def daily_market_wrap() -> str:
    """Generate end-of-day market summary."""
    return (
        "Generate DAILY MARKET WRAP for NSE:\n\n"
        "1. Closing levels of major indices\n"
        "2. Day's high/low ranges\n"
        "3. Top performers and losers\n"
        "4. Sectoral performance\n"
        "5. Bulk and block deals\n"
        "6. FII/DII net trading\n"
        "7. Notable corporate actions\n"
        "8. F&O highlights (OI changes, rollovers)\n\n"
        "Use today's date for EOD data.\n"
        "Format as a professional market report."
    )


@mcp.prompt()
def intraday_scanner_fno_only() -> str:
    """
    Primary MCP scanner to identify high-probability NSE intraday trade setups
    STRICTLY within F&O stocks using liquidity, volume, institutional activity,
    price structure, derivatives confirmation, and risk control.
    """
    return (
        "You are a professional Indian stock market analyst running an intraday trading desk. "
        "Your task is to identify high-probability intraday trade setups using ONLY F&O stocks "
        "and ONLY NseKit-MCP tools, without assumptions or discretionary bias.\n\n"
        "=============================\n"
        "UNIVERSE DEFINITION (MANDATORY)\n"
        "=============================\n"
        "Use:\n"
        '- index_live_constituents("SECURITIES IN F&O")\n\n'
        "Rule:\n"
        "- From start to end, ALL analysis must be restricted to F&O stocks only.\n"
        "- Non-F&O stocks must be ignored completely.\n\n"
        "=============================\n"
        "PROMPT 1: MARKET REGIME & RISK FILTER\n"
        "=============================\n"
        "Use:\n"
        "- market_live_status\n"
        "- india_vix\n"
        "- gift_nifty_live\n"
        "- market_advances_declines\n\n"
        "Objective:\n"
        "Determine the intraday market regime:\n"
        "1) Trending\n"
        "2) Range-bound\n"
        "3) High-volatility risk-off\n\n"
        "Output:\n"
        "- Market Bias (Bullish / Bearish / Neutral)\n"
        "- Volatility Condition (Low / Normal / High)\n"
        "- Allowed Trading Style (Scalp / Momentum / Avoid)\n\n"
        "Risk Rules:\n"
        "- Rising VIX with skewed advances/declines → reduce position size\n"
        "- Flat GIFT NIFTY with low VIX → prefer range-bound strategies\n\n"
        "=============================\n"
        "PROMPT 2: F&O LIQUIDITY & VOLUME FILTER (PRIMARY)\n"
        "=============================\n"
        "Use:\n"
        "- most_active_equities\n"
        "- equity_volume_surge\n"
        "- market_live_turnover\n\n"
        "Objective:\n"
        "From the F&O universe, identify intraday candidates where:\n"
        "- Stocks appear in most active equities\n"
        "- Volume surge is significantly higher than recent averages\n"
        "- Turnover concentration supports intraday execution\n\n"
        "Output:\n"
        "- Ranked list of F&O stocks based on:\n"
        "  1) Volume Surge\n"
        "  2) Turnover\n"
        "  3) Liquidity Quality\n\n"
        "Fallback Rule:\n"
        "- If no suitable F&O stocks are found using volume and activity filters:\n"
        '  → Select best candidates directly from index_live_constituents("SECURITIES IN F&O")\n'
        "  → Prioritize index heavyweights and consistently liquid names\n\n"
        "=============================\n"
        "PROMPT 3: INSTITUTIONAL FOOTPRINT (CASH MARKET)\n"
        "=============================\n"
        "Use:\n"
        "- equity_block_deals_live\n"
        "- equity_bulk_deals_live\n"
        "- fii_dii_activity\n\n"
        "Objective:\n"
        "Detect institutional participation in selected F&O stocks:\n"
        "- Same-day block or bulk deals\n"
        "- Alignment with overall FII directional activity\n\n"
        "Output:\n"
        "- Institutional Tag:\n"
        "  • Accumulation\n"
        "  • Distribution\n"
        "  • Noise\n\n"
        "Rule:\n"
        "- Avoid retail-only volume spikes without institutional confirmation\n\n"
        "=============================\n"
        "PROMPT 4: PRICE STRUCTURE & INTRADAY LEVELS\n"
        "=============================\n"
        "Use:\n"
        "- equity_live_stock_quote\n"
        "- price_chart_stock\n"
        "- equity_52week_high_live\n"
        "- equity_52week_low_live\n\n"
        "Objective:\n"
        "Evaluate intraday price structure for F&O stocks:\n"
        "- Opening range breakout or breakdown\n"
        "- VWAP hold or rejection\n"
        "- Strength or weakness near day high / day low\n\n"
        "Output:\n"
        "- Trend Bias (Up / Down / Range)\n"
        "- Key Levels (VWAP, Day High, Day Low)\n\n"
        "=============================\n"
        "PROMPT 5: FUTURES STRENGTH CONFIRMATION\n"
        "=============================\n"
        "Use:\n"
        "- fno_live_futures_data\n"
        "- fno_live_change_in_oi\n"
        "- fno_participant_wise_oi\n\n"
        "Objective:\n"
        "Confirm futures market participation:\n"
        "- Price ↑ + OI ↑ → Long buildup\n"
        "- Price ↓ + OI ↑ → Short buildup\n\n"
        "Output:\n"
        "- Directional Conviction Score (0–10)\n\n"
        "=============================\n"
        "PROMPT 6: OPTION CHAIN BIAS (ATM FOCUS)\n"
        "=============================\n"
        "Use:\n"
        "- fno_live_option_chain\n"
        "- fno_live_most_active_contracts_by_oi\n"
        "- symbol_specific_most_active_Calls_or_Puts_or_Contracts_by_OI\n\n"
        "Objective:\n"
        "Assess options market behavior:\n"
        "- ATM Put writing → Bullish bias\n"
        "- ATM Call writing → Bearish bias\n"
        "- Detect long gamma traps via price–OI divergence\n\n"
        "Output:\n"
        "- Option Bias (Bullish / Bearish / Neutral)\n"
        "- Trap Warning (if applicable)\n\n"
        "=============================\n"
        "PROMPT 7: HIGH PROBABILITY TRADE QUALIFIER\n"
        "=============================\n"
        "Input:\n"
        "- Consolidated outputs from Prompts 1–6\n\n"
        "Qualification Conditions:\n"
        "- F&O stock only\n"
        "- Volume expansion confirmed\n"
        "- Institutional alignment present\n"
        "- Price holding above/below VWAP\n"
        "- Futures / options confirmation\n"
        "- Market regime alignment\n\n"
        "Output:\n"
        "- Trade Decision (TRADE / NO TRADE)\n"
        "- Direction (Long / Short)\n"
        "- Confidence Score (%)\n\n"
        "=============================\n"
        "PROMPT 8: EXECUTION & RISK MANAGEMENT\n"
        "=============================\n"
        "Use:\n"
        "- equity_live_stock_quote\n\n"
        "Objective:\n"
        "Create a disciplined intraday execution plan:\n"
        "- Entry trigger based on confirmation\n"
        "- Technical stop-loss\n"
        "- Target with minimum Risk:Reward ≥ 1:1.5\n\n"
        "Output:\n"
        "- Entry Price\n"
        "- Stop-Loss\n"
        "- Target\n"
        "- Position Size Suggestion\n"
        "- Maximum Loss Per Trade\n\n"
        "Strict Rules:\n"
        "- Use ONLY NseKit-MCP tools\n"
        "- Use ONLY F&O stocks throughout\n"
        "- Do NOT assume direction or price\n"
        "- Risk management is mandatory\n"
        "- Capital preservation is priority\n"
    )


# =====================================================================
# START SERVER
# =====================================================================

if __name__ == "__main__":
    # print("🔵 Starting NseKit-MCP Async server...")
    mcp.run(transport="stdio")


# =====================================================================
# pip Install use
# =====================================================================
# def main() -> None:
#     mcp.run()
# =====================================================================
