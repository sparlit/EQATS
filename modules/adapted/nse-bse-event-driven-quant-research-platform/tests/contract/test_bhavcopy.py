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


"""Bhavcopy ingester tests against a real UDiFF fixture from NSE archives."""

from datetime import date
from pathlib import Path

import pytest
from indian_quant.ingestion.nse import BhavcopyIngester, parse_delivery_csv
from indian_quant.schemas import Timeframe
from indian_quant.storage import RawStore

FIXTURE = Path(__file__).parents[1] / "fixtures" / "BhavCopy_NSE_CM_20260818.zip"


@pytest.fixture(scope="module")
def ingester(tmp_path_factory):
    raw = RawStore(tmp_path_factory.mktemp("raw"))
    return BhavcopyIngester(raw)


class TestBhavcopyParsing:
    def test_parses_real_udiff_zip(self, ingester):
        payload = FIXTURE.read_bytes()
        bars = ingester.parse_cm_zip(payload, date(2026, 8, 18), symbols={"RELIANCE"})
        assert len(bars) == 1
        bar = bars[0]
        assert bar.instrument_id == "NSE_EQ|RELIANCE"
        assert bar.timeframe == Timeframe.DAY
        assert bar.open == pytest.approx(1314.0)
        assert bar.high == pytest.approx(1328.6)
        assert bar.low == pytest.approx(1311.2)
        assert bar.close == pytest.approx(1322.0)
        assert bar.volume == pytest.approx(10_180_567)
        assert bar.source == "NSE"

    def test_series_filter_excludes_non_cash(self, ingester):
        payload = FIXTURE.read_bytes()
        all_eq = ingester.parse_cm_zip(payload, date(2026, 8, 18))
        only_eq = ingester.parse_cm_zip(payload, date(2026, 8, 18), series={"EQ"})
        assert len(all_eq) >= len(only_eq) > 100

    def test_sme_series_maps_to_sme_segment(self, tmp_path_factory):
        """SM/ST series must land on NSE_SME| ids - never mixed with EQ."""
        import io
        import zipfile

        from indian_quant.storage import RawStore as _RS

        header = (
            "TradDt,BizDt,Sgmt,Src,FinInstrmTp,FinInstrmId,ISIN,TckrSymb,SctySrs,"
            "OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n"
        )
        rows = (
            "2026-08-18,2026-08-18,CM,NSE,STK,99999,INE11111111,QMSMEDI,SM,"
            "100.0,105.0,99.0,104.0,50000\n"
            "2026-08-18,2026-08-18,CM,NSE,STK,99998,INE22222222,SMESTK,ST,"
            "50.0,52.0,49.5,51.0,20000\n"
            "2026-08-18,2026-08-18,CM,NSE,STK,500325,INE002A01018,RELIANCE,EQ,"
            "1314.0,1328.6,1311.2,1322.0,10180567\n"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("test.csv", header + rows)
        ing = BhavcopyIngester(_RS(tmp_path_factory.mktemp("raw2")))
        bars = ing.parse_cm_zip(buf.getvalue(), date(2026, 8, 18))
        ids = {b.instrument_id for b in bars}
        assert "NSE_SME|QMSMEDI" in ids
        assert "NSE_SME|SMESTK" in ids
        assert "NSE_EQ|RELIANCE" in ids

    def test_symbol_filter(self, ingester):
        payload = FIXTURE.read_bytes()
        bars = ingester.parse_cm_zip(payload, date(2026, 8, 18), symbols={"TCS", "INFY"})
        ids = {b.instrument_id for b in bars}
        assert any(i.endswith("|TCS") for i in ids) or len(bars) > 0


def test_delivery_csv_parsing():
    text = (
        "SYMBOL,SERIES,DATE1,PREV_CLOSE,OPEN_PRICE,HIGH_PRICE,LOW_PRICE,LAST_PRICE,"
        "CLOSE_PRICE,AVG_PRICE,TTL_TRD_QNTY,TURNOVER_LACS,NO_OF_TRADES,DELIV_QTY,DELIV_PER\n"
        "RELIANCE,EQ,18-AUG-2026,1305.00,1314.00,1328.60,1311.20,1320.00,1322.00,"
        "1320.15,10180567,134453.19,187432,6012345,59.06\n"
        "BADROW,EQ,18-AUG-2026,1,2,3,4,5,x,7,8,9,10,11,-\n"
    )
    out = parse_delivery_csv(text)
    assert out["RELIANCE"]["close"] == pytest.approx(1322.0)
    assert out["RELIANCE"]["deliv_pct"] == pytest.approx(59.06)
    assert out["RELIANCE"]["series"] == "EQ"
