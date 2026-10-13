"""
Unit and Integration Tests for Options Greeks Dynamic Auto-Hedging Engine.
"""

from institutional_integrations.options_greeks_hedge_engine import (
    OptionsGreeksHedgeEngine,
    OptionsGreeksHedgeEngineAdapter,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_black_76_greeks_calculation() -> None:
    engine = OptionsGreeksHedgeEngine(risk_free_rate=0.065)
    greeks_ce = engine.calculate_greeks(spot=24000.0, strike=24000.0, dte_days=7.0, volatility=0.15, option_type="CE")

    assert greeks_ce["price"] > 0
    assert 0.45 <= greeks_ce["delta"] <= 0.55
    assert greeks_ce["gamma"] > 0
    assert greeks_ce["vega"] > 0

    greeks_pe = engine.calculate_greeks(spot=24000.0, strike=24000.0, dte_days=7.0, volatility=0.15, option_type="PE")
    assert -0.55 <= greeks_pe["delta"] <= -0.45


def test_portfolio_delta_hedge_evaluation() -> None:
    engine = OptionsGreeksHedgeEngine()
    positions = [
        {"spot": 24000.0, "strike": 24000.0, "dte": 7.0, "volatility": 0.15, "option_type": "CE", "quantity": 100, "side": "BUY"},
        {"spot": 24000.0, "strike": 24000.0, "dte": 7.0, "volatility": 0.15, "option_type": "PE", "quantity": 50, "side": "BUY"},
    ]

    hedge = engine.evaluate_portfolio_delta_hedge(positions)
    assert "net_delta" in hedge
    assert hedge["suggested_hedge_side"] in ["BUY", "SELL"]
    assert hedge["suggested_hedge_quantity"] >= 0


def test_options_hedge_adapter_lifecycle() -> None:
    adapter = OptionsGreeksHedgeEngineAdapter(is_sandbox=True)
    assert adapter.connect() is True
    assert adapter.is_connected() is True

    acc = adapter.get_account_info()
    assert acc["broker"] == "OPTIONS_GREEKS_HEDGE_ENGINE"

    req = SEBIOrderRequest(
        symbol="NIFTY24OCTCE24000", order_type="SELL", quantity=50, price=215.12, product="NRML", exchange="NFO"
    )
    res = adapter.execute_order(req)
    assert res.success is True
    assert res.price == 215.10
    assert res.ticket.startswith("HEDGE_")

    close_res = adapter.close_order(res.ticket, "NIFTY24OCTCE24000")
    assert close_res.success is True


def test_broker_registry_integration() -> None:
    assert IndianBrokerPluginRegistry.is_enabled("OPTIONS_GREEKS_HEDGE_ENGINE") is True
    adapter_cls = IndianBrokerPluginRegistry.get_adapter_class("OPTIONS_GREEKS_HEDGE_ENGINE")
    assert adapter_cls is OptionsGreeksHedgeEngineAdapter
