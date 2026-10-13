"""Unit tests for Zen Tradings institutional integrations in EQATS.

Covers:
- zen_coding_engine (9100090)
- zen_fundamentals_engine (9100091)
- zen_rft_engine (9100092)
- coding_routing_benchmark_engine (9100093)
- wq_alpha_research_engine (9100094)
- retail_skills_us_engine (9100095)
- portfolio_distiller_engine (9100096)
- eia_mcp_engine (9100097)
- eval_search_api_engine (9100098)
- autoresearch_macos_zen_engine (9100099)
"""

import zoneinfo
from datetime import datetime

from institutional_integrations.autoresearch_macos_zen_engine import (
    MAGIC_NUMBER_AUTORESEARCH_MACOS_ZEN,
    AutoresearchMacOSZenEngine,
)
from institutional_integrations.coding_routing_benchmark_engine import (
    MAGIC_NUMBER_CODING_ROUTING_BENCHMARK,
    CodingRoutingBenchmarkEngine,
)
from institutional_integrations.eia_mcp_engine import (
    MAGIC_NUMBER_EIA_MCP,
    EIAMCPEngine,
)
from institutional_integrations.eval_search_api_engine import (
    MAGIC_NUMBER_EVAL_SEARCH_API,
    EvalSearchAPIEngine,
)
from institutional_integrations.portfolio_distiller_engine import (
    MAGIC_NUMBER_PORTFOLIO_DISTILLER,
    PortfolioDistillerEngine,
)
from institutional_integrations.retail_skills_us_engine import (
    MAGIC_NUMBER_RETAIL_SKILLS_US,
    RetailSkillsUSEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)
from institutional_integrations.wq_alpha_research_engine import (
    MAGIC_NUMBER_WQ_ALPHA_RESEARCH,
    WQAlphaResearchEngine,
)
from institutional_integrations.zen_coding_engine import (
    MAGIC_NUMBER_ZEN_CODING,
    ZenCodingEngine,
)
from institutional_integrations.zen_fundamentals_engine import (
    MAGIC_NUMBER_ZEN_FUNDAMENTALS,
    ZenFundamentalsEngine,
)
from institutional_integrations.zen_rft_engine import (
    MAGIC_NUMBER_ZEN_RFT,
    ZenRFTEngine,
)


def test_zen_coding_engine():
    ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
    assert ist_tz is not None
    assert datetime.now(ist_tz) is not None

    engine = ZenCodingEngine()
    is_safe, v = engine.inspect_code_guardrails("import numpy as np\nx = np.mean([1, 2, 3])")
    assert is_safe
    assert len(v) == 0

    is_unsafe, v_unsafe = engine.inspect_code_guardrails("import os; os.system('rm -rf /')")
    assert not is_unsafe
    assert len(v_unsafe) > 0

    trace = engine.record_trace("session_1", 500, 200, 100.0, 101.5, eval_score=0.95)
    assert trace.session_id == "session_1"
    assert trace.total_cost_usd > 0
    assert trace.latency_ms == 1500.0


def test_zen_fundamentals_engine():
    engine = ZenFundamentalsEngine()
    engine.register_investment_thesis("RELIANCE", "Growth in Digital & Retail", target_pe=25.0, min_roe=15.0)

    res = engine.evaluate_fundamental_health("RELIANCE", current_pe=22.0, current_roe=16.5, fcf_yield_pct=4.2)
    assert res["status"] == "STRONG_FUNDAMENTALS"
    assert res["action"] == "BUY_OR_ACCUMULATE"


def test_zen_rft_engine():
    engine = ZenRFTEngine()
    res = engine.evaluate_financial_grader(
        task_id="task_001",
        model_output={"predicted_value": 100.05},
        ground_truth={"expected_value": 100.00, "tolerance": 0.1},
    )
    assert res.is_correct
    assert res.reward_score == 1.0

    rec = engine.get_model_replacement_recommendation()
    assert rec["can_replace_frontier_model"]


def test_coding_routing_benchmark_engine():
    engine = CodingRoutingBenchmarkEngine()
    res = engine.select_optimal_model("RUST_MATCHING")
    assert res["selected_model"] == "claude-3-5-sonnet"


