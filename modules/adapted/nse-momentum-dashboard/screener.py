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
Composite screener: ranks the universe by a research-backed momentum score,
gated by trend-structure rules and fundamental quality filters.

Score construction (all cross-sectional z-scores, then weighted):
  40%  6-month relative strength vs NIFTY   (Jegadeesh & Titman)
  25%  3-month relative strength vs NIFTY   (intermediate momentum)
  20%  proximity to 52-week high            (George & Hwang)
  15%  volume expansion                     (confirmation, NSE studies)

Hard gates (a stock must pass ALL to appear as a candidate):
  - price above 50 EMA and 200 EMA, 50 EMA rising   (trend structure)
  - price >= 85% of 52-week high
  - RSI within [45, 78]  (in momentum regime, not parabolic)
  - fundamental quality gate (ROCE, D/E, profit growth) when data available
"""


import datetime as dt
import os

import fundamentals_agent as fa
import kite_client
import numpy as np
import pandas as pd
import sector_universe
import state_db

import config
import indicators


def _zscore(s: pd.Series) -> pd.Series:
    return (s - s.mean()) / s.std(ddof=0) if s.std(ddof=0) else s * 0


def build_technical_table(
    candles: dict[str, pd.DataFrame],
    bench: pd.DataFrame,
    cfg: dict | None = None,
    long_candles: dict[str, pd.DataFrame] | None = None,
    precomputed: dict[str, pd.Series] | None = None,
    precomputed_weekly_monthly: dict | None = None,
    precomputed_weekly_monthly_ok: dict | None = None,
    precomputed_mad: dict | None = None,
) -> pd.DataFrame:
    """cfg: BUG FIX -- this used to be hardcoded to config.STRATEGY
    internally, silently ignoring any custom cfg a caller (i.e. every
    Backtest UI run) actually passed, the same class of bug apply_gates()/
    score() already had fixed. Concretely: a backtest with the weekly/
    monthly confirmation gate enabled in its OWN cfg still computed
    weekly_rsi/monthly_rsi/weekly_above_ema/monthly_above_ema as if that
    gate were off (config.STRATEGY's default), so apply_gates() -- which
    DID receive the real cfg -- compared a real threshold against columns
    that were always NaN, zeroing every candidate for the whole run. Any
    backtest customizing ema_fast/ema_slow/mom_lookback_days_*/
    skip_recent_days away from config.STRATEGY's current values had the
    same silent-ignore problem for those, not just this one gate. None
    (default) reproduces config.STRATEGY, matching every live caller
    (run_screen()) that never had a custom cfg to begin with -- this
    fix only changes behavior for a caller that explicitly passes one.

    long_candles: optional, from backtest.load_long_history_cached() --
    deep per-symbol history for indicators.compute_snapshot's weekly/
    monthly confirmation-gate lookbacks. None (default, and always the
    case for live callers today) means those fall back to `candles`
    itself, same as before this existed.

    precomputed: optional, one row per symbol (as of the date this call
    represents) from backtest.run_backtest()'s precomputed daily-EWM
    series -- from indicators.precompute_daily_series() via
    rank_universe_asof(). None (default, and always the case for live
    callers today) falls back to indicators.compute_snapshot()
    recomputing ema/atr/rsi/macd from `df` directly, exactly as before
    this param existed -- correct either way, this only changes speed.

    precomputed_weekly_monthly: optional, {symbol: (weekly_full,
    monthly_full)} from indicators.precompute_weekly_monthly_bars() via
    backtest.run_backtest() -- turns on weekly_above_ema/
    monthly_above_ema's fast path (see their docstrings) instead of
    re-resampling all of long_close from scratch for every symbol on
    every rebalance day, profiled as ~45% of a gate-enabled backtest's
    runtime. None (default, and always the case for live callers today)
    reproduces the original behavior exactly -- correct either way, this
    only changes speed. The as-of date itself is read from `bench`'s own
    last index entry (rank_universe_asof always passes bench already
    sliced to exactly `:date`, so this is never a guess).

    precomputed_weekly_monthly_ok: optional, {symbol: (weekly_ok,
    monthly_ok)} from indicators.precompute_weekly_monthly_trend_ok() via
    backtest.run_backtest() -- takes priority over precomputed_weekly_
    monthly above (a plain daily-indexed lookup, zero resample() calls,
    vs. that one's still-one-resample-per-call fast path). None (default)
    falls through to precomputed_weekly_monthly's own fast path
    unchanged -- see compute_snapshot's own docstring for the
    byte-identical verification.

    precomputed_mad: optional, {symbol: DataFrame} -- backtest.
    run_backtest()'s own lazy, per-run mad_trail_strategy.
    precompute_mad_trail() cache (see its _get_mad() docstring), only
    ever populated for symbols actually entered so far this run, not the
    whole universe. Passing this dict (even sparsely/empty-at-first, as
    long as it's not None) turns compute_snapshot()'s suggested_stop into
    a cheap .loc[asof_date] lookup on a hit, or a cheap ATR fallback on a
    miss -- never a fresh full-trail recompute purely for this ranking-
    display field.
    Matters more than the similar params above: unlike them, this one's
    absence was a REAL measured slowdown (compute_snapshot runs once per
    symbol per rebalance date -- every trading day at daily cadence --
    and backtest.py's own entry-stop logic never even reads this field,
    it uses its own separate precomputed_mad + _initial_stop()), not
    just theoretical waste. None (default, and always the case for live
    callers today, where this only runs once per symbol per scan) falls
    back to the original full per-call computation -- correct either
    way, this only changes speed."""
    cfg = cfg if cfg is not None else config.STRATEGY
    asof_date = bench.index[-1] if not bench.empty else None
    rows = {}
    for sym, df in candles.items():
        long_df = long_candles.get(sym) if long_candles else None
        long_close = long_df["close"] if long_df is not None and not long_df.empty else None
        precomputed_row = precomputed.get(sym) if precomputed else None
        precomputed_wm = precomputed_weekly_monthly.get(sym) if precomputed_weekly_monthly else None
        precomputed_wm_ok = precomputed_weekly_monthly_ok.get(sym) if precomputed_weekly_monthly_ok else None
        precomputed_mad_df = precomputed_mad.get(sym) if precomputed_mad else None
        snap = indicators.compute_snapshot(
            df,
            bench,
            cfg,
            long_close=long_close,
            precomputed_row=precomputed_row,
            precomputed_weekly_monthly=precomputed_wm,
            precomputed_weekly_monthly_ok=precomputed_wm_ok,
            precomputed_mad_df=precomputed_mad_df,
            mad_precompute_active=precomputed_mad is not None,
            asof_date=asof_date,
        )
        if snap:
            rows[sym] = snap
    return pd.DataFrame(rows).T


def apply_gates(
    tech: pd.DataFrame, fundamentals: pd.DataFrame | None = None, cfg: dict = config.STRATEGY
) -> pd.DataFrame:
    """fundamentals: fundamentals_agent.fno_value_scan() output — indexed by
    symbol, with a 'total_score' column (0-100, sector-aware: value_score/
    bank_score/nbfc_score/etc, computed from primary-source XBRL — see
    xbrl_parser.py). A symbol with no fundamental score yet (NaN) passes the
    quality gate rather than being excluded, matching this gate's behavior
    before it switched away from screener.in scraping — no data blocking a
    stock from an otherwise-valid technical setup was never the intent.

    cfg: previously hardcoded to config.STRATEGY internally, silently
    ignoring any custom cfg a caller passed to run_backtest()/run_screen()
    -- every gate threshold here (near_high_threshold, rsi_min/max,
    min_fundamental_score) was unaffected by a custom cfg override until
    this parameter was added. Only visible once a gate threshold was
    actually varied away from its global default in a custom cfg (a
    since-discarded experimental beta gate first exercised this) --
    score()'s weights were never affected, since score() already took cfg
    correctly.

    cfg["fundamental_gate_enabled"] (False by default) decouples SHOWING the
    fundamental score from FILTERING on it -- whenever fundamentals data is
    given, fundamental_score/fundamental_rubric are always attached (for
    display/manual reference, e.g. in the Screener and Live Rebalance
    tables), but they only affect quality_ok/all_gates when this flag is on.
    Live Rebalance always fetches fundamentals (so the score is visible
    there for your own confirmation) but this defaults to off so it doesn't
    silently filter live candidates on a dimension the backtest that
    actually validated this strategy never gated on -- flip it on in Admin
    if you want live trading to filter on fundamentals too.
    """
    t = tech.copy()

    # BACKTEST-ONLY experiment, off by default (config.py's
    # trend_gate_ema9_21_cross_enabled) -- a plain 9/21 EMA cross instead
    # of the usual 3-condition trend structure. Only trend_ok's own
    # formula changes; every other gate (near_high/rsi/quality/price) and
    # sell_check()'s separate, independent "closed below 200 EMA"
    # immediate-exit rule are untouched.
    if cfg.get("trend_gate_ema9_21_cross_enabled", False):
        t["trend_ok"] = t["ema9_above_ema21"]
    else:
        t["trend_ok"] = t["above_ema50"] & t["above_ema200"] & t["ema50_rising"]
    t["near_high_ok"] = t["pct_52w_high"] >= cfg["near_high_threshold"]
    t["rsi_ok"] = t["rsi"].between(cfg["rsi_min"], cfg["rsi_max"])

    # BACKTEST-ONLY (for now), off by default -- requires the higher-
    # timeframe trend to also be strong, not just the daily one: weekly
    # AND monthly price must each be above their own 200-period EMA
    # (falls back to a 50-period EMA when there isn't enough resampled
    # history for 200 yet -- see indicators._higher_tf_trend_ok).
    # Simplified to EMA-only at the user's request -- originally also
    # required weekly/monthly RSI above a floor (4 conditions total), but
    # real-run data showed that caused excessive rebalance-exit churn: a
    # held position only needed ONE of the 4 to wobble near its threshold
    # to get force-sold. NaN (not enough weekly/monthly history at all,
    # e.g. early in a backtest) fails this gate rather than passing it --
    # deliberately fail-closed, unlike the fundamental gate's fail-open
    # default, since "can't confirm the higher-timeframe trend" is a
    # reason to skip a technical entry, not ignore the check.
    if cfg.get("weekly_monthly_gate_enabled", False):
        t["weekly_monthly_gate_ok"] = (t["weekly_above_ema"].fillna(False).astype(bool)) & (
            t["monthly_above_ema"].fillna(False).astype(bool)
        )
    else:
        t["weekly_monthly_gate_ok"] = True

    # EXPERIMENTAL, backtest-only for now -- excludes candidates priced
    # above max_stock_price entirely, at the root of the "one very
    # expensive stock breaks equal-weight math" problem
    # (screener.allocate_equal_weight_buys already handles it at the
    # sizing layer via cross-slot borrowing/partial fills/hard-stop, but
    # this is a simpler, blunter alternative -- just never consider the
    # stock at all). cfg.get(..., False) so this is a no-op (byte-
    # identical current behavior) until explicitly enabled -- needs a
    # real backtest before it's ever turned on live, same as every other
    # gate here.
    if cfg.get("max_stock_price_enabled", False):
        max_price = cfg.get("max_stock_price", 5000.0)
        t["price_ok"] = t["price"] <= max_price
    else:
        t["price_ok"] = True

    gate_enabled = cfg.get("fundamental_gate_enabled", False)
    if fundamentals is not None and not fundamentals.empty:
        fund = fundamentals.reindex(t.index)
        t["fundamental_score"] = fund["total_score"]
        t["fundamental_rubric"] = fund.get("rubric")
        min_score = cfg["min_fundamental_score"]
        if gate_enabled:
            t["quality_ok"] = t["fundamental_score"].isna() | (t["fundamental_score"] >= min_score)
            t["quality_fails"] = t.apply(
                lambda r: (
                    "" if r["quality_ok"] else f"fundamental score {r['fundamental_score']:.0f} < {min_score:.0f}"
                ),
                axis=1,
            )
        else:
            t["quality_ok"] = True
            t["quality_fails"] = ""
    else:
        t["quality_ok"] = True
        t["quality_fails"] = ""

    t["all_gates"] = (
        t["trend_ok"] & t["near_high_ok"] & t["rsi_ok"] & t["quality_ok"] & t["price_ok"] & t["weekly_monthly_gate_ok"]
    )
    # BACKTEST-ONLY (for now), off by default -- restricts entries to
    # stocks whose best sector is currently among the top-N strongest
    # (cfg["top_n_sectors"]). Only attached by rank_universe_asof() when
    # both sector data AND sector_diversification_enabled are given, so
    # this AND is a no-op (column absent) for every other caller,
    # including live's run_screen() and any run without sector data.
    if "sector_diversify_ok" in t.columns:
        t["all_gates"] = t["all_gates"] & t["sector_diversify_ok"]
    return t


def score(t: pd.DataFrame, cfg: dict = config.STRATEGY) -> pd.DataFrame:
    t = t.copy()
    t["score"] = (
        0.40 * _zscore(t["rs_6m"].astype(float))
        + 0.25 * _zscore(t["rs_3m"].astype(float))
        + 0.20 * _zscore(t["pct_52w_high"].astype(float))
        + 0.15 * _zscore(t["vol_expansion"].astype(float))
    ).round(3)

    # Optional sector relative-strength tilt (see sector_universe.py). Off
    # by default (sector_bonus_weight=0) -- only present when the caller
    # attached a "sector_rs" column (backtest.rank_universe_asof / live
    # screener.run_screen, both opt-in). Not renormalized against the 4
    # terms above: only relative ranking (sort_values) matters, and this
    # keeps weight=0 byte-identical to today's score.
    if cfg.get("sector_bonus_weight", 0.0) and "sector_rs" in t.columns:
        t["score"] += cfg["sector_bonus_weight"] * _zscore(t["sector_rs"].astype(float)).fillna(0)

    # Optional overhead-resistance tilt (see resistance_zones.py). Off by
    # default (resistance_zone_weight=0) -- only present when the caller
    # attached a "resistance_clearance" column (backtest.rank_universe_asof,
    # opt-in). Higher clearance (more room before the nearest strong
    # multi-year zone above price) scores better, same convention as every
    # other factor here -- no sign flip needed. Same fillna(0)-on-missing
    # treatment as the sector bonus: a stock with no zone data (too little
    # history, or genuinely nothing nearby) contributes neutrally rather
    # than being favored or penalized for missing data.
    if cfg.get("resistance_zone_weight", 0.0) and "resistance_clearance" in t.columns:
        t["score"] += cfg["resistance_zone_weight"] * _zscore(t["resistance_clearance"].astype(float)).fillna(0)

    # EXPERIMENTAL, backtest-only for now -- tilts ranking toward higher
    # fundamental-quality names among gate-passers, same mechanic as the
    # sector bonus above (not the same as the quality GATE in apply_gates,
    # which only ever excludes/includes candidates -- this additionally
    # affects WHERE an included candidate ranks). cfg.get(..., 0.0) so this
    # is a no-op (byte-identical current behavior) until explicitly passed
    # a nonzero weight in a custom cfg -- no permanent config.py/DB key
    # added yet. NaN fundamental_score (not available for a symbol) ->
    # zscore NaN -> fillna(0), neutral rather than penalized.
    if cfg.get("fundamental_bonus_weight", 0.0) and "fundamental_score" in t.columns:
        t["score"] += cfg["fundamental_bonus_weight"] * _zscore(t["fundamental_score"].astype(float)).fillna(0)

    # BACKTEST-ONLY (for now), off by default -- EMA13/21 pullback-
    # proximity tilt (see indicators.precompute_ema_pullback_proximity).
    # Same opt-in-column mechanic as sector_rs/resistance_clearance
    # above: only present when the caller attached an
    # "ema_pullback_proximity" column, only counted when the weight is
    # nonzero. A stock already extended above EMA21 has NaN here
    # (fillna(0) below -> neutral, not penalized); one sitting right at
    # EMA13/21 from below after a pullback scores highest.
    if cfg.get("ema_pullback_weight", 0.0) and "ema_pullback_proximity" in t.columns:
        t["score"] += cfg["ema_pullback_weight"] * _zscore(t["ema_pullback_proximity"].astype(float)).fillna(0)

    return t.sort_values("score", ascending=False)


def position_size(capital: float, price: float, stop: float, cfg: dict = config.STRATEGY) -> int:
    """Volatility-based sizing: risk `risk_per_trade_pct` of capital between
    entry and ATR stop. Used by backtest.py (kept as-is for continuity with
    the documented sweeps in the README -- changing it would change every
    historical backtest number) and the Positions & Trade page's manual
    order-entry suggestion. live_rebalance.py's automated proposal uses
    capital_position_size() below instead -- see there for why."""
    risk_amount = capital * cfg["risk_per_trade_pct"] / 100
    per_share_risk = max(price - stop, 0.01)
    return max(int(risk_amount / per_share_risk), 0)


def capital_position_size(
    total_equity: float, remaining_cash: float, price: float, open_slots_remaining: int, max_positions: int
) -> int:
    """Equal-weight capital allocation: each of up to max_positions slots
    gets roughly total_equity / max_positions, so per-trade capital scales
    with account size and your configured position count directly -- unlike
    position_size() above, which sizes off a fixed risk-% and can come out
    arbitrarily small on a modest account (e.g. 20k capital, 0.5% risk, a
    ATR stop far from entry -> 1-2 share positions that don't grow with your
    capital or max_positions setting).

    Capped at min(total_equity / max_positions, remaining_cash /
    open_slots_remaining) -- the first term is the per-trade concentration
    limit (so a smaller max_positions or bigger account raises the per-trade
    budget, and capital already tied up in existing holdings is excluded via
    total_equity vs. remaining_cash); the second divides what's actually
    left in cash across the slots still to be filled THIS run, so filling
    several slots in one rebalance doesn't let an early candidate claim all
    of it."""
    if open_slots_remaining <= 0 or price <= 0:
        return 0
    max_capital_per_position = total_equity / max_positions
    per_slot_budget = min(max_capital_per_position, remaining_cash / open_slots_remaining)
    return max(int(per_slot_budget / price), 0)


def sell_check(
    sym: str,
    ranked: pd.DataFrame,
    candidates: pd.DataFrame,
    keep_zone: set,
    max_positions: int,
    cfg: dict = config.STRATEGY,
) -> str | None:
    """Returns the reason `sym` should be sold at rebalance, or None to
    keep holding it. Pulled out as one shared function 2026-08-04 --
    backtest.py's daily loop and live_rebalance.py's propose_rebalance()
    each had their own independently hand-written copy of this exact
    rule before this, verified consistent by inspection but with no
    structural guarantee against one drifting from the other on a future
    edit (unlike the gates/scoring/sizing functions in this module,
    which both already called directly). Pure refactor -- same priority
    order both callers already used (not-in-universe, then below 200
    EMA, then outside the keep zone), same short-circuit semantics,
    verified byte-identical output on real data before/after.

    ranked: full point-in-time screener output (apply_gates + score).
    candidates: ranked[ranked["all_gates"]] -- gate-passers only, still
    sorted by score descending (score() itself sorts).
    keep_zone: set(candidates.head(max_positions * 2).index).
    cfg: only consulted for the optional rsi_exit_gate_enabled/
    rsi_exit_max check below -- every other rule here reads gate columns
    apply_gates() already baked into `ranked`, not cfg directly. Defaults
    to config.STRATEGY (live) so existing callers that don't pass cfg see
    byte-identical behavior (the gate defaults off).
    """
    r = ranked.loc[sym] if sym in ranked.index else None
    if r is None:
        return "no data / not in current universe"
    if not bool(r.get("above_ema200", False)):
        return "closed below 200 EMA"
    if sym not in keep_zone:
        # BACKTEST-ONLY (for now), off by default -- see config.py's
        # rsi_exit_gate_enabled comment: this was already tried once and
        # discarded, re-exposed here for re-testing from the Backtest UI.
        # A held position whose ONLY failing gate is the entry-band RSI
        # ceiling stays held as long as RSI is still under the separate,
        # wider rsi_exit_max, instead of being force-sold here just for
        # running hot. Only fires when sym isn't a candidate at all (i.e.
        # failed some gate); a candidate merely ranked below the keep
        # zone still exits normally below, unaffected by this.
        if cfg.get("rsi_exit_gate_enabled", False) and sym not in candidates.index:
            non_rsi_gates_ok = bool(
                r.get("trend_ok", True)
                and r.get("near_high_ok", True)
                and r.get("quality_ok", True)
                and r.get("price_ok", True)
            )
            if non_rsi_gates_ok and float(r.get("rsi", 0)) <= cfg.get("rsi_exit_max", cfg["rsi_max"]):
                return None
        keep_zone_size = max_positions * 2
        if sym in candidates.index:
            rank = candidates.index.get_loc(sym) + 1
            return f"dropped out of top {keep_zone_size} rank (now #{rank} of {len(candidates)})"
        return f"failed a technical gate (trend/near-high/RSI) -- not in the top {keep_zone_size} at all"
    return None


def allocate_equal_weight_buys(
    ranked_syms: list[str],
    prices: dict[str, float],
    held: dict[str, tuple[int, float]],
    cash_pool: float,
    total_equity: float,
    max_positions: int,
    tolerance_pct: float = 0.10,
) -> dict:
    """EXPERIMENTAL, backtest-only for now -- a from-scratch replacement for
    capital_position_size()'s one-symbol-at-a-time sizing, which greedily
    skips an unaffordable top-ranked candidate and substitutes whatever
    cheaper, lower-ranked stock it finds next (this is what let a rank #9
    stock get bought over rank #1-8 ones when cash was thin). This function
    decides the WHOLE day's allocation in one pass instead:

    - Walks ranked_syms (already sorted best-first, gate-passers not yet
      held) in order, trying to fund each at the equal-weight target
      (total_equity / max_positions), borrowing headroom from not-yet-
      allocated LOWER-ranked slots (reserving at least
      target*(1-tolerance_pct) for each of them) when a candidate is
      pricier than the target allows.
    - If a candidate can't be funded at full target even after borrowing,
      it still gets a REDUCED/partial allocation from whatever's left,
      flagged with a reason -- never skipped in favor of a cheaper,
      lower-ranked stock instead.
    - Only stops entirely (leaving remaining slots unfilled) once there's
      truly not enough cash left for even one share of the current
      candidate.
    - Any cash left over after all open slots are filled (or the stop
      point reached) tops up existing HELD positions that are below
      target*(1-tolerance_pct), best-ranked first, capped at
      target*(1+tolerance_pct) -- so slack capital doesn't sit idle when
      there's nothing new left to buy.

    prices: current price for every symbol in ranked_syms AND every symbol
    in `held` (today's actual tradable price, not a stale scan-date one).
    held: {symbol: (qty, current_price)} for currently-held positions --
    only ones also present in ranked_syms are eligible for topping up (a
    held stock that's fallen out of the ranked candidates isn't).

    Returns {"new_buys": {symbol: (qty, reason_or_None)},
    "top_ups": {symbol: extra_qty}, "stopped_at": symbol_or_None,
    "remaining_cash": float}."""
    target = total_equity / max_positions
    min_alloc = target * (1 - tolerance_pct)
    max_alloc = target * (1 + tolerance_pct)

    open_slots = max_positions - len(held)
    remaining_pool = cash_pool
    new_buys: dict[str, tuple[int, str | None]] = {}
    stopped_at = None

    eligible = [s for s in ranked_syms if s not in held]
    for sym in eligible:
        if len(new_buys) >= open_slots:
            break
        price = prices.get(sym)
        if price is None or price <= 0:
            continue
        slots_after = open_slots - len(new_buys) - 1
        reserved = min_alloc * max(slots_after, 0)
        available_for_this = max(remaining_pool - reserved, 0.0)
        alloc = min(max_alloc, available_for_this)
        qty = int(alloc // price)
        reason = None
        if qty <= 0:
            # The bounded (tolerance-respecting, reservation-respecting)
            # allocation can't afford even 1 share -- either this
            # candidate's OWN share price already exceeds what tolerance
            # allows for one slot (no amount of "partial" fixes that,
            # shares aren't divisible), or reserving for later slots ate
            # all the room. Rather than skip to a cheaper, lower-ranked
            # stock, allow exactly ONE share -- the minimum indivisible
            # unit, capped there (never more) -- funded from the whole
            # remaining pool since a higher-ranked candidate has priority
            # over what's reserved for lower-ranked ones.
            if remaining_pool >= price:
                qty = 1
                reason = (
                    f"exceeds equal-weight target (1 share costs {price:,.0f} "
                    f"vs {target:,.0f} target) -- bought the minimum 1 share"
                )
            else:
                stopped_at = sym
                break
        elif qty * price < min_alloc:
            reason = (
                f"partial position -- {alloc:,.0f} available (after reserving "
                f"for other slots) vs {target:,.0f} equal-weight target"
            )
        new_buys[sym] = (qty, reason)
        remaining_pool -= qty * price

    top_ups: dict[str, int] = {}
    for sym in ranked_syms:
        if remaining_pool <= 0:
            break
        if sym not in held:
            continue
        qty_held, price_held_now = held[sym]
        current_value = qty_held * price_held_now
        if current_value >= min_alloc:
            continue
        price = prices.get(sym, price_held_now)
        if price <= 0:
            continue
        room = max_alloc - current_value
        spend = min(room, remaining_pool)
        qty = int(spend // price)
        if qty <= 0:
            continue
        top_ups[sym] = qty
        remaining_pool -= qty * price

    return {"new_buys": new_buys, "top_ups": top_ups, "stopped_at": stopped_at, "remaining_cash": remaining_pool}


def run_screen(
    with_fundamentals: bool = True, fundamentals: pd.DataFrame | None = None, progress_cb=None
) -> pd.DataFrame:
    """Full pipeline. progress_cb(stage:str, frac:float) for UI updates.

    fundamentals: pre-computed fundamentals_agent.fno_value_scan() output —
    pass this in (e.g. the dashboard's already-cached Value Score results)
    to avoid re-running a full 210-stock NSE scan on every screen. If not
    given and with_fundamentals=True, falls back to the on-disk Value Score
    cache if present, then to a fresh fno_value_scan() only as a last resort.
    """

    def report(stage, frac):
        if progress_cb:
            progress_cb(stage, frac)

    report("Fetching benchmark (NIFTY 50)...", 0.05)
    days = config.STRATEGY["history_days"]
    bench = kite_client.benchmark_candles(days)

    report("Fetching universe candles from Kite (~3 years each)...", 0.15)
    candles = kite_client.fetch_universe_candles(config.UNIVERSE, days)

    # weekly_monthly_gate_enabled needs a 200-bar (or 50-bar fallback)
    # weekly/monthly EMA, which `candles` above (history_days, ~3 years by
    # default) can't supply -- even the 50-bar monthly fallback needs
    # ~4.2 years. Without this, weekly_above_ema/monthly_above_ema read
    # NaN for every symbol, screener.apply_gates() below fills that NaN
    # as False (fail-closed, not fail-open), and weekly_monthly_gate_ok
    # ANDs straight into all_gates -- so every stock, including every
    # currently-held position, would fail every gate at once. Deferred
    # import: backtest.py imports screener at module level, so importing
    # backtest here at module level would be circular; safe as a
    # call-time import since both modules are already fully loaded by
    # the time run_screen() actually runs.
    long_candles = None
    if config.STRATEGY.get("weekly_monthly_gate_enabled", False) or config.STRATEGY.get("resistance_zone_weight", 0.0):
        import backtest as bt

        report("Fetching deep history for weekly/monthly trend gate and/or resistance zones...", 0.35)
        long_candles = bt.load_long_history_cached(
            config.UNIVERSE,
            end_date=dt.date.today() - dt.timedelta(days=1),
            progress_cb=lambda s, f: report(s, 0.35 + f * 0.2),
        )

    report("Computing technicals...", 0.60)
    tech = build_technical_table(candles, bench, long_candles=long_candles)

    # BACKTEST-ONLY-until-now overhead-resistance score tilt (see
    # resistance_zones.py) -- mirrors backtest.rank_universe_asof's own
    # attach block (backtest.py:508-516) almost verbatim. Cheap to compute
    # fresh per day (a single vectorized rolling-window pass per symbol,
    # no resample()-style per-call cost like the weekly/monthly gate had)
    # -- reuses the SAME long_candles fetched above rather than a second
    # fetch when both gates are on. No-op (column absent, score()'s guard
    # never fires) whenever resistance_zone_weight is 0 or long_candles
    # wasn't fetched, same pattern as every other optional column here.
    if long_candles is not None and config.STRATEGY.get("resistance_zone_weight", 0.0):
        import resistance_zones

        pivot_window = config.STRATEGY.get("resistance_zone_pivot_window", 10)
        clearances = []
        for sym in tech.index:
            long_df = long_candles.get(sym)
            if long_df is None or long_df.empty:
                clearances.append(None)
                continue
            pivots = resistance_zones.precompute_pivots(long_df, window=pivot_window)
            clearances.append(
                resistance_zones.resistance_clearance_asof(
                    pivots,
                    float(tech.loc[sym, "price"]),
                    pd.Timestamp(dt.date.today()),
                    lookback_years=config.STRATEGY.get("resistance_zone_lookback_years", 5.0),
                    tolerance_pct=config.STRATEGY.get("resistance_zone_cluster_tolerance_pct", 0.03),
                    search_pct=config.STRATEGY.get("resistance_zone_search_pct", 0.20),
                )
            )
        tech["resistance_clearance"] = clearances

    if with_fundamentals and fundamentals is None:
        cache_path = os.path.join("cache", "fno_value_scores.pkl")
        if os.path.exists(cache_path):
            report("Loading cached fundamental scores...", 0.65)
            fundamentals = pd.read_pickle(cache_path)
        else:
            report("Fetching fundamentals (primary XBRL)...", 0.70)
            fundamentals = fa.fno_value_scan(list(tech.index))
    elif not with_fundamentals:
        fundamentals = None

    # BACKTEST-ONLY-until-now sector relative-strength tilt (sector_bonus_
    # weight) and hard diversification cap (sector_diversification_enabled
    # + top_n_sectors/max_positions_per_sector/sector_composite_score_
    # enabled). Mirrors backtest.rank_universe_asof's own attach block
    # (backtest.py:452-502) almost verbatim -- one shared fetch/RS
    # computation serves both features (already proven safe for a single
    # live "today" call: paper_engine.load_market_data() and the Screener
    # page's own "Fetch current sector rankings" button already call
    # sector_membership_and_candles()/sector_rs_asof() exactly this way,
    # live, outside any backtest). Real cost when either is on: ~20-35
    # Kite index-candle fetches, ~15-30s -- only paid when actually
    # enabled (both off in production today). Placed AFTER fundamentals
    # resolve above (not before) so the composite-score branch's pre-gates
    # breadth check sees real fundamental data, matching backtest's own
    # ordering (fundamentals resolved before its sector block runs).
    if config.STRATEGY.get("sector_bonus_weight", 0.0) or config.STRATEGY.get("sector_diversification_enabled", False):
        report("Fetching sector index data...", 0.93)
        sector_membership, sector_candles = sector_universe.sector_membership_and_candles(
            config.UNIVERSE, days=days, verbose=False
        )
        sector_rank = sector_universe.sector_rs_asof(
            sector_candles, bench, bench.index[-1], config.STRATEGY.get("sector_rs_lookback_days", 126)
        )
        tech["sector_rs"] = [sector_universe.stock_sector_rs(sym, sector_membership, sector_rank) for sym in tech.index]
        tech["top_sector"] = [
            sector_universe.stock_top_sector(sym, sector_membership, sector_rank) for sym in tech.index
        ]
        tech["sector_group"] = tech["top_sector"].apply(lambda s: sector_universe.industry_group(s) if s else s)
        if config.STRATEGY.get("sector_diversification_enabled", False):
            top_n = config.STRATEGY.get("top_n_sectors", 3)
            if config.STRATEGY.get("sector_composite_score_enabled", False):
                pre_gates = apply_gates(tech, fundamentals=fundamentals)
                breadth = sector_universe.sector_breadth(sector_membership, pre_gates["all_gates"])
                composite = sector_universe.sector_composite_score(
                    sector_rank, sector_candles, bench.index[-1], breadth
                )
                group_rank = composite.groupby(composite.index.to_series().apply(sector_universe.industry_group)).max()
            else:
                group_rank = sector_rank.groupby(
                    sector_rank.index.to_series().apply(sector_universe.industry_group)
                ).max()
            top_group_names = set(group_rank.sort_values(ascending=False).head(top_n).index)
            tech["sector_diversify_ok"] = tech["sector_group"].isin(top_group_names)

    report("Scoring & gating...", 0.95)
    t = apply_gates(tech, fundamentals)
    t = score(t)
    report("Done", 1.0)
    return t


SCREEN_CACHE = os.path.join("cache", "screen.pkl")


def main():
    """Headless daily refresh -- e.g. from nse-screen-refresh.timer, every
    morning before market open. Runs the exact same pipeline as the
    Screener page's manual "Run screen" button and writes to the SAME
    cache (SCREEN_CACHE) it reads from -- so opening the Screener page
    shows this morning's fresh ranking without needing a manual click
    first. Wrapped in state_db.job_run() so it shows in the Job Log
    alongside the other scheduled jobs."""
    with state_db.job_run("screen_run", "scheduled") as jr:
        result = run_screen(with_fundamentals=True)
        os.makedirs("cache", exist_ok=True)
        result.to_pickle(SCREEN_CACHE)
        jr["summary"] = f"{len(result)} candidates ({int(result['all_gates'].sum())} passing all gates)"


if __name__ == "__main__":
    main()
