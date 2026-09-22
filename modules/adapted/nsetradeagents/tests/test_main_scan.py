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


"""Tests for run_scan, the daily live entry point.

Collaborators (universe, screener, graph, simulator) are stubbed so these cover
the scan's own control flow: what gets recorded, when it stops early, and how it
handles a ticker that fails.
"""

from contextlib import contextmanager

import pytest
from app.core import health
from app.models.models import DecisionRecord, ScanRun

import main


def candidate(ticker: str, score: float = 0.8) -> dict:
    return {"ticker": ticker, "score": score}


def state(*, executed: bool, rules_score: int = 71) -> dict:
    """A plausible final graph state."""
    return {
        "trade_result": (
            {
                "executed": True,
                "action": "BUY",
                "ticker": "X",
                "price": 500.0,
                "quantity": 50,
                "position_size_inr": 25000.0,
                "stop_loss": 465.0,
                "take_profit": 590.0,
                "sector": "IT",
                "atr_pct": 2.4,
                "confidence": rules_score,
                "reasoning": "",
            }
            if executed
            else {"action": "BLOCKED", "executed": False, "reasons": ["score too low"]}
        ),
        "rules_score": rules_score,
        "rules_bands": {
            "entry_timing": "ACCEPTABLE",
            "momentum_quality": "STRONG",
            "risk_reward_view": "FAVORABLE",
            "market_regime": "NEUTRAL",
        },
        "technical_signals": {
            "indicators": {
                "current_price": 500.0,
                "rsi": 62.0,
                "atr_pct": 2.4,
                "volume_ratio": 3.1,
                "momentum_5d": 5.2,
                "day_change_pct": 1.8,
            }
        },
    }


def portfolio(open_positions: int = 0, positions: list | None = None) -> dict:
    return {
        "cash": 200000.0,
        "open_positions": open_positions,
        "positions": positions or [],
    }


@pytest.fixture
def scan_env(db_session, monkeypatch):
    """Wire run_scan to an in-memory DB and stubbed collaborators."""

    @contextmanager
    def _get_db():
        yield db_session

    monkeypatch.setattr(main, "get_db", _get_db)
    monkeypatch.setattr(main, "fetch_universe", lambda: ["A.NS", "B.NS"])
    monkeypatch.setattr(main.simulator, "is_circuit_breaker_active", lambda: False)
    monkeypatch.setattr(main.simulator, "get_portfolio_state", portfolio)
    monkeypatch.setattr(main.simulator, "save_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(main.simulator, "open_trade", lambda **k: None)
    monkeypatch.setattr(main.settings, "max_positions", 5)
    return db_session


def records(db):
    return db.query(DecisionRecord).all()


# ── the happy path ───────────────────────────────────────────────────────────


def test_scan_runs_end_to_end_and_writes_a_record(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=True))

    main.run_scan()

    rows = records(scan_env)
    assert len(rows) == 1
    assert rows[0].ticker == "A.NS"
    assert rows[0].score == 71
    assert rows[0].entered is True
    assert rows[0].as_of is not None


def test_screen_is_called_with_tickers_only(scan_env, monkeypatch):
    """screen() takes the ticker list and nothing else."""
    seen = {}

    def fake_screen(tickers):
        seen["tickers"] = tickers
        return [], True, 62.0

    monkeypatch.setattr(main, "screen", fake_screen)
    main.run_scan()
    assert seen["tickers"] == ["A.NS", "B.NS"]


# ── records are written for rejections too ───────────────────────────────────


def test_blocked_candidate_still_gets_a_record(scan_env, monkeypatch):
    """The whole point of decision records: we keep the 'no' decisions."""
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    rows = records(scan_env)
    assert len(rows) == 1
    assert rows[0].entered is False
    assert rows[0].block_reason == "score too low"


