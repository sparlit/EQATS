"""
Tests for Corporate Disclosures Engine Integration Module
"""

import pytest
from unittest.mock import patch

from institutional_integrations.ngrcoydisclosures_engine import (
    CorporateDisclosuresEngine,
    CorporateDisclosuresBrokerAdapter,
    round_tick_005,
    MAGIC_NUMBER_NGRCOYDISCLOSURES,
)
from institutional_integrations.sebi_broker_adapter import (
    SEBIOrderRequest,
    IndianBrokerPluginRegistry,
)


def test_xml_parsing_and_analysis():
    engine = CorporateDisclosuresEngine()
    assert engine.magic_number == MAGIC_NUMBER_NGRCOYDISCLOSURES

    sample_xml = """<?xml version="1.0" encoding="utf-8"?>
    <feed>
        <entry>
            <Description>Director acquisition of 50000 shares</Description>
            <Url>http://example.com/doc1</Url>
            <Type_of_Submission>Directors Dealings</Type_of_Submission>
            <CompanyName>Tata Consultancy Services</CompanyName>
            <CompanySymbol>TCS</CompanySymbol>
            <Modified>2024-02-01</Modified>
            <Created>2024-02-01</Created>
        </entry>
        <entry>
            <Description>Quarterly profit surge 25 percent dividend declared</Description>
            <Url>http://example.com/doc2</Url>
            <Type_of_Submission>Financial Statements</Type_of_Submission>
            <CompanyName>Reliance Industries</CompanyName>
            <CompanySymbol>RELIANCE</CompanySymbol>
            <Modified>2024-02-01</Modified>
            <Created>2024-02-01</Created>
        </entry>
    </feed>
    """

    records = engine.parse_xml_disclosures(sample_xml)
    assert len(records) == 2
    assert records[0]["company_symbol"] == "TCS"
    assert records[1]["company_symbol"] == "RELIANCE"

    analysis1 = engine.analyze_disclosure_event(records[0])
    assert analysis1["symbol"] == "TCS"
    assert analysis1["event_type"] == "INSIDER_DEALINGS"
    assert analysis1["sentiment_score"] > 0.5
    assert analysis1["recommended_action"] == "BUY"

    analysis2 = engine.analyze_disclosure_event(records[1])
    assert analysis2["symbol"] == "RELIANCE"
    assert analysis2["event_type"] == "FINANCIAL_STATEMENTS"
    assert analysis2["sentiment_score"] == 0.9
    assert analysis2["recommended_action"] == "BUY"


def test_disclosures_broker_adapter():
    adapter = CorporateDisclosuresBrokerAdapter()
    assert IndianBrokerPluginRegistry.get_adapter_class("NGRCOY_DISCLOSURES") == CorporateDisclosuresBrokerAdapter

    req = SEBIOrderRequest(
        symbol="TCS",
        quantity=5,
        price=3800.04,
        order_type="BUY",
        product="CNC",
        exchange="NSE",
        order_kind="LIMIT",
    )

    res_unauth = adapter.execute_order(req)
    assert not res_unauth.success

    adapter.connect()

    with patch("institutional_integrations.ngrcoydisclosures_engine.is_ist_market_open", return_value=True):
        res = adapter.execute_order(req)
        assert res.success
        assert res.status == "FILLED"
        assert res.price == 3800.05
        assert res.ticket.startswith("NGRCOY-")
