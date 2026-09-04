# codespell:ignore MIS,IST
"""
Unit Test Suite for abhiwalia15/AI-for-Finance-Stocks-real-time-analysis- Adaptation Module.
Verifies AIFinanceStockAnalysisEngine sentiment polarity analysis, real-time stock scoring,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.ai_finance_stock_analysis_engine import (
    MAGIC_NUMBER_AI_FINANCE_ANALYSIS,
    AIFinanceStockAnalysisAdapter,
    AIFinanceStockAnalysisEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
    generate_indian_market_history_bars,
)


def test_news_sentiment_and_stock_analysis() -> None:
    engine = AIFinanceStockAnalysisEngine()
    headlines = [
        "Company reports record quarterly profit growth and surge in revenue",
        "Analysts upgrade stock to Buy with strong dividend payout",
        "New expansion project approved by board",
    ]

    sent_res = engine.analyze_news_sentiment(headlines)
    assert sent_res["sentiment_score"] > 0.30
    assert sent_res["bias"] == "BULLISH"

    bars = generate_indian_market_history_bars("NSE:RELIANCE", count=30)
    stock_res = engine.analyze_realtime_stock("RELIANCE", bars, headlines)

    assert stock_res["composite_score"] > 50.0
    assert stock_res["action"] in ("BUY", "HOLD")
    assert stock_res["magic_number"] == MAGIC_NUMBER_AI_FINANCE_ANALYSIS


def test_ai_finance_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("AI_FINANCE_STOCK_ANALYSIS")
    assert cls is AIFinanceStockAnalysisAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="AI_FINANCE_STOCK_ANALYSIS", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="RELIANCE", side="BUY", quantity=10, price=2850.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 2850.10
    assert res["ticket"].startswith("AIFIN_")
