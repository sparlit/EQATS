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


"""
Tests for PR-5a — closing the learn-from-losses loop:

- feedback.build_outcome / learn_from_outcome / mark_lessons_outcome / lesson_ids
- analyzer.compute_outcome (standalone)
- PerformanceTracker persistence + fixed get_summary
"""

from unittest.mock import MagicMock

from src.memory.analyzer import compute_outcome
from src.memory.feedback import (
    build_outcome,
    learn_from_outcome,
    lesson_ids,
    mark_lessons_outcome,
)
from src.memory.performance_tracker import PerformanceTracker

# ---------------------------------------------------------------------------
# compute_outcome (standalone, no journal)
# ---------------------------------------------------------------------------


def test_compute_outcome_loser():
    outcome = compute_outcome(
        {
            "side": "BUY",
            "entry_price": 100,
            "exit_price": 95,
            "profit_loss": -50,
            "mfe": 0,
            "mae": 50,
            "stop_loss": 95,
            "target_price": 110,
        }
    )
    assert outcome is not None
    assert outcome.is_winner is False
    assert outcome.hit_stop_loss is True


def test_compute_outcome_inefficient_winner():
    outcome = compute_outcome(
        {
            "side": "BUY",
            "entry_price": 100,
            "exit_price": 105,
            "profit_loss": 50,
            "mfe": 200,
            "mae": 0,
        }
    )
    assert outcome.is_winner is True
    assert outcome.efficiency == 0.25  # captured 50 of 200 MFE


# ---------------------------------------------------------------------------
# feedback helpers
# ---------------------------------------------------------------------------


def test_build_outcome():
    outcome = build_outcome(
        trade_id="T1",
        symbol="AAPL",
        strategy="momentum",
        regime="trending_up",
        side="BUY",
        entry_price=100,
        exit_price=90,
        stop_loss=92,
        target_price=110,
        pnl=-100,
        pnl_pct=-10,
        mae=120,
        mfe=20,
        hold_minutes=15,
    )
    assert outcome is not None
    assert outcome.is_winner is False
    assert outcome.symbol == "AAPL"


def test_learn_from_outcome_stores_when_classified():
    classifier = MagicMock()
    mistake = MagicMock(severity="high", category="stop_loss_too_tight")
    classifier.classify.return_value = mistake
    injector = MagicMock()

    result = learn_from_outcome(injector, classifier, MagicMock())
    assert result is mistake
    injector.store_from_classifier.assert_called_once_with(mistake)


def test_learn_from_outcome_skips_when_not_classified():
    classifier = MagicMock()
    classifier.classify.return_value = None
    injector = MagicMock()

    assert learn_from_outcome(injector, classifier, MagicMock()) is None
    injector.store_from_classifier.assert_not_called()


def test_learn_from_outcome_never_raises():
    classifier = MagicMock()
    classifier.classify.side_effect = RuntimeError("LLM down")
    injector = MagicMock()
    # Must swallow the error.
    assert learn_from_outcome(injector, classifier, MagicMock()) is None


def test_learn_from_outcome_none_outcome():
    classifier = MagicMock()
    assert learn_from_outcome(MagicMock(), classifier, None) is None
    classifier.classify.assert_not_called()


def test_mark_lessons_outcome_marks_each_id():
    memory_db = MagicMock()
    count = mark_lessons_outcome(memory_db, ["a", "b", "", None], was_successful=True)
    assert count == 2
    memory_db.mark_used.assert_any_call("a", was_successful=True)
    memory_db.mark_used.assert_any_call("b", was_successful=True)


def test_lesson_ids_extracts_and_skips_missing():
    lessons = [{"lesson_id": "L1"}, {"foo": "bar"}, {"lesson_id": "L2"}]
    assert lesson_ids(lessons) == ["L1", "L2"]
    assert lesson_ids(None) == []


# ---------------------------------------------------------------------------
# PerformanceTracker persistence + get_summary
# ---------------------------------------------------------------------------


def test_perf_tracker_persists_across_restart(tmp_path):
    path = tmp_path / "perf.json"
    t1 = PerformanceTracker(min_trades_for_real_data=2, state_file=path)
    t1.record_trade("momentum", "trending_up", 100, 1.0)
    t1.record_trade("momentum", "trending_up", -50, -0.5)

    t2 = PerformanceTracker(min_trades_for_real_data=2, state_file=path)
    perf = t2.get_strategy_performance("momentum", "trending_up")
    assert perf.total_trades == 2
    assert perf.win_rate == 0.5


def test_get_summary_by_strategy_is_well_formed(tmp_path):
    t = PerformanceTracker(state_file=tmp_path / "p.json")
    t.record_trade("momentum", "trending_up", 100, 1.0)
    t.record_trade("momentum", "trending_up", 50, 0.5)
    t.record_trade("mean_reversion", "ranging", -20, -0.2)

    summary = t.get_summary()
    assert summary["total_trades"] == 3
    assert set(summary["by_strategy"].keys()) == {"momentum", "mean_reversion"}
    assert summary["by_strategy"]["momentum"]["trades"] == 2
    assert summary["by_strategy"]["momentum"]["win_rate"] == 1.0
    assert summary["by_strategy"]["mean_reversion"]["win_rate"] == 0.0
