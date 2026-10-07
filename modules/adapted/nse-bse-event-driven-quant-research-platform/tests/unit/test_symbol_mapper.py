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


"""Symbol mapper tests."""

import pytest
from indian_quant.instruments import SymbolMapper
from indian_quant.schemas import Exchange, InstrumentIdentity, Segment


def identity(symbol="RELIANCE", isin="INE002A01018"):
    return InstrumentIdentity(
        instrument_id=f"NSE_EQ|{symbol}",
        exchange=Exchange.NSE,
        segment=Segment.EQ,
        symbol=symbol,
        isin=isin,
    )


class TestSymbolMapper:
    def test_register_and_resolve(self):
        mapper = SymbolMapper()
        mapper.register(identity())
        assert mapper.resolve("NSE_EQ|RELIANCE").symbol == "RELIANCE"
        with pytest.raises(KeyError):
            mapper.resolve("NSE_EQ|UNKNOWN")

    def test_isin_lookup(self):
        mapper = SymbolMapper()
        mapper.register(identity())
        found = mapper.by_isin("ine002a01018")
        assert found is not None and found.symbol == "RELIANCE"

    def test_canonical_to_nautilus(self):
        assert SymbolMapper.canonical_to_nautilus("NSE_EQ|RELIANCE") == "RELIANCE.NSE"
        assert (
            SymbolMapper.canonical_to_nautilus("NSE_FO|BANKNIFTY-2026-09-24-CE-52000")
            == "BANKNIFTY-2026-09-24-CE-52000.NSEFO"
        )

    def test_upstox_master_load(self, tmp_path):
        master = tmp_path / "master.csv"
        master.write_text(
            "instrument_key,trading_symbol,exchange,segment,isin,instrument_type\n"
            "NSE_EQ|INE002A01018,RELIANCE,NSE_EQ,EQ,INE002A01018,EQUITY\n"
        )
        mapper = SymbolMapper()
        count = mapper.load_upstox_master(master)
        assert count == 1
        key = mapper.upstox_key_for(identity())
        assert key == "NSE_EQ|INE002A01018"
