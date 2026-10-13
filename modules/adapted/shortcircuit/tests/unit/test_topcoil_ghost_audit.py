from __future__ import annotations

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
Top-coil setups are recorded once, and graded the way the engine trades them.

Two faults, both visible in the 22-24 Sep reports:

* A coil re-qualifies on every bar it stays tight, and each re-qualification wrote
  a fresh ML row and signal-log line. One JAYKAY setup on 23 Sep became 43
  "missed trades", which is why that day's audit processed 43 and 24 Sep's 58.
* The ghost audit graded them on the VWAP-target path: entered at the price when
  the coil ARMED (a top-coil trade only exists once the trigger breaks), exited at
  a VWAP target EOD_HOLD never uses. Its win rates measured a different strategy.
"""

import datetime as dt

import pandas as pd
import pytest
from shortcircuit.eod.eod_analyzer import IST, EODAnalyzer
from shortcircuit.execution import analyzer as an_mod
from shortcircuit.execution.analyzer import FyersAnalyzer
from shortcircuit.strategy import features as F

# ── grading ──────────────────────────────────────────────────────────────────

ARMED = dt.datetime(2026, 9, 23, 11, 49, tzinfo=IST)


def _bars(rows, start=ARMED + dt.timedelta(minutes=1)):
    """rows: (high, low, close) per minute from `start`."""
    return pd.DataFrame(
        {
            "dt": [start + dt.timedelta(minutes=i) for i in range(len(rows))],
            "high": [r[0] for r in rows],
            "low": [r[1] for r in rows],
            "close": [r[2] for r in rows],
        }
    )


def _obs(**over):
    base = {
        "exit_profile": "EOD_HOLD",
        "trigger_price": 216.06,
        "coil_high": 218.0,
        "sl_price": 219.71,
        "armed_at": ARMED.isoformat(),
    }
    base.update(over)
    return base


@pytest.fixture
def eod():
    return EODAnalyzer()


def test_a_trigger_that_never_breaks_is_not_a_trade(eod):
    r = eod._simulate_eod_hold(_obs(), _bars([(217.5, 216.5, 217.0)] * 20))
    assert r["outcome"] == "NOT_TRIGGERED" and r["exit_reason"] == "EXPIRED"


def test_a_push_through_the_coil_high_cancels_before_entry(eod):
    rows = [(217.5, 216.5, 217.0), (218.6, 217.0, 218.4), (218.0, 215.0, 215.5)]
    r = eod._simulate_eod_hold(_obs(), _bars(rows))
    assert r["outcome"] == "NOT_TRIGGERED" and r["exit_reason"] == "INVALIDATED"


def test_the_trigger_must_break_inside_fifteen_minutes(eod):
    rows = [(217.5, 216.5, 217.0)] * 16 + [(216.5, 215.0, 215.2)]
    assert eod._simulate_eod_hold(_obs(), _bars(rows))["outcome"] == "NOT_TRIGGERED"


def test_entered_then_stopped(eod):
    rows = [(216.5, 216.0, 216.1), (219.8, 216.0, 219.5)]
    r = eod._simulate_eod_hold(_obs(), _bars(rows))
    assert r["exit_reason"] == "SL_HIT" and r["outcome"] == "LOSS"
    assert r["exit_price"] == pytest.approx(219.71)


def test_entered_and_held_to_the_square_off_not_to_a_target(eod):
    """JAYKAY on 23 Sep: entered 216.05, held, closed ~212.6. No VWAP target."""
    start = ARMED + dt.timedelta(minutes=1)
    minutes = int((dt.datetime(2026, 9, 23, 15, 20, tzinfo=IST) - start).total_seconds() // 60)
    rows = [(216.5, 216.0, 216.1)] + [(214.0, 212.0, 212.6)] * (minutes - 1)
    rows[-1] = (250.0, 200.0, 240.0)  # after 15:10: must be ignored
    r = eod._simulate_eod_hold(_obs(), _bars(rows, start))
    assert r["exit_reason"] == "EOD_SQUAREOFF" and r["outcome"] == "WIN"
    assert r["exit_price"] == pytest.approx(212.6)


def test_rows_without_levels_are_skipped_not_guessed(eod):
    assert eod._simulate_eod_hold(_obs(trigger_price=None), _bars([(1, 1, 1)])) is None


def test_never_triggered_setups_stay_out_of_the_win_rate(eod):
    stats = {"total_pnl": 0.0, "win_rate": 0, "winners": 0, "losers": 0, "total_trades": 0}
    audit = {"status": "PASSED", "orphans": 0, "issues": []}
    ghosts = {
        "processed": 10,
        "wins": 1,
        "losses": 1,
        "tp_hits": 0,
        "eod_wins": 1,
        "not_triggered": 8,
    }
    text = eod.generate_report("2026-09-23", stats, audit, {"total_decisions": 0}, ghosts)
    assert "Trigger never broke**: 8" in text
    assert "Win Rate**: 50.0%" in text


# ── one observation per setup ────────────────────────────────────────────────


class _ML:
    def __init__(self):
        self.logged, self.updated = [], []

    def log_observation(self, symbol, ltp, features):
        self.logged.append(features)
        return f"obs{len(self.logged)}"

    def update_fields(self, obs_id, **fields):
        self.updated.append((obs_id, fields))
        return True


class _Ctx:
    def get_trend_label(self):
        return "UNKNOWN"


def _frame():
    t0 = dt.datetime(2026, 9, 23, 10, 0)
    px = [210 + i * 0.1 for i in range(40)]
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime([t0 + dt.timedelta(minutes=i) for i in range(40)]),
            "open": px,
            "high": [p + 0.2 for p in px],
            "low": [p - 0.2 for p in px],
            "close": px,
            "volume": [10_000] * 40,
        }
    )
    F.enrich_dataframe(df)
    return df


def _meta(trigger):
    return {
        "exit_profile": "EOD_HOLD",
        "signal_low_override": trigger,
        "coil_high": 218.0,
        "snapshot_high": 218.0,
        "pattern_bonus": "TOP_COIL_BREAKDOWN",
    }


@pytest.fixture
def analyzer(monkeypatch):
    ml = _ML()
    signals = []
    monkeypatch.setattr(an_mod, "get_ml_logger", lambda: ml)
    monkeypatch.setattr(an_mod, "log_signal", lambda *a, **k: signals.append(a[0]))
    a = FyersAnalyzer.__new__(FyersAnalyzer)
    a.market_context = _Ctx()
    a._topcoil_episodes = {}
    a.ml, a.signals = ml, signals
    return a


def test_a_re_arm_reuses_the_setups_observation(analyzer):
    df = _frame()
    first = analyzer._finalize_signal(
        "NSE:JAYKAY-EQ", 214.0, df, "TOP_COIL_BREAKDOWN", 0.0, "", _meta(213.59)
    )
    again = analyzer._finalize_signal(
        "NSE:JAYKAY-EQ", 216.0, df, "TOP_COIL_BREAKDOWN", 0.0, "", _meta(216.06)
    )
    assert len(analyzer.ml.logged) == 1 and len(analyzer.signals) == 1
    assert again["obs_id"] == first["obs_id"], "the trade must label the setup's one row"
    # ...and the row carries the trigger the engine is actually watching now
    assert analyzer.ml.updated[-1][1]["trigger_price"] == 216.06


def test_a_setup_after_the_gates_window_is_a_new_observation(analyzer):
    df = _frame()
    analyzer._finalize_signal(
        "NSE:JAYKAY-EQ", 214.0, df, "TOP_COIL_BREAKDOWN", 0.0, "", _meta(213.59)
    )
    obs, seen = analyzer._topcoil_episodes["NSE:JAYKAY-EQ"]
    analyzer._topcoil_episodes["NSE:JAYKAY-EQ"] = (obs, seen - dt.timedelta(minutes=16))
    analyzer._finalize_signal(
        "NSE:JAYKAY-EQ", 214.7, df, "TOP_COIL_BREAKDOWN", 0.0, "", _meta(214.68)
    )
    assert len(analyzer.ml.logged) == 2


def test_top_coil_rows_carry_their_levels_and_no_vwap_target(analyzer):
    analyzer._finalize_signal(
        "NSE:KSCL-EQ", 806.0, _frame(), "TOP_COIL_BREAKDOWN", 0.0, "", _meta(803.2)
    )
    f = analyzer.ml.logged[0]
    assert f["exit_profile"] == "EOD_HOLD" and f["trigger_price"] == 803.2
    assert f["coil_high"] == 218.0 and f["armed_at"]
    assert f["tp_price"] is None


def test_other_signals_are_untouched(analyzer):
    """BackToVWAPShort signals are logged every time and keep their VWAP target."""
    df = _frame()
    for _ in range(2):
        analyzer._finalize_signal("NSE:X-EQ", 214.0, df, "SHOOTING_STAR", 0.0, "", {})
    assert len(analyzer.ml.logged) == 2
    assert analyzer.ml.logged[0]["tp_price"] is not None
    assert "exit_profile" not in analyzer.ml.logged[0]