def test_record_captures_bands_and_indicators(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    row = records(scan_env)[0]
    assert row.market_regime == "NEUTRAL"
    assert row.momentum_quality == "STRONG"
    assert row.rsi == 62.0
    assert row.atr_pct == 2.4
    assert row.veto_verdict is None  # this stubbed state never reached the veto
    assert row.outcome_pnl_pct is None  # post-mortem fills this later


# ── the veto's provenance ────────────────────────────────────────────────────


def test_the_verdict_and_its_provenance_are_recorded(scan_env, monkeypatch):
    """Model and mode mark population boundaries — an Opus verdict in shadow
    mode is not comparable with a Sonnet verdict in acting mode."""
    s = state(executed=False)
    s["veto_result"] = {
        "verdict": "KILL",
        "reason": "EARNINGS_IMMINENT",
        "cited_fact": "Q2 results on 14 Aug",
        "source_url": "https://example.com/calendar",
        "checked": "results calendar",
        "transcript": '[search] {"query": "results date"}',
        "model": "claude-opus-5",
    }
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: s)
    monkeypatch.setattr(main.settings, "veto_mode", "shadow")

    main.run_scan()

    row = records(scan_env)[0]
    assert row.veto_verdict == "KILL"
    assert row.veto_reason == "EARNINGS_IMMINENT"
    assert row.veto_transcript == '[search] {"query": "results date"}'
    assert row.veto_model == "claude-opus-5"
    assert row.veto_mode == "shadow"


def test_the_mode_is_recorded_even_when_the_veto_never_ran(scan_env, monkeypatch):
    """Why mode comes from settings, not the verdict: with VETO_MODE=off there
    is no verdict to read it from, and those rows must not look like passes."""
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))
    monkeypatch.setattr(main.settings, "veto_mode", "off")

    main.run_scan()

    row = records(scan_env)[0]
    assert row.veto_verdict is None
    assert row.veto_mode == "off"


# ── early exits ──────────────────────────────────────────────────────────────


def test_no_candidates_writes_nothing(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: ([], True, 62.0))
    main.run_scan()
    assert records(scan_env) == []


def test_circuit_breaker_stops_the_scan(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main.simulator, "is_circuit_breaker_active", lambda: True)
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: pytest.fail("should not analyse"))

    main.run_scan()
    assert records(scan_env) == []


def test_stops_when_portfolio_is_full(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main.simulator, "get_portfolio_state", lambda: portfolio(5))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: pytest.fail("should not analyse"))

    main.run_scan()
    assert records(scan_env) == []


def test_skips_tickers_already_held(scan_env, monkeypatch):
    held = portfolio(1, [{"ticker": "A.NS", "sector": "IT"}])
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main.simulator, "get_portfolio_state", lambda: held)
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: pytest.fail("should not analyse"))

    main.run_scan()
    assert records(scan_env) == []


# ── failure handling ─────────────────────────────────────────────────────────


def test_one_bad_ticker_does_not_stop_the_scan(scan_env, monkeypatch):
    """A single ticker blowing up must not cost us the rest of the day."""

    def flaky(*, ticker, **k):
        if ticker == "A.NS":
            msg = "yfinance exploded"
            raise RuntimeError(msg)
        return state(executed=False)

    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS"), candidate("B.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", flaky)

    main.run_scan()

    rows = records(scan_env)
    assert [r.ticker for r in rows] == ["B.NS"]


# ── the heartbeat ────────────────────────────────────────────────────────────


def runs(db):
    return db.query(ScanRun).order_by(ScanRun.id).all()


def test_scan_records_a_run_even_when_nothing_is_found(scan_env, monkeypatch):
    """The reason ScanRun exists rather than counting DecisionRecords.

    A quiet day writes no decisions, and so does a scheduler that never fired.
    Without this row the health check cannot tell them apart.
    """
    monkeypatch.setattr(main, "screen", lambda t: ([], True, 62.0))

    main.run_scan()

    assert records(scan_env) == []
    rows = runs(scan_env)
    assert len(rows) == 1
    assert rows[0].candidates_found == 0
    assert rows[0].error is None
    assert rows[0].ran_at is not None


