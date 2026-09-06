"""Tests for the post-mortem job.

`_simulate` is exercised against synthetic bars with known outcomes;
`fill_outcomes` is exercised against an in-memory database with the price
download stubbed.
"""

from contextlib import contextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from app.models.models import DecisionRecord
from app.portfolio import postmortem
from app.portfolio.postmortem import _simulate, fill_outcomes

ENTRY_DAY = date(2024, 1, 1)


def bars(closes: list[float], start: date = ENTRY_DAY) -> pd.DataFrame:
    """Daily OHLCV where each bar spans ±1% around its close."""
    idx = pd.DatetimeIndex([start + timedelta(days=i) for i in range(len(closes))])
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c * 1.01 for c in closes],
            "Low": [c * 0.99 for c in closes],
            "Close": closes,
        },
        index=idx,
    )


def record(as_of: date = ENTRY_DAY, atr_pct: float = 3.0) -> SimpleNamespace:
    return SimpleNamespace(as_of=as_of, atr_pct=atr_pct, ticker="TEST.NS")


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setattr("app.core.config.settings.max_hold_days", 21)
    monkeypatch.setattr("app.core.config.settings.take_profit_pct", 0.18)
    monkeypatch.setattr("app.core.config.settings.stop_loss_pct", 0.07)
    monkeypatch.setattr("app.core.config.settings.trail_activation_pct", 0.12)
    monkeypatch.setattr("app.core.config.settings.trail_min_pct", 0.05)
    monkeypatch.setattr("app.core.config.settings.trail_max_pct", 0.08)


# ── _simulate ─────────────────────────────────────────────────────────────────


def test_entry_is_the_decision_day_close():
    """The post-mortem must grade the trade the live system actually takes.

    Live scans at 15:00 and buys before the close, so entry is the close of
    the decision day — not the next morning's open.
    """
    pnl, reason, exit_date = _simulate(record(), bars([100.0, 95.0, 88.0, 80.0]))

    assert reason == "stop"
    # atr 3% -> stop 2.5x = 7.5% -> 92.5, breached by the 88 bar
    assert pnl == pytest.approx(-12.0, abs=0.5)
    assert exit_date == ENTRY_DAY + timedelta(days=2)


def test_gap_through_the_stop_fills_at_the_open():
    # entry 100, stop 92.5. The next bar opens far below it.
    pnl, reason, _ = _simulate(record(), bars([100.0, 80.0]))
    assert reason == "stop"
    assert pnl == pytest.approx(-20.0, abs=0.5)  # filled at 80, not 92.5


def test_target_hit():
    """Target is 4x ATR, so 12% on a 3%-ATR stock — not the flat 18%."""
    pnl, reason, _ = _simulate(record(), bars([100.0] + [100 + i * 3 for i in range(1, 8)]))
    assert reason == "target"
    assert pnl == pytest.approx(12.0, abs=0.5)


def test_flat_stock_times_out_at_zero():
    pnl, reason, _ = _simulate(record(), bars([100.0] * 26))
    assert reason == "timeout"
    assert pnl == pytest.approx(0.0, abs=0.5)


def test_trailing_stop_locks_in_gains_below_the_target():
    """Runs to +10% (never reaching the +12% target), then fades.

    Entry 100 -> stop 92.5, target 112. The trail arms at 2x ATR (+6%), peak
    110 puts it at 110 x 0.94 = 103.4, and the fade to 103 trips it.

    The assertion on `reason` is what distinguishes a working trail from a
    position that simply timed out.
    """
    pnl, reason, _ = _simulate(record(), bars([100.0, 104.0, 110.0, 103.0]))
    assert reason == "trail"
    assert pnl == pytest.approx(3.0, abs=0.5)


def test_returns_none_without_enough_history():
    """A decision day with no bar after it cannot be graded yet."""
    assert _simulate(record(), bars([100.0])) is None


def test_returns_none_when_still_open():
    """Not yet resolved — leave it pending rather than guessing."""
    assert _simulate(record(), bars([100.0, 101.0, 102.0])) is None


def test_zero_atr_falls_back_to_the_default_stop():
    """With no ATR recorded, both levels fall back to the flat defaults."""
    pnl, reason, _ = _simulate(record(atr_pct=0.0), bars([100.0, 90.0]))
    assert reason == "stop"
    assert pnl == pytest.approx(-10.0, abs=0.5)  # flat 7% stop at 93, gapped to 90


# ── fill_outcomes ─────────────────────────────────────────────────────────────


@pytest.fixture
def pm_db(db_session, monkeypatch):
    @contextmanager
    def _get_db():
        yield db_session

    monkeypatch.setattr(postmortem, "get_db", _get_db)
    return db_session


def add_record(db, ticker="TEST.NS", days_ago=40, filled=False):
    row = DecisionRecord(
        as_of=date.today() - timedelta(days=days_ago),
        ticker=ticker,
        score=71,
        atr_pct=3.0,
        entered=False,
        outcome_pnl_pct=-5.0 if filled else None,
    )
    db.add(row)
    db.flush()
    return row


def test_fills_a_pending_record(pm_db, monkeypatch):
    add_record(pm_db)
    frame = bars([100.0, 100.0, 95.0, 88.0, 80.0], start=date.today() - timedelta(days=40))

    monkeypatch.setattr(postmortem, "safe_yf_download", lambda *a, **k: frame)
    monkeypatch.setattr(postmortem, "extract_ticker_df", lambda raw, t: frame)

    assert fill_outcomes() == 1

    row = pm_db.query(DecisionRecord).first()
    assert row.outcome_pnl_pct is not None
    assert row.outcome_reason == "stop"
    assert row.outcome_filled_at is not None


