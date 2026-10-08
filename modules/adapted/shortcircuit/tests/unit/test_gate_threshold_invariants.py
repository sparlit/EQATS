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


"""Relationships between the gate thresholds that must hold for the funnel to work.

Each of these values is individually plausible and silently wrong in combination.
The G9 one is the dangerous case: set the bypass below the C1 floor and every signal
that reaches G9 bypasses it, disabling a gate without changing a line of its code.

Measured on the 2-4 Sep 2026 sessions, which is where these values came from.
"""

import pytest
from shortcircuit import config


def test_gain_window_is_a_window():
    assert config.SCANNER_GAIN_MIN_PCT < config.SCANNER_GAIN_MAX_PCT, (
        "the scanner would admit nothing"
    )


def test_gain_ceiling_stays_clear_of_the_common_circuit_band():
    """A short that goes limit-up cannot be covered, so this must stay under 20%.

    C0 in back_to_vwap checks distance from the broker's real upper_ckt, but it only
    runs when the analyzer actually read that value: the depth fetch is wrapped in a
    bare `except: pass`, so on failure upper_circuit stays 0.0 and C0's circuit branch
    is skipped. This ceiling is the backstop for that case, which is why it is NOT
    redundant with C0 and must not be raised to "let big movers through".

    Raising it to 25.0 on 2026-09-04 was wrong and reverted the same day:
    NSE:JINDWORLD-EQ peaked at 19.83% that session, effectively pinned at a 20% band.
    """
    assert config.SCANNER_GAIN_MAX_PCT < 20.0, (
        "NSE upper circuits are commonly 20%; entering above this risks a short "
        "that cannot be covered because the stock is locked limit-up"
    )
    assert config.SCANNER_GAIN_MAX_PCT > config.SCANNER_GAIN_MIN_PCT


def test_confidence_tiers_are_ordered():
    assert (
        config.STRATEGY_VWAP_SD_FLOOR
        < config.STRATEGY_VWAP_SD_HIGH
        < config.STRATEGY_VWAP_SD_EXTREME
    ), "a tier boundary below the entry floor is unreachable"


def test_g9_bypass_sits_above_the_entry_floor():
    """Otherwise G9 never runs.

    A signal only reaches G9 after clearing C1, so it always has stretch >= the C1
    floor. If the bypass threshold were <= that floor, every surviving signal would
    take the Alpha Strike path and the higher-timeframe gate would be dead code while
    still appearing in the config, the logs and the docs.
    """
    assert config.P61_G9_BYPASS_SD_THRESHOLD > config.STRATEGY_VWAP_SD_FLOOR, (
        f"bypass {config.P61_G9_BYPASS_SD_THRESHOLD} <= C1 floor "
        f"{config.STRATEGY_VWAP_SD_FLOOR} would disable G9 entirely"
    )


def test_g9_bypass_still_leaves_g9_something_to_do():
    """The inverse failure: a bypass so high that G9 blocks every real signal.

    Over 2-4 Sep the ten signals that passed all six conditions had stretch between
    3.67 and 8.57. A bypass at or above the EXTREME tier would mean G9 adjudicates
    almost everything, which is how a +17.6% setup got vetoed on 4 Sep.
    """
    assert config.P61_G9_BYPASS_SD_THRESHOLD < config.STRATEGY_VWAP_SD_EXTREME


def test_body_ratio_is_a_fraction_of_the_candle_range():
    assert 0.0 < config.CANDLE_BODY_RATIO_MIN < 1.0


def test_body_ratio_does_not_sit_on_top_of_the_population():
    """0.382 was chosen for being a Fibonacci number, not from measurement.

    Over 2-4 Sep it produced 155 quality rejections, 98 of them at 0.34 or better —
    including NSE:ANTELOPUS-EQ at 0.38, which was then dropped for the rest of the
    day while it ran to +17%. Violent movers are wick-heavy by construction.
    """
    assert config.CANDLE_BODY_RATIO_MIN <= 0.35, (
        "a floor above ~0.35 rejects the wick-heavy candles that violent movers "
        "produce, which is the setup this strategy exists to trade"
    )


@pytest.mark.parametrize(
    "name,expected",
    [
        ("SCANNER_GAIN_MAX_PCT", 18.0),
        ("CANDLE_BODY_RATIO_MIN", 0.34),
        ("STRATEGY_VWAP_SD_FLOOR", 3.2),
        ("P61_G9_BYPASS_SD_THRESHOLD", 4.0),
    ],
)
def test_the_2026_09_04_values_are_deliberate(name, expected):
    """Pins the four values changed together on 2026-09-04.

    They are recorded here so a later edit is a decision rather than a drift. If you
    are changing one, change this test in the same commit and say why. Reverting
    STRATEGY_VWAP_SD_FLOOR to 3.3 is the first thing to try if results degrade —
    June's +38.9% was earned at 3.3.
    """
    assert getattr(config, name) == expected
