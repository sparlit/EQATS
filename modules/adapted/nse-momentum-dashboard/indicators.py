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
Technical indicators used by the screener. Pure pandas/numpy — no TA-lib
dependency so it runs anywhere.
"""


import datetime as dt

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def weekly_rsi(close: pd.Series, period: int = 14) -> float:
    """RSI(period) on weekly closes (W-FRI anchored, trading-week end) --
    the last (possibly still-forming) week's value, the same 'currently
    developing candle updates daily' convention charting platforms use
    for weekly/monthly indicators. NaN until there's at least period+1
    weekly closes of history."""
    weekly = close.resample("W-FRI").last().dropna()
    if len(weekly) < period + 1:
        return np.nan
    return float(rsi(weekly, period).iloc[-1])


def monthly_rsi(close: pd.Series, period: int = 14) -> float:
    """Same as weekly_rsi() but resampled to calendar month-end closes."""
    monthly = close.resample("ME").last().dropna()
    if len(monthly) < period + 1:
        return np.nan
    return float(rsi(monthly, period).iloc[-1])


def _higher_tf_trend_ok(
    resampled_close: pd.Series, period_primary: int = 200, period_fallback: int = 50
) -> float:
    """True if the latest (possibly still-forming) bar closed above its own
    EMA(period_primary); falls back to EMA(period_fallback) when there
    isn't enough resampled history for the primary period yet (e.g. early
    in a backtest -- a stock with 3 years of daily data has ~150-160
    weekly bars, short of 200). NaN (not even the fallback period's worth
    of history) rather than a default True/False -- same fail-closed
    convention as weekly_rsi/monthly_rsi above."""
    if len(resampled_close) >= period_primary:
        period = period_primary
    elif len(resampled_close) >= period_fallback:
        period = period_fallback
    else:
        return np.nan
    return bool(resampled_close.iloc[-1] > ema(resampled_close, period).iloc[-1])


def precompute_weekly_monthly_bars(long_close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Precomputes the FULL weekly/monthly last-close bar series ONCE from
    long_close's entire history -- the "already complete" portion
    weekly_above_ema/monthly_above_ema's fast path (precomputed_full param)
    reuses on every call instead of re-resampling all of long_close from
    scratch on every single rebalance day, which profiled as ~45% of a
    gate-enabled backtest's total runtime (the resample() call itself, not
    the EMA math on top of it, is what's expensive on a multi-year daily
    series).

    Safe because a COMPLETE calendar bucket's last-close never depends on
    what happens after it -- resample("W-FRI").last() for the week ending
    a past Friday gives the identical value whether you resample the
    whole history or just that one week's days. Slicing this precomputed
    series to `.loc[:date]` for a particular query date is therefore
    correct for every bucket EXCEPT one: the bucket for whatever week/
    month `date` itself currently falls inside, which may still be
    "forming" (`date` isn't necessarily that period's last trading day)
    -- but that bucket's label is a period-END date (e.g. the upcoming
    Friday), which is chronologically AFTER `date` while it's still
    forming, so `.loc[:date]` automatically excludes it rather than
    silently returning a wrong, future-leaking value. See
    _fast_higher_tf_close for how the caller reconstructs that one
    still-needed bucket cheaply instead."""
    weekly = long_close.resample("W-FRI").last().dropna()
    monthly = long_close.resample("ME").last().dropna()
    return weekly, monthly


