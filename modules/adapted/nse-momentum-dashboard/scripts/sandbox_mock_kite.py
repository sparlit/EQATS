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


"""Generates deterministic synthetic market data and monkeypatches every
kite_client function so the dashboard can run its REAL business logic
(screener.py, live_rebalance.py, backtest.py, state_db writes) against
fake prices instead of the real broker -- no network call to Kite ever
happens, and no real order is ever placed, while every code path that
consumes kite_client's output still runs for real.

Import and call patch_kite_client() BEFORE importing config/dashboard.
"""

import datetime as dt

import numpy as np
import pandas as pd

MOCK_CALLS: list[dict] = []  # every place_order/GTT/square-off call, for the test report

_REGIMES = ["strong_up", "mild_up", "flat", "down", "choppy"]
_candle_cache: dict[str, pd.DataFrame] = {}

N_DAYS = 1900  # ~5.2 years of trading days -- enough for a 5y backtest + warmup


def _generate_candles(symbol: str) -> pd.DataFrame:
    if symbol in _candle_cache:
        return _candle_cache[symbol]

    seed = abs(hash(symbol)) % (2**32)
    rng = np.random.RandomState(seed)
    regime = _REGIMES[seed % len(_REGIMES)]
    drift = {
        "strong_up": 0.00075,
        "mild_up": 0.0003,
        "flat": 0.0,
        "down": -0.0004,
        "choppy": 0.0001,
    }[regime]
    vol = {"strong_up": 0.018, "mild_up": 0.015, "flat": 0.012, "down": 0.02, "choppy": 0.028}[
        regime
    ]

    start_price = rng.uniform(50, 3500)
    log_returns = rng.normal(drift, vol, N_DAYS)
    close = start_price * np.exp(np.cumsum(log_returns))
    # daily O/H/L around each day's close with a small intraday range
    intraday = rng.uniform(0.004, 0.022, N_DAYS)
    high = close * (1 + intraday * rng.uniform(0.3, 1.0, N_DAYS))
    low = close * (1 - intraday * rng.uniform(0.3, 1.0, N_DAYS))
    open_ = low + (high - low) * rng.uniform(0.2, 0.8, N_DAYS)
    volume = rng.lognormal(mean=12.5, sigma=0.6, size=N_DAYS).astype(int)

    end = dt.date.today()
    dates = pd.bdate_range(end=end, periods=N_DAYS)

    df = pd.DataFrame(
        {
            "date": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    ).set_index("date")
    _candle_cache[symbol] = df
    return df


def fake_fetch_daily_candles(symbol: str, days: int = 400) -> pd.DataFrame:
    df = _generate_candles(symbol)
    return df.tail(days).copy()


def fake_fetch_universe_candles(
    symbols: list[str], days: int = 400, pause: float = 0.0
) -> dict[str, pd.DataFrame]:
    return {s: fake_fetch_daily_candles(s, days) for s in symbols}


def fake_fetch_index_candles(tradingsymbol: str, days: int = 400) -> pd.DataFrame:
    return fake_fetch_daily_candles(f"__INDEX__{tradingsymbol}", days)


def fake_benchmark_candles(days: int = 400) -> pd.DataFrame:
    return fake_fetch_index_candles("NIFTY 50", days)


def fake_get_ltp(symbols: list[str]) -> dict[str, float]:
    out = {}
    for s in symbols:
        df = _generate_candles(s)
        out[s] = float(df["close"].iloc[-1])
    return out


def fake_get_quote_with_change(symbols: list[str]) -> dict[str, dict]:
    out = {}
    for s in symbols:
        df = _generate_candles(s)
        last_price = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
        out[s] = {
            "last_price": last_price,
            "prev_close": prev_close,
            "change_pct": (last_price - prev_close) / prev_close * 100,
        }
    return out


def fake_instrument_map() -> dict:
    import config

    return {s: i + 1 for i, s in enumerate(config.UNIVERSE_RAW or [])}


def fake_index_instrument_map() -> dict:
    return {"NIFTY 50": 999901, "NIFTY BANK": 999902}


# ---------------------------------------------------------------------------
# Portfolio state -- a handful of held symbols, picked once the universe is
# known (patch_kite_client() fills this in after config.UNIVERSE loads).
# ---------------------------------------------------------------------------
_HOLDINGS_STATE: dict[str, dict] = {}


def seed_holdings(symbols: list[str]) -> None:
    """Call once, after config.UNIVERSE is available, to pick which fake
    symbols this sandbox account "holds" -- entry prices are set below
    each symbol's CURRENT fake LTP so P&L shows a believable mix of green
    and red rather than everything flat at zero."""
    rng = np.random.RandomState(42)
    for sym in symbols:
        ltp = fake_get_ltp([sym])[sym]
        entry_mult = rng.uniform(0.85, 1.15)
        qty = int(rng.choice([5, 7, 10, 13, 20]))
        _HOLDINGS_STATE[sym] = {
            "quantity": qty,
            "t1_quantity": 0,
            "average_price": round(ltp * entry_mult, 2),
            "product": "CNC",
            "exchange": "NSE",
        }


def fake_get_holdings() -> pd.DataFrame:
    rows = []
    for sym, h in _HOLDINGS_STATE.items():
        ltp = fake_get_ltp([sym])[sym]
        qty = h["quantity"] + h["t1_quantity"]
        pnl = (ltp - h["average_price"]) * qty
        rows.append(
            {
                "tradingsymbol": sym,
                "quantity": h["quantity"],
                "t1_quantity": h["t1_quantity"],
                "average_price": h["average_price"],
                "last_price": ltp,
                "pnl": pnl,
                "product": h["product"],
                "exchange": h["exchange"],
                "close_price": ltp,
            }
        )
    return pd.DataFrame(rows)


def fake_get_positions() -> pd.DataFrame:
    # No intraday/BTST activity in this sandbox account -- pure CNC swing
    # positions only show up via get_holdings(), matching a realistic
    # calendar-entry momentum account with no same-day trading.
    return pd.DataFrame(
        columns=[
            "tradingsymbol",
            "quantity",
            "average_price",
            "last_price",
            "pnl",
            "product",
            "exchange",
        ]
    )


def fake_get_margins() -> dict:
    return {
        "equity": {
            "available": {
                "live_balance": 250000.0,
                "cash": 250000.0,
                "opening_balance": 250000.0,
                "collateral": 0.0,
                "intraday_payin": 0.0,
            },
            "utilised": {
                "debits": 0.0,
                "exposure": 0.0,
                "span": 0.0,
                "option_premium": 0.0,
                "holding_sales": 0.0,
                "turnover": 0.0,
                "liquid_collateral": 0.0,
                "stock_collateral": 0.0,
            },
            "net": 250000.0,
        }
    }


_ORDERS: list[dict] = []
_GTTS: dict[str, dict] = {}  # symbol -> {"id": int, "trigger_price": float}
_next_order_id = [700000000]
_next_gtt_id = [80000]


def fake_place_order(
    symbol: str,
    qty: int,
    side: str,
    product: str = "CNC",
    order_type: str = "MARKET",
    price: float | None = None,
) -> str:
    _next_order_id[0] += 1
    order_id = str(_next_order_id[0])
    ltp = fake_get_ltp([symbol])[symbol]
    fill_price = price if (order_type == "LIMIT" and price) else ltp
    _ORDERS.append(
        {
            "order_id": order_id,
            "tradingsymbol": symbol,
            "transaction_type": side,
            "quantity": qty,
            "price": fill_price,
            "average_price": fill_price,
            "status": "COMPLETE",
            "order_timestamp": dt.datetime.now(),
            "product": product,
            "exchange": "NSE",
        }
    )
    # keep the fake holdings book consistent so subsequent pages reflect
    # this order immediately, same as a real fill would.
    if side == "BUY":
        existing = _HOLDINGS_STATE.get(symbol)
        if existing:
            total_qty = existing["quantity"] + qty
            existing["average_price"] = (
                existing["average_price"] * existing["quantity"] + fill_price * qty
            ) / total_qty
            existing["quantity"] = total_qty
        else:
            _HOLDINGS_STATE[symbol] = {
                "quantity": qty,
                "t1_quantity": 0,
                "average_price": fill_price,
                "product": product,
                "exchange": "NSE",
            }
    else:
        existing = _HOLDINGS_STATE.get(symbol)
        if existing:
            existing["quantity"] = max(0, existing["quantity"] - qty)
            if existing["quantity"] == 0:
                del _HOLDINGS_STATE[symbol]
    MOCK_CALLS.append(
        {
            "fn": "place_order",
            "symbol": symbol,
            "qty": qty,
            "side": side,
            "product": product,
            "order_type": order_type,
            "price": fill_price,
            "order_id": order_id,
        }
    )
    return order_id


def fake_place_gtt_stoploss(symbol: str, qty: int, trigger_price: float, last_price: float) -> int:
    _next_gtt_id[0] += 1
    gtt_id = _next_gtt_id[0]
    _GTTS[symbol] = {"id": gtt_id, "trigger_price": trigger_price, "qty": qty}
    MOCK_CALLS.append(
        {
            "fn": "place_gtt_stoploss",
            "symbol": symbol,
            "qty": qty,
            "trigger_price": trigger_price,
            "gtt_id": gtt_id,
        }
    )
    return gtt_id


def fake_get_active_gtts() -> pd.DataFrame:
    rows = []
    for sym, g in _GTTS.items():
        rows.append(
            {
                "id": g["id"],
                "status": "active",
                "updated_at": dt.datetime.now().isoformat(),
                "condition": {
                    "exchange": "NSE",
                    "tradingsymbol": sym,
                    "trigger_values": [g["trigger_price"]],
                    "last_price": fake_get_ltp([sym])[sym],
                },
                "orders": [
                    {
                        "transaction_type": "SELL",
                        "quantity": g["qty"],
                        "product": "CNC",
                        "order_type": "LIMIT",
                        "price": round(g["trigger_price"] * 0.995, 1),
                    }
                ],
            }
        )
    return pd.DataFrame(rows)


def fake_modify_gtt_trigger(
    trigger_id: int, symbol: str, qty: int, new_trigger_price: float, last_price: float
) -> int:
    _GTTS[symbol] = {"id": trigger_id, "trigger_price": new_trigger_price, "qty": qty}
    MOCK_CALLS.append(
        {
            "fn": "modify_gtt_trigger",
            "symbol": symbol,
            "trigger_id": trigger_id,
            "new_trigger_price": new_trigger_price,
        }
    )
    return trigger_id


def fake_delete_gtt(trigger_id: int) -> None:
    for sym, g in list(_GTTS.items()):
        if g["id"] == trigger_id:
            del _GTTS[sym]
    MOCK_CALLS.append({"fn": "delete_gtt", "trigger_id": trigger_id})


def fake_square_off_position(symbol: str) -> str | None:
    h = _HOLDINGS_STATE.get(symbol)
    if not h or h["quantity"] <= 0:
        return None
    qty = h["quantity"]
    order_id = fake_place_order(symbol, qty, "SELL", product="CNC")
    MOCK_CALLS.append(
        {"fn": "square_off_position", "symbol": symbol, "qty": qty, "order_id": order_id}
    )
    return order_id


def fake_get_orders() -> pd.DataFrame:
    return pd.DataFrame(_ORDERS)


def patch_kite_client() -> None:
    import kite_client

    kite_client.fetch_daily_candles = fake_fetch_daily_candles
    kite_client.fetch_universe_candles = fake_fetch_universe_candles
    kite_client.fetch_index_candles = fake_fetch_index_candles
    kite_client.benchmark_candles = fake_benchmark_candles
    kite_client.get_ltp = fake_get_ltp
    kite_client.get_quote_with_change = fake_get_quote_with_change
    kite_client.instrument_map = fake_instrument_map
    kite_client.index_instrument_map = fake_index_instrument_map
    kite_client.get_holdings = fake_get_holdings
    kite_client.get_positions = fake_get_positions
    kite_client.get_margins = fake_get_margins
    kite_client.place_order = fake_place_order
    kite_client.place_gtt_stoploss = fake_place_gtt_stoploss
    kite_client.get_active_gtts = fake_get_active_gtts
    kite_client.modify_gtt_trigger = fake_modify_gtt_trigger
    kite_client.delete_gtt = fake_delete_gtt
    kite_client.square_off_position = fake_square_off_position
    kite_client.get_orders = fake_get_orders
    print("[sandbox] kite_client fully mocked -- zero real API calls will be made")
