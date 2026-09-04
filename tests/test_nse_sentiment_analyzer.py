"""
Unit & Integration Tests for NSE Sentiment Analyzer (AshayK003/nse-sentiment-analyzer Adaptation)
"""

from datetime import datetime
from institutional_integrations.nse_sentiment_analyzer import NSESentimentAnalyzer, MAGIC_NUMBER
from institutional_integrations.sebi_broker_adapter import IndianBrokerPluginRegistry


def test_nse_sentiment_analyzer_initialization() -> None:
    analyzer = NSESentimentAnalyzer(sentiment_threshold=0.3)
    assert analyzer.sentiment_threshold == 0.3
    assert MAGIC_NUMBER == 9100028


def test_nse_sentiment_evaluation() -> None:
    analyzer = NSESentimentAnalyzer()
    headlines = [
        "Company reports record profit growth and expansion",
        "Dividend payout announced following surge in Q2 earnings",
    ]

    market_time = datetime(2025, 10, 15, 11, 30, 0)
    result = analyzer.evaluate_sentiment("RELIANCE", headlines, 2850.12, timestamp=market_time)

    assert result["symbol"] == "RELIANCE"
    assert result["price"] == 2850.10  # 0.05 INR tick rounding
    assert result["sentiment_label"] == "BULLISH"
    assert result["sentiment_score"] > 0.0
    assert result["magic_number"] == 9100028


def test_nse_sentiment_plugin_registry() -> None:
    plugin_cls = IndianBrokerPluginRegistry.get_adapter_class("ashayk003_nse_sentiment")
    assert plugin_cls is not None
    assert plugin_cls is NSESentimentAnalyzer
