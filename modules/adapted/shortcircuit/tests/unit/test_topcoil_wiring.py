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
The wiring that keeps an EOD_HOLD trade intact from detector to exit.

TopCoilShort's measured result depends entirely on the trade being left alone
until the 15:10 square-off. Three separate mechanisms in the engine will each cut
it short on their own — the take-profit ladder, the 45-minute time stop, and the
1.5% soft stop, which sits INSIDE the 1.63% median hard stop and would silently
govern about half of these exits. Each is pinned below, because any one of them
reverts the strategy to the -0.21% version without failing anything else.

Also pinned: the detector cannot run unless TOPCOIL_ENABLED is set, and it only
ever sees symbols the primary strategy has already rejected. A second detector
that could weaken an existing gate would be a much worse thing than a flat
strategy.
"""

import pytest
import shortcircuit.config as cfg
from shortcircuit.execution import focus_engine as fe


class _Engine:
    """A FocusEngine reduced to start_focus and the state that method touches."""

    start_focus = fe.FocusEngine.start_focus

    def __init__(self, order_manager=None):
        self.order_manager = order_manager
        self.active_trade = None
        self.is_running = False
        self.thread = None
        self._consecutive_flat_reads = 1
        self._api_fail_streak = 1
        self._last_broker_pos_check = 0.0
        self._flat_check_not_before = 0.0

    # The real loop polls the broker at 5Hz. These tests only care about the trade
    # dict start_focus builds before it spawns the thread.
    def focus_loop(self):
        return None


def _pos(**over):
    """A filled short: entry 100, hard stop 101.63 — the measured median risk."""
    base = {
        "symbol": "NSE:T-EQ",
        "entry_price": 100.0,
        "stop_loss": 101.63,
        "qty": 20,
        "tick_size": 0.05,
    }
    base.update(over)
    return base


@pytest.fixture(autouse=True)
def _short_side(monkeypatch):
    monkeypatch.setattr(cfg, "TRADE_DIRECTION", "SHORT", raising=False)
    monkeypatch.setattr(cfg, "TP_MODE", "SCALE", raising=False)


# The soft stop must not pre-empt the measured hard stop


def test_eod_hold_pushes_the_soft_stop_behind_the_hard_stop():
    eng = _Engine()
    eng.start_focus("NSE:T-EQ", _pos(exit_profile="EOD_HOLD"))
    t = eng.active_trade
    assert t["soft_sl"] > t["sl"], (
        "a soft stop inside the hard stop exits the trade early and turns "
        "EOD_HOLD back into the variant that lost 0.21% per trade"
    )


def test_default_trades_keep_their_soft_stop():
    """The change must be confined to EOD_HOLD — the primary strategy's 1.5%
    soft stop is load-bearing for it and is not being revisited here."""
    eng = _Engine()
    eng.start_focus("NSE:T-EQ", _pos())
    assert eng.active_trade["soft_sl"] == pytest.approx(101.5)


def test_soft_stop_is_untouched_when_there_is_no_hard_stop():
    eng = _Engine()
    eng.start_focus("NSE:T-EQ", _pos(exit_profile="EOD_HOLD", stop_loss=0.0))
    assert eng.active_trade["soft_sl"] == pytest.approx(101.5)


# No take-profit ladder


def test_eod_hold_runs_without_a_take_profit():
    eng = _Engine(order_manager=None)
    eng.start_focus("NSE:T-EQ", _pos(exit_profile="EOD_HOLD"))
    t = eng.active_trade
    assert t["tp_mode"] == "OFF"
    assert t["tp_1"] is None and t["tp"] is None


def test_eod_hold_never_asks_for_take_profit_levels():
    """compute_take_profits is the source of the 1%-of-entry target the whole
    book has been exiting at. An EOD_HOLD trade must not even consult it."""

    class _OM:
        def __init__(self):
            self.calls = 0

        def compute_take_profits(self, entry, pos):
            self.calls += 1
            return {"tp": entry * 0.99}

    om = _OM()
    eng = _Engine(order_manager=om)
    eng.start_focus("NSE:T-EQ", _pos(exit_profile="EOD_HOLD"))
    assert om.calls == 0

    eng.start_focus("NSE:T-EQ", _pos())  # a default trade still does
    assert om.calls == 1


# No 45-minute time stop


def test_time_stop_skips_eod_hold_positions():
    """The edge is in the trades that take longer than 45 minutes to work: the
    thesis is distribution into the close, not a fading 45-minute impulse."""
    src = fe.__file__
    with open(src) as fh:
        body = fh.read()
    assert "not _eod_hold and _max_hold > 0" in body, (
        "the time stop no longer checks the exit profile — EOD_HOLD positions "
        "will be closed at MAX_HOLD_TIME_MINUTES"
    )


# The detector is off unless it is switched on


def test_live_experiment_flags_are_coherent():
    """2026-09-21: the operator enabled TopCoilShort and switched the primary
    strategy off for a week, to isolate it. That is a deliberate live experiment
    with a measured expectancy of about -0.17%/trade, not a proven edge.

    This test does not police the choice — it pins the two flags together, because
    the dangerous state is TOPCOIL off AND BACKTOVWAP off, which leaves the bot
    scanning all day and unable to signal at all."""
    assert cfg.TOPCOIL_ENABLED or cfg.BACKTOVWAP_ENABLED, (
        "both detectors are disabled — the bot cannot produce a signal"
    )


def test_topcoil_floor_is_guarded_while_it_is_live():
    """The floor is the one parameter that separates flat from clearly losing."""
    if cfg.TOPCOIL_ENABLED:
        assert cfg.TOPCOIL_GAIN_MIN_PCT >= 12.0


def test_primary_strategy_is_skippable():
    from shortcircuit.execution import analyzer as an

    with open(an.__file__) as fh:
        body = fh.read()
    assert "if getattr(config, 'BACKTOVWAP_ENABLED', True):" in body, (
        "the primary detector must be switchable, and must default to ON when the flag is absent"
    )


def test_gain_floor_is_not_the_scanner_floor():
    """7.5% admits the bucket where this pattern is inverted — a pumped stock
    coiling at its high below ~10% goes UP more often and further."""
    assert cfg.TOPCOIL_GAIN_MIN_PCT >= 12.0, (
        "below ~12% the up/down excursion ratio is 1.25 — a bull flag — and this "
        "detector would be shorting into the drift"
    )
    assert cfg.TOPCOIL_GAIN_MIN_PCT > cfg.SCANNER_GAIN_MIN_PCT


def test_analyzer_does_not_consult_the_detector_when_disabled(monkeypatch):
    from shortcircuit.execution import analyzer as an

    monkeypatch.setattr(cfg, "TOPCOIL_ENABLED", False, raising=False)
    src = an.__file__
    with open(src) as fh:
        body = fh.read()
    assert "if result is None and getattr(config, 'TOPCOIL_ENABLED', False):" in body, (
        "the second detector must run only after the primary has rejected, and only behind its flag"
    )


def test_analyzer_overrides_signal_low_with_the_coil_trigger():
    """The validation gate enters on signal_low. Left at its default (the previous
    bar's low) the trade would trigger somewhere unrelated to the coil, and the
    whole entry geometry the measurement rests on would be gone."""
    from shortcircuit.execution import analyzer as an

    with open(an.__file__) as fh:
        body = fh.read()
    assert "if signal_meta.get('signal_low_override'):" in body
    assert "signal_data['signal_low'] = float(signal_meta['signal_low_override'])" in body


def test_position_state_carries_the_exit_profile():
    """focus_engine's time stop reads the profile off active_positions, not off
    the signal — the signal is long gone by the time the time stop runs."""
    from shortcircuit.execution import order_manager as om

    with open(om.__file__) as fh:
        body = fh.read()
    assert "'exit_profile': _exit_profile," in body
    assert "None if _eod_hold else self.compute_take_profits(ltp, signal)" in body