def _precompute_higher_tf_trend_ok_daily(
    close: pd.Series, freq: str, period_primary: int, period_fallback: int
) -> pd.Series:
    """2026-08-25 addition: fully vectorized, resample-free version of
    calling weekly_above_ema/monthly_above_ema (via _fast_higher_tf_close)
    for EVERY date in `close`'s index one at a time -- eliminates the
    per-call resample() overhead that profiled as the dominant cost of a
    daily-rebalance, weekly_monthly_gate_enabled backtest (500,000+
    resample() calls over a full 5yr/202-symbol run). Mathematically
    identical to the old per-call path, not an approximation -- see the
    verification below.

    Two pieces, matching _fast_higher_tf_close's own two cases exactly:

    1) COMPLETE buckets (a full trading week/month that's already
       finished): the bucket's trend_ok only needs computing ONCE per
       bucket, not once per daily date that happens to fall after it --
       both ema(complete, period_primary) and ema(complete, period_fallback)
       are single vectorized ewm() calls over the short (~260-week or
       ~60-month) resampled series, then the period_primary-vs-fallback
       choice and the > comparison are also fully vectorized.

    2) The CURRENT, still-forming bucket (every day strictly between the
       last complete bucket-end and the next one): _fast_higher_tf_close
       resamples just an 8/33-day tail to get this one value, but that
       tail-resample's `.last()` is provably just `close.loc[date]`
       itself (the most recent close within the still-forming period IS
       the last value chronologically, by construction) -- so no
       resampling is needed at all. What DOES still need real computation
       is the EMA value AS IF this provisional close were appended to the
       complete series: since ewm(adjust=False) is a simple one-step
       recursive update (new_ema = alpha*new_value + (1-alpha)*prev_ema,
       alpha = 2/(period+1) -- matches indicators.ema()'s own ewm(span=
       period, adjust=False) formula exactly), that's an O(1) scalar
       computation per day using the LAST complete bucket's own
       precomputed EMA value as the recursion's starting point. The
       period_primary-vs-fallback choice for a forming bucket uses
       complete_bucket_count + 1 (matching _fast_higher_tf_close
       appending exactly one synthetic row before the length check).

    Returns a pd.Series indexed exactly like `close`, dtype "boolean"
    (nullable, so True/False/pd.NA all round-trip correctly through
    .fillna/.astype(bool) the same way the old NaN-float convention did)."""
    complete = close.resample(freq).last().dropna()
    n = len(complete)
    if n == 0:
        return pd.Series(pd.array([pd.NA] * len(close), dtype="boolean"), index=close.index)

    ema_primary_full = ema(complete, period_primary).to_numpy()
    ema_fallback_full = ema(complete, period_fallback).to_numpy()
    complete_vals = complete.to_numpy()
    lengths = np.arange(1, n + 1)
    use_primary = lengths >= period_primary
    use_fallback = (~use_primary) & (lengths >= period_fallback)
    chosen_ema = np.where(
        use_primary, ema_primary_full, np.where(use_fallback, ema_fallback_full, np.nan)
    )
    complete_ok = complete_vals > chosen_ema  # NaN comparisons -> False; masked below
    complete_valid = use_primary | use_fallback

    alpha_primary = 2.0 / (period_primary + 1)
    alpha_fallback = 2.0 / (period_fallback + 1)

    close_vals = close.to_numpy()
    daily_index = close.index
    # Position (0-based) of the last COMPLETE bucket at/before each daily
    # date, -1 if none yet. searchsorted on complete's own (sorted,
    # unique) bucket-end dates.
    bucket_pos = complete.index.searchsorted(daily_index, side="right") - 1
    is_exact_bucket_end = daily_index.isin(complete.index)

    result = np.full(len(daily_index), np.nan)
    valid_mask = np.zeros(len(daily_index), dtype=bool)
    for i in range(len(daily_index)):
        j = bucket_pos[i]
        if is_exact_bucket_end[i] and j >= 0 and complete.index[j] == daily_index[i]:
            if complete_valid[j]:
                result[i] = complete_ok[j]
                valid_mask[i] = True
            continue
        complete_count = j + 1  # strictly-prior complete buckets (0 if none yet)
        total_len = complete_count + 1  # +1 for this day's own provisional bucket
        if total_len >= period_primary:
            prev_ema = ema_primary_full[j] if j >= 0 else close_vals[i]
            alpha = alpha_primary
        elif total_len >= period_fallback:
            prev_ema = ema_fallback_full[j] if j >= 0 else close_vals[i]
            alpha = alpha_fallback
        else:
            continue
        new_ema = alpha * close_vals[i] + (1 - alpha) * prev_ema
        result[i] = close_vals[i] > new_ema
        valid_mask[i] = True

    out = pd.array(np.where(valid_mask, result.astype(bool), pd.NA), dtype="boolean")
    return pd.Series(out, index=daily_index)


def precompute_weekly_monthly_trend_ok(df: pd.DataFrame, cfg: dict) -> tuple[pd.Series, pd.Series]:
    """Caller-facing entry point for _precompute_higher_tf_trend_ok_daily --
    one call per symbol (ONCE, over its full history), returns (weekly_ok,
    monthly_ok) daily-aligned boolean/NA series ready for a plain `.loc[date]`
    lookup in build_technical_table/apply_gates instead of a per-day
    weekly_above_ema()/monthly_above_ema() call. cfg's ema_slow/ema_fast
    supply the same period_primary/period_fallback weekly_above_ema/
    monthly_above_ema already default to (200/50)."""
    close = df["close"]
    period_primary = cfg.get("ema_slow", 200)
    period_fallback = cfg.get("ema_fast", 50)
    weekly_ok = _precompute_higher_tf_trend_ok_daily(
        close, "W-FRI", period_primary, period_fallback
    )
    monthly_ok = _precompute_higher_tf_trend_ok_daily(close, "ME", period_primary, period_fallback)
    return weekly_ok, monthly_ok


