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
Thin wrapper around Kite Connect (Zerodha).

Handles: login flow, instrument-token lookup, historical candles,
positions/holdings, order placement and square-off.

Daily flow:
  1. Run `python kite_client.py login` -> prints login URL.
  2. Open URL, log in, copy `request_token` from the redirect URL.
  3. Run `python kite_client.py token <request_token>` -> saves access token
     to cache/state.db (see state_db.py) -- or use the dashboard's own
     "Login to Kite" button, which does this automatically.
"""


import datetime as dt
import sys
import time
from functools import lru_cache

import pandas as pd
import state_db
from kiteconnect import KiteConnect

import config

# pykiteconnect defaults to a 7-second read timeout -- too tight for real
# usage: a batch call (get_ltp for many symbols, historical candles, order
# placement) occasionally takes longer than that under ordinary Zerodha API
# load, especially near market open/close, and 7s isn't enough margin to
# ride that out. Every KiteConnect(...) construction below passes this
# explicitly rather than relying on the library default -- hit for real as
# frequent "Read timed out. (read timeout=7)" errors and a sluggish Live
# Rebalance page (which makes several sequential Kite calls per load).
KITE_TIMEOUT = 30


def get_kite() -> KiteConnect:
    kite = KiteConnect(api_key=config.KITE_API_KEY, timeout=KITE_TIMEOUT)
    if config.KITE_ACCESS_TOKEN:
        kite.set_access_token(config.KITE_ACCESS_TOKEN)
    return kite


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def login_url() -> str:
    """The official Kite Connect OAuth login URL -- redirects to Zerodha's
    own login + 2FA page, then back to this app's registered redirect URL
    with a one-time request_token. No credentials of any kind touch this
    codebase; the actual login always happens on Zerodha's own page."""
    kite = KiteConnect(api_key=config.KITE_API_KEY, timeout=KITE_TIMEOUT)
    return kite.login_url()


def print_login_url() -> None:
    print("Open this URL, log in, then copy request_token from redirect URL:")
    print(login_url())


def exchange_request_token(request_token: str) -> str:
    kite = KiteConnect(api_key=config.KITE_API_KEY, timeout=KITE_TIMEOUT)
    session = kite.generate_session(request_token, api_secret=config.KITE_API_SECRET)
    token = session["access_token"]
    state_db.save_kite_access_token(token)
    print("Access token saved to cache/state.db (valid until ~6 AM next day).")
    return token


# ---------------------------------------------------------------------------
# Instruments & historical data
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def instrument_map() -> dict:
    """symbol -> instrument_token for NSE equities."""
    kite = get_kite()
    instruments = kite.instruments("NSE")
    return {
        row["tradingsymbol"]: row["instrument_token"]
        for row in instruments
        if row["segment"] == "NSE" and row["instrument_type"] == "EQ"
    }


@lru_cache(maxsize=1)
def get_cash_instruments() -> list[str]:
    """NSE-listed liquid-fund ETFs suitable for parking idle cash -- every
    tradable equity symbol containing "LIQUID" (LIQUIDBEES, LIQUIDCASE,
    HDFCLIQUID, ABSLLIQUID, etc.), sorted. Feeds the Ledger page's
    cash-sweep instrument dropdown (see live_rebalance.sweep_idle_cash())
    -- fetched live rather than hardcoded so a new fund listing or a
    delisting is picked up automatically. Cached for the process
    lifetime, same pattern as tick_size_map() -- this list changes on
    the order of months, not within a session."""
    im = instrument_map()
    return sorted(s for s in im if "LIQUID" in s.upper())


@lru_cache(maxsize=1)
def tick_size_map() -> dict:
    """symbol -> tick_size (Rs) for NSE equities. Kite rejects any LIMIT
    price that isn't an exact multiple of a stock's own tick size, which
    is NOT a flat value across the exchange -- commonly 0.05, but 0.10/
    0.50/1.00 for others. Needed by place_order()'s market-protection
    LIMIT retry below, which used to round to a flat 1 decimal place and
    silently failed live on any stock whose real tick size was coarser
    than that (confirmed 2026-08-04: DIVISLAB/ABB at 0.50 tick and OFSS/
    BAJAJ-AUTO at 1.00 tick all rejected with "Tick size for this script
    is 0.50/1.00" -- RADICO/BAJFINANCE only happened to work because a
    flat 1-decimal rounding coincidentally satisfied their tick size)."""
    kite = get_kite()
    instruments = kite.instruments("NSE")
    return {
        row["tradingsymbol"]: row["tick_size"]
        for row in instruments
        if row["segment"] == "NSE" and row["instrument_type"] == "EQ"
    }


