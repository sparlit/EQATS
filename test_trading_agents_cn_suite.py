"""
Unit and Integration Tests for TradingAgents-CN Suite.
"""

import pytest

from institutional_integrations.trading_agents_cn_suite import (
    ChinaMarketAnalystAgent,
    EnhancedNewsFilterEngine,
    DataCompletenessChecker,
)


def test_china_market_analyst_agent():
    agent = ChinaMarketAnalystAgent()
    report = agent.analyze_market(
        symbol="000001.SH",
        northbound_net_flow_mn=2500.0,
        pboc_stance="EASING",
        shanghai_comp_return_pct=1.2,
    )

    assert report.symbol == "000001.SH"
    assert report.market_bias == "BULLISH"
    assert report.sentiment_index > 60.0
    assert "Northbound Flow=+2500M" in report.summary


def test_enhanced_news_filter_engine():
    filter_engine = EnhancedNewsFilterEngine()

    raw_articles = [
        {"title": "Fed announces rate hike", "source": "Bloomberg", "sentiment": "BEARISH"},
        {"title": "FED announces rate hike!", "source": "Reuters", "sentiment": "BEARISH"},  # Duplicate
        {"title": "Bitcoin surges past $100k", "source": "CoinDesk", "sentiment": "BULLISH"},
    ]

    filtered = filter_engine.filter_and_deduplicate(raw_articles, target_symbol="BTC")
    assert len(filtered) == 2  # Deduplicated
    assert filtered[0].relevance_score >= filtered[1].relevance_score


def test_data_completeness_checker():
    checker = DataCompletenessChecker()

    # Timestamps with 1 missing bar (interval 60s)
    timestamps = [1000.0, 1060.0, 1180.0]  # Missing 1120.0
    report = checker.check_completeness(timestamps, expected_interval_seconds=60.0)

    assert report.total_expected_bars == 4
    assert report.total_actual_bars == 3
    assert report.missing_bar_count == 1
    assert report.has_gaps is True
    assert report.completeness_pct == 75.0
