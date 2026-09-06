"""
Unit tests for NumericalStandardErrorEngine and BraverockNSEBrokerAdapter (Repo 084 Adaptation, Magic 9100081)
"""

from unittest.mock import patch

import pytest
from institutional_integrations.braverock_nse_engine import (
    NumericalStandardErrorEngine,
    BraverockNSEBrokerAdapter,
    MAGIC_NUMBER,
    round_tick_005,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
)


def test_nse_engine_calculations():
    engine = NumericalStandardErrorEngine()
    series = [0.01 * (i % 5 - 2) + 0.005 * i for i in range(100)]

    bm = engine.compute_batch_means(series, nbatch=10)
    assert bm > 0

    obm = engine.compute_overlapping_batch_means(series, batch_size=15)
    assert obm > 0

    nw = engine.compute_newey_west_kernel(series)
    assert nw > 0

    summary = engine.analyze_time_series(series)
    assert summary.mean != 0.0
    assert summary.nse_bm > 0
    assert summary.effective_sample_size > 0


def test_braverock_adapter():
    adapter = BraverockNSEBrokerAdapter()
    assert adapter.magic_number == MAGIC_NUMBER
    adapter.connect()
    assert adapter.is_connected() is True

    req = SEBIOrderRequest(
        symbol="TCS",
        exchange="NSE",
        order_type="BUY",
        product="CNC",
        quantity=10,
        price=3500.03,
    )

    with patch("institutional_integrations.braverock_nse_engine.is_ist_market_open", return_value=True):
        resp = adapter.execute_order(req)
        assert resp.success is True
        assert resp.status == "FILLED"
        assert resp.price == 3500.05
        assert resp.ticket.startswith("BRAVEROCK-TCS-")


def test_registry_integration():
    brokers = IndianBrokerPluginRegistry.list_registered_brokers()
    assert "BRAVEROCK_NSE" in brokers
