# codespell:ignore MIS,IST
"""
Unit Test Suite for abuhurairalakdawala/indian-share-market Adaptation Module.
Verifies IndianShareMarketEngine fundamental scoring, sector momentum matrix,
CAGR/Sharpe calculation, 0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.indian_share_market_engine import (
    MAGIC_NUMBER_INDIAN_SHARE_MARKET,
    IndianShareMarketAdapter,
    IndianShareMarketEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
)


def test_indian_share_market_fundamental_and_sector_eval() -> None:
    engine = IndianShareMarketEngine()
    eval_res = engine.evaluate_fundamental_score(
        pe_ratio=12.5, pb_ratio=1.8, roe_pct=18.5, debt_to_equity=0.2, div_yield_pct=2.5
    )

    assert eval_res["fundamental_score"] >= 75.0
    assert eval_res["rating"] == "STRONG_BUY"
    assert eval_res["magic_number"] == MAGIC_NUMBER_INDIAN_SHARE_MARKET

    sectors = engine.evaluate_sector_momentum()
    assert "NIFTY_BANK" in sectors
    assert sectors["NIFTY_BANK"]["momentum"] == "BULLISH"

    portfolio = engine.calculate_portfolio_cagr_sharpe(
        initial_capital=1000000.0,
        current_value=1500000.0,
        duration_years=3.0,
        returns_list=[0.01, 0.02, -0.005, 0.015, 0.018],
    )
    assert portfolio["cagr_pct"] > 10.0
    assert portfolio["sharpe_ratio"] > 0.0


def test_indian_share_market_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("INDIAN_SHARE_MARKET")
    assert cls is IndianShareMarketAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="INDIAN_SHARE_MARKET", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="SBIN", side="BUY", quantity=20, price=830.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 830.10
    assert res["ticket"].startswith("INMKT_")