def test_scan_records_the_candidate_count(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS"), candidate("B.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    assert runs(scan_env)[0].candidates_found == 2


def test_circuit_breaker_still_records_a_run(scan_env, monkeypatch):
    """An early return is still a run — finally fires on the way out."""
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main.simulator, "is_circuit_breaker_active", lambda: True)

    main.run_scan()

    rows = runs(scan_env)
    assert len(rows) == 1
    assert rows[0].candidates_found == 1  # found them, just didn't act on them


def test_scan_records_the_error_when_it_crashes(scan_env, monkeypatch):
    """A crashed scan must leave a trace, not just vanish."""

    def boom(tickers):
        msg = "universe fetch died"
        raise RuntimeError(msg)

    monkeypatch.setattr(main, "screen", boom)

    with pytest.raises(RuntimeError):
        main.run_scan()

    rows = runs(scan_env)
    assert len(rows) == 1
    assert "universe fetch died" in rows[0].error


def test_a_broken_heartbeat_write_does_not_mask_the_real_error(monkeypatch):
    """An exception raised inside finally replaces the one on its way out.

    If the database is down, the useful error is whatever actually failed —
    not the follow-on failure to record that it failed.
    """

    @contextmanager
    def dead_db():
        msg = "database unreachable"
        raise RuntimeError(msg)
        yield  # pragma: no cover

    monkeypatch.setattr(main, "get_db", dead_db)
    monkeypatch.setattr(main, "fetch_universe", lambda: ["A.NS"])
    monkeypatch.setattr(main, "screen", lambda t: (_ for _ in ()).throw(ValueError("the real problem")))

    with pytest.raises(ValueError, match="the real problem"):
        main.run_scan()


def test_the_heartbeat_is_reported_in_memory_too(scan_env, monkeypatch):
    """/health reads the cached value rather than querying, so the scan must
    push it — otherwise health stays stale until the process restarts."""
    monkeypatch.setattr(main, "screen", lambda t: ([], True, 62.0))

    main.run_scan()

    assert health._last_scan is not None
    assert health._loaded is True


# ── a blocked regime still collects data ─────────────────────────────────────
#
# The gate stops execution, not observation. Breadth was shut on 40% of
# sessions 2022-25 (57% in 2025) with closed streaks up to 74 sessions, so a
# scan that records nothing on blocked days could gather no shadow data for
# months.


def test_a_blocked_regime_records_decisions_but_opens_nothing(scan_env, monkeypatch):
    opened = []
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], False, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=True))
    monkeypatch.setattr(main.simulator, "open_trade", lambda **k: opened.append(k))

    main.run_scan()

    rows = records(scan_env)
    assert len(rows) == 1, "the decision must still be recorded"
    assert opened == [], "but no position may be opened"


def test_a_blocked_regime_marks_the_reason_on_the_record(scan_env, monkeypatch):
    """Without this you cannot tell later whether a skip was the score or the
    regime — which is exactly what makes the gate measurable after the fact."""
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], False, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=True))

    main.run_scan()

    row = records(scan_env)[0]
    assert row.entered is False
    assert row.block_reason.startswith("regime:")


def test_a_score_block_keeps_its_own_reason_when_the_regime_is_shut(scan_env, monkeypatch):
    """The regime reason only replaces the block reason for trades that would
    otherwise have executed."""
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], False, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    assert records(scan_env)[0].block_reason == "score too low"


def test_the_shadow_sample_is_capped_on_a_blocked_day(scan_env, monkeypatch):
    """No position ever opens, so the max-positions break never fires. Without
    a cap, 20 candidates would mean 20 veto calls on a day with no trades."""
    many = [candidate(f"T{i}.NS") for i in range(20)]
    monkeypatch.setattr(main, "screen", lambda t: (many, False, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))
    monkeypatch.setattr(main.settings, "max_positions", 5)

    main.run_scan()

    assert len(records(scan_env)) == 5


