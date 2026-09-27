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


"""Canonical contract tests: the most important tests in the repo."""

from datetime import UTC, date, datetime

import pytest
from indian_quant.schemas import (
    AdjustmentStatus,
    Announcement,
    CorporateAction,
    CorporateActionType,
    Exchange,
    InstrumentIdentity,
    Lineage,
    MarketBar,
    OptionInstrument,
    OptionQuote,
    OptionType,
    QualityStatus,
    SecurityType,
    Segment,
    Timeframe,
    bars_to_frame,
    make_instrument_id,
    make_option_local_id,
    parse_instrument_id,
)
from pydantic import ValidationError


def ts(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=UTC)


class TestInstrumentIdentity:
    def test_canonical_id_format(self):
        assert make_instrument_id(Exchange.NSE, Segment.EQ, "RELIANCE") == "NSE_EQ|RELIANCE"
        assert make_instrument_id(Exchange.BSE, Segment.EQ, "500325") == "BSE_EQ|500325"
        exchange, segment, local = parse_instrument_id("NSE_FO|BANKNIFTY-2026-09-24-CE-52000")
        assert (exchange, segment, local) == ("NSE", "FO", "BANKNIFTY-2026-09-24-CE-52000")

    def test_invalid_canonical_id_rejected(self):
        with pytest.raises(ValueError):
            parse_instrument_id("RELIANCE")

    def test_identity_roundtrip(self):
        identity = InstrumentIdentity(
            instrument_id="NSE_EQ|RELIANCE",
            exchange=Exchange.NSE,
            segment=Segment.EQ,
            symbol="RELIANCE",
            isin="INE002A01018",
        )
        assert identity.nautilus_instrument_id == "RELIANCE.NSE"
        assert identity.security_type == SecurityType.EQUITY

    def test_isin_validation(self):
        with pytest.raises(ValidationError):
            InstrumentIdentity(
                instrument_id="NSE_EQ|X",
                exchange=Exchange.NSE,
                segment=Segment.EQ,
                symbol="X",
                isin="BAD",
            )

    def test_option_requires_all_fields(self):
        with pytest.raises(ValidationError):
            InstrumentIdentity(
                instrument_id="NSE_FO|OPT",
                exchange=Exchange.NSE,
                segment=Segment.FO,
                symbol="OPT",
                security_type=SecurityType.OPTION,
            )

    def test_fo_segment_rejects_equity_type(self):
        with pytest.raises(ValidationError):
            InstrumentIdentity(
                instrument_id="NSE_FO|NIFTY",
                exchange=Exchange.NSE,
                segment=Segment.FO,
                symbol="NIFTY",
                security_type=SecurityType.EQUITY,
            )


class TestOptionInstrument:
    def test_build(self):
        opt = OptionInstrument.build(
            exchange=Exchange.NSE,
            underlying="BANKNIFTY",
            expiry=date(2026, 9, 24),
            strike=52000.0,
            option_type=OptionType.CE,
            lot_size=15,
        )
        assert opt.instrument_id == "NSE_FO|BANKNIFTY-2026-09-24-CE-52000"
        assert opt.option_type == OptionType.CE
        assert make_option_local_id("banknifty", date(2026, 9, 24), "pe", 52000) == ("BANKNIFTY-2026-09-24-PE-52000")


class TestMarketBar:
    def bar(self, **overrides):
        base = {
            "instrument_id": "NSE_EQ|RELIANCE",
            "exchange": "NSE",
            "timestamp": ts("2025-06-02T10:00:00+00:00"),
            "timeframe": Timeframe.DAY,
            "open": 2400.0,
            "high": 2450.0,
            "low": 2390.0,
            "close": 2440.0,
            "volume": 1_000_000,
            "source": "NSE",
        }
        base.update(overrides)
        return MarketBar(**base)

    def test_valid_bar(self):
        bar = self.bar()
        assert bar.quality_status == QualityStatus.RAW
        assert bar.adjustment_status == AdjustmentStatus.UNADJUSTED

    def test_high_below_close_rejected(self):
        with pytest.raises(ValidationError):
            self.bar(high=2300.0)

    def test_low_above_open_rejected(self):
        with pytest.raises(ValidationError):
            self.bar(low=2410.0)

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            self.bar(close=-1)

    def test_negative_volume_rejected(self):
        with pytest.raises(ValidationError):
            self.bar(volume=-5)

    def test_frame_conversion_sorted(self):
        b1 = self.bar(timestamp=ts("2025-06-03T10:00:00+00:00"))
        b2 = self.bar()
        df = bars_to_frame([b1, b2])
        assert list(df["timestamp"]) == sorted(df["timestamp"])
        assert set(df.columns) >= {"open", "high", "low", "close", "volume"}


class TestCorporateAction:
    def test_dividend_requires_amount(self):
        with pytest.raises(ValidationError):
            CorporateAction(
                instrument_id="NSE_EQ|RELIANCE",
                action_type=CorporateActionType.DIVIDEND,
                ex_date=date(2025, 7, 4),
                source="NSE",
            )

    def test_split_ratio_adjustment(self):
        action = CorporateAction(
            instrument_id="NSE_EQ|XYZ",
            action_type=CorporateActionType.SPLIT,
            old_value=10.0,
            new_value=2.0,
            ex_date=date(2025, 7, 4),
            source="NSE",
        )
        assert action.adjustment_ratio() == pytest.approx(0.2)

    def test_bonus_ratio_parsing(self):
        action = CorporateAction(
            instrument_id="NSE_EQ|XYZ",
            action_type=CorporateActionType.BONUS,
            ratio=1.0,
            ex_date=date(2025, 7, 4),
            source="NSE",
        )
        assert action.adjustment_ratio() == pytest.approx(0.5)


class TestAnnouncement:
    def test_minimal(self):
        ann = Announcement(
            announcement_id="a1",
            instrument_id="NSE_EQ|RELIANCE",
            exchange="NSE",
            published_at=ts("2025-07-01T10:00:00+00:00"),
            headline="Board meeting intimation",
            source="NSE",
        )
        assert ann.extra == {}


class TestOptionQuote:
    def test_bid_ask_ordering_enforced(self):
        with pytest.raises(ValidationError):
            OptionQuote(
                instrument_id="NSE_FO|X",
                timestamp=ts("2025-07-01T10:00:00+00:00"),
                bid=105.0,
                ask=100.0,
                source="UPSTOX",
            )

    def test_greeks_live_here_only(self):
        q = OptionQuote(
            instrument_id="NSE_FO|X",
            timestamp=ts("2025-07-01T10:00:00+00:00"),
            delta=0.42,
            gamma=0.001,
            theta=-12.0,
            vega=8.0,
            implied_volatility=0.18,
            source="UPSTOX",
        )
        assert q.delta == 0.42


class TestLineage:
    def test_defaults(self):
        lineage = Lineage(source="NSE", source_tool="nse_equity_historical")
        assert lineage.schema_version == 1
        assert lineage.ingestion_timestamp.tzinfo is not None
