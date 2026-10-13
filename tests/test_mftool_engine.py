"""
Unit tests for mftool_engine.py (nayakwadis/mftool adaptation).
Checks NAV analytics, scheme search, asset allocation, 0.05 INR tick rounding,
IST session validation, and SEBIBrokerAdapter compliance.
"""

from datetime import datetime, timezone
import zoneinfo

from institutional_integrations.mftool_engine import (
    MAGIC_NUMBER_MFTOOL,
    MFToolAdapter,
    MFToolEngine,
    round_tick_005,
    validate_ist_market_session,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_mftool_round_tick_005() -> None:
    assert round_tick_005(125.42) == 125.40
    assert round_tick_005(125.43) == 125.45
    assert round_tick_005(125.47) == 125.45
    assert round_tick_005(125.48) == 125.50


def test_mftool_validate_ist_market_session() -> None:
    ist = zoneinfo.ZoneInfo("Asia/Kolkata")
    trading_dt = datetime(2025, 3, 10, 11, 30, tzinfo=ist)  # Monday 11:30 AM IST
    off_dt = datetime(2025, 3, 10, 18, 0, tzinfo=ist)      # Monday 6:00 PM IST
    weekend_dt = datetime(2025, 3, 8, 12, 0, tzinfo=ist)  # Saturday 12:00 PM IST

    assert validate_ist_market_session(trading_dt) is True
    assert validate_ist_market_session(off_dt) is False
    assert validate_ist_market_session(weekend_dt) is False


def test_mftool_engine_scheme_search() -> None:
    engine = MFToolEngine()
    results = engine.search_schemes("Small Cap")
    assert "100027" in results
    assert "100052" in results
    assert len(results) >= 2


def test_mftool_engine_nav_metrics() -> None:
    engine = MFToolEngine(risk_free_rate=0.06)
    navs = [100.0, 102.0, 101.5, 105.0, 110.0, 108.0, 115.0, 120.0]
    metrics = engine.calculate_nav_metrics(navs, period_years=1.0)

    assert metrics["current_nav"] == 120.0
    assert metrics["cagr"] == 0.2
    assert metrics["volatility"] > 0.0
    assert metrics["max_drawdown"] > 0.0
    assert "sharpe_ratio" in metrics


def test_mftool_engine_asset_allocation() -> None:
    engine = MFToolEngine()
    holdings = [
        {"name": "HDFC Bank", "weight": 40.0, "type": "equity"},
        {"name": "ICICI Bank", "weight": 30.0, "type": "equity"},
        {"name": "Govt Bonds", "weight": 20.0, "type": "debt"},
        {"name": "Cash", "weight": 10.0, "type": "cash"},
    ]
    alloc = engine.compute_asset_allocation(holdings)

    assert alloc["equity_percentage"] == 70.0
    assert alloc["debt_percentage"] == 20.0
    assert alloc["cash_percentage"] == 10.0
    assert alloc["total_schemes"] == 4


def test_mftool_adapter_execution() -> None:
    adapter = MFToolAdapter(is_sandbox=True)
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    acct = adapter.get_account_info()
    assert acct["broker"] == "MFTOOL_MUTUAL_FUND_ENGINE"

    price_info = adapter.get_current_price("100027")
    assert price_info["last"] == 125.45

    req = SEBIOrderRequest(
        symbol="100027",
        quantity=50.0,
        order_type="BUY",
        price=125.43,
        exchange="MF",
        product="CNC",
    )
    resp = adapter.execute_order(req)
    assert resp.success is True
    assert resp.price == 125.45
    assert resp.status == "EXECUTED"

    close_res = adapter.close_order("MF_123", "100027")
    assert close_res.success is True
    assert close_res.status == "CLOSED"

    assert adapter.modify_order("MF_123", price=126.0) is True
    assert adapter.disconnect() is True


def test_mftool_registry() -> None:
    reg_class1 = IndianBrokerPluginRegistry.get_adapter_class("MFTOOL")
    reg_class2 = IndianBrokerPluginRegistry.get_adapter_class("MFTOOL_MUTUAL_FUND_ENGINE")

    assert reg_class1 is MFToolAdapter
    assert reg_class2 is MFToolAdapter