def test_an_open_regime_is_not_capped_by_the_shadow_limit(scan_env, monkeypatch):
    """On a normal day the position count does the limiting, and candidates
    blocked on score must not consume the budget."""
    many = [candidate(f"T{i}.NS") for i in range(20)]
    monkeypatch.setattr(main, "screen", lambda t: (many, True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    assert len(records(scan_env)) == 20


def test_the_regime_state_is_recorded_on_every_decision(scan_env, monkeypatch):
    """The gate only reaches block_reason for candidates that would otherwise
    have executed. Without this column a score-blocked candidate looks the same
    in an open and a shut market, and the gate can never be judged."""
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], False, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    row = records(scan_env)[0]
    assert row.regime_open is False
    assert row.block_reason == "score too low"  # the regime is not in here


def test_an_open_regime_is_recorded_too(scan_env, monkeypatch):
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    assert records(scan_env)[0].regime_open is True


def test_the_breadth_reading_is_recorded_not_just_the_verdict(scan_env, monkeypatch):
    """Storing only regime_open would freeze the 50% floor permanently — the
    raw reading is what lets the threshold be re-examined against outcomes."""
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], False, 43.7))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: state(executed=False))

    main.run_scan()

    row = records(scan_env)[0]
    assert row.breadth_pct == pytest.approx(43.7)
    assert row.regime_open is False


def test_the_market_context_inputs_are_recorded(scan_env, monkeypatch):
    """market_regime is 25 of the 100 points and cannot rank candidates.
    Recalibrating it later needs the values it was derived from, not the band."""
    s = state(executed=False)
    s["market_context"] = {"india_vix": 14.2, "nifty_20d_pct": -3.1}
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main, "analyze_ticker", lambda **k: s)

    main.run_scan()

    row = records(scan_env)[0]
    assert row.india_vix == pytest.approx(14.2)
    assert row.nifty_20d_pct == pytest.approx(-3.1)


# ── the daily snapshot ───────────────────────────────────────────────────────


def test_a_snapshot_is_saved_even_when_nothing_is_found(scan_env, monkeypatch):
    """The equity curve must not have holes on flat days. This used to sit
    after the candidate loop, so a quiet or blocked market recorded nothing and
    the dashboard stayed blank until the first trade."""
    saved = []
    monkeypatch.setattr(main, "screen", lambda t: ([], True, 62.0))
    monkeypatch.setattr(main.simulator, "save_snapshot", lambda *a, **k: saved.append(1))

    main.run_scan()

    assert saved == [1]


def test_a_snapshot_is_saved_when_the_circuit_breaker_fires(scan_env, monkeypatch):
    saved = []
    monkeypatch.setattr(main, "screen", lambda t: ([candidate("A.NS")], True, 62.0))
    monkeypatch.setattr(main.simulator, "is_circuit_breaker_active", lambda: True)
    monkeypatch.setattr(main.simulator, "save_snapshot", lambda *a, **k: saved.append(1))

    main.run_scan()

    assert saved == [1]


def test_a_snapshot_is_saved_even_when_the_scan_crashes(scan_env, monkeypatch):
    saved = []

    def boom(tickers):
        msg = "universe fetch died"
        raise RuntimeError(msg)

    monkeypatch.setattr(main, "screen", boom)
    monkeypatch.setattr(main.simulator, "save_snapshot", lambda *a, **k: saved.append(1))

    with pytest.raises(RuntimeError):
        main.run_scan()

    assert saved == [1]


def test_a_failing_snapshot_does_not_mask_the_real_error(scan_env, monkeypatch):
    """Raised from inside finally, it would replace the exception on its way
    out — same trap as the heartbeat write."""

    def boom(tickers):
        msg = "the real problem"
        raise ValueError(msg)

    monkeypatch.setattr(main, "screen", boom)
    monkeypatch.setattr(
        main.simulator,
        "save_snapshot",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )

    with pytest.raises(ValueError, match="the real problem"):
        main.run_scan()