def _fast_higher_tf_close(
    precomputed_full: pd.Series, close_upto_date: pd.Series, date, freq: str
) -> pd.Series:
    """Reconstructs exactly what close_upto_date.resample(freq).last().
    dropna() would produce, without re-resampling all of close_upto_date --
    see precompute_weekly_monthly_bars's docstring for why this is safe.
    Every complete bucket comes straight from the precomputed series;
    only the possibly-still-forming bucket containing `date` is resampled
    fresh, from a short trailing slice of close_upto_date (a resample
    bucket's aggregation only ever looks at rows within its own calendar
    range, so resampling just the tail reproduces the identical value for
    that one bucket as resampling the full series would)."""
    complete = precomputed_full.loc[:date]
    tail_days = 8 if freq == "W-FRI" else 33
    current = close_upto_date.tail(tail_days).resample(freq).last().dropna()
    if not current.empty and (complete.empty or current.index[-1] > complete.index[-1]):
        return pd.concat([complete, current.tail(1)])
    return complete


def weekly_above_ema(
    close: pd.Series,
    period_primary: int = 200,
    period_fallback: int = 50,
    precomputed_full: pd.Series | None = None,
    asof_date=None,
) -> float:
    """precomputed_full/asof_date: optional fast-path pair (from
    precompute_weekly_monthly_bars()'s weekly return value, plus the date
    this call represents) -- reconstructs the same resampled series far
    cheaper than resampling all of `close` from scratch every call (see
    _fast_higher_tf_close). Both None (default, and always the case for
    live callers today) reproduces the original full-resample-every-time
    behavior exactly -- correct either way, this only changes speed."""
    if precomputed_full is not None and asof_date is not None:
        weekly = _fast_higher_tf_close(precomputed_full, close, asof_date, "W-FRI")
    else:
        weekly = close.resample("W-FRI").last().dropna()
    return _higher_tf_trend_ok(weekly, period_primary, period_fallback)


def monthly_above_ema(
    close: pd.Series,
    period_primary: int = 200,
    period_fallback: int = 50,
    precomputed_full: pd.Series | None = None,
    asof_date=None,
) -> float:
    """Same fast-path contract as weekly_above_ema -- see its docstring."""
    if precomputed_full is not None and asof_date is not None:
        monthly = _fast_higher_tf_close(precomputed_full, close, asof_date, "ME")
    else:
        monthly = close.resample("ME").last().dropna()
    return _higher_tf_trend_ok(monthly, period_primary, period_fallback)


def weekly_snapshot(
    close: pd.Series, rsi_period: int = 14, ema_primary: int = 200, ema_fallback: int = 50
) -> tuple[float, float]:
    """RSI + above-EMA trend in one pass off a single weekly resample --
    compute_snapshot's hot path used to call weekly_rsi() and
    weekly_above_ema() separately, each resampling `close` to weekly on
    its own (profiled: resample() dominates each function's cost, so
    that was ~2x the resampling work needed). Returns (rsi, trend_ok),
    each independently NaN per its own insufficient-history rule."""
    weekly = close.resample("W-FRI").last().dropna()
    rsi_val = float(rsi(weekly, rsi_period).iloc[-1]) if len(weekly) >= rsi_period + 1 else np.nan
    return rsi_val, _higher_tf_trend_ok(weekly, ema_primary, ema_fallback)


def monthly_snapshot(
    close: pd.Series, rsi_period: int = 14, ema_primary: int = 200, ema_fallback: int = 50
) -> tuple[float, float]:
    """Same as weekly_snapshot() but off a single monthly resample."""
    monthly = close.resample("ME").last().dropna()
    rsi_val = float(rsi(monthly, rsi_period).iloc[-1]) if len(monthly) >= rsi_period + 1 else np.nan
    return rsi_val, _higher_tf_trend_ok(monthly, ema_primary, ema_fallback)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    return macd_line, signal_line, macd_line - signal_line


