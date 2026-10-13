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
Live/paper orchestration for the "DaysLowVolumnBreakout" intraday
strategy -- run as `python intraday_engine.py` during real market hours
(09:15-15:10 IST -- squareoff timed to Zerodha's own 15:12:00
auto-square-off for F&O-enabled equity MIS, see run_live()'s own
comment on this), no flags needed for normal/scheduled use: the mode
is decided entirely by config.STRATEGY["intraday_live_enabled"] (the
Admin page checkbox) at each invocation, so a scheduled daily launch
runs the exact same command every day and automatically trades live
the very next time it starts after that checkbox is saved on, with no
per-day manual step. Paper mode (the default, while that flag is off)
simulates every fill at the exact computed price, no Kite orders; live
mode places real MIS orders. `--paper` on the command line forces
paper regardless (a manual safety valve); `--live` is accepted for
explicit intent but can never bypass the config gate if it's off.

Structured so the DECISION logic (given data already fetched) is
independently testable without wall-clock waits or a real Kite session
-- see verify_intraday_engine.py, which replays one real historical
day's actual 5-min candles through run_selection()/process_candle()/
check_intracandle_exit() and confirms the engine reproduces the same
entries/exits the already-verified batch backtest (intraday_strategy.
find_entry()/simulate_exit()) produces for that day. Only run_live()
itself (the real-time wall-clock loop) is unverifiable outside real
market hours.
"""


import datetime as dt
import time

import intraday_db as idb
import intraday_market as mkt
import intraday_strategy as strat
import kite_client
import live_ticker
import notify
import nse_holidays
import pandas as pd
import sector_universe as su
import state_db

import config

EMA_WARMUP_DAYS = (
    120  # >> "several weeks" Spec.md §1 asks for, comfortably covers EMA21/ATR14 warmup
)
# Per-boundary refresh window -- deliberately small (see run_live()'s own
# comment on this): only needs to safely reach back to the last candle
# already in a tracker's cached t.hist, which is at most a few calendar
# days ago even across a weekend/holiday. Measured 2026-09-17: a days=3
# fetch is ~13x faster than re-pulling the full EMA_WARMUP_DAYS (0.11s
# vs 1.2-1.4s per symbol) -- Kite's historical API appears to chunk a
# request internally in proportion to the days asked for.
_REFRESH_WINDOW_DAYS = 3
# Fallback only -- config.STRATEGY["intraday_paper_capital"]/["intraday_live_capital"]
# (both Admin-editable) are what run_live() actually seeds each mode's
# starting capital from; this constant is just the .get() default for a
# fresh install where those keys haven't been written to the DB yet.
DEFAULT_PAPER_CAPITAL = 1_000_000.0
# How often the loop wakes up to check the ticker's in-memory cache and
# wall-clock conditions (candle boundary, 15:10 squareoff) -- NOT a network
# poll cadence any more (see live_ticker.py): trigger/stop/target prices
# themselves come from live WebSocket ticks the instant they arrive, this
# just bounds how quickly the loop notices them.
CHECK_INTERVAL_SECONDS = 1
TICK_STALE_SECONDS = 20  # fall back to a REST get_ltp() if the feed goes quiet this long
# NSE settlement-type suffixes a stock's Kite trading symbol can carry
# while under a temporary special settlement/surveillance category (most
# commonly "-BE", trade-for-trade) -- the company itself trades
# completely normally, just under this suffixed symbol instead of its
# plain one. See _prev_close_and_0925()'s docstring for why this matters.
_NSE_SETTLEMENT_SUFFIXES = ("-BE", "-BZ", "-BL", "-BT")


def _push(title: str, message: str) -> None:
    """Sends a push to every subscribed device (same pattern/helper as
    state_db.job_run()'s own notify calls) -- no-op if VAPID keys aren't
    configured or nobody's subscribed. Never allowed to interrupt the
    engine's own trading logic: notification delivery is best-effort,
    not a hard dependency for anything that calls this."""
    try:
        for dead in notify.send_webpush_all(
            state_db.get_push_subscriptions(), title, message, notify.DASHBOARD_URL
        ):
            state_db.delete_push_subscription(dead)
    except Exception as e:
        print(f"[intraday_engine] push notification failed -- {e}")


# ---------------------------------------------------------------------------
# §2 -- day-bias + candidate selection (testable: pass in already-fetched data)
# ---------------------------------------------------------------------------


def run_selection(
    date: str,
    nifty50_symbols: list[str],
    fno_symbols: list[str],
    close_0925: dict[str, float],
    prev_day_close: dict[str, float],
    mode: str,
) -> dict:
    """Spec.md §2, given today's 09:25-candle closes + previous closes
    already fetched for the full nifty50 UNION fno universe. Writes
    intraday_days/intraday_daily_selection and returns
    {"nifty_ratio", "day_bias", "candidates": [{"symbol","direction"}]}
    -- candidates is empty when day_bias is None (skip day)."""
    nifty_ratio, nifty_rets = mkt.compute_first15_breadth(
        nifty50_symbols, close_0925, prev_day_close
    )
    bias = strat.day_bias(nifty_ratio)
    advancers = sum(1 for v in nifty_rets.values() if v > 0)
    decliners = sum(1 for v in nifty_rets.values() if v < 0)
    idb.record_day(date, nifty_ratio, bias, advancers, decliners)

    if bias is None:
        return {"nifty_ratio": nifty_ratio, "day_bias": None, "candidates": []}

    fno_rets = {}
    for sym in fno_symbols:
        c0925, prev_close = close_0925.get(sym), prev_day_close.get(sym)
        if c0925 is None or prev_close is None or prev_close == 0:
            continue
        fno_rets[sym] = strat.first15_return(c0925, prev_close)

    # v5.4 §4/§8 -- overnight-gap filter applied to the FULL ranked
    # universe BEFORE picking the top TOP_N_CANDIDATES, not just to the
    # top-N after the fact -- a gapped-out stock that would have ranked
    # in the top 5 is skipped and the next-best non-gapped stock takes
    # its place. Walking the ranked list lazily (stopping once
    # TOP_N_CANDIDATES are accepted) means this only ever fetches the
    # 09:15 candle for as many symbols as actually needed to fill the
    # pool (typically just a few beyond 5, matching the spec's own ~6.5%
    # measured discard rate), not the whole ~200-symbol F&O universe.
    ranked_all = strat.select_candidates(pd.Series(fno_rets), bias, n=len(fno_rets))
    today_date = dt.date.fromisoformat(date)
    accepted: list[tuple[str, float, float | None]] = []  # (symbol, ret_first15_pct, gap_pct)
    for sym, ret in ranked_all.items():
        gap = _overnight_gap_pct(sym, prev_day_close.get(sym), today_date)
        if not strat.passes_gap_filter(gap):
            print(
                f"[intraday_engine] {sym}: excluded from candidate pool -- "
                f"09:15 gap {'unresolvable' if gap is None else f'{gap:+.2f}%'} "
                f"(threshold ±{strat.GAP_FILTER_PCT}%)"
            )
            continue
        accepted.append((sym, float(ret), gap))
        if len(accepted) >= strat.TOP_N_CANDIDATES:
            break

    candidates = [
        {"symbol": sym, "direction": bias, "rank": i + 1} for i, (sym, _, _) in enumerate(accepted)
    ]
    idb.record_candidates(
        date,
        [
            {"rank": i + 1, "symbol": sym, "ret_first15_pct": round(ret, 3), "gap_pct": gap}
            for i, (sym, ret, gap) in enumerate(accepted)
        ],
    )
    return {"nifty_ratio": nifty_ratio, "day_bias": bias, "candidates": candidates}


def _overnight_gap_pct(symbol: str, prev_close: float | None, today: dt.date) -> float | None:
    """v5.4 §4 step 1 -- today's 09:15 candle's own OPEN vs the previous
    day's close. Read from the historical-candle API (not quote()): by
    the time run_selection() runs (09:30, after its own wait), the 09:15
    candle has already closed and its open is a fixed historical fact --
    no need to have polled at 09:15:00 itself."""
    if prev_close is None or prev_close == 0:
        return None
    try:
        intraday = kite_client.fetch_intraday_candles(symbol, days=2, interval="5minute")
        row = intraday[intraday.index == pd.Timestamp(today) + pd.Timedelta(hours=9, minutes=15)]
        if row.empty:
            return None
        return (float(row.iloc[0]["open"]) - prev_close) / prev_close * 100.0
    except Exception as e:
        print(f"[intraday_engine] {symbol}: gap-filter fetch failed -- {e}")
        return None


def resolve_sector_gates(
    date: str,
    candidates: list[dict],
    close_0925: dict[str, float],
    prev_close: dict[str, float],
    today: dt.date,
) -> None:
    """Spec v2 §6 -- for each candidate, resolve its primary sector and
    compute that sector's OWN first-15m A/D ratio ONCE (§6.4: fixed for
    the whole day, looked up -- not recomputed -- when a breakout later
    triggers). Mutates each `candidates` dict in place, adding "sector",
    "sector_ratio", "sector_gate_pass"; also persists these to
    intraday_daily_selection so the Dashboard can show them.

    §10.3's data-completeness warning is handled here explicitly: a
    sector typically has far fewer constituents than NIFTY50/F&O (15-30
    vs 50-200+), so ONE missing member's data materially skews the
    ratio. close_0925/prev_close are extended with a fetch for any
    sector constituent not already covered by the caller's own batch
    (mirrors _prev_close_and_0925()'s own fetch), but if any constituent
    STILL has no data after that, the gate fails closed (sector_ratio=
    None, sector_gate_pass=False) rather than silently computing a ratio
    off an incomplete member set -- do not loosen this to "skip missing
    symbols and compute anyway", that is exactly the bug §10.3 found."""
    catalog = su.fetch_index_constituents()
    symbols = [c["symbol"] for c in candidates]
    profiles = su.resolve_sector_profiles(symbols)

    for c in candidates:
        sym = c["symbol"]
        sector = profiles.get(sym, {}).get("primary_sector")
        c["sector"] = sector
        if sector is None:
            # §6.1.5 -- no resolvable primary sector at all: automatic fail.
            c["sector_ratio"] = None
            c["sector_gate_pass"] = False
            idb.update_candidate_sector_gate(date, sym, None, None, False)
            continue

        members = list(catalog.get(sector, {}).keys())
        missing = [s for s in members if s not in close_0925 or s not in prev_close]
        if missing:
            extra_c0925, extra_prev = _prev_close_and_0925(missing, today)
            close_0925.update(extra_c0925)
            prev_close.update(extra_prev)
        still_missing = [s for s in members if s not in close_0925 or s not in prev_close]
        if still_missing:
            print(
                f"[intraday_engine] sector gate: {sector} incomplete data for "
                f"{len(still_missing)}/{len(members)} constituents "
                f"({still_missing[:5]}{'...' if len(still_missing) > 5 else ''}) -- "
                f"treating gate as FAILED (Spec v2 §10.3 fail-closed on incomplete data)"
            )
            c["sector_ratio"] = None
            c["sector_gate_pass"] = False
            idb.update_candidate_sector_gate(date, sym, sector, None, False)
            continue

        sector_ratio, _ = mkt.compute_first15_breadth(members, close_0925, prev_close)
        gate_pass = strat.sector_gate_pass(sector_ratio, c["direction"])
        c["sector_ratio"] = sector_ratio
        c["sector_gate_pass"] = gate_pass
        idb.update_candidate_sector_gate(date, sym, sector, sector_ratio, gate_pass)


# ---------------------------------------------------------------------------
# Per-candidate tracking
# ---------------------------------------------------------------------------


class CandidateTracker:
    """Live state for one of the day's (at most 2) candidates -- the
    engine keeps one of these per candidate, updated as candles close
    and (once a position opens) as LTP ticks arrive."""

    def __init__(
        self,
        date: str,
        symbol: str,
        direction: str,
        ema21_series: pd.Series,
        atr14_series: pd.Series,
        first_candle_low: float,
        first_candle_high: float,
        rank: int,
        sector: str | None = None,
        sector_ratio: float | None = None,
        sector_gate_pass: bool = False,
        sig_range_low: float | None = None,
        sig_range_high: float | None = None,
        ema50_series: pd.Series | None = None,
        fvg_lo: float | None = None,
        fvg_hi: float | None = None,
    ):
        self.date = date
        self.symbol = symbol
        self.direction = direction
        self.ema21_series = ema21_series
        self.atr14_series = atr14_series
        # v5.4 §5n -- the fair-value-gap veto zone, from the day's 09:15
        # and 09:25 candles -- fixed for the whole day like sig_range_low/
        # high, no mid-day refresh needed (both source candles are fully
        # known and unchanging well before this tracker is even built).
        self.fvg_lo = fvg_lo
        self.fvg_hi = fvg_hi
        # v5.4 §5m -- the signal candle's own trend filter. None (not
        # just an all-NaN series) would mean "filter off" to step_candle()
        # -- run_live() always builds a real series (see tracker
        # construction below), so this is adopted/on for every live
        # tracker; kept as a constructor default only so other callers
        # (tests) aren't forced to supply one.
        self.ema50_series = ema50_series
        # v3 Spec §4 -- this candidate's rank in the day's top-5 pool,
        # used ONLY to break ties when two-or-more candidates confirm a
        # breakout at the exact same candle timestamp (lower rank wins).
        self.rank = rank
        # v2 Spec §3.2 step 1b -- the day's 09:15 candle's own low/high,
        # fixed for the whole day (never refreshed, unlike ema21_series/
        # atr14_series which need the newest candle appended each boundary).
        self.first_candle_low = first_candle_low
        self.first_candle_high = first_candle_high
        # v5.4 §5i.1 -- the one-sided signal gate's own fixed reference
        # range (09:20+09:25 candles' low/high), separate from the 09:15
        # first-candle values above. None fails closed -- see
        # intraday_strategy.signal_in_range().
        self.sig_range_low = sig_range_low
        self.sig_range_high = sig_range_high
        # v2 Spec §6 -- resolved once at 09:30 (resolve_sector_gates()),
        # looked up (not recomputed) the moment a breakout triggers.
        self.sector = sector
        self.sector_ratio = sector_ratio
        self.sector_gate_pass = sector_gate_pass
        self.signal_state = strat.new_signal_state()
        self.vol_min_so_far: float | None = None
        self.signal_db_id: int | None = None
        self.position_id: int | None = None
        self.done = False  # invalidated, or position fully closed -- nothing left to do today
        # Cached raw candle history (EMA_WARMUP_DAYS deep), set by the
        # caller right after construction. Performance-critical: each
        # candle-close boundary used to re-fetch this whole ~120-day
        # history per candidate just to pick up ONE new candle (measured
        # 2026-09-17: ~1.2-1.4s/symbol, i.e. up to ~6s sequential for a
        # full 5-candidate pool, most of it wasted re-downloading days
        # already known) -- that blocked the tick-driven stop/target/
        # entry checks for the SAME 6s once every 5 minutes, on live
        # market data. Instead, each boundary now fetches only a small
        # recent window (~0.11s/symbol, measured) and merges it into this
        # cached frame before recomputing ema21_series/atr14_series -- see
        # run_live()'s per-boundary loop.
        self.hist: pd.DataFrame | None = None
        # v5.2 EMA-trail: the newest CLOSED candle label already checked
        # against the trail EMA for this tracker's open position (so a
        # boundary is never evaluated twice, and a skipped boundary is
        # caught up in order rather than lost).
        self.trail_checked_through = pd.Timestamp.min


def process_candle(tracker: CandidateTracker, ts: pd.Timestamp, row: pd.Series) -> dict | None:
    """One closed 5-min candle for one candidate -- advances its signal
    state (step_candle()) only. Returns the raw event dict (see
    step_candle()'s docstring), or None if nothing happened or
    tracker.done already.

    v3 Spec §4's causal multi-candidate walk requires collecting every
    candidate's "triggered" event at the SAME boundary FIRST, sorting by
    rank, then applying the day's shared 2-slot cap -- so unlike v2,
    this function does NOT itself call _open_position_from_trigger() on
    a trigger; the caller (run_live()'s boundary-processing block) does,
    only for the entries that actually win a slot after that sort. The
    tracker is marked done the instant it triggers regardless of what
    happens next (Spec v3 §4: resolved the moment a breakout confirms,
    whether or not it ends up winning a slot).

    Caller must update tracker.vol_min_so_far with this candle's own
    volume (running min, inclusive) BEFORE calling this -- see
    step_candle()'s docstring for why (the running min starts at 09:15,
    two candles before the signal window itself opens at 09:30)."""
    if tracker.done or tracker.position_id is not None:
        # A position is already open (triggered by this same candle's
        # close just above, or by a live tick before this candle even
        # closed -- see check_tick_entry()) -- step_candle() would
        # otherwise keep hunting for a brand-new signal candle on every
        # subsequent close and could trigger a SECOND, unmanaged entry
        # for a candidate that already has one open (each candidate
        # gets at most one position per day, Spec.md §4).
        return None
    e21 = tracker.ema21_series.get(ts)
    sig_atr = tracker.atr14_series.get(ts)
    e50 = tracker.ema50_series.get(ts) if tracker.ema50_series is not None else None
    new_state, event = strat.step_candle(
        tracker.signal_state,
        ts,
        row,
        tracker.direction,
        e21,
        sig_atr,
        tracker.vol_min_so_far,
        tracker.first_candle_low,
        tracker.first_candle_high,
        tracker.sig_range_low,
        tracker.sig_range_high,
        e50=e50,
        fvg_lo=tracker.fvg_lo,
        fvg_hi=tracker.fvg_hi,
    )
    tracker.signal_state = new_state

    if event is None:
        return None

    if event["type"] == "invalidated":
        if tracker.signal_db_id is not None:
            idb.update_signal_status(tracker.signal_db_id, "invalidated")
        # Always recorded here too (not just when a signal happened to be
        # active) -- a candidate invalidated on its very first eligible
        # candle never has a signal_db_id at all, and would otherwise
        # leave the Dashboard with no way to tell "invalidated" apart
        # from "still watching" for the rest of the day.
        idb.mark_candidate_status(tracker.date, tracker.symbol, "invalidated")
        tracker.done = True
        return event

    if event["type"] == "signal_formed":
        # §5l -- re-signal removed: "replaced_expired" is True when this
        # same candle just killed a DIFFERENT signal (the old continuation
        # gate/window exhausted) before qualifying as an ordinary fresh
        # signal in its own right, all within the same step_candle() call
        # -- retire that old row as "expired" (step_candle() never emits
        # a separate signal_expired event for it) before creating the new
        # one, so the Dashboard/tradebook still shows both lines.
        if event.get("replaced_expired") and tracker.signal_db_id is not None:
            idb.update_signal_status(tracker.signal_db_id, "expired")
        tracker.signal_db_id = idb.create_signal(
            tracker.date,
            tracker.symbol,
            str(event["time"]),
            event["high"],
            event["low"],
            event["atr"],
        )
        return event

    if event["type"] == "signal_expired":
        if tracker.signal_db_id is not None:
            idb.update_signal_status(tracker.signal_db_id, "expired")
        tracker.signal_db_id = None
        return event

    if event["type"] == "triggered":
        if tracker.signal_db_id is not None:
            idb.update_signal_status(tracker.signal_db_id, "triggered")
        # Resolved the instant it triggers (Spec v3 §4) -- whether this
        # candidate actually gets a trade depends on the sector gate AND
        # the day's remaining slots, both applied by the caller after
        # collecting every candidate's trigger at this same boundary.
        tracker.done = True
        return event

    return event


def _open_position_from_trigger(
    tracker: CandidateTracker, event: dict, capital_alloc: float, risk_budget: float, mode: str
) -> dict:
    """Shared by both trigger paths -- process_candle()'s candle-close
    "triggered" event (step_candle()) and check_tick_trigger()'s live-
    tick equivalent -- so a breakout is sized/recorded identically no
    matter which one detected it first.

    v2 Spec §6 -- the sector-confirmation gate is checked HERE, right
    after a breakout triggers and before any sizing/order placement --
    it can only ever drop THIS candidate's trade, never affect the
    other candidate. tracker.sector_gate_pass was resolved once at 09:30
    (resolve_sector_gates()), not recomputed now."""
    if not tracker.sector_gate_pass:
        tracker.done = True
        idb.mark_candidate_status(tracker.date, tracker.symbol, "sector_gate_failed")
        _sector_detail = (
            f"{tracker.sector or 'unresolved'}, ratio {tracker.sector_ratio:.2f}"
            if tracker.sector_ratio is not None
            else f"{tracker.sector or 'unresolved'}, no data"
        )
        _push(
            f"KK Trading — {tracker.symbol} trade dropped (sector gate)",
            f"Breakout triggered but {tracker.symbol}'s sector ({_sector_detail}) "
            f"didn't confirm {tracker.direction} -- no trade taken ({mode} mode).",
        )
        return {
            "type": "sector_gate_failed",
            "sector": tracker.sector,
            "sector_ratio": tracker.sector_ratio,
        }

    entry_price, stop_price = event["entry_price"], event["stop_price"]
    qty = strat.position_size(capital_alloc, risk_budget, entry_price, stop_price)
    if qty <= 0:
        tracker.done = True
        return {"type": "entry_skipped_zero_qty"}
    target = strat.target_price(entry_price, stop_price, tracker.direction)
    order_id = None
    if mode == "live":
        side = "BUY" if tracker.direction == strat.LONG else "SELL"
        order_id = kite_client.place_order(
            tracker.symbol,
            qty,
            side,
            product="MIS",
            order_type="SL",
            price=entry_price,
            trigger_price=entry_price,
        )
    tracker.position_id = idb.record_new_position(
        tracker.date,
        tracker.symbol,
        tracker.direction,
        str(event["entry_time"]),
        entry_price,
        stop_price,
        target,
        qty,
        mode,
        signal_time=str(event["signal_time"]),
        order_id=order_id,
    )
    capital_used = qty * entry_price  # notional deployed -- qty x fill price, not margin/leverage
    _push(
        f"KK Trading — {tracker.symbol} position opened ({mode})",
        f"{tracker.direction} qty {qty} @ ₹{entry_price:.2f} (₹{capital_used:,.2f} deployed) -- "
        f"stop ₹{stop_price:.2f}, target ₹{target:.2f}",
    )
    return {
        "type": "position_opened",
        "position_id": tracker.position_id,
        "qty": qty,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target": target,
        "capital_used": capital_used,
    }


def check_tick_entry(
    tracker: CandidateTracker,
    ltp: float,
    now: dt.datetime,
    capital_alloc: float,
    risk_budget: float,
    mode: str,
    day_state: dict,
) -> dict | None:
    """Tick-driven counterpart to process_candle()'s candle-close trigger
    check (Spec.md §6.2) -- called on every live tick for a candidate
    that has an active signal but no position yet, so a breakout is
    caught the instant price crosses the trigger level rather than
    waiting up to 5 minutes for the candle to close. No-ops once
    tracker.done, a position already exists, or the day's trade slots
    (`day_state["slots_remaining"]`, Spec v3 §4) are already used up.

    Note: unlike the candle-close path, this does NOT (and cannot) check
    the v3 confirm-color rule -- a live tick has no "candle color" until
    that candle closes. A tick-driven trigger is a reasonable-but-not-
    identical-to-backtest approximation for this reason (see Spec v3
    §9's live-vs-candle-close audit); it is still gated by the sector
    gate and the day's slot cap exactly like the candle-close path."""
    if tracker.done or tracker.position_id is not None or day_state["slots_remaining"] <= 0:
        return None
    event = strat.check_tick_trigger(tracker.signal_state, tracker.direction, ltp, now)
    if event is None:
        return None
    # Mirror step_candle()'s own state mutation on trigger (clears
    # active_signal) so the candle-close path, if it still runs for this
    # boundary, doesn't see a stale active signal and re-trigger it.
    tracker.signal_state = dict(tracker.signal_state, active_signal=None, breakout_counter=0)
    if tracker.signal_db_id is not None:
        idb.update_signal_status(tracker.signal_db_id, "triggered")
    tracker.done = True  # resolved the instant it triggers (Spec v3 §4)
    result = _open_position_from_trigger(tracker, event, capital_alloc, risk_budget, mode)
    if result["type"] == "position_opened":
        day_state["slots_remaining"] -= 1
    return result


def _closed_only(hist: pd.DataFrame | None, boundary: pd.Timestamp) -> pd.DataFrame | None:
    """NO-LOOK-AHEAD guard: keeps only candles whose label is <= the last
    fully CLOSED candle's label (`boundary`). A candle's label is its
    OPEN time, so anything labeled after `boundary` is still forming (or
    hasn't started) and its close/EMA contribution is not yet knowable."""
    if hist is None:
        return None
    return hist[hist.index <= boundary]


def _floor5(ts: pd.Timestamp) -> pd.Timestamp:
    """The 5-minute candle label (open time) containing `ts`."""
    ts = pd.Timestamp(ts)
    return ts.replace(second=0, microsecond=0, nanosecond=0) - pd.Timedelta(minutes=ts.minute % 5)


def check_intracandle_exit(
    tracker: CandidateTracker, ltp: float, now: dt.datetime, mode: str
) -> dict | None:
    """v5.4 exit, tick-driven part (§2.2/§5b/§5i.2). Between candle
    closes, watch LTP against the open position's stop/target:

    1. STOP/BREAKEVEN first, always. Before the first half books, the
       ORIGINAL stop protects the full remaining quantity (the v5
       spec's prose said the runner rides with no stop at all; the
       validated backtest code and v5.2's own exit-path table, e.g.
       "EMA5-trail -> stop: 89 positions", said otherwise -- corrected
       here). Once the first half IS booked (fixed target or the EMA
       trail), §5b's breakeven rule shifts the level protecting the
       runner from the original stop up (LONG) / down (SHORT) to the
       ENTRY PRICE -- checked here, before the target/touch block below,
       so it can only ever take effect from the tick after the booking
       confirmed, never the same tick.
    2. TARGET, only until first touched: price reaching the 1:2R target
       no longer books the first half there by default. Where the target
       sits vs EMA10 (§5i.2 -- EMA5 is no longer consulted at all) of the
       last COMPLETED candle (never the still-forming touch candle -- no
       look-ahead) decides whether to DEFER (persist target_touch_time +
       trail_ema, sell nothing; the trail itself is checked at candle
       closes by step_position_boundary()) or, if EMA10 doesn't apply,
       book the first half at the fixed target exactly like v5.1.

    No-ops if this tracker has no open position, or while `now` is still
    inside the position's own ENTRY CANDLE (v5.4 §5i.3 -- ported exactly
    as specified: no intrabar stop -- or target -- check applies to the
    entry candle itself, so a dip that recovers before that candle
    closes survives, deliberately matching the backtest's own blind spot
    rather than exploiting the live feed's finer information. The only
    check on the entry candle is its own CLOSE vs the stop, handled
    separately by check_entry_candle_close() once that candle closes;
    normal tick-driven checking resumes from the next candle onward)."""
    if tracker.position_id is None:
        return None
    pos = idb.get_position(tracker.position_id)
    if pos is None or pos["status"] != "open":
        return None
    if _floor5(now) == _floor5(pd.Timestamp(pos["entry_time"])):
        return None

    direction = pos["direction"]
    already_took_target = pos["qty_remaining"] < pos["qty"]
    active_stop = pos["entry_price"] if already_took_target else pos["stop_price"]
    hit_stop = ltp <= active_stop if direction == strat.LONG else ltp >= active_stop
    if hit_stop:
        leg_type = "breakeven" if already_took_target else "stop"
        return _close_leg(tracker, pos, leg_type, pos["qty_remaining"], active_stop, now, mode)
    if already_took_target:
        return None  # runner survives this tick; nothing else to check until squareoff

    # Target logic applies only once: not yet touched.
    if pos.get("target_touch_time") is not None:
        return None
    hit_target = (
        ltp >= pos["target_price"] if direction == strat.LONG else ltp <= pos["target_price"]
    )
    if not hit_target:
        return None

    half = pos["qty"] // 2
    # EMA10 from the last COMPLETED candle only (§5i.2).
    last_closed = _last_closed_candle_label(now)
    closed = _closed_only(getattr(tracker, "hist", None), last_closed)
    e10 = None
    if closed is not None and not closed.empty:
        e10 = strat.ema_n(closed["close"], strat.TRAIL_EMA_SLOW).iloc[-1]
    trail = strat.choose_trail_ema(direction, pos["target_price"], e10)

    if half <= 0:
        # A 1-share position can't be split -- mark touched (so this isn't
        # re-evaluated every tick) and let it ride whole; stop/squareoff
        # still apply.
        idb.mark_target_touched(tracker.position_id, str(now), None)
        return None
    if trail is None:
        # EMA10 doesn't apply -> v5.1 behavior: book the first half at
        # the fixed target price right now (runner's stop becomes
        # breakeven starting the NEXT tick, via already_took_target above).
        idb.mark_target_touched(tracker.position_id, str(now), None)
        return _close_leg(tracker, pos, "target", half, pos["target_price"], now, mode)

    idb.mark_target_touched(tracker.position_id, str(now), trail)
    _push(
        f"KK Trading — {pos['symbol']} target touched ({mode})",
        f"1:2R target {pos['target_price']:.2f} reached -- first-half booking "
        f"deferred, trailing EMA{trail}; original stop still protects the full position.",
    )
    return {
        "type": "target_touched",
        "trail_ema": trail,
        "target": pos["target_price"],
        "ema10": float(e10),
    }


def check_entry_candle_close(
    tracker: CandidateTracker, boundary: pd.Timestamp, now: dt.datetime, mode: str
) -> dict | None:
    """v5.4 §5i.3 -- the "entry-candle close" rule, ported EXACTLY as
    specified: no intrabar stop check applies to the entry candle
    itself (check_intracandle_exit() suppresses all tick-driven
    checking for that same window -- see its own docstring); the ONLY
    check on the entry candle is its own CLOSE versus the stop,
    evaluated once, the moment that candle actually closes. If breached,
    the FULL position closes at that CLOSE price (not the stop price) --
    a deliberate, accepted trade-off: the realized loss can overshoot
    the position's sized risk budget (spec's own measured bound: mean
    1.30R, median 1.19R, max 2.40R across the affected trades). Normal
    intrabar stop/target behavior resumes from the next candle onward,
    unaffected by this.

    Must be called from the per-boundary loop that processes newly
    CLOSED candles, once per boundary. No-ops for any boundary other
    than this position's own entry candle, for a tracker with no open
    position, or if this isn't a brand-new (nothing booked yet)
    position -- this rule only ever concerns the very first candle."""
    if tracker.position_id is None:
        return None
    pos = idb.get_position(tracker.position_id)
    if pos is None or pos["status"] != "open" or pos["qty_remaining"] != pos["qty"]:
        return None
    entry_candle_label = _floor5(pd.Timestamp(pos["entry_time"]))
    if boundary != entry_candle_label:
        return None
    if tracker.hist is None:
        return None
    row = tracker.hist[tracker.hist.index == boundary]
    if row.empty:
        return None
    close_px = float(row.iloc[0]["close"])
    direction = pos["direction"]
    breached = (
        (close_px <= pos["stop_price"])
        if direction == strat.LONG
        else (close_px >= pos["stop_price"])
    )
    if not breached:
        return None
    return _close_leg(tracker, pos, "entry_candle_close", pos["qty_remaining"], close_px, now, mode)


def _refresh_position_hist(tracker: CandidateTracker, boundary: pd.Timestamp) -> bool:
    """Merges a small recent window of closed candles into tracker.hist
    (same pattern as the signal path -- keep the NEWEST value for any
    overlapping label, since a just-closed candle can still settle for a
    few minutes) and drops anything labeled after `boundary`. Returns
    False (leaving hist untouched) if the fetch fails, so a transient API
    error can't take down the engine loop while a position is open."""
    try:
        delta = kite_client.fetch_intraday_candles(
            tracker.symbol, days=_REFRESH_WINDOW_DAYS, interval="5minute"
        )
    except Exception as e:
        print(f"[intraday_engine] {tracker.symbol}: candle refresh failed -- {e}")
        return False
    merged = pd.concat([tracker.hist, delta]) if tracker.hist is not None else delta
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    tracker.hist = _closed_only(merged, boundary)
    return True


def step_position_boundary(
    tracker: CandidateTracker, boundary: pd.Timestamp, now: dt.datetime, mode: str, live_price_fn
) -> dict | None:
    """v5.2 exit, candle-close part (spec §1 steps 3-5). Called once per
    newly CLOSED candle (label `boundary`) for a tracker with an open
    position -- independent of the day's remaining trade slots.

    While the first-half booking is deferred: for each closed candle
    AFTER the touch candle (the touch candle itself is excluded, like the
    backtest), compare that candle's own close to that same candle's own
    trail EMA. The first candle closing through it (LONG: below, SHORT:
    above) books 50% at the NEXT candle's open.

    NO LOOK-AHEAD: only candles labeled <= `boundary` (fully closed) are
    ever examined; the fill is the next candle's open only if that candle
    is ALREADY closed in hist (catch-up case) -- otherwise it's the live
    price right now, i.e. the first price after the crossing candle
    closed, never the crossing candle's own close (a value the order
    could not actually have traded at)."""
    if tracker.position_id is None:
        return None
    pos = idb.get_position(tracker.position_id)
    if pos is None or pos["status"] != "open":
        return None
    if pos["qty_remaining"] < pos["qty"]:
        return None  # first half already booked -- nothing candle-close-driven left

    _refresh_position_hist(tracker, boundary)  # keeps EMAs current for the touch decision too

    touch_time, span = pos.get("target_touch_time"), pos.get("trail_ema")
    if touch_time is None or span is None or pd.isna(span) or tracker.hist is None:
        return None
    span = int(span)
    touch_label = _floor5(touch_time)
    hist = _closed_only(tracker.hist, boundary)
    ema = strat.ema_n(hist["close"], span)
    start = max(touch_label, tracker.trail_checked_through)  # strictly AFTER the touch candle
    todo = hist[(hist.index > start) & (hist.index <= boundary)]
    tracker.trail_checked_through = boundary
    for ts, row in todo.iterrows():
        if not strat.trail_crossed(pos["direction"], float(row["close"]), ema.get(ts)):
            continue
        later = hist[hist.index > ts]
        if not later.empty:
            fill_px = float(later.iloc[0]["open"])  # next candle already closed: exact open
        else:
            fill_px = live_price_fn()
            if fill_px is None:
                fill_px = float(row["close"])  # last resort only; no live price available
        half = pos["qty"] // 2
        if half <= 0:
            return None
        return _close_leg(tracker, pos, f"ema{span}_trail_exit", half, fill_px, now, mode)
    return None


def force_squareoff(
    tracker: CandidateTracker, ltp: float, now: dt.datetime, mode: str
) -> dict | None:
    """Spec §5.4 -- force-close, time-driven regardless of price. Called
    by run_live() once its own loop exits at 15:10:00 real time -- a
    2-minute safety buffer before Zerodha's own 15:12:00 auto-square-off
    for F&O-enabled equity (CAS cash segment) MIS positions, the actual
    broker-enforced cutoff this code trades against. NOT the same as the
    backtest's own squareoff-price convention (the "15:10"-labeled
    candle's close = 15:15:00 real time, Spec v3 §9) -- that price isn't
    achievable live for this broker, see run_live()'s own comment on
    this exact point."""
    if tracker.position_id is None:
        return None
    pos = idb.get_position(tracker.position_id)
    if pos is None or pos["status"] != "open":
        return None
    return _close_leg(tracker, pos, "squareoff", pos["qty_remaining"], ltp, now, mode)


def _close_leg(
    tracker: CandidateTracker,
    pos: dict,
    leg_type: str,
    qty: int,
    exit_price: float,
    now: dt.datetime,
    mode: str,
) -> dict:
    side = "SELL" if pos["direction"] == strat.LONG else "BUY"
    order_id = None
    if mode == "live":
        order_id = kite_client.place_order(
            pos["symbol"], qty, side, product="MIS", order_type="MARKET"
        )
    sign = 1 if pos["direction"] == strat.LONG else -1
    gross = (exit_price - pos["entry_price"]) * qty * sign
    cost = strat.round_trip_cost(pos["entry_price"], exit_price, qty, direction=pos["direction"])
    net = gross - cost
    idb.close_position_leg(
        tracker.position_id, leg_type, qty, exit_price, str(now), gross, cost, net, order_id
    )
    if leg_type in ("stop", "squareoff", "breakeven", "entry_candle_close"):
        # All four always close the FULL remaining quantity (breakeven
        # is the §5b runner exit, entry_candle_close is §5i.3's own
        # full-position exit) -- nothing left for this tracker to do for
        # the rest of the day.
        tracker.done = True
    _push(
        f"KK Trading — {pos['symbol']} {leg_type} hit ({mode})",
        f"qty {qty} @ ₹{exit_price:.2f} -- net P&L ₹{net:+,.2f}",
    )
    return {
        "type": "leg_closed",
        "leg_type": leg_type,
        "qty": qty,
        "exit_price": exit_price,
        "net_pnl": net,
    }


# ---------------------------------------------------------------------------
# Real-time loop -- run_live() itself is not unit-testable (wall-clock,
# real Kite session); everything it calls above is.
# ---------------------------------------------------------------------------


def _prev_close_and_0925(
    symbols: list[str], today: dt.date
) -> tuple[dict[str, float], dict[str, float]]:
    """Fetches, for each symbol: previous trading day's daily close, and
    today's 09:25-candle close (= price at 09:30 real time). A symbol
    missing either is silently excluded (matches the validated scratch
    script's own dropna behavior, see intraday_strategy.day_bias's
    caller in run_selection()).

    Fast path: ONE batched kite.quote() call (kite_client.get_quote_
    with_change()) for every symbol at once -- measured 2026-09-15:
    0.15s for 204 symbols, vs ~72s for the old one-symbol-at-a-time
    historical-candle loop (Kite's historical API has no batch mode;
    quote() does). quote()'s own last_price becomes the "09:25 candle
    close" value -- Spec.md's own definition of that value IS "price at
    09:30 real time", so this is a direct read of the same thing, not
    an approximation of a different one. Relies on this function only
    ever being called right at/after 09:30 (true today: run_live()'s
    only call site is immediately after _wait_until(09:30)) -- calling
    it much later in the day would make last_price stale for this
    purpose, since it's no longer close to 09:30.

    Falls back to the old slow-but-robust per-symbol historical-candle
    fetch ONLY for symbols the batched call (and the settlement-suffix
    retry below) didn't return usable data for (rare -- e.g. a
    newly-listed stock quote() doesn't recognize yet), so a handful of
    stragglers can't silently degrade the whole run back to 72s."""
    close_0925, prev_close = {}, {}
    try:
        quotes = kite_client.get_quote_with_change(symbols)
        for sym, q in quotes.items():
            if q.get("last_price"):
                close_0925[sym] = float(q["last_price"])
            if q.get("prev_close"):
                prev_close[sym] = float(q["prev_close"])
    except Exception as e:
        print(
            f"[intraday_engine] batched quote() fetch failed, falling back to "
            f"per-symbol fetch for all {len(symbols)} symbols -- {e}"
        )

    missing = [s for s in symbols if s not in close_0925 or s not in prev_close]
    if missing:
        # A "missing" symbol is often NOT actually missing data -- NSE
        # temporarily moves a stock into a trade-for-trade/surveillance
        # settlement segment, which changes its Kite trading symbol to
        # e.g. "HFCL-BE" instead of "HFCL", while the underlying company
        # keeps trading completely normally. Confirmed live 2026-09-17:
        # HFCL had real, current quote data the whole time under -BE;
        # treating it as genuinely missing would have wrongly failed the
        # sector gate (Spec v2 §6/§10.3) closed for a stock that wasn't
        # actually missing anything. Tried BEFORE the slow per-symbol
        # historical-candle fallback below, since it's one more cheap
        # batch call, not a real fallback path.
        suffix_keys = [f"{s}{suf}" for s in missing for suf in _NSE_SETTLEMENT_SUFFIXES]
        try:
            suffix_quotes = kite_client.get_quote_with_change(suffix_keys)
        except Exception as e:
            suffix_quotes = {}
            print(f"[intraday_engine] settlement-suffix retry fetch failed -- {e}")
        for s in missing:
            for suf in _NSE_SETTLEMENT_SUFFIXES:
                q = suffix_quotes.get(f"{s}{suf}")
                if q and q.get("last_price") and q.get("prev_close"):
                    close_0925[s] = float(q["last_price"])
                    prev_close[s] = float(q["prev_close"])
                    break

    missing = [s for s in symbols if s not in close_0925 or s not in prev_close]
    if missing:
        print(
            f"[intraday_engine] {len(missing)} symbol(s) still missing after the "
            f"batched quote() + settlement-suffix retry -- falling back to per-symbol "
            f"fetch for those"
        )
    today_ts = pd.Timestamp(today)
    for sym in missing:
        try:
            daily = kite_client.fetch_daily_candles(sym, days=10)
            prior = daily[daily.index.normalize() < today_ts]
            if not prior.empty:
                prev_close[sym] = float(prior["close"].iloc[-1])
            intraday = kite_client.fetch_intraday_candles(sym, days=2, interval="5minute")
            row = intraday[intraday.index == today_ts + pd.Timedelta(hours=9, minutes=25)]
            if not row.empty:
                close_0925[sym] = float(row["close"].iloc[0])
        except Exception as e:
            print(f"[intraday_engine] {sym}: fallback prev_close/0925 fetch failed -- {e}")
        time.sleep(0.1)
    return close_0925, prev_close


def _wait_until(target: dt.time) -> None:
    now = dt.datetime.now()
    target_dt = dt.datetime.combine(now.date(), target)
    if now < target_dt:
        time.sleep((target_dt - now).total_seconds())


def _last_closed_candle_label(now: dt.datetime) -> dt.datetime:
    """The label (start time) of the most recently FULLY CLOSED 5-min
    candle as of `now` -- e.g. at 09:37, the candle labeled 09:30
    (covering 09:30-09:35) is the last one closed; the candle labeled
    09:35 (covering 09:35-09:40) is still forming. Getting this off by
    one candle would make the engine try to process a bar that hasn't
    closed yet (caught during review, before ever running live)."""
    floor = now.replace(second=0, microsecond=0) - dt.timedelta(minutes=now.minute % 5)
    return floor - dt.timedelta(minutes=5)


def _get_live_ltp(ticker: live_ticker.LiveTicker, token: int, symbol: str) -> float | None:
    """Prefers the live WebSocket tick; falls back to a one-off REST
    get_ltp() call if the feed has gone stale (e.g. mid-reconnect) or
    hasn't produced a tick for this token yet, so a quiet patch in the
    feed can't silently freeze trigger/stop/target checks."""
    age = ticker.last_tick_age(token)
    if age is not None and age <= TICK_STALE_SECONDS:
        return ticker.get_ltp(token)
    try:
        return kite_client.get_ltp([symbol])[symbol]
    except Exception as e:
        print(f"[intraday_engine] {symbol}: REST LTP fallback failed -- {e}")
        return ticker.get_ltp(token)


def run_live(mode: str = "paper") -> None:
    """Entry point: `python intraday_engine.py` (paper mode) during real
    market hours. Idles/exits immediately on a non-trading day."""
    today = dt.date.today()
    if not nse_holidays.is_trading_day(today):
        print(f"{dt.datetime.now():%d %b %Y %H:%M:%S} Not an NSE trading day -- exiting.")
        return
    date_str = today.isoformat()
    starting_capital = config.STRATEGY.get(
        "intraday_live_capital" if mode == "live" else "intraday_paper_capital",
        DEFAULT_PAPER_CAPITAL,
    )
    idb.ensure_capital_seeded(mode, starting_capital)

    print(f"Waiting for 09:30 ({dt.datetime.now():%H:%M:%S} now)...")
    _wait_until(dt.time(9, 30))

    nifty50 = mkt.fetch_nifty50_constituents()
    fno_syms = list(config.UNIVERSE)
    all_syms = sorted(set(nifty50) | set(fno_syms))
    print(f"Fetching 09:25 close + prev close for {len(all_syms)} symbols...")
    close_0925, prev_close = _prev_close_and_0925(all_syms, today)

    sel = run_selection(date_str, nifty50, fno_syms, close_0925, prev_close, mode)
    print(
        f"nifty_ratio={sel['nifty_ratio']:.2f}  day_bias={sel['day_bias']}  "
        f"candidates={sel['candidates']}"
    )
    if sel["day_bias"] is None:
        print("No clear day bias -- no trading today.")
        _push(
            "KK Trading — no intraday trade today",
            f"NIFTY 50 first-15m ratio was {sel['nifty_ratio']:.2f} -- doesn't "
            f"clear the LONG (>{strat.BIAS_RATIO_LONG_MIN}) or SHORT "
            f"(<{strat.BIAS_RATIO_SHORT_MAX}) threshold. Sitting out today ({mode} mode).",
        )
        return
    if not sel["candidates"]:
        print("Day bias set but no valid candidates -- no trading today.")
        _push(
            "KK Trading — no intraday trade today",
            f"Day bias was {sel['day_bias']} (ratio {sel['nifty_ratio']:.2f}) "
            f"but no valid F&O candidates found. Sitting out today ({mode} mode).",
        )
        return

    # v2 Spec §6.4 -- resolve each candidate's sector-confirmation-gate
    # ratio ONCE here, right after selection, using the same 09:30
    # snapshot data (extended with any sector constituents not already
    # covered) -- fixed for the whole day, looked up (never recomputed)
    # the moment a breakout later triggers (see _open_position_from_trigger()).
    resolve_sector_gates(date_str, sel["candidates"], close_0925, prev_close, today)

    _cands_df = idb.get_candidates(date_str)
    _cand_summary = ", ".join(
        f"#{int(r['rank'])} {r['symbol']} ({r['ret_first15_pct']:+.2f}%) "
        f"sector={r['sector']} ratio={r['sector_ratio']:.2f} "
        f"gate={'PASS' if r['sector_gate_pass'] else 'FAIL'}"
        if pd.notna(r["sector_ratio"])
        else f"#{int(r['rank'])} {r['symbol']} ({r['ret_first15_pct']:+.2f}%) sector=unresolved"
        for _, r in _cands_df.iterrows()
    )
    _push(
        f"KK Trading — {sel['day_bias']} day ({mode})",
        f"NIFTY 50 ratio {sel['nifty_ratio']:.2f} -> {sel['day_bias']}. "
        f"Candidates: {_cand_summary}",
    )

    capital = idb.get_capital(mode)["current_capital"]
    capital_alloc = (capital / strat.MAX_TRADES_PER_DAY) * strat.LEVERAGE
    risk_budget = capital * strat.MAX_RISK_PCT_PER_TRADE

    trackers = []
    for c in sel["candidates"]:
        sym = c["symbol"]
        hist = kite_client.fetch_intraday_candles(sym, days=EMA_WARMUP_DAYS, interval="5minute")
        ema21_series = strat.ema21(hist["close"])
        atr14_series = strat.atr14(hist)
        # v5.4 §5m (adopted, supersedes §5l) -- the signal candle must
        # also close on the trend side of EMA50. EMA_WARMUP_DAYS=120 is
        # ~9,000 5-min candles, comfortably past the 50-candle min_periods
        # for any symbol with at least a few hours of trading history, so
        # this only ever fails closed (NaN) in a genuinely new listing's
        # first day or two.
        ema50_series = strat.ema_n(hist["close"], 50)
        today_so_far = hist[hist.index.normalize() == pd.Timestamp(today)]
        # v2 Spec §3.2 step 1b -- the day's very first (09:15) candle's
        # own low/high, captured once, fixed for the whole day.
        first_candle = today_so_far.loc[
            today_so_far.index == pd.Timestamp(today) + pd.Timedelta(hours=9, minutes=15)
        ]
        if first_candle.empty:
            print(
                f"[intraday_engine] {sym}: 09:15 candle missing -- cannot apply the "
                f"first-candle gate safely, dropping this candidate for today."
            )
            idb.mark_candidate_status(date_str, sym, "invalidated")
            continue
        first_candle_low = float(first_candle.iloc[0]["low"])
        first_candle_high = float(first_candle.iloc[0]["high"])
        # v5.4 §5i.1 -- the one-sided signal gate's own fixed reference
        # range, from the 09:20 AND 09:25 candles specifically (distinct
        # from the 09:15 first_candle above). Both are already-closed
        # history by the time this runs (09:30+), same timing guarantee
        # as the 09:15 candle. Missing either -> fail closed (None),
        # matching signal_in_range()'s own fail-closed contract.
        c20 = today_so_far.loc[
            today_so_far.index == pd.Timestamp(today) + pd.Timedelta(hours=9, minutes=20)
        ]
        c25 = today_so_far.loc[
            today_so_far.index == pd.Timestamp(today) + pd.Timedelta(hours=9, minutes=25)
        ]
        if not c20.empty and not c25.empty:
            sig_range_low = min(float(c20.iloc[0]["low"]), float(c25.iloc[0]["low"]))
            sig_range_high = max(float(c20.iloc[0]["high"]), float(c25.iloc[0]["high"]))
        else:
            print(
                f"[intraday_engine] {sym}: 09:20/09:25 candle missing -- one-sided "
                f"signal gate fails closed, no fresh signal can form for this candidate today."
            )
            sig_range_low, sig_range_high = None, None
        # v5.4 §5n (adopted, supersedes §5m) -- the fair-value-gap veto
        # zone, from the SAME 09:15 (first_candle) and 09:25 (c25)
        # candles already fetched above -- no new data needed. (None,
        # None) when c25 is missing or there's genuinely no gap that day
        # -- both correctly leave the veto inert (see fvg_vetoed()).
        if not c25.empty:
            fvg_lo, fvg_hi = strat.fair_value_gap(
                first_candle_high,
                first_candle_low,
                float(c25.iloc[0]["high"]),
                float(c25.iloc[0]["low"]),
            )
        else:
            fvg_lo, fvg_hi = None, None
        t = CandidateTracker(
            date_str,
            sym,
            c["direction"],
            ema21_series,
            atr14_series,
            first_candle_low,
            first_candle_high,
            c["rank"],
            sector=c.get("sector"),
            sector_ratio=c.get("sector_ratio"),
            sector_gate_pass=c.get("sector_gate_pass", False),
            sig_range_low=sig_range_low,
            sig_range_high=sig_range_high,
            ema50_series=ema50_series,
            fvg_lo=fvg_lo,
            fvg_hi=fvg_hi,
        )
        t.hist = hist
        # Seed the running vol-min from today's pre-window candles (09:15-
        # 09:30) -- see step_candle()'s docstring; the running min starts
        # at session open, not at the 09:30 signal-window start.
        pre_window = today_so_far.loc[
            today_so_far.index < pd.Timestamp(today) + pd.Timedelta(hours=9, minutes=30)
        ]
        t.vol_min_so_far = float(pre_window["volume"].min()) if not pre_window.empty else None
        trackers.append(t)

    # Live tick feed (WebSocket, not REST polling) -- all candidates'
    # trigger/stop/target checks below react to real ticks as they
    # arrive instead of a fixed poll cadence. See live_ticker.py.
    inst_map = kite_client.instrument_map()
    token_by_symbol = {t.symbol: inst_map[t.symbol] for t in trackers if t.symbol in inst_map}
    ticker = live_ticker.LiveTicker({tok: sym for sym, tok in token_by_symbol.items()})
    ticker.start()

    # v3 Spec §4 -- the day's shared trade-slot cap, mutated by both the
    # candle-close path (below) and the tick-driven path
    # (check_tick_entry()) -- a single dict so both share the same live
    # count rather than each keeping its own (which would let both
    # independently think a slot was free and double-fill it).
    day_state = {"slots_remaining": strat.MAX_TRADES_PER_DAY}

    try:
        last_candle_ts = None
        last_pos_candle_ts = None  # v5.2 trail step's own boundary tracker
        print("Entering intraday loop (09:30-15:10)...")
        while True:
            now = dt.datetime.now()
            # Two DIFFERENT 15:xx numbers are in play here, and only one
            # of them governs live trading:
            #  - The backtest's own squareoff price convention (Spec v3
            #    §9) uses the "15:10"-labeled candle's CLOSE, i.e. the
            #    price at 15:15:00 real time -- that's what the published
            #    backtest numbers assume was achievable.
            #  - Zerodha (the broker this account trades through) auto-
            #    square-offs MIS positions on F&O-enabled equity (cash
            #    segment, CAS) at 15:12:00 real time, NOT 15:15 -- a hard
            #    broker-side risk-management cutoff, not something this
            #    code can trade past. Waiting until 15:15 would mean
            #    Zerodha's own system force-closes the position first, at
            #    an uncontrolled price, before this code's own squareoff
            #    order even fires.
            # This live loop follows the ACHIEVABLE constraint (15:12),
            # not the backtest's theoretical one -- exiting at 15:10
            # leaves a 2-minute safety buffer for order placement/fill
            # latency before Zerodha's own cutoff. This is a genuine,
            # unavoidable gap between backtested and live squareoff
            # pricing for this broker -- squareoff-reason exits will
            # price off wherever the market is at 15:10 instead of
            # 15:15, which can come out better or worse than the
            # backtest's own assumption trade to trade, not
            # systematically either way.
            if now.time() >= dt.time(15, 10):
                break

            boundary = _last_closed_candle_label(now)

            # v5.2 EMA-trail (candle-close part): for every OPEN position,
            # check the newly closed candle against its trail EMA. Its own
            # boundary tracker (NOT last_candle_ts) and deliberately outside
            # the `slots_remaining > 0` gate of the signal block below --
            # that gate stops all signal processing once both slots fill,
            # which is exactly when open positions most need this.
            if last_pos_candle_ts is None or boundary > last_pos_candle_ts:
                for t in trackers:
                    if t.position_id is None:
                        continue
                    # v5.4 s5i.3 -- the entry-candle close rule, checked
                    # once right as the entry candle itself closes, BEFORE
                    # the trail-boundary step below (which already no-ops
                    # for a position that hasn't touched target yet, so
                    # ordering is not load-bearing, just logical).
                    _ecev = check_entry_candle_close(t, boundary, dt.datetime.now(), mode)
                    if _ecev:
                        print(f"{boundary} {t.symbol}: {_ecev}")
                        continue  # position just closed -- nothing left to check this boundary
                    _tok = token_by_symbol.get(t.symbol)
                    _px_fn = (
                        (lambda _t=t, _k=_tok: _get_live_ltp(ticker, _k, _t.symbol))
                        if _tok is not None
                        else (lambda: None)
                    )
                    _ev = step_position_boundary(t, boundary, dt.datetime.now(), mode, _px_fn)
                    if _ev:
                        print(f"{boundary} {t.symbol}: {_ev}")
                last_pos_candle_ts = boundary

            # v2 Spec §3.1 -- SIGNAL_WINDOW_START moved to "09:30" (the
            # candle labeled 09:30 is now itself eligible), so this gate
            # follows the same constant rather than a separate hardcoded
            # time, to avoid the two silently drifting apart again.
            if (
                boundary.time() >= dt.datetime.strptime(strat.SIGNAL_WINDOW_START, "%H:%M").time()
                and (last_candle_ts is None or boundary > last_candle_ts)
                and day_state["slots_remaining"] > 0
            ):
                # v3 Spec §4 -- collect EVERY candidate's event at this
                # SAME boundary first; only after all of them have been
                # advanced do we sort the ones that triggered by rank and
                # apply the day's shared slot cap. Acting on each tracker
                # immediately as it's evaluated (as v1/v2 did, fine there
                # since it only ever had 2 candidates and no shared slot
                # cap to race over) would let whichever candidate simply
                # happens to iterate first claim a slot regardless of
                # rank, if two or more confirm at this exact timestamp --
                # this collect-then-sort step is what Spec v3 §4 requires
                # instead: ties broken by rank, not iteration order.
                fires_this_candle = []  # (rank, tracker, event)
                for t in trackers:
                    if t.done or t.position_id is not None:
                        # Once a position is open, EMA21/ATR14/vol tracking
                        # no longer matters (process_candle() would no-op
                        # anyway, see its own guard) -- skip the refetch
                        # below entirely rather than pay for it uselessly
                        # every 5 minutes until the position closes.
                        continue
                    # Refresh t.hist with just a SMALL recent window and
                    # merge it in, rather than re-fetching the whole
                    # ~120-day history every boundary -- the trackers'
                    # series were only ever set ONCE at setup time (before
                    # market open even finished its first 15 minutes), so
                    # t.ema21_series.get(ts)/t.atr14_series.get(ts) came
                    # back None for every candle closing after that
                    # snapshot, silently disabling both invalidation and
                    # signal formation for the whole day (confirmed live
                    # 2026-09-16: YESBANK's real 09:35 candle satisfied
                    # every signal condition when replayed offline with
                    # fresh series, but produced nothing live because
                    # sig_atr came back None from the frozen snapshot) --
                    # that bug's fix originally re-fetched the FULL
                    # history each time, which worked but cost ~1.2-1.4s/
                    # symbol (measured 2026-09-17), blocking the tick-
                    # driven stop/target/entry checks below for up to ~6s
                    # across a full 5-candidate pool, once every 5 minutes,
                    # on live market data. A small window (days=3, safely
                    # covers today + a weekend/holiday gap) measured at
                    # ~0.11s/symbol instead -- merged into the cached
                    # t.hist (keeping the newest value for any overlapping
                    # timestamp, since a just-closed candle's own data can
                    # still settle/revise slightly for a few minutes after
                    # its close -- confirmed live 2026-09-17) before
                    # recomputing the continuous EMA21/ATR14 series.
                    delta = kite_client.fetch_intraday_candles(
                        t.symbol, days=_REFRESH_WINDOW_DAYS, interval="5minute"
                    )
                    row_df = delta[delta.index == boundary]
                    if row_df.empty:
                        continue
                    t.hist = pd.concat([t.hist, delta])
                    t.hist = t.hist[~t.hist.index.duplicated(keep="last")].sort_index()
                    t.hist = _closed_only(t.hist, boundary)  # no look-ahead: never a forming candle
                    t.ema21_series = strat.ema21(t.hist["close"])
                    t.atr14_series = strat.atr14(t.hist)
                    # v5.4 §5m -- same frozen-snapshot bug class as the
                    # ema21/atr14 refresh above (2026-09-16 YESBANK fix):
                    # without refreshing this too, ema50_series would stay
                    # pinned to its 09:15-ish initial snapshot all day,
                    # silently going stale (though its own NaN-fails-closed
                    # behavior means staleness here would block signals
                    # rather than wrongly admit them -- still wrong, just a
                    # safer failure direction than the original bug).
                    t.ema50_series = strat.ema_n(t.hist["close"], 50)
                    row = row_df.iloc[0]
                    t.vol_min_so_far = (
                        row["volume"]
                        if t.vol_min_so_far is None
                        else min(t.vol_min_so_far, row["volume"])
                    )
                    event = process_candle(t, boundary, row)
                    if event and event["type"] == "triggered":
                        fires_this_candle.append((t.rank, t, event))
                    elif event:
                        print(f"{boundary} {t.symbol}: {event}")
                last_candle_ts = boundary

                for _rank, t, event in sorted(fires_this_candle, key=lambda x: x[0]):
                    if day_state["slots_remaining"] <= 0:
                        # Lost the tie / day already filled by an earlier
                        # candidate this same boundary -- t.done is already
                        # True (set in process_candle() the instant it
                        # triggered), no position opened, nothing more to do.
                        print(
                            f"{boundary} {t.symbol}: triggered but day's "
                            f"{strat.MAX_TRADES_PER_DAY} slots already filled -- no trade"
                        )
                        continue
                    result = _open_position_from_trigger(t, event, capital_alloc, risk_budget, mode)
                    print(f"{boundary} {t.symbol}: {result}")
                    if result["type"] == "position_opened":
                        day_state["slots_remaining"] -= 1

            for t in trackers:
                # BUGFIX 2026-09-18: `done` means "stop searching for a NEW
                # entry" (set the instant a trigger fires, Spec v3 §4) --
                # it does NOT mean "nothing left to watch for this
                # candidate." A tracker with an OPEN position still has
                # `done=True` (set the moment it triggered) but must keep
                # being checked here for its stop/target, or it silently
                # loses tick-driven exit monitoring for the rest of the
                # day the instant it opens -- confirmed live: ATHERENERG's
                # stop was breached and sat unclosed for several minutes
                # because this exact guard skipped it every single tick
                # after entry, until a manual intervention closed it. Only
                # skip a tracker that's BOTH done AND has no open position
                # (invalidated / expired / sector-gate-failed / slots-
                # filled -- genuinely nothing left to do for it).
                if t.done and t.position_id is None:
                    continue
                token = token_by_symbol.get(t.symbol)
                if token is None:
                    continue
                ltp = _get_live_ltp(ticker, token, t.symbol)
                if ltp is None:
                    continue
                now2 = dt.datetime.now()
                # Tick-driven entry, restored -- catches a breakout the
                # instant a live tick crosses the trigger level rather than
                # waiting up to 5 minutes for the candle to close. This can
                # NEVER fire during the signal candle itself: active_signal
                # is only ever set inside step_candle() once that candle has
                # actually CLOSED (intraday_strategy.py's step_candle(),
                # bottom branch) -- so the earliest any live tick can be
                # checked against a trigger is already within the candle
                # immediately following the signal candle, never before.
                if t.position_id is None:
                    event = check_tick_entry(
                        t, ltp, now2, capital_alloc, risk_budget, mode, day_state
                    )
                else:
                    event = check_intracandle_exit(t, ltp, now2, mode)
                if event:
                    print(f"{now2:%H:%M:%S} {t.symbol}: {event}")

            if day_state["slots_remaining"] <= 0:
                # v3 Spec §4 -- "the outer timestamp loop then breaks --
                # no further candles are processed for that day, for any
                # remaining candidate." Any candidate still watching (not
                # yet done) has nothing left it could do -- mark it done
                # so the tick loop above also stops touching it, but keep
                # the process itself alive (still need to watch any OPEN
                # position's stop/target/squareoff through end of day).
                for t in trackers:
                    if t.position_id is None and not t.done:
                        t.done = True
                        idb.mark_candidate_status(t.date, t.symbol, "day_slots_filled")

            time.sleep(CHECK_INTERVAL_SECONDS)

        print(
            "15:10 -- squaring off any remaining open positions "
            "(2-min buffer before Zerodha's 15:12 auto-square-off)..."
        )
        for t in trackers:
            if t.position_id is None:
                continue
            token = token_by_symbol.get(t.symbol)
            ltp = _get_live_ltp(ticker, token, t.symbol) if token is not None else None
            if ltp is None:
                try:
                    ltp = kite_client.get_ltp([t.symbol])[t.symbol]
                except Exception:
                    pos = idb.get_position(t.position_id)
                    ltp = pos["entry_price"] if pos else None
            if ltp is None:
                continue
            event = force_squareoff(t, ltp, dt.datetime.now(), mode)
            if event:
                print(f"squareoff {t.symbol}: {event}")
    finally:
        ticker.stop()

    # Sum every leg closed today (target/stop legs closed earlier in the
    # loop, plus the squareoff legs just above) straight from the DB --
    # a single source of truth, no separate running total to keep in sync.
    all_legs_today = idb.get_legs(date=date_str, mode=mode)
    total_day_pnl = float(all_legs_today["net_pnl"].sum()) if not all_legs_today.empty else 0.0
    new_capital = idb.apply_day_pnl(mode, total_day_pnl)
    print(f"\nDay done. Net P&L: Rs.{total_day_pnl:+,.2f}  New capital: Rs.{new_capital:,.2f}")
    _push(
        f"KK Trading — intraday day done ({mode})",
        f"Net P&L ₹{total_day_pnl:+,.2f} -- new capital ₹{new_capital:,.2f}",
    )


if __name__ == "__main__":
    import sys

    # config.STRATEGY["intraday_live_enabled"] (Admin page checkbox) is the
    # single source of truth for which mode a plain, no-flags invocation
    # runs in -- this is what makes "check the box, save" alone enough:
    # a scheduled daily launch runs this exact same command every trading
    # day with no flags, so whichever mode it trades in is decided
    # entirely by whatever's saved in Admin, not by a human remembering to
    # type --live that morning (or forgetting to remove it).
    #
    # --paper forces paper regardless (a deliberate manual safety valve,
    # e.g. testing on a day live is otherwise enabled). --live is accepted
    # for explicit intent/backward compatibility but can NOT bypass the
    # config gate if it's off -- there is no command-line way to place a
    # real order without first opting in from the Admin page.
    live_enabled = config.STRATEGY.get("intraday_live_enabled", False)
    if "--paper" in sys.argv:
        _mode = "paper"
    else:
        _mode = "live" if live_enabled else "paper"
        if "--live" in sys.argv and not live_enabled:
            print(
                "intraday_live_enabled is off in config.STRATEGY -- refusing --live, "
                "running paper mode instead."
            )
    run_live(mode=_mode)
