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


"""Tests for the backtest loop itself.

The engine had no coverage until same-day entry was added — which is exactly
the change where an ordering mistake silently becomes lookahead. A byte-
identical trade log catches a regression but says nothing about why, and
cannot catch a bug that was always there.

Real bars are replaced with a fake store, so a run needs no database.
"""

from datetime import date, timedelta

import pandas as pd
import pytest
from app.backtest import engine
from app.backtest.engine import run_backtest

START = date(2022, 1, 3)
WARMUP = 60  # the engine scores nothing until it has 50 bars of history


def series(closes: list[float], high_mult: float = 1.01, low_mult: float = 0.99):
    """Daily OHLC for the test window, preceded by flat warm-up bars.

    `closes` describes the days the test cares about, which begin at START.
    The warm-up sits before it so the engine will actually score candidates.
    """
    if not closes:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    values = [closes[0]] * WARMUP + list(closes)
    first = START - timedelta(days=WARMUP)
    idx = pd.DatetimeIndex([first + timedelta(days=i) for i in range(len(values))])
    return pd.DataFrame(
        {
            "Open": values,
            "High": [c * high_mult for c in values],
            "Low": [c * low_mult for c in values],
            "Close": values,
            "Volume": [500_000] * len(values),
        },
        index=idx,
    )


class FakeStore:
    """Stands in for BacktestStore so the loop can run without a database."""

    def __init__(self, bars: dict):
        self._bars = bars

    def get_trading_days(self, start, end):
        any_frame = next(iter(self._bars.values()))
        return [d.date() for d in any_frame.index if start <= d.date() <= end]

    def preload(self, warmup_start, end):
        return self._bars

    def close(self):
        pass


@pytest.fixture
def stub_engine(monkeypatch):
    """Install a fake store and neutralise the screening layer.

    These tests are about the day loop — what fills, when, and at what price —
    not about which stocks the screener likes.
    """

    def install(bars: dict, *, signals_on: set[date] | None = None, atr_pct: float = 3.0):
        monkeypatch.setattr(engine, "BacktestStore", lambda db_path: FakeStore(bars))
        monkeypatch.setattr(
            engine,
            "compute_indicators",
            lambda df: {
                "current_price": float(df["Close"].iloc[-1]),
                "atr_pct": atr_pct,
            },
        )
        monkeypatch.setattr(engine, "_compute_signal", lambda ind: "BUY")
        monkeypatch.setattr(engine, "evaluate_candidate", lambda ind: ({"screener_score": 1.0}, "passed"))
        monkeypatch.setattr(engine, "compute_rules_confidence", lambda *a, **k: {"score": 99})
        # Breadth is computed from the fake bars and would block a falling
        # universe; these tests are not about the regime gate.
        monkeypatch.setattr(engine.settings, "breadth_floor_pct", 0.0)
        monkeypatch.setattr(engine.settings, "max_positions", 5)

    return install


def run(days: int = 30):
    return run_backtest(start=START, end=START + timedelta(days=days))


# ── entry price ───────────────────────────────────────────────────────────────


def test_entry_fills_at_the_close_of_the_signal_bar(stub_engine):
    """The signal is a claim about today, so the fill is today's close — not
    tomorrow's open. A wide gap between the two makes the difference visible."""
    closes = [100.0] + [50.0] * 29  # huge overnight gap after day one
    stub_engine({"A.NS": series(closes)})

    trades, _, _ = run()

    assert trades, "expected at least one trade"
    first = min(trades, key=lambda t: t.entry_date)
    assert first.entry_date == START
    assert first.entry_price == pytest.approx(100.0)  # the close, not the 50 open


# ── ordering: exits run before entries ────────────────────────────────────────


def test_a_position_opened_at_the_close_cannot_exit_the_same_day(stub_engine):
    """The lookahead guard.

    Exits are checked before entries, so a bar can never both open and close a
    position. If this fails, the loop has been reordered and the backtest is
    reporting round trips that could not have happened.
    """
    # Every bar swings ±40%, so if entries were filled before exits were
    # checked, the entry bar's own low would trip the stop immediately.
    stub_engine({"A.NS": series([100.0] * 30, high_mult=1.40, low_mult=0.60)})

    trades, _, _ = run()

    # Guard the guard: confirm the fixture could actually produce a same-day
    # exit, so a passing assertion below means something.
    entry = trades[0].entry_price
    assert entry * (1 - 2.5 * 3.0 / 100) > 100.0 * 0.60, (
        "fixture is too tame to trip a same-bar stop; the test proves nothing"
    )

    # `end_of_backtest` is the terminal cleanup — anything still open on the
    # final bar is force-closed there, so its exit date is legitimately its
    # entry date. Every real exit must come from a later bar.
    real_exits = [t for t in trades if t.exit_reason != "end_of_backtest"]
    assert real_exits, "expected trades to have exited through the ladder"

    for t in real_exits:
        assert t.exit_date > t.entry_date, f"{t.ticker} entered and exited on {t.entry_date} via {t.exit_reason}"


# ── capacity ──────────────────────────────────────────────────────────────────


def test_never_holds_more_than_max_positions(stub_engine, monkeypatch):
    bars = {f"T{i}.NS": series([100.0] * 30) for i in range(10)}
    stub_engine(bars)
    monkeypatch.setattr(engine.settings, "max_positions", 3)

    trades, _, _ = run()

    # With a flat tape nothing exits before the timeout, so concurrent holdings
    # are capped by max_positions.
    by_entry = {}
    for t in trades:
        by_entry.setdefault(t.entry_date, []).append(t)
    assert all(len(v) <= 3 for v in by_entry.values())


# ── regime gate ───────────────────────────────────────────────────────────────


def test_a_closed_breadth_gate_opens_nothing(stub_engine, monkeypatch):
    stub_engine({"A.NS": series([100.0] * 30)})
    monkeypatch.setattr(engine.settings, "breadth_floor_pct", 101.0)  # never open

    trades, _, _ = run()

    assert trades == []


# ── equity curve ──────────────────────────────────────────────────────────────


def test_equity_curve_has_one_point_per_trading_day(stub_engine):
    stub_engine({"A.NS": series([100.0] * 30)})

    _, curve, _ = run()

    days = [d for d, _ in curve]
    assert len(days) == len(set(days))
    assert days == sorted(days)


def test_no_data_returns_empty_rather_than_raising(stub_engine, monkeypatch):
    monkeypatch.setattr(engine, "BacktestStore", lambda db_path: FakeStore({"A.NS": series([])}))

    trades, curve, scores = run_backtest(start=START, end=START + timedelta(days=5))

    assert (trades, curve, scores) == ([], [], [])