def momentum_return(close: pd.Series, lookback: int, skip: int = 0) -> float:
    """Return over `lookback` trading days, skipping the most recent `skip`
    days (classic 12-2 / 6-1 momentum construction to avoid the short-term
    reversal effect documented by Jegadeesh 1990)."""
    if len(close) < lookback + skip + 1:
        return np.nan
    end = close.iloc[-1 - skip]
    start = close.iloc[-1 - skip - lookback]
    return (end / start - 1) * 100


def pct_of_52w_high(close: pd.Series) -> float:
    window = close.tail(252)
    return float(close.iloc[-1] / window.max()) if len(window) else np.nan


def volume_expansion(volume: pd.Series, short: int = 20, long: int = 60) -> float:
    if len(volume) < long:
        return np.nan
    return float(volume.tail(short).mean() / volume.tail(long).mean())


def relative_strength(close: pd.Series, bench_close: pd.Series, lookback: int) -> float:
    """Stock return minus benchmark return over `lookback` days (in pct pts).

    Profiled as the single biggest cost (46% of a real backtest's
    runtime once the sector-diversification gate started calling this
    ~35 extra times/day, once per tracked sector index on top of its
    existing per-stock use) in a daily-cadence backtest: pd.concat's
    join/align machinery has real fixed per-call overhead that a naive
    "just trim the input first" fix barely dents (measured only ~1.2x)
    since it doesn't touch that overhead, only the size of what gets
    aligned.

    Fast path: NSE-listed instruments (a stock vs. NIFTY, or a stock vs.
    a sector index) almost always share the exact same trading calendar,
    so the join is usually a no-op -- verify the two series already
    agree on every date in the needed window (an index .equals() check,
    cheap and vectorized) and skip pd.concat's alignment machinery
    entirely if so, just index by position. Measured 16x faster than the
    original always-align version, verified byte-identical on real data.
    Falls back to the original (correct, if slower) join-based path for
    the rare case the two calendars genuinely disagree in that window
    (e.g. one side has a stock-specific trading halt)."""
    tail_n = lookback + 1
    if (
        len(close) >= tail_n
        and len(bench_close) >= tail_n
        and close.index[-tail_n:].equals(bench_close.index[-tail_n:])
    ):
        stock_ret = (close.iloc[-1] / close.iloc[-tail_n] - 1) * 100
        bench_ret = (bench_close.iloc[-1] / bench_close.iloc[-tail_n] - 1) * 100
        return stock_ret - bench_ret
    buffer = lookback + 30
    aligned = pd.concat(
        [close.tail(buffer), bench_close.tail(buffer)], axis=1, join="inner"
    ).dropna()
    if len(aligned) < lookback + 1:
        return np.nan
    s, b = aligned.iloc[:, 0], aligned.iloc[:, 1]
    stock_ret = (s.iloc[-1] / s.iloc[-1 - lookback] - 1) * 100
    bench_ret = (b.iloc[-1] / b.iloc[-1 - lookback] - 1) * 100
    return stock_ret - bench_ret


