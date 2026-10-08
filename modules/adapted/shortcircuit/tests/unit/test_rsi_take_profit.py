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
The operator's RSI take-profit on top-coil shorts.

Rule (30 Sep 2026): once an EOD_HOLD short is in profit, cover when the 1-minute
RSI(14) closes below 40, because a relief rally follows. It does follow — in 82% of
147 historical cases price bounced at least 0.5% within 30 minutes. Measured over
190 trades the average return is unchanged (+0.009% vs +0.058%, t=-0.27) while the
per-trade swing falls from 2.76% to 1.14% and the worst drawdown from -39% to -17%.

What is pinned here is that the live check runs the rule that was measured:
completed bars only, in profit only, never in the first 5 minutes (the breakdown
that triggers the entry drags RSI under 40 by itself — FERMENTA read 39.6 on its
entry bar), and a decided exit is retried every 10s, never re-fired at 5Hz.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd
import pytest
import shortcircuit.config as cfg
from shortcircuit.eod.eod_analyzer import IST, EODAnalyzer
from shortcircuit.execution import focus_engine as fe
from shortcircuit.strategy.features import compute_rsi_wilder

NOW = 1_790_000_000 // 60 * 60 + 30  # 30s into a minute


# ── the RSI itself ───────────────────────────────────────────────────────────


def test_rsi_extremes_and_insufficient_data():
    assert compute_rsi_wilder([10 + 0.1 * i for i in range(40)]) == pytest.approx(100.0)
    assert compute_rsi_wilder([10 - 0.1 * i for i in range(40)]) == pytest.approx(0.0)
    assert compute_rsi_wilder([1.0, 2.0]) != compute_rsi_wilder([1.0, 2.0])  # NaN


