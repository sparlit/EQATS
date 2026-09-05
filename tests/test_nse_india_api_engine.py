"""
Tests for NSE India API Evangelist Specification & Security Governance Engine Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.nse_india_api_engine import (
    NSEIndiaAPIEngine,
    NSEIndiaAPIBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_NSE_INDIA_API,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_domain_security_and_api_health_score():
    engine = NSEIndiaAPIEngine()
    assert engine.magic_number == MAGIC_NUMBER_NSE_INDIA_API

    policy_sample = {
        "domain": "nseindia.com",
        "dnssec": True,
        "spf": True,
        "dmarc": True,
        "dmarc_policy": "reject",
    }

    sec_res = engine.validate_domain_security(policy_sample)
    assert sec_res["is_security_compliant"]
    assert sec_res["dmarc_policy"] == "reject"

    health = engine.compute_api_health_score(latency_ms=120.0, error_rate_pct=0.5, uptime_pct=99.9)
    assert health["health_score"] > 80.0
    assert health["status"] == "HEALTHY"


def test_nse_india_api_broker_adapter():
    adapter = NSEIndiaAPIBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("NSE_INDIA_API") == NSEIndiaAPIBrokerAdapter

    req = SEBIOrderRequest(
        symbol="NIFTY",
        quantity=50,
        price=22000.02,
        order_type="BUY",
        product="MIS",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.nse_india_api_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 22000.00
        assert res.ticket.startswith("NSEINDIA-")