def regression_momentum(close: pd.Series, lookback: int) -> float:
    """BACKTEST-ONLY (for now), off by default (config.STRATEGY[
    "mom_method"] = "fixed_lookback") -- explicit request, after a real
    trade (OFSS, 2026-08-18->08-21) showed rs_3m collapsing from 5.74 to
    0.44 in just 3 trading days on almost no price change, purely
    because the 30-day-ago anchor point slid past OFSS's own early-July
    rally (a "base effect" -- see relative_strength's plain two-point
    construction above, which only ever looks at the window's two
    endpoints).

    Fits ln(price) against a plain day-index (0..lookback-1) over the
    trailing `lookback` sessions via OLS, then returns the fitted
    slope -- annualized to a %/year figure -- weighted by the fit's R^2
    (Andreas Clenow's "Stocks on the Move" construction: a smooth,
    consistent trend scores higher than an equally-sized but choppier
    one). Unlike a two-point return, every day in the window pulls on
    the fitted line in proportion to how far it sits from it, so no
    single edge-day can swing the whole figure the way OFSS's did.

    NaN (matching momentum_return/relative_strength's own behavior) if
    there isn't at least `lookback` bars of history yet."""
    if len(close) < lookback:
        return np.nan
    y = np.log(close.tail(lookback).to_numpy())
    x = np.arange(len(y), dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    ss_res = np.sum((y - fitted) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    annualized_slope_pct = (np.exp(slope * 252) - 1) * 100
    return annualized_slope_pct * r_squared


def regression_relative_strength(close: pd.Series, bench_close: pd.Series, lookback: int) -> float:
    """Drop-in regression-slope replacement for relative_strength() above
    -- same "stock minus benchmark" framing (so it plugs into score()'s
    existing rs_3m/rs_6m weights unchanged), but each side is scored via
    regression_momentum() instead of a plain two-point return."""
    stock_mom = regression_momentum(close, lookback)
    bench_mom = regression_momentum(bench_close, lookback)
    if np.isnan(stock_mom) or np.isnan(bench_mom):
        return np.nan
    return stock_mom - bench_mom


def precompute_daily_series(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Precomputes every date-indexed daily EWM series compute_snapshot
    needs (ema_fast, ema_slow, ema50_rising, macd_bullish, atr, rsi) ONCE
    over the full `df`, for a caller (backtest.run_backtest) to look up
    by date instead of recomputing from scratch inside a growing
    df.loc[:date] slice on every single rebalance day -- profiled as the
    dominant cost of a daily-cadence backtest (~87% of total runtime).

    Safe because every one of these is a CAUSAL ewm(adjust=False): the
    value at position i depends only on rows [0..i], never anything
    after, so precomputing over the whole series and looking a date up
    afterward is mathematically identical to recomputing over
    series.iloc[:i+1] each time -- a byte-identical optimization, not an
    approximation. Deliberately excludes the weekly/monthly resampled
    indicators: those are NOT safe to precompute this way (the
    "currently forming" week/month bucket would silently pull in future
    days if resampled from the full series once) -- they stay computed
    per-call in compute_snapshot, gated off by default."""
    close = df["close"]
    ema_f = ema(close, cfg["ema_fast"])
    ema_s = ema(close, cfg["ema_slow"])
    ema_9 = ema(close, 9)
    _, _, hist = macd(close)
    return pd.DataFrame(
        {
            "ema_fast": ema_f,
            "ema_slow": ema_s,
            "ema50_rising": ema_f > ema_f.shift(5),
            # BACKTEST EXPERIMENT (trend_gate_ema9_21_cross_enabled, off by
            # default) -- a simple 9/21 EMA cross as an alternative trend_ok
            # definition, see apply_gates(). ema_fast is 21 in this config, so
            # this reuses it rather than adding a separate "ema21" series.
            "ema9_above_ema21": ema_9 > ema_f,
            "macd_bullish": hist > 0,
            "atr": atr(df, cfg["atr_period"]),
            "rsi": rsi(close, cfg["rsi_period"]),
        },
        index=df.index,
    )


def precompute_ema_pullback_proximity(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """BACKTEST-ONLY (for now), off by default (config.STRATEGY[
    "ema_pullback_weight"] = 0.0) -- explicit request ("how far price is
    near EMA 13 and 21... entry should happen near EMA 13 or 21 with
    pullback.. price should be below EMA 21"): a proximity score for
    screener.score()'s optional 5th weighted z-score term, same
    opt-in-column pattern as sector_rs/resistance_clearance.

    proximity = -|close - nearest(EMA13, EMA21)| / ATR14, but ONLY on
    days close <= EMA21 (a real pullback zone) -- NaN otherwise, so an
    extended stock (price above EMA21) never gets a bonus for merely
    being close to EMA21 from above, and score()'s existing .fillna(0)
    convention treats those (and any other NaN) as neutral rather than
    penalized. Peaks at 0 exactly at whichever EMA price is nearest,
    and fades the further price has fallen below both -- rewards a
    fresh, shallow pullback over either an extended stock or one that's
    broken down hard.

    Approach A (continuous, no separate pullback-candle gate) per
    explicit selection -- proximity alone decides the score; how the
    pullback got there isn't separately checked here."""
    close = df["close"]
    ema13 = ema(close, cfg.get("ema_pullback_fast", 13))
    ema21 = ema(close, cfg.get("ema_pullback_mid", 21))
    atr14 = atr(df, cfg.get("ema_pullback_atr_period", 14))
    nearest_dist = pd.concat([(close - ema13).abs(), (close - ema21).abs()], axis=1).min(axis=1)
    proximity = -nearest_dist / atr14.replace(0, np.nan)
    return proximity.where(close <= ema21)


def compute_snapshot(
    df: pd.DataFrame,
    bench: pd.DataFrame,
    cfg: dict,
    long_close: pd.Series | None = None,
    precomputed_row: pd.Series | None = None,
    precomputed_weekly_monthly: tuple | None = None,
    precomputed_weekly_monthly_ok: tuple | None = None,
    precomputed_mad_df: pd.DataFrame | None = None,
    mad_precompute_active: bool = False,
    asof_date=None,
) -> dict:
    """All technical metrics for one symbol from its daily candles.

    precomputed_weekly_monthly/asof_date: optional, (weekly_full,
    monthly_full) from indicators.precompute_weekly_monthly_bars() (via
    backtest.run_backtest() -> screener.build_technical_table()) plus the
    date this snapshot represents -- turns on weekly_above_ema/
    monthly_above_ema's fast path instead of them re-resampling all of
    long_close from scratch on every call. None (default, and always the
    case for live callers today) reproduces the original behavior exactly
    -- correct either way, this only changes how fast.

    long_close: optional, deep (many-year) daily close history for the
    same symbol -- from backtest.load_long_history_cached() via
    screener.build_technical_table(). Used only for the weekly/monthly
    confirmation gate's RSI/EMA, which need far more history than a
    single backtest run's own `df` window usually has (a 200-bar monthly
    EMA needs ~16.7 years; even the 50-bar fallback needs ~4.2). None
    (default, and always the case for live callers today) falls back to
    `close` (this run's own window), same as before this param existed --
    those two indicators will then likely read NaN (fail-closed) unless
    `df` itself happens to be that deep.

    precomputed_row: optional, one row (as of the date this snapshot
    represents) from precompute_daily_series() -- from
    backtest.run_backtest() via screener.build_technical_table(). None
    (default, and always the case for live callers today) recomputes
    ema/atr/rsi/macd from `df` directly, exactly as before this param
    existed -- correct either way, this only changes how fast.

    precomputed_weekly_monthly_ok: optional, (weekly_ok, monthly_ok) --
    the DAILY-aligned boolean/NA series pair from
    precompute_weekly_monthly_trend_ok(), one call per symbol over its
    full history. When given (with asof_date), takes priority over
    precomputed_weekly_monthly above: a plain .loc[asof_date] lookup,
    zero resample() calls at all, vs. that one's still-one-resample-per-
    call fast path. Verified byte-identical to the original (no-cache)
    weekly_above_ema/monthly_above_ema output across ~9,200 sampled
    daily values, including dense day-by-day coverage through week/
    month boundaries -- not an approximation. None (default) falls
    through to precomputed_weekly_monthly's own fast path unchanged.

    precomputed_mad_df/mad_precompute_active: optional -- see
    _suggested_stop()'s own docstring, this pair distinguishes "backtest's
    lazy cache is active but this symbol isn't in it yet" from "no
    precompute infra at all" so the ranking-display suggested_stop field
    never forces an expensive computation for a symbol that was never
    actually entered."""
    if df.empty or len(df) < cfg["ema_slow"]:
        return {}

    close, volume = df["close"], df["volume"]
    price = float(close.iloc[-1])

    if precomputed_row is not None:
        ema_fast_v = float(precomputed_row["ema_fast"])
        ema_slow_v = float(precomputed_row["ema_slow"])
        ema50_rising_v = bool(precomputed_row["ema50_rising"])
        ema9_above_ema21_v = bool(precomputed_row["ema9_above_ema21"])
        macd_bullish_v = bool(precomputed_row["macd_bullish"])
        atr_now = float(precomputed_row["atr"])
        rsi_now = float(precomputed_row["rsi"])
    else:
        ema_f = ema(close, cfg["ema_fast"])
        ema_s = ema(close, cfg["ema_slow"])
        ema_9 = ema(close, 9)
        _, _, hist = macd(close)
        ema_fast_v = float(ema_f.iloc[-1])
        ema_slow_v = float(ema_s.iloc[-1])
        ema50_rising_v = float(ema_f.iloc[-1]) > float(ema_f.iloc[-6])
        ema9_above_ema21_v = float(ema_9.iloc[-1]) > float(ema_f.iloc[-1])
        macd_bullish_v = float(hist.iloc[-1]) > 0
        atr_now = float(atr(df, cfg["atr_period"]).iloc[-1])
        rsi_now = float(rsi(close, cfg["rsi_period"]).iloc[-1])

    # Profiled: computed unconditionally on every symbol on every
    # rebalance day even when weekly_monthly_gate_enabled is off (the
    # default) was ~45% of a real backtest's total runtime -- pure waste
    # for any run not using this gate. Simplified to EMA-trend only (no
    # RSI) at the user's request, after real-run data showed the RSI leg
    # (4 stacked conditions total: weekly/monthly RSI + weekly/monthly
    # EMA) caused excessive rebalance-exit churn -- a held position only
    # needed ONE of those 4 to wobble near its threshold to get force-
    # sold, even with nothing fundamentally wrong. Two conditions instead
    # of four is a real, meaningful reduction in how often that happens.
    # Note: this does NOT meaningfully speed the gate up -- the resample()
    # call, not the rsi() math on top of it, is the expensive part, and
    # weekly_above_ema/monthly_above_ema still need their own resample.
    weekly_rsi_val = monthly_rsi_val = np.nan
    if cfg.get("weekly_monthly_gate_enabled", False):
        wk_close = long_close if long_close is not None else close
        if precomputed_weekly_monthly_ok is not None and asof_date is not None:
            weekly_ok_daily, monthly_ok_daily = precomputed_weekly_monthly_ok
            w = weekly_ok_daily.get(asof_date, pd.NA) if hasattr(weekly_ok_daily, "get") else pd.NA
            m = (
                monthly_ok_daily.get(asof_date, pd.NA)
                if hasattr(monthly_ok_daily, "get")
                else pd.NA
            )
            weekly_trend_ok = np.nan if pd.isna(w) else bool(w)
            monthly_trend_ok = np.nan if pd.isna(m) else bool(m)
        elif precomputed_weekly_monthly is not None and asof_date is not None:
            weekly_full, monthly_full = precomputed_weekly_monthly
            weekly_trend_ok = weekly_above_ema(
                wk_close,
                cfg.get("ema_slow", 200),
                cfg.get("ema_fast", 50),
                precomputed_full=weekly_full,
                asof_date=asof_date,
            )
            monthly_trend_ok = monthly_above_ema(
                wk_close,
                cfg.get("ema_slow", 200),
                cfg.get("ema_fast", 50),
                precomputed_full=monthly_full,
                asof_date=asof_date,
            )
        else:
            weekly_trend_ok = weekly_above_ema(
                wk_close, cfg.get("ema_slow", 200), cfg.get("ema_fast", 50)
            )
            monthly_trend_ok = monthly_above_ema(
                wk_close, cfg.get("ema_slow", 200), cfg.get("ema_fast", 50)
            )
    else:
        weekly_trend_ok = monthly_trend_ok = np.nan

    # BACKTEST-ONLY (for now), off by default -- explicit request after
    # OFSS's rs_3m collapsed 5.74->0.44 in 3 days on a base effect (see
    # regression_relative_strength's docstring). "fixed_lookback"
    # (default) reproduces the original plain two-point return exactly;
    # "regression" swaps in the R^2-weighted regression-slope version.
    rs_func = (
        regression_relative_strength
        if cfg.get("mom_method", "fixed_lookback") == "regression"
        else relative_strength
    )
    return {
        "price": price,
        "mom_3m": momentum_return(close, cfg["mom_lookback_days_short"], cfg["skip_recent_days"]),
        "mom_6m": momentum_return(close, cfg["mom_lookback_days_long"], cfg["skip_recent_days"]),
        "rs_3m": rs_func(close, bench["close"], cfg["mom_lookback_days_short"]),
        "rs_6m": rs_func(close, bench["close"], cfg["mom_lookback_days_long"]),
        "pct_52w_high": pct_of_52w_high(close),
        "rsi": rsi_now,
        "weekly_rsi": weekly_rsi_val,
        "monthly_rsi": monthly_rsi_val,
        "weekly_above_ema": weekly_trend_ok,
        "monthly_above_ema": monthly_trend_ok,
        "above_ema50": price > ema_fast_v,
        "above_ema200": price > ema_slow_v,
        "ema50_rising": ema50_rising_v,
        "ema9_above_ema21": ema9_above_ema21_v,
        "macd_bullish": macd_bullish_v,
        "vol_expansion": volume_expansion(volume),
        "avg_volume_3m": float(volume.tail(cfg["mom_lookback_days_short"]).mean()),
        "atr": atr_now,
        "atr_pct": atr_now / price * 100,
        "suggested_stop": _suggested_stop(
            df, price, atr_now, cfg, precomputed_mad_df, mad_precompute_active, asof_date
        ),
    }


def _suggested_stop(
    df: pd.DataFrame,
    price: float,
    atr_now: float,
    cfg: dict,
    precomputed_mad_df: pd.DataFrame | None = None,
    mad_precompute_active: bool = False,
    asof_date=None,
) -> float:
    """Initial stop for a NEW buy -- the ATR distance below, unless
    mad_stop_enabled and the MAD volatility trail's own lower band is a
    sensible support (bull MAD-regime, sitting below price), same
    fallback rule as backtest.py's _initial_stop().

    precomputed_mad_df: optional, this symbol's full MAD trail (from
    mad_trail_strategy.precompute_mad_trail(), via backtest.run_backtest()
    -> screener.build_technical_table()) -- a plain .loc[asof_date] lookup
    instead of recomputing the whole rolling median/MAD/ATR trail from
    scratch on every call.

    mad_precompute_active: distinguishes "backtest's lazy per-run MAD
    cache is in play, but this particular symbol hasn't been entered yet
    so its trail was never computed" (precomputed_mad_df is None AND this
    is True -> cheap atr_stop fallback, never trigger a fresh computation
    here) from "no precompute infra at all, this is a live caller"
    (precomputed_mad_df is None AND this is False -> the full from-
    scratch computation below is correct and cheap, live only calls this
    once per symbol per scan). This field is ranking-display-only in a
    backtest context (backtest.py's OWN entry/ratchet decisions use their
    own lazy get_mad(), not this one), so it's never worth forcing a
    computation here purely to populate a column nobody reads mid-run --
    see backtest.run_backtest()'s _get_mad() docstring for the lazy-cache
    side of this."""
    atr_stop = price - cfg["atr_stop_multiple"] * atr_now
    if not cfg.get("mad_stop_enabled", False):
        return atr_stop
    if precomputed_mad_df is not None:
        if asof_date is not None and asof_date in precomputed_mad_df.index:
            last = precomputed_mad_df.loc[asof_date]
        elif asof_date is None and not precomputed_mad_df.empty:
            last = precomputed_mad_df.iloc[-1]
        else:
            return atr_stop
    elif mad_precompute_active:
        return atr_stop
    else:
        import mad_trail_strategy

        mad_cfg = mad_trail_strategy.cfg_from_strategy(cfg)
        mad_df = mad_trail_strategy.precompute_mad_trail(df, mad_cfg)
        if mad_df.empty:
            return atr_stop
        last = mad_df.iloc[-1]
    if last["regime"] == 1 and not pd.isna(last["lower"]) and last["lower"] < price:
        return float(last["lower"])
    return atr_stop


def xirr(cash_flows: list[tuple[dt.date, float]]) -> float | None:
    """Annualized rate of return for irregularly-timed cash flows -- the
    correct generalization of CAGR (reduces to plain CAGR when there's a
    single initial deposit, stays accurate once monthly top-ups start,
    unlike a naive CAGR calc which assumes one lump sum). Convention:
    negative amounts are money going in (deposits), positive amounts are
    money coming out (today's portfolio value, treated as a hypothetical
    liquidation).

    Solves for the rate r making NPV == 0 via Newton-Raphson:
        sum(amount_i / (1 + r) ** (days_i / 365)) == 0
    Pure Python/math -- no scipy or numpy_financial dependency, consistent
    with this module's existing pattern of hand-rolled indicators.

    Returns None if there are fewer than 2 cash flows (nothing to
    annualize) or if Newton-Raphson fails to converge (e.g. all flows have
    the same sign, so no rate can zero the NPV)."""
    if len(cash_flows) < 2:
        return None

    t0 = cash_flows[0][0]
    years = [(d - t0).days / 365.0 for d, _ in cash_flows]
    amounts = [a for _, a in cash_flows]

    def npv(rate: float) -> float:
        return sum(a / (1 + rate) ** y for a, y in zip(amounts, years, strict=False))

    def dnpv(rate: float) -> float:
        return sum(
            -y * a / (1 + rate) ** (y + 1) for a, y in zip(amounts, years, strict=False) if y > 0
        )

    rate = 0.1
    for _ in range(100):
        f = npv(rate)
        df_ = dnpv(rate)
        if df_ == 0:
            return None
        new_rate = rate - f / df_
        if new_rate <= -1:
            new_rate = (rate - 1) / 2  # halve the step toward the -1 boundary
        if abs(new_rate - rate) < 1e-9:
            return new_rate
        rate = new_rate
    return None