def _round_to_tick(symbol: str, price: float) -> float:
    """Rounds `price` to the nearest valid multiple of this symbol's own
    tick size -- shared by every place/modify order or GTT call below
    that used to round to a flat 1 decimal place and got rejected
    outright on any stock with a coarser tick size (0.50/1.00)."""
    tick = tick_size_map().get(symbol, 0.05)
    return round(round(price / tick) * tick, 2)


@lru_cache(maxsize=1)
def index_instrument_map() -> dict:
    """tradingsymbol -> instrument_token for NSE indices (NIFTY 50, sector
    indices like NIFTY AUTO/NIFTY BANK/NIFTY ENERGY, etc.) -- these are a
    different segment ('INDICES') and so are invisible to instrument_map()
    above, which explicitly filters to tradeable equities only."""
    kite = get_kite()
    instruments = kite.instruments("NSE")
    return {
        row["tradingsymbol"]: row["instrument_token"]
        for row in instruments
        if row["segment"] == "INDICES"
    }


_MAX_DAY_INTERVAL_SPAN = 2000  # Kite's historical API hard limit for "day" candles


def _fetch_chunked(token: int, days: int) -> pd.DataFrame:
    """Daily OHLCV for `token` covering the last `days` calendar days.

    Kite's historical API rejects a single "day"-interval request spanning
    more than ~2000 days ("interval exceeds max limit: 2000 days") -- deep
    backtests (5y history + lookback buffer) exceed that, so requests longer
    than the limit are split into sequential chunks and concatenated. Shared
    by every candle fetcher below (stocks, NIFTY 50, sector indices) --
    previously duplicated verbatim between fetch_daily_candles and
    benchmark_candles, which became worth fixing once sector indices became
    a third consumer of the same chunking logic.
    """
    kite = get_kite()
    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=days)

    if days <= _MAX_DAY_INTERVAL_SPAN:
        candles = kite.historical_data(token, from_date, to_date, "day")
    else:
        candles = []
        chunk_start = from_date
        while chunk_start < to_date:
            chunk_end = min(chunk_start + dt.timedelta(days=_MAX_DAY_INTERVAL_SPAN), to_date)
            candles += kite.historical_data(token, chunk_start, chunk_end, "day")
            chunk_start = chunk_end + dt.timedelta(days=1)
            if chunk_start < to_date:
                time.sleep(0.35)  # stay under the historical API rate limit

    df = pd.DataFrame(candles)
    if df.empty:
        return df
    # Kite's raw response is tz-aware (IST) -- stripped here so this
    # matches _fetch_chunked_intraday()'s own tz_localize(None) below and
    # every caller gets naive timestamps without having to remember to
    # normalize themselves (backtest.py's own _tz_naive() wrapping every
    # call site was a workaround for this NOT being done here; confirmed
    # 2026-09-15 as a real bug when intraday_engine.py's first live run
    # called fetch_daily_candles() directly and hit "Invalid comparison
    # between dtype=datetime64[us, tzoffset...] and Timestamp" comparing
    # this tz-aware index against a naive pd.Timestamp).
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.drop_duplicates(subset="date").sort_values("date")
    return df.set_index("date")


def fetch_daily_candles(symbol: str, days: int = 400) -> pd.DataFrame:
    """Daily OHLCV for `symbol` covering the last `days` calendar days."""
    token = instrument_map().get(symbol)
    if token is None:
        raise ValueError(f"Unknown NSE symbol: {symbol}")
    return _fetch_chunked(token, days)


# Kite's historical API max span per intraday interval -- confirmed
# empirically (2026-09-13, real account): a 101-day 5minute request
# fails with "interval exceeds max limit: 100 days"; a 100-day request
# succeeds. Only 5minute is used by the intraday strategy today; the
# other intervals are Kite's own documented limits, included so this
# dict is a complete reference if another interval is ever needed --
# re-verify empirically before relying on any of the un-exercised ones.
_MAX_INTRADAY_INTERVAL_SPAN = {
    "minute": 60,
    "3minute": 100,
    "5minute": 100,
    "10minute": 100,
    "15minute": 200,
    "30minute": 200,
    "60minute": 400,
}