def test_rsi_matches_wilder_smoothing():
    """Wilder smoothing (alpha = 1/14), as broker charts draw it — not a simple
    moving average, which reads noticeably different on the same closes."""
    closes = [
        100,
        101,
        100.5,
        102,
        101,
        103,
        102.5,
        101,
        100,
        99,
        99.5,
        98,
        97.5,
        98.2,
        97,
        96.5,
        97.1,
        96,
        95.5,
        96.2,
    ]
    s = pd.Series(closes, dtype=float).diff()
    up = s.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    dn = (-s.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean().iloc[-1]
    assert compute_rsi_wilder(closes) == pytest.approx(100 - 100 / (1 + up / dn))


# ── the live check ───────────────────────────────────────────────────────────


@dataclass
class _C:
    epoch: int
    close: float


class _Broker:
    def __init__(self, candles):
        self.candles = candles

    def get_local_candles(self, symbol, n=100):
        return self.candles[-n:]


class _OM:
    def __init__(self, broker):
        self.broker = broker


class _Engine:
    _rsi_take_profit_due = fe.FocusEngine._rsi_take_profit_due

    def __init__(self, candles):
        self.order_manager = _OM(_Broker(candles))


def _candles(n_warm=40, after=None, forming=None):
    """n_warm completed bars rising gently, then `after` closes from the entry bar
    on, then optionally a forming bar. The last completed bar ends at NOW's minute."""
    after = after or []
    closes = [100 + 0.05 * i for i in range(n_warm)] + list(after)
    first = NOW // 60 * 60 - 60 * len(closes)
    out = [_C(first + 60 * k, c) for k, c in enumerate(closes)]
    if forming is not None:
        out.append(_C(NOW // 60 * 60, forming))
    return out, first + 60 * n_warm  # candles, entry-bar epoch


def _trade(entry_epoch, entry=102.0, **over):
    t = {
        "exit_profile": "EOD_HOLD",
        "direction": "SHORT",
        "entry": entry,
        "entry_minute": entry_epoch,
        "remaining_qty": 3,
    }
    t.update(over)
    return t


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(cfg, "TOPCOIL_RSI_TP_ENABLED", True, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_RSI_TP_THRESHOLD", 40.0, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_RSI_TP_PERIOD", 14, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_RSI_TP_SKIP_MINUTES", 5, raising=False)
    monkeypatch.setattr(cfg, "TOPCOIL_RSI_TP_MIN_CANDLES", 30, raising=False)
    monkeypatch.setattr(fe.time, "time", lambda: NOW)


FALLING = [101.5, 101.0, 100.6, 100.2, 99.8, 99.4, 99.0]  # entry bar + 6 more


def test_fires_on_a_completed_bar_in_profit_after_the_skip():
    c, e = _candles(after=FALLING)
    rsi = _Engine(c)._rsi_take_profit_due("NSE:X-EQ", _trade(e))
    assert rsi is not None and rsi < 40


def test_not_inside_the_first_five_minutes():
    c, e = _candles(after=FALLING[:4])  # entry bar + 3
    assert _Engine(c)._rsi_take_profit_due("NSE:X-EQ", _trade(e)) is None


def test_not_when_the_trade_is_not_in_profit():
    c, e = _candles(after=FALLING)
    assert _Engine(c)._rsi_take_profit_due("NSE:X-EQ", _trade(e, entry=98.0)) is None


def test_the_forming_bar_is_ignored():
    """A forming bar's RSI swings on every tick; only closes count."""
    c, e = _candles(after=[102.0] * 7, forming=90.0)
    assert _Engine(c)._rsi_take_profit_due("NSE:X-EQ", _trade(e, entry=103.0)) is None


def test_each_bar_is_judged_once():
    c, e = _candles(after=FALLING)
    eng, t = _Engine(c), _trade(e)
    assert eng._rsi_take_profit_due("NSE:X-EQ", t) is not None
    assert eng._rsi_take_profit_due("NSE:X-EQ", t) is None


def test_too_few_candles_leaves_the_position_alone():
    """After a mid-session restart the aggregator has little history; an unwarmed
    RSI is not a signal, so the stop and 15:10 remain the only exits."""
    c, e = _candles(n_warm=15, after=FALLING)
    assert _Engine(c)._rsi_take_profit_due("NSE:X-EQ", _trade(e)) is None


@pytest.mark.parametrize("over", [{"exit_profile": "DEFAULT"}, {"direction": "LONG"}])
def test_only_top_coil_shorts(over):
    c, e = _candles(after=FALLING)
    assert _Engine(c)._rsi_take_profit_due("NSE:X-EQ", _trade(e, **over)) is None


def test_switch_off(monkeypatch):
    monkeypatch.setattr(cfg, "TOPCOIL_RSI_TP_ENABLED", False, raising=False)
    c, e = _candles(after=FALLING)
    assert _Engine(c)._rsi_take_profit_due("NSE:X-EQ", _trade(e)) is None


def test_a_decided_exit_is_retried_every_ten_seconds_not_redecided(monkeypatch):
    c, e = _candles(after=[102.0] * 7)  # RSI nowhere near 40 now
    eng = _Engine(c)
    t = _trade(e, _rsi_reading=35.0, _rsi_retry_at=NOW + 10)
    assert eng._rsi_take_profit_due("NSE:X-EQ", t) is None  # waiting
    monkeypatch.setattr(fe.time, "time", lambda: NOW + 10)
    assert eng._rsi_take_profit_due("NSE:X-EQ", t) == 35.0  # retry the decision


def test_the_loop_hook_respects_manual_override_and_comes_before_the_tp_engine():
    src = fe.__file__
    body = open(src).read()
    hook = body.index(
        "_rsi_hit = None if manual_override else self._rsi_take_profit_due(symbol, t)"
    )
    assert hook < body.index("# Take-profit engine — see config.TP_MODE")
    assert 'safe_exit(symbol, "RSI_TP")' in body


# ── the ghost audit grades it the same way ───────────────────────────────────

ARMED = dt.datetime(2026, 9, 29, 10, 0, tzinfo=IST)


def _session(after):
    """40 rising warm-up bars ending at ARMED, then `after` bars."""
    start = ARMED - dt.timedelta(minutes=40)
    closes = [100 + 0.05 * i for i in range(40)] + list(after)
    rows = [(max(c, c) + 0.1, c - 0.1, c) for c in closes]
    return pd.DataFrame(
        {
            "dt": [start + dt.timedelta(minutes=i) for i in range(len(closes))],
            "high": [r[0] for r in rows],
            "low": [r[1] for r in rows],
            "close": [r[2] for r in rows],
        }
    )


def _obs():
    return {
        "exit_profile": "EOD_HOLD",
        "trigger_price": 101.8,
        "coil_high": 102.1,
        "sl_price": 103.5,
        "armed_at": ARMED.isoformat(),
    }


def test_ghost_audit_applies_the_rsi_exit():
    sess = _session([101.9, 101.5] + FALLING + [99.0] * 20)
    after = sess[sess["dt"] > ARMED]
    r = EODAnalyzer()._simulate_eod_hold(_obs(), after, session=sess)
    assert r["exit_reason"] == "RSI_TP" and r["outcome"] == "WIN"


def test_ghost_audit_without_the_switch_holds_to_the_close(monkeypatch):
    monkeypatch.setattr(cfg, "TOPCOIL_RSI_TP_ENABLED", False, raising=False)
    sess = _session([101.9, 101.5] + FALLING + [99.0] * 20)
    after = sess[sess["dt"] > ARMED]
    r = EODAnalyzer()._simulate_eod_hold(_obs(), after, session=sess)
    assert r["exit_reason"] == "EOD_SQUAREOFF"
