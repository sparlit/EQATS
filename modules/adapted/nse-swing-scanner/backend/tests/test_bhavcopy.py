import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Tests for the bhavcopy parser and multi-provider chain."""
from unittest.mock import patch

import pandas as pd
import pytest
from bhavcopy import (
    BSE_PROVIDER,
    NSE_PROVIDER,
    YFINANCE_PROVIDER,
    _parse_bhavcopy,
    _try_bse_archives,
    _try_nse_archives,
    _try_yfinance_traded_value,
    _yfinance_fetch_one,
    fetch_bhavcopy,
    lookup_delivery,
)

# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parse_bhavcopy_standard():
    csv = """SYMBOL,CLOSE,DELIVQTY,DELIVVAL
RELIANCE,2900,123456,78901.5
TCS,3500,98765,34567.8
INFY,1500,50000,7500.0
"""
    df = pd.read_csv(pd.io.common.StringIO(csv))
    parsed = _parse_bhavcopy(df)
    assert "RELIANCE" in parsed
    assert "TCS" in parsed
    assert parsed["RELIANCE"]["delivery_qty"] == 123456
    # NSE publishes delivery value in lakhs
    assert parsed["RELIANCE"]["delivery_value_inr"] == pytest.approx(78901.5 * 1_00_000)
    assert parsed["TCS"]["delivery_value_inr"] == pytest.approx(34567.8 * 1_00_000)
    assert parsed["RELIANCE"]["delivery_kind"] == "actual"


def test_parse_bhavcopy_fallback_to_qty_close():
    """If DELIVVAL column is missing, derive value from DELIVQTY * CLOSE."""
    csv = """SYMBOL,CLOSE,DELIVQTY
RELIANCE,2900,100
"""
    df = pd.read_csv(pd.io.common.StringIO(csv))
    parsed = _parse_bhavcopy(df)
    assert parsed["RELIANCE"]["delivery_value_inr"] == pytest.approx(100 * 2900)


def test_parse_bhavcopy_no_symbol_column_returns_empty():
    csv = """FOO,BAR
1,2
"""
    df = pd.read_csv(pd.io.common.StringIO(csv))
    parsed = _parse_bhavcopy(df)
    assert parsed == {}


def test_parse_bhavcopy_handles_missing_delivery_columns():
    csv = """SYMBOL,CLOSE