def _fetch_chunked_intraday_range(
    token: int, from_date: dt.date, to_date: dt.date, interval: str
) -> pd.DataFrame:
    """Same chunking idea as _fetch_chunked(), for an intraday interval
    whose max span is far smaller than "day"'s 2000 -- the intraday
    strategy's continuous EMA21/ATR14 warmup (Spec.md §1: "a minimum of
    several weeks... before these indicators are trustworthy") routinely
    needs more history than one request covers. Unlike _fetch_chunked_
    intraday() below, `to_date` is an explicit caller-supplied date, not
    always `dt.date.today()` -- this is what makes a historical (not
    just "last N days from now") intraday backtest possible at all."""
    max_span = _MAX_INTRADAY_INTERVAL_SPAN.get(interval, 100)
    kite = get_kite()

    if (to_date - from_date).days <= max_span:
        candles = kite.historical_data(token, from_date, to_date, interval)
    else:
        candles = []
        chunk_start = from_date
        while chunk_start < to_date:
            chunk_end = min(chunk_start + dt.timedelta(days=max_span), to_date)
            candles += kite.historical_data(token, chunk_start, chunk_end, interval)
            chunk_start = chunk_end + dt.timedelta(days=1)
            if chunk_start < to_date:
                time.sleep(0.35)  # stay under the historical API rate limit

    df = pd.DataFrame(candles)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.drop_duplicates(subset="date").sort_values("date")
    return df.set_index("date")


def _fetch_chunked_intraday(token: int, days: int, interval: str) -> pd.DataFrame:
    """`days` calendar days ending today -- see _fetch_chunked_intraday_range()."""
    to_date = dt.date.today()
    from_date = to_date - dt.timedelta(days=days)
    return _fetch_chunked_intraday_range(token, from_date, to_date, interval)


def fetch_intraday_candles(symbol: str, days: int = 120, interval: str = "5minute") -> pd.DataFrame:
    """Intraday OHLCV for `symbol` covering the last `days` calendar
    days -- used by the intraday strategy's continuous EMA21/ATR14
    (computed once over this whole series, never re-cold-started per
    day, per Spec.md §1)."""
    token = instrument_map().get(symbol)
    if token is None:
        raise ValueError(f"Unknown NSE symbol: {symbol}")
    return _fetch_chunked_intraday(token, days, interval)


def fetch_intraday_candles_range(
    symbol: str, from_date: dt.date, to_date: dt.date, interval: str = "5minute"
) -> pd.DataFrame:
    """Intraday OHLCV for `symbol` over an explicit [from_date, to_date]
    historical window, chunked the same way as fetch_intraday_candles()
    but not anchored to "today" -- used by intraday_backtest.py to
    replay a past date range rather than only ever watching the last
    `days` calendar days up to now."""
    token = instrument_map().get(symbol)
    if token is None:
        raise ValueError(f"Unknown NSE symbol: {symbol}")
    return _fetch_chunked_intraday_range(token, from_date, to_date, interval)


def fetch_universe_candles(
    symbols: list[str], days: int = 400, pause: float = 0.35
) -> dict[str, pd.DataFrame]:
    """Fetch candles for many symbols, respecting Kite's ~3 req/s historical
    API rate limit."""
    out = {}
    for sym in symbols:
        try:
            out[sym] = fetch_daily_candles(sym, days)
        except Exception as e:  # keep going; surface errors in the dashboard
            out[sym] = pd.DataFrame()
            print(f"[warn] {sym}: {e}")
        time.sleep(pause)
    return out


def fetch_index_candles(tradingsymbol: str, days: int = 400) -> pd.DataFrame:
    """Daily OHLCV for an NSE index (NIFTY 50, or a sector index like
    NIFTY AUTO/NIFTY BANK/NIFTY ENERGY) covering the last `days` calendar
    days. Used for relative-strength calculations -- both the NIFTY 50
    benchmark and sector-strength ranking need real historical index
    levels, not just today's snapshot."""
    token = index_instrument_map().get(tradingsymbol)
    if token is None:
        raise ValueError(f"Unknown NSE index: {tradingsymbol}")
    return _fetch_chunked(token, days)


def benchmark_candles(days: int = 400) -> pd.DataFrame:
    """NIFTY 50 index candles for relative-strength calculations."""
    return fetch_index_candles("NIFTY 50", days)


# ---------------------------------------------------------------------------
# Portfolio state
# ---------------------------------------------------------------------------


def get_positions() -> pd.DataFrame:
    kite = get_kite()
    pos = kite.positions().get("net", [])
    return pd.DataFrame(pos)


