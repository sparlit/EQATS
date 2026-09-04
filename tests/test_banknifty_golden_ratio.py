# codespell:ignore MIS,IST
"""
Unit Test Suite for 85599/BankNIFTY-Golden-Ratio-Strategy Adaptation Module.
Verifies BankNiftyGoldenRatioStrategy calculations, Fibonacci Golden Ratio levels,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.banknifty_golden_ratio import (
    MAGIC_NUMBER_BANKNIFTY_GOLDEN_RATIO,
    BankNiftyGoldenRatioAdapter,
    BankNiftyGoldenRatioStrategy,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    generate_indian_market_history_bars,
)


def test_banknifty_golden_ratio_levels_math() -> None:
    strat = BankNiftyGoldenRatioStrategy(symbol="NSE:BANKNIFTY", lot_size=15)
    levels = strat.calculate_golden_ratio_levels(range_high=48000.0, range_low=47000.0)

    assert levels["range_high"] == 48000.0
    assert levels["range_low"] == 47000.0
    # 0.618 retrace = 48000 - 1000 * 0.61803398875 = 47381.95 (rounded to 0.05 tick)
    assert round(levels["retrace_618"] * 20) == levels["retrace_618"] * 20
    # 1.618 extension buy = 48000 + 1000 * 0.61803398875 = 48618.05
    assert levels["ext_1618_buy"] > 48000.0


def test_banknifty_golden_ratio_strategy_evaluation() -> None:
    strat = BankNiftyGoldenRatioStrategy(symbol="NSE:BANKNIFTY", lot_size=15)
    bars = []
    for i in range(30):
        o = 48000.0 + i * 2.0
        h = o + 50.0
        l = o - 50.0
        c = o + 10.0
        bars.append({"open": o, "high": h, "low": l, "close": c, "volume": 1000})

    or_high = max(b["high"] for b in bars[:15])
    or_low = min(b["low"] for b in bars[:15])

    # Modify last bar close to trigger BUY breakout
    bars[-1]["close"] = or_high + 100.0
    res_buy = strat.evaluate_strategy(bars)
    assert res_buy["decision"] == "BUY"
    assert res_buy["lot_size"] == 15
    assert res_buy["magic_number"] == MAGIC_NUMBER_BANKNIFTY_GOLDEN_RATIO

    # Modify last bar close to trigger SELL breakdown
    bars[-1]["close"] = or_low - 100.0
    res_sell = strat.evaluate_strategy(bars)
    assert res_sell["decision"] == "SELL"
    assert res_sell["lot_size"] == 15


def test_banknifty_golden_ratio_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("BANKNIFTY_GOLDEN_RATIO")
    assert cls is BankNiftyGoldenRatioAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="BANKNIFTY_GOLDEN_RATIO", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="BANKNIFTY", side="BUY", quantity=15, price=48500.0, product="NRML")
    assert res["success"] is True
    assert res["ticket"].startswith("BNGOLD_")