RELIANCE,2900
"""
    df = pd.read_csv(pd.io.common.StringIO(csv))
    parsed = _parse_bhavcopy(df)
    # No delivery columns means we can't compute a value
    assert "RELIANCE" not in parsed or "delivery_value_inr" not in parsed.get("RELIANCE", {})


# ---------------------------------------------------------------------------
# Multi-provider chain
# ---------------------------------------------------------------------------


def test_fetch_bhavcopy_nse_path_when_nse_returns_data(monkeypatch):
    """When NSE succeeds, the chain returns its payload with delivery_kind='actual'."""
    monkeypatch.delenv("NSE_SWING_NO_CACHE", raising=False)
    nse_payload = {
        "source": f"{NSE_PROVIDER}:http://example/bhav.csv",
        "status": "ok",
        "as_of": "2026-07-03",
        "data": {"RELIANCE": {"delivery_qty": 100, "delivery_value_inr": 5_000_000, "delivery_kind": "actual"}},
    }
    with (
        patch("bhavcopy._try_nse_archives", return_value=nse_payload),
        patch("bhavcopy._try_yfinance_traded_value") as yf,
        patch("bhavcopy._try_bse_archives") as bse,
    ):
        out = fetch_bhavcopy(
            universe_symbols=["RELIANCE"],
            universe_yf_tickers=["RELIANCE.NS"],
        )
    assert out["status"] == "ok"
    assert out["source"].startswith(NSE_PROVIDER)
    assert "provider_chain" in out
    assert len(out["provider_chain"]) == 1
    yf.assert_not_called()
    bse.assert_not_called()


def test_fetch_bhavcopy_falls_back_to_yfinance_proxy(monkeypatch):
    """When NSE fails, the yfinance proxy serves traded_value data."""
    monkeypatch.delenv("NSE_SWING_NO_CACHE", raising=False)
    nse_failed = {"source": NSE_PROVIDER, "status": "source_failed", "data": {}, "error": "blocked"}
    yf_payload = {
        "source": YFINANCE_PROVIDER,
        "status": "ok",
        "as_of": "2026-07-03",
        "data": {
            "RELIANCE": {
                "delivery_qty": 1_000_000,
                "delivery_value_inr": 1_500_000_000,  # 1.5B INR ≈ 150 cr
                "delivery_pct": None,
                "delivery_kind": "traded_value_proxy",
            }
        },
        "delivery_kind": "traded_value_proxy",
        "universe_size": 1,
    }
    with (
        patch("bhavcopy._try_nse_archives", return_value=nse_failed),
        patch("bhavcopy._try_yfinance_traded_value", return_value=yf_payload),
        patch("bhavcopy._try_bse_archives") as bse,
    ):
        out = fetch_bhavcopy(
            universe_symbols=["RELIANCE"],
            universe_yf_tickers=["RELIANCE.NS"],
        )
    assert out["status"] == "ok"
    assert out["source"] == YFINANCE_PROVIDER
    assert out["data"]["RELIANCE"]["delivery_kind"] == "traded_value_proxy"
    assert out["data"]["RELIANCE"]["delivery_value_inr"] == 1_500_000_000
    chain = out["provider_chain"]
    assert chain[0]["provider"] == NSE_PROVIDER
    assert chain[1]["provider"] == YFINANCE_PROVIDER
    assert chain[1]["status"] == "ok"
    bse.assert_not_called()


def test_fetch_bhavcopy_all_providers_fail_returns_source_failed(monkeypatch):
    """When every provider fails, the result is source_failed with the chain recorded."""
    monkeypatch.delenv("NSE_SWING_NO_CACHE", raising=False)
    nse_failed = {"source": NSE_PROVIDER, "status": "source_failed", "data": {}, "error": "blocked"}
    yf_failed = {"source": YFINANCE_PROVIDER, "status": "source_failed", "data": {}, "error": "yfinance down"}
    bse_failed = {"source": BSE_PROVIDER, "status": "source_failed", "data": {}, "error": "blocked"}
    with (
        patch("bhavcopy._try_nse_archives", return_value=nse_failed),
        patch("bhavcopy._try_yfinance_traded_value", return_value=yf_failed),
        patch("bhavcopy._try_bse_archives", return_value=bse_failed),
    ):
        out = fetch_bhavcopy(
            universe_symbols=["RELIANCE"],
            universe_yf_tickers=["RELIANCE.NS"],
        )
    assert out["status"] == "source_failed"
    assert out["data"] == {}
    assert len(out["provider_chain"]) == 3
    assert all(c["status"] == "source_failed" for c in out["provider_chain"])


def test_lookup_delivery_returns_kind_and_fallback():
    """lookup_delivery must surface the new fields for downstream consumers."""
    payload = {
        "source": YFINANCE_PROVIDER,
        "status": "ok",
        "as_of": "2026-07-03",
        "fallback_from": NSE_PROVIDER,
        "data": {
            "RELIANCE": {
                "delivery_qty": 100.0,
                "delivery_value_inr": 5_000_000.0,
                "delivery_pct": None,
                "delivery_kind": "traded_value_proxy",
            }
        },
    }
    hit = lookup_delivery(payload, "RELIANCE")
    assert hit["delivery_value_inr"] == 5_000_000.0
    assert hit["delivery_kind"] == "traded_value_proxy"
    assert hit["fallback_from"] == NSE_PROVIDER
    assert hit["source_status"] == "ok"
    miss = lookup_delivery(payload, "TCS")
    assert miss["delivery_value_inr"] is None
    assert miss["source_status"] == "missing"


def test_yfinance_fetch_one_handles_empty_dataframe():
    """If yfinance returns an empty DataFrame, _yfinance_fetch_one returns None."""
    import pandas as pd

    with patch("yfinance.Ticker") as fake_ticker:
        fake_ticker.return_value.history.return_value = pd.DataFrame()
        assert _yfinance_fetch_one("RELIANCE.NS") is None


def test_yfinance_fetch_one_returns_trade_value():
    """If yfinance returns OHLCV, _yfinance_fetch_one returns volume × close as traded value."""
    dates = pd.date_range("2026-07-01", periods=3, freq="B")
    hist = pd.DataFrame(
        {
            "Close": [100.0, 105.0, 110.0],
            "Volume": [1000.0, 2000.0, 3000.0],
        },
        index=dates,
    )
    with patch("yfinance.Ticker") as fake_ticker:
        fake_ticker.return_value.history.return_value = hist
        out = _yfinance_fetch_one("RELIANCE.NS")
    assert out is not None
    assert out["close"] == 110.0
    assert out["volume"] == 3000.0
    # Sanity: traded_value = volume × close
    assert out["volume"] * out["close"] == 330_000.0