def get_holdings() -> pd.DataFrame:
    """Holdings (CNC), quantity normalized to what you actually own.

    Kite reports a just-bought lot that hasn't yet settled into demat under
    `t1_quantity` instead of `quantity` -- also seen transiently for
    already-settled holdings in the early-morning window before the day's
    settlement file is processed. Either way, `quantity` alone silently
    undercounts (0 for a real position) until settlement catches up, so it's
    folded into `quantity` here once, at the source, rather than every
    consumer needing to know about this Kite-internal settlement split."""
    kite = get_kite()
    df = pd.DataFrame(kite.holdings())
    if not df.empty and "t1_quantity" in df.columns:
        df["quantity"] = df["quantity"] + df["t1_quantity"]
    return df


def get_margins() -> dict:
    kite = get_kite()
    return kite.margins()


def get_ltp(symbols: list[str]) -> dict[str, float]:
    kite = get_kite()
    keys = [f"NSE:{s}" for s in symbols]
    data = kite.ltp(keys)
    return {k.split(":")[1]: v["last_price"] for k, v in data.items()}


def get_quote_with_change(symbols: list[str]) -> dict[str, dict]:
    """symbol -> {"last_price", "prev_close", "change_pct"} -- prev_close
    is Kite's own ohlc.close (previous trading day's close), the same
    convention Kite's own app uses for day-change%. Heavier than
    get_ltp() (kite.quote()'s full payload vs LTP-only), so only used
    where a day-change % is actually shown, not every plain price."""
    kite = get_kite()
    keys = [f"NSE:{s}" for s in symbols]
    data = kite.quote(keys)
    out = {}
    for k, v in data.items():
        sym = k.split(":")[1]
        last_price = v["last_price"]
        prev_close = (v.get("ohlc") or {}).get("close")
        change_pct = ((last_price - prev_close) / prev_close * 100) if prev_close else None
        out[sym] = {"last_price": last_price, "prev_close": prev_close, "change_pct": change_pct}
    return out


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------


def place_order(
    symbol: str,
    qty: int,
    side: str,
    product: str = "CNC",
    order_type: str = "MARKET",
    price: float | None = None,
    trigger_price: float | None = None,
) -> str:
    """Place an NSE equity order. Returns order_id.

    side: "BUY" | "SELL"
    product: "CNC" (delivery, right for 3-6 month holds) or "MIS" (intraday)
    trigger_price: required for order_type "SL" (stop-loss limit -- needs
    both trigger_price and price) or "SL-M" (stop-loss market -- trigger_
    price only) -- the intraday strategy's exchange-side conditional
    entry/exit orders (Spec.md §6.3) use these, CNC orders elsewhere in
    this app don't.

    Some stocks reject a plain MARKET order via the API outright (e.g.
    under a periodic call auction or specific surveillance measures) with
    "Market orders without market protection are not allowed via API" --
    a real failure hit live on ADANIENSOL. Zerodha's own fix is exactly
    what the error says: use a LIMIT order instead. Rather than let the
    whole buy/sell fail, retry ONCE as a marketable limit (0.5% past LTP
    -- buy up, sell down) tight enough to fill immediately in practice for
    an F&O-liquid name, but bounded so a fast-moving price can't blow
    through it the way an unprotected market fill could.
    """
    kite = get_kite()
    kwargs = {
        "variety": kite.VARIETY_REGULAR,
        "exchange": kite.EXCHANGE_NSE,
        "tradingsymbol": symbol,
        "transaction_type": side,
        "quantity": int(qty),
        "product": product,
        "order_type": order_type,
    }
    if order_type in ("LIMIT", "SL") and price:
        kwargs["price"] = price
    if order_type in ("SL", "SL-M") and trigger_price:
        kwargs["trigger_price"] = trigger_price
    try:
        return kite.place_order(**kwargs)
    except Exception as e:
        if order_type == "MARKET" and "market protection" in str(e).lower():
            ltp = get_ltp([symbol])[symbol]
            buffer = 1.005 if side == "BUY" else 0.995
            kwargs["order_type"] = "LIMIT"
            kwargs["price"] = _round_to_tick(symbol, ltp * buffer)
            return kite.place_order(**kwargs)
        raise


