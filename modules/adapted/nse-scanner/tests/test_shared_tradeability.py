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


import pandas as pd
from v2.tradeability import evaluate_tradeability


def frame(symbol: str, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbol,
            "trade_date": pd.to_datetime(dates),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1000,
        }
    )


MASTER = {"series": "EQ", "active": 1}
JB_EVENT = {
    "event_type": "AMALGAMATION",
    "status": "EFFECTIVE",
    "effective_date": "2026-07-08",
    "last_trading_date": "2026-07-16",
    "successor_symbol": "TORNTPHARM",
    "terminal": "1",
}


def test_terminal_merger_wins_over_staleness_and_missing_master():
    result = evaluate_tradeability(
        "JBCHEPHARM",
        frame("JBCHEPHARM", ["2026-07-16"]),
        market_date="2026-08-25",
        master_row=None,
        lifecycle_event=JB_EVENT,
        session_calendar=("2026-07-16", "2026-08-25"),
    )
    assert not result.eligible
    assert result.reason_code == "TERMINAL_MERGER"
    assert result.successor_symbol == "TORNTPHARM"


def test_historical_replay_keeps_pre_terminal_symbol_valid():
    result = evaluate_tradeability(
        "JBCHEPHARM",
        frame("JBCHEPHARM", ["2026-07-16"]),
        market_date="2026-07-16",
        master_row=MASTER,
        lifecycle_event=JB_EVENT,
        session_calendar=("2026-07-16",),
    )
    assert result.eligible


def test_successor_remains_tradeable():
    result = evaluate_tradeability(
        "TORNTPHARM",
        frame("TORNTPHARM", ["2026-08-25"]),
        market_date="2026-08-25",
        master_row=MASTER,
        session_calendar=("2026-08-25",),
    )
    assert result.eligible


def test_stale_symbol_is_rejected_in_market_sessions():
    result = evaluate_tradeability(
        "STALE",
        frame("STALE", ["2026-08-21"]),
        market_date="2026-08-25",
        master_row=MASTER,
        session_calendar=("2026-08-21", "2026-08-24", "2026-08-25"),
    )
    assert result.reason_code == "STALE_SYMBOL_PRICE"
    assert result.staleness_sessions == 2


def test_missing_master_fails_closed_only_when_master_is_available():
    prices = frame("X", ["2026-08-25"])
    strict = evaluate_tradeability(
        "X", prices, market_date="2026-08-25", master_row=None, session_calendar=("2026-08-25",), require_metadata=True
    )
    bootstrap = evaluate_tradeability(
        "X", prices, market_date="2026-08-25", master_row=None, session_calendar=("2026-08-25",), require_metadata=False
    )
    assert strict.reason_code == "NOT_IN_CURRENT_NSE_UNIVERSE"
    assert bootstrap.eligible


def test_etf_is_rejected_even_when_its_master_series_is_eq():
    result = evaluate_tradeability(
        "NEXT50IETF",
        frame("NEXT50IETF", ["2026-08-25"]),
        market_date="2026-08-25",
        master_row={"series": "EQ", "active": 1, "company_name": "Nifty Next 50 ETF"},
        session_calendar=("2026-08-25",),
    )
    assert not result.eligible
    assert result.reason_code == "ETF_SECURITY"


def test_nse_etf_ticker_conventions_are_rejected_without_name_metadata():
    for symbol in ("PHARMABEES", "HDFCNIFIT", "HDFCPVTBAN", "MOSMALL250", "MOMENTUM50"):
        result = evaluate_tradeability(
            symbol,
            frame(symbol, ["2026-08-25"]),
            market_date="2026-08-25",
            master_row=MASTER,
            session_calendar=("2026-08-25",),
        )
        assert not result.eligible
        assert result.reason_code == "ETF_SECURITY"
