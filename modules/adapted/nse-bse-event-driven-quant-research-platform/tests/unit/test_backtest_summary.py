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


"""Backtest result summarization regression tests."""

import pandas as pd
from indian_quant.nautilus.adapters.backtest import (
    BacktestResult,
    _money_to_float,
    summarize_result,
)


def test_money_to_float_parses_nautilus_money_strings():
    assert _money_to_float("3599.00 INR") == 3599.0
    assert _money_to_float("-1460.00 INR") == -1460.0
    assert _money_to_float("1,234.50 INR") == 1234.5


def test_summarize_sums_realized_pnl_from_money_strings():
    positions = pd.DataFrame({"realized_pnl": ["100.00 INR", "-40.00 INR"]})
    result = BacktestResult(
        run_id="r",
        instrument_id="TESTCO.NSE",
        n_fills=4,
        fills=pd.DataFrame(),
        positions=positions,
        account=pd.DataFrame({"total": ["999999.00 INR"]}),
    )
    metrics = summarize_result(result)
    assert metrics["gross_pnl"] == 60.0
    assert metrics["net_pnl"] == 60.0
    assert metrics["final_total"] == 999999.0
    assert metrics["n_closed_positions"] == 2


def test_summarize_reports_commissions_and_net():
    fills = pd.DataFrame({"commissions": ["[10.00 INR]", "[5.00 INR]"]})
    positions = pd.DataFrame({"realized_pnl": ["100.00 INR"]})
    result = BacktestResult(
        run_id="r",
        instrument_id="TESTCO.NSE",
        n_fills=2,
        fills=fills,
        positions=positions,
        account=pd.DataFrame({"total": ["85.00 INR"]}),
    )
    metrics = summarize_result(result)
    assert metrics["total_commissions"] == 15.0
    assert metrics["net_pnl"] == 100.0
    assert metrics["gross_pnl"] == 115.0
