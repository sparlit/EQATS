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
Pure logic for the "DaysLowVolumnBreakout" intraday strategy -- v3
(Top-5 Causal), ported strictly from
strategies/DaysLowVolumnBreakout_v3_Top5Causal_Spec.md, cross-checked
directly against its reference implementation (E:\\trading-workspace\\
intraday-pullback-trading\\scratch_baseline_top5_best.py). v3 changes
vs v2 (kept for history in DaysLowVolumnBreakout_v2_SectorGate_Spec.md):

1. Candidate pool widened from top-2/day to **top-5/day**, walked with
   a genuinely time-ordered ("causal") mechanism -- see
   step_candidates_causal() below. This replaces the old rank-ordered
   per-candidate independent scan, which had a real look-ahead bug (a
   late-firing higher-rank signal could claim a slot ahead of an
   early-firing lower-rank one -- impossible for a live system to know
   in advance). MAX_TRADES_PER_DAY stays 2 -- only the pool searched
   widened, not the number of trades taken.
2. Signal-candle volume tolerance loosened from 5% to 10%
   (VOL_THRESHOLD_PCT).
3. Breakout window widened from 1 to 2 candles (BREAKOUT_WINDOW), with
   a NEW requirement: every candle in that window must be the
   confirming/continuation color (green for LONG, red for SHORT -- the
   opposite of the signal candle's own pullback color). A single
   wrong-colored candle drops the signal immediately, it does not wait
   out the remaining window. The volume condition is checked ONLY at
   signal-candle detection, never re-checked on the breakout candles
   (tested and found dramatically worse if re-checked -- Spec v3 §6/§12).

First-candle gate, EMA21 gate, sector-confirmation gate (still strict
2.0/0.5, independent of the day-bias threshold), target/exit management,
and position sizing are UNCHANGED from v2.

No Kite/broker/dashboard imports here on purpose -- everything in this
module is pure pandas/stdlib, so it can be unit-tested and backtested
with zero live dependencies.
"""


import datetime as dt

import pandas as pd

LONG = "LONG"
SHORT = "SHORT"

# Spec v5 (Gated-2nd-Candle) §2 constants -- current baseline, supersedes
# v2/v3/v4 for paper trading. See strategies/
# DaysLowVolumnBreakout_v5_GatedSecondCandle_Spec.md.
SIGNAL_WINDOW_START = "09:25"  # v5: CHANGED from v3's "09:30" -- day-bias,
# sector-gate, and this candle's own shape are all resolved from the SAME
# 09:25-candle close, so allowing it as a signal candle isn't a look-ahead
# change (spec §3.1) -- verified: CAGR 21.51%->23.93%, PF 1.55->1.63,
# DD -8.34%->-7.57% on the same top-2 pool/rule otherwise.
SIGNAL_WINDOW_END = "15:05"
NEW_SIGNAL_CUTOFF = dt.time(11, 0)  # v5: REVERTED from v3's 10:30 -- that
# value does NOT transfer across pool sizes (spec §3.1's explicit sweep:
# 10:30 on this top-2/gated-2nd-candle rule scores CAGR 15.20%/PF 1.42,
# clearly worse than 11:00; 10:30 only won for the earlier top-5 pool).
VOL_THRESHOLD_PCT = 0.05  # v5: REVERTED from v3's 0.10 back to v2's 5%
# tolerance -- part of the v5 baseline rule set, not carried over from v3.
ATR_PCT_BUFFER = 0.05
BREAKOUT_WINDOW = 2  # v5's "gated-2nd-candle" entry (spec §2): window
# candle #1 checks only the trigger price-cross; if it doesn't trigger,
# THIS ALREADY-CLOSED candle is gated on confirming color + lower volume
# than the signal candle + staying within the signal candle's own
# high/low range before candle #2 gets a chance at the same trigger
# check. See step_candle()/find_entry()'s own trigger-checked-first
# ordering below -- this already matches v5's rule exactly (verified
# 2026-09-18): color/volume/range are only ever evaluated on a candle
# that has ALREADY closed without triggering, never on the candle
# currently being checked for its own trigger, which is what makes this
# genuinely real-time-executable rather than needing to see a candle's
# own close before acting on its own trigger touch (the v3/v4 flaw this
# spec found and rejected -- see spec §1).
ATR_PERIOD = 14
EMA_SPAN = 21
REWARD_RISK = 2.0
# SQUAREOFF_TIME is a CANDLE LABEL (open-time), not a real-clock time --
# the "15:10"-labeled candle covers 15:10:00-15:14:59 and closes at
# 15:15:00 real time (Spec v3 §9's explicit audit finding: a live system
# that naively squares off "at 15:10 real time" exits 5 minutes early on
# the wrong price). intraday_engine.py's live loop must trigger its
# force-squareoff at 15:15:00 real time to match this.
SQUAREOFF_TIME = "15:10"
TOP_N_CANDIDATES = 5  # v5.4: back to top-5 (from v5/v5.3's top-2) -- per
# explicit instruction, for PAPER trading only. v5.4's own §0 flags an
# unreconciled conflict: this dashboard's own earlier v3/v5 top-5 re-test
# found top-5 WORSE than top-2 (CAGR 17.93% vs 24.14%, DD -19.59% vs
# -11.46%), while v5.4's own CHRONO-corrected backtest found top-5
# BETTER (37.88% vs v5.3's 34.26%) -- the two disagree by >2x and neither
# project has explained why. v5.4 §0 explicitly says NOT to deploy this
# for real capital until that's resolved; paper mode is exactly the safe
# way to actually test the disputed finding. MAX_TRADES_PER_DAY (below)
# stays 2 -- the pool searched widens, the day's trade cap does not.
#
# CHRONO note (v5.4 §2.3/§5.1): the "look-ahead in slot-filling" bug
# CHRONO fixes is a BACKTEST-SCRIPT artifact (a whole-day-at-once script
# picking the best-ranked 2 of however many signalled, with hindsight of
# which would trigger later) -- it does NOT apply to this live/paper
# engine, which only ever sees candidates trigger one at a time in real
# chronological order and fills a slot the INSTANT a trigger wins one
# (see run_live()'s fires_this_candle collect-then-sort, which only ever
# breaks a genuine SAME-boundary tie by rank, never reaches across
# different times). Confirmed by v5.4's own §5.1: "a live system never
# has the 'which 2 of many' problem... implementing this live is simpler
# than the backtest, not harder." No code change was needed for CHRONO
# itself -- only the pool width (TOP_N_CANDIDATES) and the gap filter
# below are new.

GAP_FILTER_PCT = 5.0  # v5.4 §4/§8 -- discard a candidate whose 09:15
# candle's own OPEN gapped more than this % (either direction) from the
# previous day's close, checked once before it's even ranked into the
# day's top-N pool (a gapped-out stock is replaced by the next-best
# non-gapped one, not just skipped leaving a hole). Tested directly on
# v5.3's live top-2 rules (§8): win rate, profit factor, and drawdown
# all improved together (PF 1.53->1.72, DD -10.23%->-9.03%) at a real
# CAGR cost from fewer trades (13% of candidates discarded).


def passes_gap_filter(gap_pct: float | None, threshold: float = GAP_FILTER_PCT) -> bool:
    """None (the 09:15 candle/prev-close couldn't be resolved) fails
    closed -- the same "skip it if we can't be sure" discipline the
    sector gate already uses elsewhere in this codebase, not silently
    letting an unverifiable candidate through."""
    return gap_pct is not None and abs(gap_pct) <= threshold


# Spec v2 §2.2 day-bias ratio gate -- CHANGED from v1's strict 2.0/0.5
# to this more moderate threshold (§9.4's sweep: neither the strict v1
# value nor a fully-relaxed 1.0/1.0 performed as well as this one).
BIAS_RATIO_LONG_MIN = 1.5
BIAS_RATIO_SHORT_MAX = 0.66

# Spec v2 §6.3 -- entry-time sector-confirmation gate threshold.
# Deliberately kept STRICT (2.0/0.5) independent of the day-bias
# threshold above -- §9.5's sweep found relaxing this to match a looser
# day-bias threshold consistently hurt performance in every combination
# tested. Checked only once a breakout has already triggered (§6),
# against a ratio computed once at 09:30 (see intraday_engine.py).
SECTOR_GATE_RATIO_LONG_MIN = 2.0
SECTOR_GATE_RATIO_SHORT_MAX = 0.5

# Spec.md §7 position sizing
MAX_TRADES_PER_DAY = 2
LEVERAGE = 5.0
MAX_RISK_PCT_PER_TRADE = 0.005

# Spec.md §8 cost model (Zerodha intraday equity)
BROKERAGE_PCT = 0.0003
BROKERAGE_CAP = 20.0
STT_SELL_PCT = 0.00025
EXCHANGE_TXN_PCT = 0.0000297
GST_PCT = 0.18


# ---------------------------------------------------------------------------
# §1 -- continuous (non session-reset) indicators
# ---------------------------------------------------------------------------

TRAIL_EMA_SLOW = 10  # v5.4 §5i.2 -- the only EMA the first-half trail
# consults now. EMA5 (formerly TRAIL_EMA_FAST) was removed entirely from
# the defer/trail decision -- see choose_trail_ema()'s own docstring.


def ema_n(close: pd.Series, span: int) -> pd.Series:
    """Continuous (never reset) 5-min EMA of the close, same convention as
    ema21() -- `ewm(span=N, adjust=False, min_periods=N)`. Causal by
    construction: each value depends only on that candle and earlier."""
    return close.ewm(span=span, adjust=False, min_periods=span).mean()


def choose_trail_ema(direction: str, target: float, ema10: float | None) -> int | None:
    """v5.4 §5i.2 -- EMA10-ONLY trail, replacing v5.2/v5.3's EMA5/EMA10
    dual-tier decision (EMA5 is no longer consulted at all). At the 1:2R
    touch, defer booking and trail EMA10 whenever the target sits on the
    momentum side of it (above for LONG, below for SHORT); otherwise
    book at the fixed target immediately, exactly like v5.1.

    Counterintuitive but measured: this makes the trail LOOSER, not
    tighter, since EMA10 sits further from price than EMA5 did --
    positions ride longer, a few more get stopped instead of booking
    early, and the survivors run much further (avg win, best trade, PF,
    and expectancy all rose together on the reference backtest: CAGR
    43.50%->47.60%, a real effect, not noise -- §5i.2's own analysis
    found every touch already deferred under both rules, so the entire
    change is which EMA gets trailed, not whether deferral happens).

    Returns 10, or None (book at the fixed target). Missing/NaN EMA10 ->
    None.

    NO LOOK-AHEAD: callers must pass the EMA10 of the most recent
    COMPLETED candle, never the still-forming touch candle's (whose own
    close isn't known yet) -- v5.2 §2's own live-implementation note,
    unchanged by this simplification."""
    if ema10 is None or pd.isna(ema10):
        return None
    if direction == LONG:
        return TRAIL_EMA_SLOW if target > ema10 else None
    return TRAIL_EMA_SLOW if target < ema10 else None


def signal_trend_ok(direction: str, close: float, ema50: float | None) -> bool:
    """v5.4 §5m -- the signal candle must close on the trend side of
    EMA50 (5-min, continuous, span=50, min_periods=50): LONG needs
    close > EMA50, SHORT needs close < EMA50. A symbol with fewer than
    50 candles of history (NaN EMA50) fails closed -- REJECTS the
    signal rather than passing it, same fail-closed convention as
    signal_in_range(). Supersedes §5l as the adopted configuration --
    6-year-consistent but a light touch (spec's own measured bound: 69
    of ~5,900 evaluated signals skipped, 6 fewer positions overall)."""
    if ema50 is None or pd.isna(ema50):
        return False
    return close > ema50 if direction == LONG else close < ema50


def trail_crossed(direction: str, close: float, ema: float | None) -> bool:
    """v5.2 §1 step 3 -- a candle's own close vs that same candle's own
    EMA (both known simultaneously at candle close): LONG crosses when
    close < EMA, SHORT when close > EMA."""
    if ema is None or pd.isna(ema):
        return False
    return close < ema if direction == LONG else close > ema


def ema21(close: pd.Series) -> pd.Series:
    """Continuous 5-min EMA21 over a symbol's whole multi-day history --
    NEVER reset per day (Spec.md §1). Must be computed once over the
    full series and looked up by timestamp, not recomputed from a
    single day's slice (that would silently produce a different,
    wrongly-cold-started value)."""
    return close.ewm(span=EMA_SPAN, adjust=False, min_periods=EMA_SPAN).mean()


def atr14(df: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    """Wilder's ATR, continuous over the whole series (Spec.md §1)."""
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ---------------------------------------------------------------------------
# §2 -- daily candidate selection
# ---------------------------------------------------------------------------


def first15_return(close_0925: float, prev_day_close: float) -> float:
    """Spec.md §2.2 -- the 09:25-candle close (= price at 09:30 real
    time) vs the previous day's official close, as a percent."""
    return (close_0925 / prev_day_close - 1) * 100


def day_bias(nifty_ratio: float) -> str | None:
    """Spec v2 §2.2's day-bias gate. `nifty_ratio` = advancers/decliners
    among NIFTY50 constituents by first15_return sign (ratio = +inf if
    decliners == 0). Returns None -- the day is SKIPPED entirely -- when
    the ratio doesn't clear either threshold. Do not casually retune
    BIAS_RATIO_LONG_MIN/SHORT_MAX -- the relationship between this
    threshold and outcome was NOT monotonic in Spec v2 §9.4's sweep."""
    if nifty_ratio > BIAS_RATIO_LONG_MIN:
        return LONG
    if nifty_ratio < BIAS_RATIO_SHORT_MAX:
        return SHORT
    return None


def sector_gate_pass(sector_ratio: float, direction: str) -> bool:
    """Spec v2 §6.3 -- the entry-time sector-confirmation gate itself
    (just the threshold check; intraday_engine.py owns resolving a
    candidate's primary sector and computing sector_ratio, since that
    needs sector-membership I/O this pure module deliberately has none
    of). Checked only once a candidate's breakout has already triggered
    (§6) -- a fail here drops that candidate's trade entirely, it does
    not block the OTHER candidate.

    Deliberately independent of day_bias()'s own (now-relaxed) threshold
    -- this stays at the strict 2.0/0.5 regardless (§9.5)."""
    if direction == LONG:
        return sector_ratio > SECTOR_GATE_RATIO_LONG_MIN
    return sector_ratio < SECTOR_GATE_RATIO_SHORT_MAX


def select_candidates(
    fno_ret_first15: pd.Series, bias: str, n: int = TOP_N_CANDIDATES
) -> pd.Series:
    """Spec.md §2.3-2.4 -- rank the F&O universe (NOT NIFTY50 -- that's
    only used for the breadth ratio above) by first15_return, best-first
    for LONG / worst-first for SHORT, and take the top `n`. No sector or
    trend filter (Spec.md §9.1 -- explicitly tested and rejected).

    An RVOL (relative volume) pre-filter was tried and backtested here
    (5yr replay, 2021-2026): it cut net P&L by 62% (Rs.15.7L -> Rs.6.0L)
    by swapping out the day's strongest first15m movers for weaker ones
    that merely had higher relative volume -- diluting exactly the
    signal this strategy depends on. Removed; do not re-add without a
    backtest showing it actually helps."""
    ranked = fno_ret_first15.sort_values(ascending=(bias == SHORT))
    return ranked.head(n)


# ---------------------------------------------------------------------------
# §3-§5 -- signal detection, entry/stop, target/exit management
# ---------------------------------------------------------------------------


def signal_in_range(
    direction: str,
    open_: float,
    close: float,
    sig_range_low: float | None,
    sig_range_high: float | None,
) -> bool:
    """v5.4 §5i.1 -- the "one-sided signal gate": a candle may only
    become a FRESH signal candle if its BODY (open/close -- wicks
    ignored) has not broken the reference range on the trade's own
    side. sig_range_low/high are the day's fixed 09:20+09:25-candle
    range (min low / max high of those two specific candles, captured
    once per day -- NOT the day's very first (09:15) candle used by the
    separate EMA21/first-candle invalidation gate).

    LONG: min(open, close) >= sig_range_low (the pullback hasn't
    cracked the opening range's floor). SHORT: max(open, close) <=
    sig_range_high (the bounce hasn't cleared its ceiling). The
    OPPOSITE side is unconstrained -- a LONG signal may sit freely
    above sig_range_high.

    Only ever applied to a FRESH signal candle -- never to a re-signal
    (the reference implementation this was ported from never calls
    this in its re-signal branch; re-signal already has its own,
    separate "extends the pullback further" condition).

    Fails CLOSED if the range couldn't be resolved (e.g. a data gap
    around 09:20/09:25) -- same discipline as the sector gate elsewhere
    in this codebase: no candle can become a signal candle that day for
    this candidate, rather than silently letting an unverifiable one
    through."""
    if sig_range_low is None or sig_range_high is None:
        return False
    body_hi = max(open_, close)
    body_lo = min(open_, close)
    if direction == LONG:
        return body_lo >= sig_range_low
    return body_hi <= sig_range_high


def fair_value_gap(
    candle0_high: float, candle0_low: float, candle2_high: float, candle2_low: float
) -> tuple[float | None, float | None]:
    """v5.4 §5n -- the day's fixed fair-value-gap zone, from the 1st
    (09:15, index 0) and 3rd (09:25, index 2) candles' own high/low --
    a price zone that traded only once that morning. Returns (fvg_lo,
    fvg_hi), or (None, None) if the two candles overlap (no gap that
    day -- the veto below is then inert, NOT fail-closed, since "no
    gap" is a normal, common outcome, not a data problem):

      bullish gap  candle0_high < candle2_low   -> [candle0_high, candle2_low]
      bearish gap  candle0_low  > candle2_high  -> [candle2_high, candle0_low]
      no gap       the two candles overlap      -> (None, None), filter inert
    """
    if candle0_high < candle2_low:
        return candle0_high, candle2_low
    if candle0_low > candle2_high:
        return candle2_high, candle0_low
    return None, None


def fvg_vetoed(close: float, fvg_lo: float | None, fvg_hi: float | None) -> bool:
    """v5.4 §5n -- True if a signal candle's own CLOSE falls inside the
    day's fair-value-gap zone (bounds INCLUSIVE -- a close landing
    exactly on a zone edge counts as inside, per the spec's own
    measured choice). A day with no gap (fvg_lo/hi both None) never
    vetoes anything -- this is the opposite fail-direction from
    signal_in_range()'s fail-closed-on-missing-data convention,
    deliberately, since "no gap" isn't missing data, it's the normal
    case for most days."""
    if fvg_lo is None or fvg_hi is None:
        return False
    return fvg_lo <= close <= fvg_hi


def find_entry(
    day: pd.DataFrame,
    direction: str,
    ema21_series: pd.Series,
    atr14_series: pd.Series,
    first_candle_low: float,
    first_candle_high: float,
    sig_range_low: float | None = None,
    sig_range_high: float | None = None,
    ema50_series: pd.Series | None = None,
    fvg_lo: float | None = None,
    fvg_hi: float | None = None,
) -> dict | None:
    """Spec v2 §3.2's walk-forward loop, for one candidate on one day.

    `day`: that symbol's 5-min OHLCV candles for the day, indexed by
    timestamp (any candles outside the signal window are ignored).
    `ema21_series`/`atr14_series`: this symbol's CONTINUOUS multi-day
    series (§1) -- looked up by timestamp, never recomputed per day.
    `first_candle_low`/`first_candle_high`: the day's very first (09:15)
    candle's own low/high, captured once before this loop runs (§3.2 v2
    step 1b) -- a fixed value for the whole day, not looked up per candle.
    `ema50_series`: v5.4 §5m's trend filter on the signal candle, same
    continuous-series/lookup-by-timestamp convention as ema21_series.
    None disables the filter entirely (pre-§5m behavior) -- pass a real
    series (strat.ema_n(close, 50)) to turn it on; a real series with a
    NaN value at a given timestamp (not enough history yet) still fails
    that candle closed, same as a missing sig_range.
    `sig_range_low`/`sig_range_high`: v5.4 §5i.1's one-sided signal gate
    reference range (09:20+09:25 candles), also fixed for the whole day.
    None disables signal formation entirely for this call (fail-closed,
    see signal_in_range()) -- pass real values once the range is known.
    `fvg_lo`/`fvg_hi`: v5.4 §5n's fair-value-gap veto zone (see
    fair_value_gap()), also fixed for the whole day. None (the default,
    either because the caller didn't wire this in, or because
    fair_value_gap() itself found no gap that day) means the veto is
    simply INERT -- opposite fail-direction from sig_range above.

    Returns {"signal_time", "entry_time", "entry_price", "stop_price"}
    on a triggered entry, else None (day invalidated, or no signal ever
    triggered by SIGNAL_WINDOW_END). At most one trade per candidate per
    day -- the moment an entry triggers, this returns immediately."""
    win = day.between_time(SIGNAL_WINDOW_START, SIGNAL_WINDOW_END)
    if win.empty:
        return None

    # "lowest volume so far today" resets each day at 09:15 (§1's one
    # session-scoped exception) -- NOT the same as the signal window,
    # which starts at 09:30.
    day_open_ts = win.index[0].normalize() + pd.Timedelta(hours=9, minutes=15)
    vol_so_far_full = day.loc[day.index >= day_open_ts, "volume"]

    invalidated = False
    active_signal = None  # {"time", "hi", "lo", "atr", "volume", "signal_close"}
    breakout_counter = 0

    for ts, row in win.iterrows():
        sig_atr = atr14_series.get(ts)  # this candle's own ATR -- needed both
        # for a fresh signal formation below AND for the continuation gate while
        # an existing signal is active, computed once here either way.
        # 1. EMA21 day-invalidation gate -- checked every candle,
        # regardless of any active signal (Spec §3.2 step 1, §9.5).
        e21 = ema21_series.get(ts)
        if pd.notna(e21) and (
            direction == LONG and row["close"] < e21 or direction == SHORT and row["close"] > e21
        ):
            invalidated = True
        # 1b. NEW v2 -- first-candle-close-through invalidation gate,
        # same whole-day-kill-switch semantics as the EMA21 gate above,
        # just a different reference level (the day's own 09:15 candle).
        if (
            direction == LONG
            and row["close"] < first_candle_low
            or direction == SHORT
            and row["close"] > first_candle_high
        ):
            invalidated = True
        if invalidated:
            return None

        # 2. An active signal -- check this candle for the breakout trigger.
        if active_signal is not None:
            breakout_counter += 1
            # Trigger checked FIRST -- see step_candle()'s own comment for
            # why a range/volume gate can never be satisfied by the
            # actual triggering candle (breaking out necessarily exceeds
            # the signal candle's own high/low).
            buf = active_signal["atr"] * ATR_PCT_BUFFER
            if direction == LONG:
                trigger_level = active_signal["hi"] + buf
                triggered = row["high"] >= trigger_level
            else:
                trigger_level = active_signal["lo"] - buf
                triggered = row["low"] <= trigger_level
            if triggered:
                stop_price = (
                    (active_signal["lo"] - buf)
                    if direction == LONG
                    else (active_signal["hi"] + buf)
                )
                return {
                    "signal_time": active_signal["time"],
                    "entry_time": ts,
                    "entry_price": trigger_level,
                    "stop_price": stop_price,
                }
            # v3.1 NEW -- this window candle did NOT trigger. Before
            # continuing to the next window candle it must have been a
            # clean continuation of the signal candle's own pullback: the
            # confirming/continuation color (green for LONG, red for
            # SHORT), LOWER volume than the signal candle, and its own
            # high/low still WITHIN the signal candle's range -- fail any
            # of these and the signal drops immediately rather than
            # waiting out the remaining window candle(s) (Spec v3 §6
            # point 1, extended). See step_candle()'s own comment for the
            # live-vs-backtest rationale, kept identical here.
            gate_ok = False
            if breakout_counter < BREAKOUT_WINDOW:
                confirm_is_green = row["close"] > row["open"]
                confirm_is_red = row["close"] < row["open"]
                wants_confirm_color = confirm_is_green if direction == LONG else confirm_is_red
                volume_ok = row["volume"] < active_signal["volume"]
                range_ok = row["high"] <= active_signal["hi"] and row["low"] >= active_signal["lo"]
                gate_ok = wants_confirm_color and volume_ok and range_ok
            if gate_ok:
                continue
            # §5l -- v5.1/v5.3's "re-signal on close" is REMOVED entirely
            # (no close-extension test, no volume-vs-signal test, no
            # chain_len cap). The dying signal's own candle -- candle #1
            # that just failed the continuation gate above, or candle #2
            # that exhausted the window -- falls straight through to
            # step 3 below and is re-tested as an ORDINARY fresh signal
            # candle: same day's-lowest-volume/color/one-sided-gate bar
            # as any other candle, nothing special carried over from the
            # dying signal. If it doesn't qualify, nothing is active and
            # the scan just continues from the next candle. Verified
            # worth +1.83 CAGR / -0.88pp drawdown over the old re-signal
            # rule (Spec §5l.1) -- the old rule only required volume
            # lower than the signal it replaced, not the day's actual
            # running minimum, so it manufactured weaker setups from
            # already-failing ones.
            active_signal = None
            breakout_counter = 0
            # falls through to step 3 -- deliberately no `continue` here

        # 3. No active signal (either never had one this candle, or it
        # just died above) -- check whether THIS candle is a fresh
        # signal candle (only before NEW_SIGNAL_CUTOFF).
        if active_signal is None:
            if ts.time() > NEW_SIGNAL_CUTOFF:
                continue
            is_red = row["close"] < row["open"]
            is_green = row["close"] > row["open"]
            wants_color = is_red if direction == LONG else is_green
            vol_min_so_far = vol_so_far_full.loc[:ts].min()
            is_lowest_volume = row["volume"] <= vol_min_so_far * (1 + VOL_THRESHOLD_PCT)
            in_range = signal_in_range(
                direction, float(row["open"]), float(row["close"]), sig_range_low, sig_range_high
            )
            # v5.4 §5m -- trend_ok defaults to True (filter off) when no
            # ema50_series is given at all, matching the spec's own
            # --trend-filter=off toggle; once a series IS given, a NaN
            # value (not enough history) fails this candle closed.
            trend_ok = (
                signal_trend_ok(direction, float(row["close"]), ema50_series.get(ts))
                if ema50_series is not None
                else True
            )
            fvg_ok = not fvg_vetoed(float(row["close"]), fvg_lo, fvg_hi)
            if (
                wants_color
                and is_lowest_volume
                and in_range
                and trend_ok
                and fvg_ok
                and pd.notna(sig_atr)
                and sig_atr > 0
            ):
                # float(...) on every field here, not just open/close above --
                # a candle whose OHLCV all happen to be whole numbers (no
                # paise) gets fetched as an int64 dtype column, and a raw
                # numpy.int64 (unlike numpy.float64) silently serializes to
                # a BLOB instead of a number if this dict's values ever
                # reach sqlite3 unwrapped (verified live: BAJAJ-AUTO,
                # 2026-10-01, every OHLC value a round number that day).
                active_signal = {
                    "time": ts,
                    "hi": float(row["high"]),
                    "lo": float(row["low"]),
                    "atr": sig_atr,
                    "volume": float(row["volume"]),
                    "signal_close": float(row["close"]),
                }
                breakout_counter = 0

    return None


def diagnose_day(
    day: pd.DataFrame,
    direction: str,
    ema21_series: pd.Series,
    atr14_series: pd.Series,
    first_candle_low: float,
    first_candle_high: float,
    sig_range_low: float | None = None,
    sig_range_high: float | None = None,
    ema50_series: pd.Series | None = None,
    fvg_lo: float | None = None,
    fvg_hi: float | None = None,
) -> dict:
    """Read-only diagnostic twin of find_entry() -- walks the IDENTICAL
    §3.2/§5l/§5m/§5n loop, candle-by-candle-for-candle, but instead of stopping at
    the first trigger, records WHY every candle that didn't advance the
    state machine failed to, and ends with a synthesized plain-English
    final outcome. Built for the Intraday Logs page's "why didn't/did
    this candidate trade today" view -- pure reconstruction from the same
    real candle data + rules find_entry()/step_candle() themselves use,
    no DB writes, no effect on the live engine or its state.

    Deliberately kept as a SEPARATE function rather than adding a
    trace-collecting flag to find_entry() -- that function is the one
    backtest.py actually calls for real P&L, and every added branch here
    is a branch that function doesn't need to carry just to explain
    itself after the fact.

    Returns {"trace": [...], "outcome": {...}}:
      trace: one dict per evaluated candle, {"time", "stage", "result"
        ("ok"/"fail"/"triggered"), "reason", plus the raw OHLCV/checks
        that produced it} -- "stage" is "invalidation", "continuation"
        (checking an active signal's window candle), or "fresh" (checking
        whether this candle becomes a new signal).
      outcome: {"type", "detail", ...} where type is one of:
        "invalidated", "triggered", "expired_no_retrigger" (a signal
        formed and died, nothing else ever qualified after it),
        "no_signal_all_day" (not invalidated, but nothing EVER passed
        the fresh-signal checks), "empty" (no candles in the window at
        all, e.g. a holiday/data gap).
    """
    win = day.between_time(SIGNAL_WINDOW_START, SIGNAL_WINDOW_END)
    trace: list[dict] = []
    if win.empty:
        return {
            "trace": trace,
            "outcome": {"type": "empty", "detail": "No candles in the signal window."},
        }

    day_open_ts = win.index[0].normalize() + pd.Timedelta(hours=9, minutes=15)
    vol_so_far_full = day.loc[day.index >= day_open_ts, "volume"]

    active_signal = None
    breakout_counter = 0
    any_signal_ever = False
    last_signal_death: dict | None = None  # {"time", "reason"} of the most recent expiry

    for ts, row in win.iterrows():
        sig_atr = atr14_series.get(ts)
        e21 = ema21_series.get(ts)
        invalidated_now = False
        inval_reason = None
        if pd.notna(e21):
            if direction == LONG and row["close"] < e21:
                invalidated_now, inval_reason = (
                    True,
                    f"closed {row['close']:.2f} below EMA21 {e21:.2f}",
                )
            elif direction == SHORT and row["close"] > e21:
                invalidated_now, inval_reason = (
                    True,
                    f"closed {row['close']:.2f} above EMA21 {e21:.2f}",
                )
        if not invalidated_now:
            if direction == LONG and row["close"] < first_candle_low:
                invalidated_now = True
                inval_reason = (
                    f"closed {row['close']:.2f} below the day's 09:15 low {first_candle_low:.2f}"
                )
            elif direction == SHORT and row["close"] > first_candle_high:
                invalidated_now = True
                inval_reason = (
                    f"closed {row['close']:.2f} above the day's 09:15 high {first_candle_high:.2f}"
                )
        if invalidated_now:
            trace.append(
                {"time": ts, "stage": "invalidation", "result": "fail", "reason": inval_reason}
            )
            return {
                "trace": trace,
                "outcome": {"type": "invalidated", "time": ts, "detail": inval_reason},
            }

        if active_signal is not None:
            breakout_counter += 1
            buf = active_signal["atr"] * ATR_PCT_BUFFER
            if direction == LONG:
                trigger_level = active_signal["hi"] + buf
                triggered = row["high"] >= trigger_level
            else:
                trigger_level = active_signal["lo"] - buf
                triggered = row["low"] <= trigger_level
            if triggered:
                stop_price = (
                    (active_signal["lo"] - buf)
                    if direction == LONG
                    else (active_signal["hi"] + buf)
                )
                reason = (
                    f"triggered on window candle #{breakout_counter} -- "
                    f"{'high' if direction == LONG else 'low'} crossed "
                    f"{trigger_level:.2f} (signal from {active_signal['time']:%H:%M})"
                )
                trace.append(
                    {"time": ts, "stage": "continuation", "result": "triggered", "reason": reason}
                )
                return {
                    "trace": trace,
                    "outcome": {
                        "type": "triggered",
                        "signal_time": active_signal["time"],
                        "entry_time": ts,
                        "entry_price": trigger_level,
                        "stop_price": stop_price,
                        "detail": reason,
                    },
                }

            confirm_is_green = row["close"] > row["open"]
            confirm_is_red = row["close"] < row["open"]
            wants_confirm_color = confirm_is_green if direction == LONG else confirm_is_red
            volume_ok = row["volume"] < active_signal["volume"]
            range_ok = row["high"] <= active_signal["hi"] and row["low"] >= active_signal["lo"]
            gate_ok = (
                breakout_counter < BREAKOUT_WINDOW
                and wants_confirm_color
                and volume_ok
                and range_ok
            )
            if gate_ok:
                trace.append(
                    {
                        "time": ts,
                        "stage": "continuation",
                        "result": "ok",
                        "reason": f"window candle #{breakout_counter} kept the "
                        f"{active_signal['time']:%H:%M} signal alive",
                    }
                )
                continue

            fails = []
            if breakout_counter >= BREAKOUT_WINDOW:
                fails.append(f"{BREAKOUT_WINDOW}-candle breakout window exhausted")
            else:
                if not wants_confirm_color:
                    fails.append("wrong confirming color")
                if not volume_ok:
                    fails.append(
                        f"volume {row['volume']:,.0f} not below signal's "
                        f"{active_signal['volume']:,.0f}"
                    )
                if not range_ok:
                    fails.append("high/low broke outside the signal candle's own range")
            dead_reason = f"{active_signal['time']:%H:%M} signal died: " + "; ".join(fails)
            trace.append(
                {"time": ts, "stage": "continuation", "result": "fail", "reason": dead_reason}
            )
            last_signal_death = {"time": ts, "reason": dead_reason}
            active_signal = None
            breakout_counter = 0
            # falls through to the fresh check below -- §5l, no re-signal

        if active_signal is None:
            if ts.time() > NEW_SIGNAL_CUTOFF:
                trace.append(
                    {
                        "time": ts,
                        "stage": "fresh",
                        "result": "fail",
                        "reason": f"past the {NEW_SIGNAL_CUTOFF:%H:%M} new-signal cutoff",
                    }
                )
                continue
            is_red = row["close"] < row["open"]
            is_green = row["close"] > row["open"]
            wants_color = is_red if direction == LONG else is_green
            vol_min_so_far = vol_so_far_full.loc[:ts].min()
            is_lowest_volume = row["volume"] <= vol_min_so_far * (1 + VOL_THRESHOLD_PCT)
            in_range = signal_in_range(
                direction, float(row["open"]), float(row["close"]), sig_range_low, sig_range_high
            )
            atr_ok = pd.notna(sig_atr) and sig_atr > 0
            e50 = ema50_series.get(ts) if ema50_series is not None else None
            trend_ok = True if e50 is None else signal_trend_ok(direction, float(row["close"]), e50)
            fvg_ok = not fvg_vetoed(float(row["close"]), fvg_lo, fvg_hi)
            if wants_color and is_lowest_volume and in_range and trend_ok and fvg_ok and atr_ok:
                any_signal_ever = True
                active_signal = {
                    "time": ts,
                    "hi": float(row["high"]),
                    "lo": float(row["low"]),
                    "atr": sig_atr,
                    "volume": float(row["volume"]),
                    "signal_close": float(row["close"]),
                }
                breakout_counter = 0
                trace.append(
                    {
                        "time": ts,
                        "stage": "fresh",
                        "result": "ok",
                        "reason": f"new {'LONG' if direction == LONG else 'SHORT'} "
                        f"signal candle (H {row['high']:.2f} / L {row['low']:.2f})",
                    }
                )
                continue

            fails = []
            if not wants_color:
                fails.append(f"wrong color (need {'red' if direction == LONG else 'green'})")
            if not is_lowest_volume:
                fails.append(
                    f"volume {row['volume']:,.0f} not the day's lowest "
                    f"(so-far min {vol_min_so_far:,.0f})"
                )
            if not in_range:
                if sig_range_low is None or sig_range_high is None:
                    fails.append("one-sided gate reference range unavailable (fails closed)")
                elif direction == LONG:
                    body_lo = min(row["open"], row["close"])
                    fails.append(
                        f"body low {body_lo:.2f} dipped below the one-sided gate's "
                        f"floor {sig_range_low:.2f} (09:20/09:25 reference)"
                    )
                else:
                    body_hi = max(row["open"], row["close"])
                    fails.append(
                        f"body high {body_hi:.2f} rose above the one-sided gate's "
                        f"ceiling {sig_range_high:.2f} (09:20/09:25 reference)"
                    )
            if not trend_ok:
                if ema50_series is not None and pd.isna(e50):
                    fails.append("EMA50 unavailable (fewer than 50 candles of history)")
                else:
                    fails.append(
                        f"close {row['close']:.2f} on the wrong side of EMA50 "
                        f"{e50:.2f} (§5m trend filter)"
                    )
            if not fvg_ok:
                fails.append(
                    f"close {row['close']:.2f} sits inside the fair-value-gap zone "
                    f"[{fvg_lo:.2f}, {fvg_hi:.2f}] (§5n veto)"
                )
            if not atr_ok:
                fails.append("ATR unavailable")
            trace.append(
                {"time": ts, "stage": "fresh", "result": "fail", "reason": "; ".join(fails)}
            )

    if any_signal_ever:
        outcome = {
            "type": "expired_no_retrigger",
            "detail": (
                last_signal_death["reason"]
                if last_signal_death
                else "Signal(s) formed but none ever triggered."
            ),
        }
    else:
        outcome = {
            "type": "no_signal_all_day",
            "detail": "No candle today ever qualified as a fresh signal candle.",
        }
    return {"trace": trace, "outcome": outcome}


# ---------------------------------------------------------------------------
# Incremental (candle-by-candle) version of find_entry()'s walk-forward
# loop -- for live/paper use, where candles arrive one at a time rather
# than as a whole day at once. find_entry() itself stays untouched and
# is still what backtests/verification use; this is an additive,
# separately-verified equivalent (see verify_step_candle.py: replayed
# candle-by-candle, this produces IDENTICAL trigger decisions to
# find_entry() over the same 5-year ground truth).
# ---------------------------------------------------------------------------


def new_signal_state() -> dict:
    """A fresh per-candidate-per-day state for step_candle()."""
    return {"invalidated": False, "active_signal": None, "breakout_counter": 0}


def step_candle(
    state: dict,
    ts,
    row: pd.Series,
    direction: str,
    e21: float | None,
    sig_atr: float | None,
    vol_min_so_far: float,
    first_candle_low: float,
    first_candle_high: float,
    sig_range_low: float | None = None,
    sig_range_high: float | None = None,
    e50: float | None = None,
    fvg_lo: float | None = None,
    fvg_hi: float | None = None,
) -> tuple[dict, dict | None]:
    """One incremental step of the §3.2 walk-forward loop. Does NOT
    mutate `state` -- returns a new state dict (caller keeps its own
    running copy, e.g. one per candidate per day).

    `e21`/`sig_atr`: this candle's own EMA21/ATR14 values (the caller
    looks these up from its continuous series, same as find_entry()).
    `vol_min_so_far`: the running minimum volume from 09:15 through and
    INCLUDING this candle -- the caller must update its own running min
    with this candle's volume BEFORE calling step_candle (find_entry()'s
    vol_so_far_full.loc[:ts].min() is inclusive of ts).
    `first_candle_low`/`first_candle_high`: the day's 09:15 candle's own
    low/high (v2 §3.2 step 1b) -- fixed for the whole day, the caller
    captures it once and passes the same value on every call.
    `e50`: v5.4 §5m's trend filter on the signal candle -- this candle's
    own EMA50 value. Python `None` (the default) means the filter is OFF
    entirely (pre-§5m behavior, matching find_entry()'s own ema50_series
    =None convention); a real NaN (e.g. `float("nan")`, what a pandas
    lookup actually returns for a timestamp before 50 candles of history
    exist) means the filter IS on but unavailable for this candle, which
    fails it closed -- `None` and NaN are deliberately distinguishable
    here (`x is None` vs `pd.isna(x)`), not the same "missing" bucket.
    `sig_range_low`/`sig_range_high`: v5.4 §5i.1's one-sided signal gate
    reference range (09:20+09:25 candles), also fixed for the whole day.
    None fails closed -- see signal_in_range().
    `fvg_lo`/`fvg_hi`: v5.4 §5n's fair-value-gap veto zone (see
    fair_value_gap()), fixed for the whole day. None means inert (no
    veto) -- either no gap that day, or the caller didn't wire this in.

    Returns (new_state, event) -- event is None (nothing happened this
    candle) or one of:
      {"type": "invalidated"}
      {"type": "signal_formed", "time", "high", "low", "atr", "replaced_expired"}
      {"type": "signal_expired"}
      {"type": "triggered", "signal_time", "entry_time", "entry_price", "stop_price"}

    "signal_formed"'s "replaced_expired" is True when this same candle
    just killed a DIFFERENT signal before qualifying as a fresh one
    itself (§5l) -- the caller (intraday_engine.process_candle) needs
    this to know to retire the OLD signal_db_id as "expired" before
    creating a row for the new one, since step_candle() itself never
    emits a separate signal_expired event for that intermediate death.
    """
    if state["invalidated"]:
        return state, None
    state = dict(state)

    if pd.notna(e21):
        if direction == LONG and row["close"] < e21 or direction == SHORT and row["close"] > e21:
            state["invalidated"] = True
    # v2 NEW -- first-candle-close-through gate (§3.2 step 1b), same
    # whole-day-kill-switch semantics as the EMA21 gate just above.
    if not state["invalidated"] and (
        direction == LONG
        and row["close"] < first_candle_low
        or direction == SHORT
        and row["close"] > first_candle_high
    ):
        state["invalidated"] = True
    if state["invalidated"]:
        state["active_signal"] = None
        return state, {"type": "invalidated"}

    active = state["active_signal"]
    if active is not None:
        state["breakout_counter"] += 1
        # Trigger is checked FIRST, before any quality gate -- a genuine
        # breakout candle necessarily exceeds the signal candle's own
        # high/low (that's what "trigger" means), so a range/volume gate
        # can never be satisfied BY the triggering candle itself; it only
        # makes sense as a check on a candle that did NOT trigger, to
        # decide whether the window continues to the next candle.
        buf = active["atr"] * ATR_PCT_BUFFER
        if direction == LONG:
            trigger_level = active["hi"] + buf
            triggered = row["high"] >= trigger_level
        else:
            trigger_level = active["lo"] - buf
            triggered = row["low"] <= trigger_level
        if triggered:
            stop_price = (active["lo"] - buf) if direction == LONG else (active["hi"] + buf)
            event = {
                "type": "triggered",
                "signal_time": active["time"],
                "entry_time": ts,
                "entry_price": trigger_level,
                "stop_price": stop_price,
            }
            state["active_signal"] = None
            return state, event
        # v3.1 -- this window candle did NOT trigger. Before letting the
        # window continue to the next candle, it must have been a clean
        # continuation of the signal candle's own pullback: the
        # confirming color (green for LONG, red for SHORT), LOWER volume
        # than the signal candle (not a fresh volume spike), and its own
        # high/low still WITHIN the signal candle's range (hasn't already
        # poked outside it without actually triggering). Fail any of
        # these and the signal drops immediately rather than waiting out
        # the remaining window candle(s). This is a CANDLE-CLOSE-only
        # check (a live tick has no "color"/final volume mid-candle) --
        # check_tick_trigger()'s own tick-driven trigger check
        # deliberately evaluates none of this, matching how the trigger
        # price-crossing itself is checked continuously while these can
        # only be confirmed at close. In practice this only actually
        # runs for a window candle that didn't already trigger via a live
        # tick during its own formation -- process_candle()'s own
        # tracker.done guard skips calling this entirely once a tick has
        # already triggered.
        gate_ok = False
        if state["breakout_counter"] < BREAKOUT_WINDOW:
            # Candle #1 only -- same continuation gate as before decides
            # whether candle #2 gets a look.
            confirm_is_green = row["close"] > row["open"]
            confirm_is_red = row["close"] < row["open"]
            wants_confirm_color = confirm_is_green if direction == LONG else confirm_is_red
            volume_ok = row["volume"] < active["volume"]
            range_ok = row["high"] <= active["hi"] and row["low"] >= active["lo"]
            gate_ok = wants_confirm_color and volume_ok and range_ok
        if gate_ok:
            return state, None
        # §5l -- v5.1/v5.3's "re-signal on close" is REMOVED entirely (no
        # close-extension test, no volume-vs-signal test, no chain_len
        # cap). The dying signal's own candle -- candle #1 that just
        # failed the continuation gate above, or candle #2 that
        # exhausted the window -- falls straight through below and is
        # re-tested as an ORDINARY fresh signal candle: same day's-
        # lowest-volume/color/one-sided-gate bar as any other candle,
        # nothing carried over from the dying signal. Verified worth
        # +1.83 CAGR / -0.88pp drawdown over the old re-signal rule
        # (Spec §5l.1) -- the old rule only required volume lower than
        # the signal it replaced, not the day's actual running minimum,
        # so it manufactured weaker setups from already-failing ones.
        state["active_signal"] = None
        state["breakout_counter"] = 0
        replaced_expired = True
    else:
        replaced_expired = False

    if ts.time() > NEW_SIGNAL_CUTOFF:
        return state, ({"type": "signal_expired"} if replaced_expired else None)
    is_red = row["close"] < row["open"]
    is_green = row["close"] > row["open"]
    wants_color = is_red if direction == LONG else is_green
    is_lowest_volume = row["volume"] <= vol_min_so_far * (1 + VOL_THRESHOLD_PCT)
    in_range = signal_in_range(
        direction, float(row["open"]), float(row["close"]), sig_range_low, sig_range_high
    )
    # v5.4 §5m -- e50=None means the filter is off entirely; a real NaN
    # (filter on, not enough history yet) fails this candle closed. See
    # this function's own docstring for the None-vs-NaN distinction.
    trend_ok = True if e50 is None else signal_trend_ok(direction, float(row["close"]), e50)
    fvg_ok = not fvg_vetoed(float(row["close"]), fvg_lo, fvg_hi)
    if (
        wants_color
        and is_lowest_volume
        and in_range
        and trend_ok
        and fvg_ok
        and pd.notna(sig_atr)
        and sig_atr > 0
    ):
        # float(...) throughout -- see find_entry()'s matching comment:
        # an all-whole-number OHLCV candle (int64 dtype) silently
        # serializes to a BLOB instead of a number if a raw numpy.int64
        # ever reaches sqlite3 unwrapped (verified live: BAJAJ-AUTO,
        # 2026-10-01 -- crashed _render_live_section() downstream).
        hi, lo = float(row["high"]), float(row["low"])
        state["active_signal"] = {
            "time": ts,
            "hi": hi,
            "lo": lo,
            "atr": sig_atr,
            "volume": float(row["volume"]),
            "signal_close": float(row["close"]),
        }
        state["breakout_counter"] = 0
        return state, {
            "type": "signal_formed",
            "time": ts,
            "high": hi,
            "low": lo,
            "atr": sig_atr,
            "replaced_expired": replaced_expired,
        }
    return state, ({"type": "signal_expired"} if replaced_expired else None)


def check_tick_trigger(state: dict, direction: str, ltp: float, ts) -> dict | None:
    """Continuous (tick-driven) breakout-trigger check for use BETWEEN
    candle closes -- Spec.md §6.2 calls for trigger detection to be
    tick-driven rather than waiting for a candle to fully close (up to
    5 minutes of delay). Mirrors step_candle()'s own trigger check
    exactly (same trigger_level/stop_price formulas), just evaluated
    against a single live price instead of a closed candle's high/low.

    Does NOT mutate `state` and does not itself clear active_signal --
    the caller (which owns the tracker's state) does that, the same way
    it already does for step_candle()'s own "triggered" event, so both
    paths update state identically. Returns None if there's no active
    signal (or the tick hasn't reached the trigger level yet).

    Because a real intraday candle's high/low is simply the extreme of
    every tick within it, this can only trigger a candidate on the SAME
    candle step_candle() would have -- it just detects the crossing the
    moment a tick reaches it, instead of waiting for that candle to
    close, so it never changes which candle is the trigger candle."""
    if state.get("invalidated"):
        return None
    active = state.get("active_signal")
    if active is None:
        return None
    buf = active["atr"] * ATR_PCT_BUFFER
    if direction == LONG:
        trigger_level = active["hi"] + buf
        triggered = ltp >= trigger_level
    else:
        trigger_level = active["lo"] - buf
        triggered = ltp <= trigger_level
    if not triggered:
        return None
    stop_price = (active["lo"] - buf) if direction == LONG else (active["hi"] + buf)
    return {
        "type": "triggered",
        "signal_time": active["time"],
        "entry_time": ts,
        "entry_price": trigger_level,
        "stop_price": stop_price,
    }


def target_price(
    entry: float, stop: float, direction: str, reward_risk: float = REWARD_RISK
) -> float:
    """Spec.md §5 -- flat reward:risk target."""
    risk = abs(entry - stop)
    return entry + reward_risk * risk if direction == LONG else entry - reward_risk * risk


def simulate_exit(
    day: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry: float,
    stop: float,
    direction: str,
    reward_risk: float = REWARD_RISK,
    squareoff_time: str = SQUAREOFF_TIME,
) -> list[dict]:
    """Spec.md §5's half-target/half-squareoff exit management, walking
    forward from entry_time over the SAME day's candles. No breakeven
    move on the remaining half after target (§9.2 -- tested and found
    marginally worse). Returns a list of 1-2 leg dicts:
    {"exit_time", "exit_price", "reason", "qty_frac"} -- reason is one
    of "target"/"stop"/"squareoff"/"eod_data_end"."""
    target = target_price(entry, stop, direction, reward_risk)
    sq = day.between_time(squareoff_time, squareoff_time).index
    squareoff_ts = sq[0] if len(sq) else None

    legs: list[dict] = []
    target_taken = False
    remaining_frac = 1.0

    for ts, row in day[day.index > entry_time].iterrows():
        hit_stop = row["low"] <= stop if direction == LONG else row["high"] >= stop
        hit_target = row["high"] >= target if direction == LONG else row["low"] <= target

        if hit_stop:
            legs.append(
                {"exit_time": ts, "exit_price": stop, "reason": "stop", "qty_frac": remaining_frac}
            )
            return legs

        if not target_taken and hit_target:
            legs.append(
                {"exit_time": ts, "exit_price": target, "reason": "target", "qty_frac": 0.5}
            )
            remaining_frac = 0.5
            target_taken = True

        if squareoff_ts is not None and ts >= squareoff_ts:
            legs.append(
                {
                    "exit_time": ts,
                    "exit_price": float(row["close"]),
                    "reason": "squareoff",
                    "qty_frac": remaining_frac,
                }
            )
            return legs

    last = day.iloc[-1]
    legs.append(
        {
            "exit_time": day.index[-1],
            "exit_price": float(last["close"]),
            "reason": "eod_data_end",
            "qty_frac": remaining_frac,
        }
    )
    return legs


def simulate_exit_v54(
    day: pd.DataFrame,
    entry_time: pd.Timestamp,
    entry: float,
    stop: float,
    direction: str,
    ema10_series: pd.Series,
    reward_risk: float = REWARD_RISK,
    squareoff_time: str = SQUAREOFF_TIME,
) -> list[dict]:
    """Batch/backtest equivalent of the LIVE engine's actual adopted exit
    management -- intraday_engine.py's check_entry_candle_close() +
    check_intracandle_exit() + step_position_boundary() + force_squareoff()
    combined into one candle-by-candle walk, instead of live's tick-driven
    version of the same rules. Unlike simulate_exit() above (the older,
    pre-§5b/§5i.2 v5.1 rule -- no breakeven, no EMA10 trail -- kept only
    for history/comparison, not what the live engine runs today), this is
    what intraday_backtest.py uses, since it's the only pure-logic version
    of the CURRENT live rule set:

      1. Entry-candle-close rule (§5i.3): if the entry candle's own CLOSE
         already breaches the stop, exit the FULL position at that close.
      2. Stop/breakeven (§5b): the original stop protects the full
         position until the first half books (fixed target or EMA10
         trail); from the candle AFTER that booking, the stop protecting
         the runner is the ENTRY price instead.
      3. Target touch -> EMA10 trail decision (§5i.2, choose_trail_ema()):
         at the 1:2R touch, defer and trail EMA10 if the target sits on
         its momentum side, else book the half at the fixed target
         immediately. ema10_series must be ema_n(close, TRAIL_EMA_SLOW)
         computed over the SAME continuous multi-day series find_entry()'s
         caller already built (never cold-started per day).
      4. Trail-crossed exit (step_position_boundary()): the first candle
         AFTER the touch candle whose own close crosses back through
         EMA10 books the half at the NEXT candle's open (or, if there is
         no next candle in `day`, that crossing candle's own close -- the
         closest batch equivalent of live's "fall back to the current
         price" case).
      5. Squareoff at the "15:10"-labeled candle's own CLOSE (Spec v3 §9 --
         NOT force_squareoff()'s real-time-LTP convention, which only
         exists because live can't achieve this exact price).

    Deliberate batch-vs-tick approximation: the touch candle's own EMA10
    (not the prior COMPLETED candle's) decides the trail, since a 5-min
    candle walk has no tick-level "still forming" distinction once that
    candle's full OHLC is already known -- the same convention the
    strategy's reference backtest uses, and what the spec's published
    CAGR/DD numbers are measured against."""
    target = target_price(entry, stop, direction, reward_risk)
    sq = day.between_time(squareoff_time, squareoff_time).index
    squareoff_ts = sq[0] if len(sq) else None

    if entry_time in day.index:
        ec = day.loc[entry_time]
        breached = (
            (float(ec["close"]) <= stop) if direction == LONG else (float(ec["close"]) >= stop)
        )
        if breached:
            return [
                {
                    "exit_time": entry_time,
                    "exit_price": float(ec["close"]),
                    "reason": "entry_candle_close",
                    "qty_frac": 1.0,
                }
            ]

    legs: list[dict] = []
    target_touched = False
    target_taken = False
    trailing = False
    remaining_frac = 1.0
    active_stop = stop

    rows_after = list(day[day.index > entry_time].iterrows())
    for k, (ts, row) in enumerate(rows_after):
        hit_stop = row["low"] <= active_stop if direction == LONG else row["high"] >= active_stop
        if hit_stop:
            reason = "breakeven" if target_taken else "stop"
            legs.append(
                {
                    "exit_time": ts,
                    "exit_price": active_stop,
                    "reason": reason,
                    "qty_frac": remaining_frac,
                }
            )
            return legs

        if not target_touched:
            hit_target = row["high"] >= target if direction == LONG else row["low"] <= target
            if hit_target:
                target_touched = True
                trail_span = choose_trail_ema(direction, target, ema10_series.get(ts))
                if trail_span is None:
                    legs.append(
                        {"exit_time": ts, "exit_price": target, "reason": "target", "qty_frac": 0.5}
                    )
                    remaining_frac = 0.5
                    target_taken = True
                    active_stop = entry
                else:
                    trailing = True
        elif trailing and not target_taken:
            if trail_crossed(direction, float(row["close"]), ema10_series.get(ts)):
                fill_ts, fill_px = ts, float(row["close"])
                if k + 1 < len(rows_after):
                    nts, nrow = rows_after[k + 1]
                    if squareoff_ts is None or nts <= squareoff_ts:
                        fill_ts, fill_px = nts, float(nrow["open"])
                legs.append(
                    {
                        "exit_time": fill_ts,
                        "exit_price": fill_px,
                        "reason": f"ema{TRAIL_EMA_SLOW}_trail_exit",
                        "qty_frac": 0.5,
                    }
                )
                remaining_frac = 0.5
                target_taken = True
                active_stop = entry

        if squareoff_ts is not None and ts >= squareoff_ts:
            legs.append(
                {
                    "exit_time": ts,
                    "exit_price": float(row["close"]),
                    "reason": "squareoff",
                    "qty_frac": remaining_frac,
                }
            )
            return legs

    last = day.iloc[-1]
    legs.append(
        {
            "exit_time": day.index[-1],
            "exit_price": float(last["close"]),
            "reason": "eod_data_end",
            "qty_frac": remaining_frac,
        }
    )
    return legs


# ---------------------------------------------------------------------------
# §7 -- position sizing
# ---------------------------------------------------------------------------


def position_size(capital_alloc: float, risk_budget: float, entry: float, stop: float) -> int:
    """Spec.md §7 -- min of risk-based and capital-based sizing,
    whichever binds first, floored to a whole share."""
    risk_per_share = abs(entry - stop)
    if risk_per_share <= 0 or entry <= 0:
        return 0
    qty_by_risk = int(risk_budget // risk_per_share)
    qty_by_capital = int(capital_alloc // entry)
    return max(min(qty_by_risk, qty_by_capital), 0)


def leg_quantities(qty: int, legs: list[dict]) -> list[int]:
    """Splits a whole-share `qty` across simulate_exit()'s legs,
    honoring each leg's qty_frac while keeping the total exact (any
    rounding remainder goes to the last leg)."""
    if len(legs) == 1:
        return [qty]
    first = int(qty * legs[0]["qty_frac"])
    return [first, qty - first]


# ---------------------------------------------------------------------------
# §8 -- transaction cost model
# ---------------------------------------------------------------------------


def round_trip_cost(
    entry_price: float, exit_price: float, qty: int, direction: str = LONG
) -> float:
    """Spec.md §8 -- total cost (brokerage + STT + exchange + GST) for
    one round-trip (one buy leg + one sell leg) of `qty` shares.

    `direction` (v3 fix, Spec v3 §9): STT applies to whichever leg is
    the actual SELL order, not always the exit leg. For LONG (buy then
    sell), that's the exit. For SHORT (short-sell then cover-buy), the
    SELL leg is the ENTRY, not the exit -- the previous default (always
    charging STT on exit_turnover) silently mischarged every SHORT
    trade, which this strategy trades more often than LONG (day-bias/
    sector-gate mechanics naturally skew SHORT). `direction` defaults to
    LONG only for source-compatibility with any pre-v3 caller that
    doesn't pass it; live/backtest code should always pass it explicitly."""
    buy_turnover = entry_price * qty
    sell_turnover = exit_price * qty
    stt_turnover = sell_turnover if direction == LONG else buy_turnover

    brokerage = min(BROKERAGE_PCT * buy_turnover, BROKERAGE_CAP) + min(
        BROKERAGE_PCT * sell_turnover, BROKERAGE_CAP
    )
    stt = STT_SELL_PCT * stt_turnover
    exchange_txn = EXCHANGE_TXN_PCT * (buy_turnover + sell_turnover)
    gst = GST_PCT * (brokerage + exchange_txn)

    return brokerage + stt + exchange_txn + gst
