# codespell:ignore MIS,IST
"""
Unit Test Suite for akshayraje/get-nse-bhavcopy Adaptation Module.
Verifies NSEBhavcopyEngine CSV parsing, delivery percentage calculations,
0.05 INR tick rounding, and microkernel plugin registry lookup.
"""

from typing import Any

from institutional_integrations.nse_bhavcopy_engine import (
    MAGIC_NUMBER_NSE_BHAVCOPY,
    NSEBhavcopyAdapter,
    NSEBhavcopyEngine,
)
from institutional_integrations.sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIOrderRequest,
    UnifiedIndianBrokerClientAdapter,
)


def test_equity_bhavcopy_csv_parsing_and_delivery_pct() -> None:
    engine = NSEBhavcopyEngine()
    csv_sample = (
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,DELIV_QTY\n"
        "RELIANCE,EQ,2840.12,2865.03,2835.18,2850.11,1000000,600000\n"
        "SBIN,EQ,820.00,835.00,818.00,830.50,2000000,800000\n"
        "INFY,IT,1800.00,1820.00,1790.00,1810.00,500000,300000\n"
    )

    records = engine.parse_equity_bhavcopy_csv(csv_sample)
    assert len(records) == 2  # INFY excluded as SERIES != EQ
    assert records[0]["symbol"] == "RELIANCE"
    assert records[0]["close"] == 2850.10  # 0.05 INR tick rounding
    assert records[0]["delivery_pct"] == 60.0
    assert records[0]["accumulation_signal"] is True  # > 55% delivery & close > open
    assert records[0]["magic_number"] == MAGIC_NUMBER_NSE_BHAVCOPY


def test_fo_bhavcopy_csv_parsing() -> None:
    engine = NSEBhavcopyEngine()
    fo_csv_sample = (
        "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,CLOSE,OPEN_INT,CHG_IN_OI\n"
        "OPTSTK,RELIANCE,28-MAR-2024,2850.00,CE,45.20,1500000,120000\n"
        "FUTIDX,NIFTY,28-MAR-2024,0.00,XX,24500.10,8500000,-250000\n"
    )

    fo_records = engine.parse_fo_bhavcopy_csv(fo_csv_sample)
    assert len(fo_records) == 2
    assert fo_records[0]["symbol"] == "RELIANCE"
    assert fo_records[0]["open_interest"] == 1500000
    assert fo_records[1]["symbol"] == "NIFTY"
    assert fo_records[1]["change_in_oi"] == -250000


def test_nse_bhavcopy_microkernel_registry() -> None:
    cls = IndianBrokerPluginRegistry.get_adapter_class("NSE_BHAVCOPY")
    assert cls is NSEBhavcopyAdapter

    adapter = UnifiedIndianBrokerClientAdapter(broker_name="NSE_BHAVCOPY", api_key="key", is_sandbox=True)
    assert adapter.login() is True
    res = adapter.place_order(symbol="RELIANCE", side="BUY", quantity=10, price=2850.12, product="CNC")
    assert res["success"] is True
    assert res["price"] == 2850.10
    assert res["ticket"].startswith("BHAV_")