def test_ignores_records_that_are_too_recent(pm_db, monkeypatch):
    add_record(pm_db, days_ago=3)
    monkeypatch.setattr(
        postmortem, "safe_yf_download", lambda *a, **k: pytest.fail("should not fetch")
    )
    assert fill_outcomes() == 0


def test_ignores_already_filled_records(pm_db, monkeypatch):
    add_record(pm_db, filled=True)
    monkeypatch.setattr(
        postmortem, "safe_yf_download", lambda *a, **k: pytest.fail("should not fetch")
    )
    assert fill_outcomes() == 0


def test_one_bad_ticker_does_not_stop_the_job(pm_db, monkeypatch):
    add_record(pm_db, ticker="GOOD.NS")
    add_record(pm_db, ticker="BAD.NS")
    frame = bars([100.0, 100.0, 95.0, 88.0, 80.0], start=date.today() - timedelta(days=40))

    def flaky(raw, ticker):
        if ticker == "BAD.NS":
            raise ValueError("malformed frame")
        return frame

    monkeypatch.setattr(postmortem, "safe_yf_download", lambda *a, **k: frame)
    monkeypatch.setattr(postmortem, "extract_ticker_df", flaky)

    assert fill_outcomes() == 1


def test_unresolved_records_stay_pending(pm_db, monkeypatch):
    """No stop/target hit yet and no timeout — try again tomorrow."""
    add_record(pm_db)
    frame = bars([100.0, 100.0, 101.0], start=date.today() - timedelta(days=40))

    monkeypatch.setattr(postmortem, "safe_yf_download", lambda *a, **k: frame)
    monkeypatch.setattr(postmortem, "extract_ticker_df", lambda raw, t: frame)

    assert fill_outcomes() == 0
    assert pm_db.query(DecisionRecord).first().outcome_pnl_pct is None


# ── alpha ─────────────────────────────────────────────────────────────────────
#
# Raw return misjudges whole years. In 2025 the system lost 4.2% while its
# universe lost 5.3% — a good year that looks like a bad one.


def test_alpha_is_the_outcome_minus_the_benchmark(pm_db, monkeypatch):
    add_record(pm_db)
    start = date.today() - timedelta(days=40)
    stock = bars([100.0, 95.0, 88.0, 80.0], start=start)   # stops out at -12%
    index = bars([100.0, 98.0, 96.0, 94.0], start=start)   # index falls too

    def fake_download(tickers, *a, **k):
        return index if tickers == postmortem.BENCHMARK else stock

    monkeypatch.setattr(postmortem, "safe_yf_download", fake_download)
    monkeypatch.setattr(postmortem, "extract_ticker_df", lambda raw, t: stock)

    assert fill_outcomes() == 1

    row = pm_db.query(DecisionRecord).first()
    assert row.outcome_pnl_pct == pytest.approx(-12.0, abs=0.5)
    # index went 100 -> 96 over the same window, so -4%
    assert row.outcome_alpha_pct == pytest.approx(-8.0, abs=0.5)


def test_losing_less_than_the_market_is_positive_alpha(pm_db, monkeypatch):
    add_record(pm_db)
    start = date.today() - timedelta(days=40)
    stock = bars([100.0, 95.0, 88.0, 80.0], start=start)   # -12%
    index = bars([100.0, 90.0, 80.0, 70.0], start=start)   # index falls harder

    def fake_download(tickers, *a, **k):
        return index if tickers == postmortem.BENCHMARK else stock

    monkeypatch.setattr(postmortem, "safe_yf_download", fake_download)
    monkeypatch.setattr(postmortem, "extract_ticker_df", lambda raw, t: stock)

    fill_outcomes()

    row = pm_db.query(DecisionRecord).first()
    assert row.outcome_pnl_pct < 0
    assert row.outcome_alpha_pct > 0


def test_a_missing_benchmark_still_records_the_raw_outcome(pm_db, monkeypatch):
    """A failed index download must not cost us the outcome itself."""
    add_record(pm_db)
    start = date.today() - timedelta(days=40)
    stock = bars([100.0, 95.0, 88.0, 80.0], start=start)

    def fake_download(tickers, *a, **k):
        if tickers == postmortem.BENCHMARK:
            raise RuntimeError("index unavailable")
        return stock

    monkeypatch.setattr(postmortem, "safe_yf_download", fake_download)
    monkeypatch.setattr(postmortem, "extract_ticker_df", lambda raw, t: stock)

    assert fill_outcomes() == 1

    row = pm_db.query(DecisionRecord).first()
    assert row.outcome_pnl_pct is not None
    assert row.outcome_alpha_pct is None


def test_the_exit_date_is_recorded(pm_db, monkeypatch):
    """Without it the holding window is unknown, so alpha cannot be recomputed."""
    add_record(pm_db)
    start = date.today() - timedelta(days=40)
    frame = bars([100.0, 95.0, 88.0, 80.0], start=start)

    monkeypatch.setattr(postmortem, "safe_yf_download", lambda *a, **k: frame)
    monkeypatch.setattr(postmortem, "extract_ticker_df", lambda raw, t: frame)

    fill_outcomes()

    row = pm_db.query(DecisionRecord).first()
    assert row.outcome_exit_date == start + timedelta(days=2)
