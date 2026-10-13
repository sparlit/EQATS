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
Tests for G7 — the gate that decides whether the market is safe to trade at all.

Three things here are worth more than the coverage number:

  * The time windows. Nothing before 09:30, nothing after 15:10. These bound
    when the bot may open a position at all.
  * Fail-closed on index data. When Nifty data is missing or stale, G7 blocks.
    A false block costs a bounded number of missed trades; a false pass during a
    hard index uptrend does not have a bounded cost.
  * The circuit blacklist resets on a date change, not on a timer. A stale
    blacklist would either leak across sessions or clear mid-session.

Clock-dependent tests are frozen. Times in the source are IST, so the UTC
instants below are chosen to land on the intended IST wall-clock time.
"""

import datetime as dt

import pandas as pd
import pytest
from freezegun import freeze_time
from shortcircuit import config
from shortcircuit.strategy.market_context import MarketContext

# 09:30 IST = 04:00 UTC · 15:10 IST = 09:40 UTC
BEFORE_OPEN = "2026-08-03 03:00:00"  # 08:30 IST
IN_WINDOW = "2026-08-03 06:00:00"  # 11:30 IST
AFTER_CUTOFF = "2026-08-03 10:00:00"  # 15:30 IST


class StubFyers:
    def __init__(self, response=None):
        self.response = response or {"s": "ok", "candles": []}
        self.calls: list[dict] = []

    def history(self, data=None):
        self.calls.append(data)
        return self.response


@pytest.fixture
def ctx() -> MarketContext:
    """Morning range supplied, so the range-fetch path is not exercised here."""
    return MarketContext(StubFyers(), morning_high=25_000.0, morning_low=24_800.0)


def seed_cache(ctx: MarketContext):
    """
    The cache dicts are built on the first real fetch. Tests that stub the fetch
    out never trigger that, so they seed the attributes themselves.
    """
    if not hasattr(ctx, "_index_cache"):
        ctx._index_cache = {}
        ctx._index_cache_time = {}


def candles_at(close: float):
    """Index candles in Fyers' positional shape; close is index 4."""
    return [[0, 0, 0, 0, close, 0]]


def prime_index(ctx: MarketContext, close: float, *, age_s: float = 0.0, monkeypatch=None):
    """
    Make the regime check see a given index close at a given cache age.

    The cache dicts are created lazily on first fetch rather than in __init__,
    so they are seeded here instead of assumed.
    """
    import time as _t

    seed_cache(ctx)
    ctx._index_cache[ctx.nifty_symbol] = candles_at(close)
    ctx._index_cache_time[ctx.nifty_symbol] = _t.time() - age_s
    monkeypatch.setattr(ctx, "_refresh_morning_range_if_needed", lambda: None)
    monkeypatch.setattr(ctx, "_get_index_data_cached", lambda symbol=None: candles_at(close))


# construction


def test_morning_range_is_valid_when_both_bounds_are_supplied(ctx):
    assert ctx.morning_range_valid is True
    assert ctx.morning_high == 25_000.0
    assert ctx.morning_low == 24_800.0


def test_missing_morning_range_is_not_valid():
    c = MarketContext(StubFyers())
    assert c.morning_range_valid is False
    assert c.morning_high == 0.0 and c.morning_low == 0.0


def test_inverted_morning_range_is_rejected():
    """high below low gives a non-positive range, which must not count as valid."""
    c = MarketContext(StubFyers(), morning_high=24_800.0, morning_low=25_000.0)
    assert c.morning_range_valid is False


def test_an_invalid_index_symbol_raises_rather_than_trading_blind(monkeypatch):
    monkeypatch.setattr(MarketContext, "NIFTY_SYMBOL", "GARBAGE")
    with pytest.raises(ValueError):
        MarketContext(StubFyers())


# time gates


@freeze_time(BEFORE_OPEN)
def test_blocked_before_0930(ctx):
    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is False
    assert "Pre-Market" in reason