def test_wq_alpha_research_engine():
    engine = WQAlphaResearchEngine()
    m_data = {
        "RELIANCE": {"close": 2500.0, "close_5d_ago": 2400.0, "volume": 10000.0},
        "TCS": {"close": 3500.0, "close_5d_ago": 3550.0, "volume": 5000.0},
    }
    res = engine.evaluate_alpha_expression("alpha_001", "ts_delta(close, 5)/volume", m_data)
    assert "RELIANCE" in res.ranked_weights
    assert res.ranked_weights["RELIANCE"] > res.ranked_weights["TCS"]


def test_retail_skills_us_engine():
    engine = RetailSkillsUSEngine()
    holdings = [
        {"symbol": "INFY", "quantity": 100, "cost_basis": 1800.0, "current_price": 1400.0},
        {"symbol": "TCS", "quantity": 50, "cost_basis": 3200.0, "current_price": 3500.0},
    ]
    candidates = engine.evaluate_tax_loss_harvesting(holdings)
    assert len(candidates) == 1
    assert candidates[0].symbol == "INFY"


def test_portfolio_distiller_engine():
    engine = PortfolioDistillerEngine(target_max_holdings=2)
    raw = [
        {"symbol": "STOCK_A", "metrics": {"value": 0.9, "momentum": 0.8, "quality": 0.9}},
        {"symbol": "STOCK_B", "metrics": {"value": 0.2, "momentum": 0.3, "quality": 0.4}},
        {"symbol": "STOCK_C", "metrics": {"value": 0.8, "momentum": 0.9, "quality": 0.85}},
    ]
    res = engine.distill_portfolio(raw)
    assert res["distilled_count"] == 2
    symbols = [d["symbol"] for d in res["distilled_holdings"]]
    assert "STOCK_A" in symbols
    assert "STOCK_C" in symbols


def test_eia_mcp_engine():
    engine = EIAMCPEngine()
    res = engine.parse_eia_inventory_report("EIA_CRUDE_01", "Crude Oil", current_value=420.0, prior_value=425.0)
    assert res["macro_signal"] == "BULLISH_ENERGY_COMMODITIES"


def test_eval_search_api_engine():
    engine = EvalSearchAPIEngine()
    engine.index_document("doc_1", "NSE Options Volatility Surface Analysis", "https://example.com/1", 0.9, 0.95)
    results = engine.query_financial_search("NSE Options")
    assert len(results) == 1
    assert results[0]["doc_id"] == "doc_1"


def test_autoresearch_macos_zen_engine():
    engine = AutoresearchMacOSZenEngine(min_sharpe_promotion=1.5)
    run = engine.run_experiment_iteration("exp_01", "MomentumAlpha", {"period": 14}, sharpe=1.8, max_dd=10.0)
    assert run.is_promoted
    promoted = engine.get_promoted_strategies()
    assert len(promoted) == 1


def test_broker_adapters_plugin_registry():
    adapters = [
        ("ZEN_CODING", MAGIC_NUMBER_ZEN_CODING),
        ("ZEN_FUNDAMENTALS", MAGIC_NUMBER_ZEN_FUNDAMENTALS),
        ("ZEN_RFT", MAGIC_NUMBER_ZEN_RFT),
        ("CODING_ROUTING_BENCHMARK", MAGIC_NUMBER_CODING_ROUTING_BENCHMARK),
        ("WQ_ALPHA_RESEARCH", MAGIC_NUMBER_WQ_ALPHA_RESEARCH),
        ("RETAIL_SKILLS_US", MAGIC_NUMBER_RETAIL_SKILLS_US),
        ("PORTFOLIO_DISTILLER", MAGIC_NUMBER_PORTFOLIO_DISTILLER),
        ("EIA_MCP", MAGIC_NUMBER_EIA_MCP),
        ("EVAL_SEARCH_API", MAGIC_NUMBER_EVAL_SEARCH_API),
        ("AUTORESEARCH_MACOS_ZEN", MAGIC_NUMBER_AUTORESEARCH_MACOS_ZEN),
    ]

    for key, magic_num in adapters:
        adapter_cls = IndianBrokerPluginRegistry.get_adapter_class(key)
        assert adapter_cls is not None, f"Plugin {key} not found in registry"
        inst = adapter_cls()
        assert inst.connect()
        assert inst.is_connected()

        # Place order and check price tick rounding & magic number
        req = SEBIOrderRequest(symbol="TATAMOTORS", quantity=10, price=950.13, order_type="BUY")
        resp = inst.place_order(req)
        assert resp.success
        assert resp.price == 950.15
        assert resp.raw_response["magic_number"] == magic_num

        info = inst.get_account_info()
        assert info["magic_number"] == magic_num
