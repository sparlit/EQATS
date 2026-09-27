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


"""Tests for journal CRUD operations in PgMetadataStore."""

import sys
from pathlib import Path

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.config.connections import get_engine
from indian_quant.storage.pg_metadata import PgMetadataStore

# All test symbols created by this module
_TEST_SYMBOLS = ("TESTJOURNAL", "TESTEXIT", "TESTREVIEW", "TESTLIST", "TESTSETUP", "TESTSTOP")


@pytest.fixture
def pg_store():
    """Create a PgMetadataStore, yield it, then clean up test data."""
    engine = get_engine()
    store = PgMetadataStore(engine)
    yield store
    # Cleanup: delete test data
    with engine.begin() as conn:
        for sym in _TEST_SYMBOLS:
            conn.execute(sa.text("DELETE FROM trade_journal WHERE symbol = :sym"), {"sym": sym})
            conn.execute(sa.text("DELETE FROM paper_signals WHERE symbol = :sym"), {"sym": sym})
    store.close()


class TestJournalCRUD:
    def test_journal_record_on_entry(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="TESTJOURNAL", close_at_signal=100.0, qty=10, horizon_days=10, stop_pct=0.07, segment="EQ"
        )
        journal_id = pg_store.journal_record_on_entry(
            paper_trade_id=pid,
            symbol="TESTJOURNAL",
            entry_date="2026-09-01",
            entry_price=100.0,
            entry_signal="dz_hi_up",
            setup_type="delivery_momentum",
            stop_loss=93.0,
            target_price=110.0,
            position_size=10,
            risk_amount=70.0,
            conviction=0.5,
            sector="Test",
        )
        assert journal_id > 0

        entry = pg_store.journal_entry(pid)
        assert entry is not None
        assert entry["symbol"] == "TESTJOURNAL"
        assert entry["setup_type"] == "delivery_momentum"
        assert entry["stop_loss"] == 93.0

    def test_journal_record_on_exit(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="TESTEXIT", close_at_signal=100.0, qty=10, horizon_days=10, stop_pct=0.07, segment="EQ"
        )
        pg_store.journal_record_on_entry(
            paper_trade_id=pid, symbol="TESTEXIT", entry_date="2026-09-01", entry_price=100.0, entry_signal="dz_hi_up"
        )

        result = pg_store.journal_record_on_exit(
            pid,
            exit_date="2026-09-10",
            exit_price=105.0,
            exit_reason="HORIZON",
            days_held=7,
            return_pct=5.0,
            return_bps=500.0,
            net_bps=393.0,
        )
        assert result is True

        entry = pg_store.journal_entry(pid)
        assert entry["exit_price"] == 105.0
        assert entry["exit_reason"] == "HORIZON"
        assert entry["net_bps"] == 393.0

    def test_journal_add_review(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="TESTREVIEW", close_at_signal=100.0, qty=10, horizon_days=10, stop_pct=0.07, segment="EQ"
        )
        pg_store.journal_record_on_entry(
            paper_trade_id=pid, symbol="TESTREVIEW", entry_date="2026-09-01", entry_price=100.0, entry_signal="dz_hi_up"
        )

        result = pg_store.journal_add_review(
            pid,
            review_rating=4,
            what_went_right="Good signal",
            what_went_wrong="Could have held longer",
            lessons_learned="Patience pays",
            would_repeat=True,
            setup_quality="A",
            execution_grade="B",
        )
        assert result is True

        entry = pg_store.journal_entry(pid)
        assert entry["review_rating"] == 4
        assert entry["what_went_right"] == "Good signal"
        assert entry["would_repeat"] is True

    def test_journal_list(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="TESTLIST", close_at_signal=100.0, qty=10, horizon_days=10, stop_pct=0.07, segment="EQ"
        )
        pg_store.journal_record_on_entry(
            paper_trade_id=pid,
            symbol="TESTLIST",
            entry_date="2026-09-01",
            entry_price=100.0,
            entry_signal="dz_hi_up",
            setup_type="delivery_momentum",
        )

        entries = pg_store.journal_list(limit=500)
        assert len(entries) >= 1
        symbols = [e["symbol"] for e in entries]
        assert "TESTLIST" in symbols

    def test_journal_list_by_setup(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="TESTSETUP", close_at_signal=100.0, qty=10, horizon_days=10, stop_pct=0.07, segment="EQ"
        )
        pg_store.journal_record_on_entry(
            paper_trade_id=pid,
            symbol="TESTSETUP",
            entry_date="2026-09-01",
            entry_price=100.0,
            entry_signal="surveillance",
            setup_type="surveillance_recovery",
        )

        entries = pg_store.journal_list(setup_type="surveillance_recovery")
        assert any(e["symbol"] == "TESTSETUP" for e in entries)

    def test_journal_stats(self, pg_store):
        stats = pg_store.journal_stats()
        assert "total_trades" in stats
        assert "winners" in stats
        assert "losers" in stats

    def test_journal_update_stop(self, pg_store):
        pid = pg_store.record_paper_signal(
            symbol="TESTSTOP", close_at_signal=100.0, qty=10, horizon_days=10, stop_pct=0.07, segment="EQ"
        )
        pg_store.journal_record_on_entry(
            paper_trade_id=pid, symbol="TESTSTOP", entry_date="2026-09-01", entry_price=100.0, entry_signal="dz_hi_up"
        )

        result = pg_store.journal_update_stop(
            pid, date="2026-09-05", old_stop=93.0, new_stop=95.0, reason="Trailing stop"
        )
        assert result is True

        entry = pg_store.journal_entry(pid)
        assert entry["stop_moved"] is True