@freeze_time(AFTER_CUTOFF)
def test_blocked_after_1510(ctx):
    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is False
    assert "EOD Cutoff" in reason


@freeze_time("2026-08-03 04:00:00")  # exactly 09:30 IST
def test_the_open_boundary_is_inclusive(ctx, monkeypatch):
    prime_index(ctx, 24_900.0, monkeypatch=monkeypatch)
    allowed, reason = ctx.is_safe_trade_window()
    assert "Pre-Market" not in reason


@freeze_time("2026-08-03 09:40:00")  # exactly 15:10 IST
def test_the_cutoff_boundary_is_exclusive(ctx):
    """At 15:10 exactly, entries are already closed."""
    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is False
    assert "EOD Cutoff" in reason


# fail-closed on index data


@freeze_time(IN_WINDOW)
def test_missing_index_data_blocks(ctx, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MARKET_REGIME_FILTER", True)
    seed_cache(ctx)
    monkeypatch.setattr(ctx, "_get_index_data_cached", lambda symbol=None: None)
    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is False
    assert "fail closed" in reason.lower()


@freeze_time(IN_WINDOW)
def test_stale_index_data_blocks(ctx, monkeypatch):
    """Older than 15 minutes is treated as no data at all."""
    monkeypatch.setattr(config, "ENABLE_MARKET_REGIME_FILTER", True)
    seed_cache(ctx)
    monkeypatch.setattr(ctx, "_get_index_data_cached", lambda symbol=None: candles_at(24_900.0))
    ctx._index_cache_time[ctx.nifty_symbol] = 0.0  # epoch: maximally stale
    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is False
    assert "stale" in reason.lower()


@freeze_time(IN_WINDOW)
def test_missing_morning_range_blocks(monkeypatch):
    c = MarketContext(StubFyers())
    monkeypatch.setattr(config, "ENABLE_MARKET_REGIME_FILTER", True)
    prime_index(c, 24_900.0, monkeypatch=monkeypatch)
    allowed, reason = c.is_safe_trade_window()
    assert allowed is False
    assert "Morning range" in reason


# regime detection


@freeze_time(IN_WINDOW)
def test_strong_index_uptrend_blocks_new_shorts(ctx, monkeypatch):
    """Shorting into a hard index trend is the unbounded-risk case."""
    monkeypatch.setattr(config, "ENABLE_MARKET_REGIME_FILTER", True)
    threshold = config.MARKET_REGIME_CONFIG["strong_trend_threshold"]
    close = 25_000.0 * (1 + threshold + 0.005)
    prime_index(ctx, close, monkeypatch=monkeypatch)

    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is False
    assert "Strong Trend Up" in reason
    assert ctx.get_trend_label() == "TREND_UP"


@freeze_time(IN_WINDOW)
def test_range_day_allows_trading(ctx, monkeypatch):
    monkeypatch.setattr(config, "ENABLE_MARKET_REGIME_FILTER", True)
    prime_index(ctx, 25_010.0, monkeypatch=monkeypatch)
    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is True
    assert "Range" in reason


@freeze_time(IN_WINDOW)
def test_index_trending_down_allows_trading(ctx, monkeypatch):
    """A falling index is favourable for a short, not a reason to block."""
    monkeypatch.setattr(config, "ENABLE_MARKET_REGIME_FILTER", True)
    prime_index(ctx, 25_000.0 * 0.99, monkeypatch=monkeypatch)
    allowed, _ = ctx.is_safe_trade_window()
    assert allowed is True
    assert ctx.get_trend_label() == "TREND_DOWN"


@freeze_time(IN_WINDOW)
def test_regime_label_is_still_computed_when_the_filter_is_disabled(ctx, monkeypatch):
    """
    This is the shipped configuration: G7 is label-only. The label must still be
    maintained, because the ML log records it. An earlier revision returned early
    and left the label at UNKNOWN forever.
    """
    monkeypatch.setattr(config, "ENABLE_MARKET_REGIME_FILTER", False)
    threshold = config.MARKET_REGIME_CONFIG["strong_trend_threshold"]
    prime_index(ctx, 25_000.0 * (1 + threshold + 0.005), monkeypatch=monkeypatch)

    allowed, reason = ctx.is_safe_trade_window()
    assert allowed is True, "the filter is disabled, so it must not block"
    assert "Disabled" in reason
    assert ctx.get_trend_label() == "TREND_UP", "label must be updated even when not gating"


def test_trend_label_defaults_to_unknown(ctx):
    assert ctx.get_trend_label() == "UNKNOWN"


# circuit blacklist


def test_marking_a_symbol_blacklists_it(ctx):
    assert ctx.is_circuit_hitter("NSE:TEST-EQ") is False
    ctx.mark_circuit_touched("NSE:TEST-EQ")
    assert ctx.is_circuit_hitter("NSE:TEST-EQ") is True


def test_the_blacklist_is_session_permanent(ctx):
    """No TTL. Once a symbol hits a circuit it stays blocked all session."""
    ctx.mark_circuit_touched("NSE:TEST-EQ")
    for _ in range(50):
        assert ctx.is_circuit_hitter("NSE:TEST-EQ") is True


def test_the_blacklist_only_blocks_the_symbol_marked(ctx):
    ctx.mark_circuit_touched("NSE:TEST-EQ")
    assert ctx.is_circuit_hitter("NSE:OTHER-EQ") is False


def test_the_blacklist_clears_on_a_new_session(ctx):
    ctx.mark_circuit_touched("NSE:TEST-EQ")
    ctx._circuit_blacklist_date = dt.date(2000, 1, 1)  # pretend yesterday
    assert ctx.is_circuit_hitter("NSE:TEST-EQ") is False, (
        "stale blacklist leaked into a new session"
    )


def test_the_blacklist_does_not_clear_within_the_same_day(ctx):
    ctx.mark_circuit_touched("NSE:TEST-EQ")
    ctx._refresh_circuit_blacklist_if_needed()
    assert ctx.is_circuit_hitter("NSE:TEST-EQ") is True


# volume z-score


def test_volume_z_score_of_a_spike_is_positive(ctx):
    vols = [1_000] * 20 + [50_000]
    df = pd.DataFrame({"volume": vols})
    assert ctx.get_volume_z_score(df) > 1.0


def test_volume_z_score_is_zero_for_flat_volume(ctx):
    """Zero standard deviation must not divide by zero."""
    df = pd.DataFrame({"volume": [1_000] * 20})
    assert ctx.get_volume_z_score(df) == 0.0


@pytest.mark.parametrize(
    "df",
    [
        None,
        pd.DataFrame({"volume": [1, 2, 3]}),  # fewer than 10 rows
    ],
)
def test_volume_z_score_guards_return_zero_not_nan(ctx, df):
    """
    A NaN here would propagate into the ML log and into pattern detection.
    Returning 0.0 keeps the failure inert.
    """
    result = ctx.get_volume_z_score(df)
    assert result == 0.0


# index data: WS cache first, REST second


class StubBroker:
    """Stands in for the broker's live websocket quote cache."""

    def __init__(self, snapshot=None, raises: bool = False):
        self.snapshot = snapshot if snapshot is not None else {}
        self.raises = raises

    def get_quote_cache_snapshot(self):
        if self.raises:
            raise RuntimeError("cache unavailable")
        return self.snapshot


@pytest.fixture(autouse=True)
def _no_rate_limit_sleep(monkeypatch):
    """The real limiter sleeps to honour Fyers' quota; irrelevant here."""
    from shortcircuit.broker import rest_limiter as rl

    monkeypatch.setattr(rl.rest_limiter, "acquire", lambda *a, **k: True)


def test_index_is_read_from_the_ws_cache_without_any_rest_call():
    """The primary path costs zero REST calls, which is the point of it."""
    fyers = StubFyers()
    broker = StubBroker({MarketContext.NIFTY_SYMBOL: {"ltp": 25_123.0, "volume": 10}})
    c = MarketContext(fyers, broker=broker)

    candles = c._get_index_data_cached()
    assert candles[-1][4] == 25_123.0, "close must be at index 4 for consumers"
    assert fyers.calls == [], "WS cache hit still made a REST call"


def test_zero_ltp_in_the_ws_cache_falls_through_to_rest():
    """A cached entry of 0 is absence, not a price."""
    fyers = StubFyers({"s": "ok", "candles": candles_at(25_200.0)})
    broker = StubBroker({MarketContext.NIFTY_SYMBOL: {"ltp": 0}})
    c = MarketContext(fyers, broker=broker)

    assert c._get_index_data_cached()[-1][4] == 25_200.0
    assert len(fyers.calls) == 1


def test_a_broken_ws_cache_falls_through_to_rest_instead_of_raising():
    fyers = StubFyers({"s": "ok", "candles": candles_at(25_200.0)})
    c = MarketContext(fyers, broker=StubBroker(raises=True))
    assert c._get_index_data_cached()[-1][4] == 25_200.0


def test_rest_result_is_cached_and_reused():
    fyers = StubFyers({"s": "ok", "candles": candles_at(25_200.0)})
    c = MarketContext(fyers)
    c._get_index_data_cached()
    c._get_index_data_cached()
    assert len(fyers.calls) == 1, "second call should have been served from cache"


def test_rate_limited_response_extends_the_backoff():
    """A 429 must back off far longer than an ordinary error, or it compounds."""
    fyers = StubFyers({"s": "error", "code": 429, "message": "rate limit"})
    c = MarketContext(fyers)
    c._get_index_data_cached()
    assert c._index_backoff[c.nifty_symbol] == 300


def test_ordinary_error_uses_the_short_backoff():
    fyers = StubFyers({"s": "error", "code": 500, "message": "server error"})
    c = MarketContext(fyers)
    c._get_index_data_cached()
    assert c._index_backoff[c.nifty_symbol] == 60


def test_backoff_window_suppresses_a_second_attempt():
    fyers = StubFyers({"s": "error", "code": 500, "message": "boom"})
    c = MarketContext(fyers)
    c._get_index_data_cached()
    c._get_index_data_cached()
    assert len(fyers.calls) == 1, "backoff did not suppress the retry"


def test_failure_returns_stale_cache_rather_than_nothing():
    """Stale index data still lets G7 evaluate; None makes it fail closed."""
    fyers = StubFyers({"s": "ok", "candles": candles_at(25_200.0)})
    c = MarketContext(fyers)
    good = c._get_index_data_cached()

    c._index_cache_time[c.nifty_symbol] = 0.0  # expire
    c._index_last_attempt[c.nifty_symbol] = 0.0  # allow another attempt
    fyers.response = {"s": "error", "code": 500}
    assert c._get_index_data_cached() is good


def test_no_data_and_no_cache_returns_none():
    c = MarketContext(StubFyers({"s": "error", "code": 500}))
    assert c._get_index_data_cached() is None


def test_broker_exception_during_rest_is_swallowed():
    class Boom:
        def history(self, data=None):
            raise ConnectionError("down")

    assert MarketContext(Boom())._get_index_data_cached() is None


# morning range over REST


def ist_epoch(y, m, d, hh, mm):
    from zoneinfo import ZoneInfo

    return int(dt.datetime(y, m, d, hh, mm, tzinfo=ZoneInfo("Asia/Kolkata")).timestamp())


@freeze_time(IN_WINDOW)
def test_morning_range_is_taken_from_the_0915_to_0930_window():
    """[t, o, h, l, c, v] — high is index 2, low index 3."""
    bars = [
        [ist_epoch(2026, 8, 3, 9, 20), 0, 25_100.0, 24_900.0, 0, 0],
        [ist_epoch(2026, 8, 3, 9, 25), 0, 25_300.0, 25_000.0, 0, 0],
        [ist_epoch(2026, 8, 3, 11, 0), 0, 99_999.0, 1.0, 0, 0],  # outside window
    ]
    c = MarketContext(StubFyers({"s": "ok", "candles": bars}))
    high, low = c._fetch_morning_range_from_rest()
    assert high == 25_300.0 and low == 24_900.0, "a later bar leaked into the range"


@freeze_time(IN_WINDOW)
def test_morning_range_falls_back_to_all_of_todays_bars():
    """No 09:15–09:30 bars, so everything from 09:15 onward is used instead."""
    bars = [[ist_epoch(2026, 8, 3, 11, 0), 0, 25_400.0, 25_050.0, 0, 0]]
    c = MarketContext(StubFyers({"s": "ok", "candles": bars}))
    assert c._fetch_morning_range_from_rest() == (25_400.0, 25_050.0)


@freeze_time(IN_WINDOW)
@pytest.mark.parametrize(
    "response",
    [
        {"s": "error", "code": 500},
        {"s": "ok", "candles": []},
    ],
)
def test_morning_range_failure_returns_zeros(response):
    c = MarketContext(StubFyers(response))
    assert c._fetch_morning_range_from_rest() == (0.0, 0.0)


@freeze_time(IN_WINDOW)
def test_morning_range_exception_returns_zeros():
    class Boom:
        def history(self, data=None):
            raise ConnectionError("down")

    assert MarketContext(Boom())._fetch_morning_range_from_rest() == (0.0, 0.0)


@freeze_time(IN_WINDOW)
def test_only_todays_bars_count_towards_the_morning_range():
    """The request spans five days, so yesterday's open must not be included."""
    bars = [
        [ist_epoch(2026, 8, 2, 9, 20), 0, 99_999.0, 1.0, 0, 0],  # yesterday
        [ist_epoch(2026, 8, 3, 9, 20), 0, 25_100.0, 24_900.0, 0, 0],  # today
    ]
    c = MarketContext(StubFyers({"s": "ok", "candles": bars}))
    assert c._fetch_morning_range_from_rest() == (25_100.0, 24_900.0)


# morning range refresh


@freeze_time(IN_WINDOW)
def test_refresh_populates_the_range_on_success():
    bars = [[ist_epoch(2026, 8, 3, 9, 20), 0, 25_100.0, 24_900.0, 0, 0]]
    c = MarketContext(StubFyers({"s": "ok", "candles": bars}))
    c._refresh_morning_range_if_needed()
    assert c.morning_range_valid is True
    assert (c.morning_high, c.morning_low) == (25_100.0, 24_900.0)


@freeze_time(IN_WINDOW)
def test_refresh_marks_the_range_invalid_when_the_fetch_fails():
    """
    Invalid rather than stale. G7 blocks on an invalid range, which is the
    fail-closed side.
    """
    c = MarketContext(StubFyers({"s": "error", "code": 500}))
    c._refresh_morning_range_if_needed()
    assert c.morning_range_valid is False
    assert c.morning_high == 0.0


@freeze_time(IN_WINDOW)
def test_refresh_is_throttled():
    """600 s between attempts, added to stop the fetch triggering Fyers 429s."""
    bars = [[ist_epoch(2026, 8, 3, 9, 20), 0, 25_100.0, 24_900.0, 0, 0]]
    fyers = StubFyers({"s": "ok", "candles": bars})
    c = MarketContext(fyers)
    c._refresh_morning_range_if_needed()
    c._refresh_morning_range_if_needed()
    assert len(fyers.calls) == 1, "throttle did not suppress the second fetch"


@freeze_time(IN_WINDOW)
def test_refresh_skips_when_todays_range_is_already_valid():
    fyers = StubFyers({"s": "ok", "candles": []})
    c = MarketContext(fyers, morning_high=25_000.0, morning_low=24_800.0)
    c._cache_date = dt.datetime.now().date()
    c._last_range_fetch_time = 0.0  # throttle open
    c._refresh_morning_range_if_needed()
    assert fyers.calls == [], "refetched a range that was already valid for today"