def place_gtt_stoploss(symbol: str, qty: int, trigger_price: float, last_price: float) -> int:
    """Place a GTT stop-loss (good for delivery positions held weeks/months —
    a plain SL order expires end of day, GTT persists)."""
    kite = get_kite()
    trigger = _round_to_tick(symbol, trigger_price)
    return kite.place_gtt(
        trigger_type=kite.GTT_TYPE_SINGLE,
        tradingsymbol=symbol,
        exchange=kite.EXCHANGE_NSE,
        trigger_values=[trigger],
        last_price=last_price,
        orders=[
            {
                "transaction_type": kite.TRANSACTION_TYPE_SELL,
                "quantity": int(qty),
                "product": kite.PRODUCT_CNC,
                "order_type": kite.ORDER_TYPE_LIMIT,
                "price": _round_to_tick(symbol, trigger_price * 0.995),
            }
        ],
    )["trigger_id"]


def get_active_gtts() -> pd.DataFrame:
    """Kite's own live GTT list -- source of truth for "does this holding
    actually have a stop-loss right now," not just our local state file
    (see live_rebalance.py's position-state tracking)."""
    kite = get_kite()
    return pd.DataFrame(kite.get_gtts())


def modify_gtt_trigger(
    trigger_id: int, symbol: str, qty: int, new_trigger_price: float, last_price: float
) -> int:
    """Raise an existing GTT's trigger price -- mirrors place_gtt_stoploss's
    order shape exactly, just targeting an existing trigger_id instead of
    creating a new one."""
    kite = get_kite()
    trigger = _round_to_tick(symbol, new_trigger_price)
    return kite.modify_gtt(
        trigger_id=trigger_id,
        trigger_type=kite.GTT_TYPE_SINGLE,
        tradingsymbol=symbol,
        exchange=kite.EXCHANGE_NSE,
        trigger_values=[trigger],
        last_price=last_price,
        orders=[
            {
                "transaction_type": kite.TRANSACTION_TYPE_SELL,
                "quantity": int(qty),
                "product": kite.PRODUCT_CNC,
                "order_type": kite.ORDER_TYPE_LIMIT,
                "price": _round_to_tick(symbol, new_trigger_price * 0.995),
            }
        ],
    )["trigger_id"]


def delete_gtt(trigger_id: int) -> None:
    """Cancels a GTT -- used after a manual/automatic market exit (e.g. the
    morning gap-down safety check) to remove the now-stale stop-loss trigger
    rather than leaving it pointing at a position that no longer exists."""
    kite = get_kite()
    kite.delete_gtt(trigger_id)


def square_off_position(symbol: str) -> str | None:
    """Close the net position in `symbol` at market. Handles both
    positions (MIS/NRML) and CNC holdings.

    A CNC (delivery) row showing a NEGATIVE net quantity is NOT a real
    short -- Zerodha doesn't allow naked CNC shorting for retail, so this
    is always the same-day-sell settlement-lag artifact (a same-day sell
    of an existing holding leaves a negative "day" position that nets to
    0 against the holding overnight -- see get_live_holdings()'s docstring
    in live_rebalance.py for the same quirk documented elsewhere). The old
    unconditional "negative -> BUY" logic treated that as a short to
    cover and placed a BUY -- confirmed live 2026-09-09: check_gap_down_
    stops() called this right after COFORGE's own GTT had already sold it
    moments earlier at market open (a real race -- the GTT can trigger on
    a gap before this scheduled check even runs), and it bought the
    position straight back, silently undoing the GTT's protective exit.
    Only a genuine intraday product (MIS/NRML) can have a real short here
    -- for CNC, skip a negative row and fall through to the holdings
    check below, which correctly returns None (nothing left to sell) once
    the position is genuinely already flat."""
    kite = get_kite()

    for p in kite.positions().get("net", []):
        if p["tradingsymbol"] != symbol or p["quantity"] == 0:
            continue
        if p["quantity"] < 0 and p["product"] == "CNC":
            continue  # phantom same-day-sell artifact, not a real short
        side = "SELL" if p["quantity"] > 0 else "BUY"
        return place_order(symbol, abs(p["quantity"]), side, product=p["product"])

    for h in kite.holdings():
        qty = h["quantity"] + h.get("t1_quantity", 0)
        if h["tradingsymbol"] == symbol and qty > 0:
            return place_order(symbol, qty, "SELL", product="CNC")

    return None


def get_orders() -> pd.DataFrame:
    kite = get_kite()
    return pd.DataFrame(kite.orders())


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "login":
        print_login_url()
    elif len(sys.argv) > 2 and sys.argv[1] == "token":
        exchange_request_token(sys.argv[2])
    else:
        print("Usage: python kite_client.py login | token <request_token>")
