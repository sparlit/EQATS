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
Multi-day BATCH backtest for the "DaysLowVolumnBreakout" intraday
strategy, over a short recent date range reachable via live Kite
historical data (kite_client.fetch_intraday_candles_range()) -- NOT a
reproduction of the v5.4 spec's own published 5-year numbers, which
come from E:\\trading-workspace\\intraday-pullback-trading's own local
disk cache of 5-min history; this dashboard has no access to that cache
and no cheap way to pull years of 5-minute candles for the whole F&O
universe from Kite's live API (100-day chunk limit per request, ~200
symbols). Intended for sanity-checking the CURRENTLY DEPLOYED rule set
(day bias -> candidate selection -> gap filter -> sector gate -> signal
detection -> CHRONO slot-filling -> position sizing -> exit management)
against real recent market data, the same way page_backtest() does for
the positional strategy.

Mirrors intraday_engine.py's run_live()/run_selection()/
resolve_sector_gates() decision logic as closely as a candle-granularity
batch replay can, but is a PURE, DB-free simulation: it never writes to
intraday_db's tables (those hold real paper/live trading history --
writing backtest rows there would corrupt it). Returns a plain dict of
DataFrames; the caller is responsible for caching/displaying the
result, exactly like backtest.py's own run_backtest() for the
positional strategy.

Candle data is cached to disk (cache/intraday_backtest/{5min,daily}/
{SYMBOL}.csv), mirroring backtest.py's own load_candles_cached() --
a past trading day's candles never change once that day has closed, so
re-fetching the whole F&O+NIFTY50 universe (~200+ symbols) from Kite on
every single run (including two runs over overlapping date ranges)
would pay the same slow, rate-limited cost for data already on disk.
Only the genuinely missing portion of a requested range is ever
fetched (extending the cache earlier, later, or both); the most recent
cached day is always treated as possibly incomplete and re-fetched, in
case today was still live when it was last written.
"""


import datetime as dt
import os

import intraday_market as mkt
import intraday_strategy as strat
import kite_client
import nse_holidays
import pandas as pd
import sector_universe as su

import config

EMA_WARMUP_DAYS = 120  # same depth as intraday_engine.py's EMA_WARMUP_DAYS
CACHE_DIR = os.path.join("cache", "intraday_backtest")


def _trading_days(start_date: dt.date, end_date: dt.date) -> list[dt.date]:
    days = []
    d = start_date
    while d <= end_date:
        if nse_holidays.is_trading_day(d):
            days.append(d)
        d += dt.timedelta(days=1)
    return days


def _candle_at(
    candles5: dict[str, pd.DataFrame], sym: str, day_ts: pd.Timestamp, hh: int, mm: int
) -> pd.Series | None:
    df = candles5.get(sym)
    if df is None or df.empty:
        return None
    row = df[df.index == day_ts + pd.Timedelta(hours=hh, minutes=mm)]
    return row.iloc[0] if not row.empty else None


def _prev_close(daily: dict[str, pd.DataFrame], sym: str, day_ts: pd.Timestamp) -> float | None:
    d = daily.get(sym)
    if d is None or d.empty:
        return None
    prior = d[d.index.normalize() < day_ts]
    return float(prior["close"].iloc[-1]) if not prior.empty else None


def _cache_path(kind: str, symbol: str) -> str:
    return os.path.join(CACHE_DIR, kind, f"{symbol}.csv")


def _read_cache(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path, index_col=0, parse_dates=True)
    except Exception as e:
        print(f"[intraday_backtest] {path}: cache read failed, ignoring -- {e}")
        return pd.DataFrame()


def _write_cache(path: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path)


def _load_or_fetch_5min(symbol: str, warmup_from: dt.date, fetch_to: dt.date) -> pd.DataFrame:
    """5-min candles for `symbol` over [warmup_from, fetch_to], cached to
    disk across runs. Only fetches the piece(s) actually missing from
    the cache -- extending it earlier (if a new run's warmup reaches
    further back), later (if fetch_to moved forward), or both -- and
    always re-fetches from the cache's own last cached day onward
    whenever that day is today or later, since that day may have been
    cached while still mid-session and incomplete."""
    path = _cache_path("5min", symbol)
    cached = _read_cache(path)
    today = dt.date.today()

    if cached.empty:
        fresh = kite_client.fetch_intraday_candles_range(symbol, warmup_from, fetch_to)
        _write_cache(path, fresh)
        return fresh

    cached_min, cached_max = cached.index.min().date(), cached.index.max().date()
    pieces = [cached]

    if warmup_from < cached_min:
        back = kite_client.fetch_intraday_candles_range(
            symbol, warmup_from, cached_min - dt.timedelta(days=1)
        )
        if not back.empty:
            pieces.append(back)

    if cached_max < fetch_to:
        fwd = kite_client.fetch_intraday_candles_range(
            symbol, cached_max + dt.timedelta(days=1), fetch_to
        )
        if not fwd.empty:
            pieces.append(fwd)
    elif cached_max >= today:
        # Last cached day is today (or later, if the clock rolled over
        # since) -- it may have been written mid-session, so refresh it
        # rather than trust a stale partial day.
        refresh = kite_client.fetch_intraday_candles_range(symbol, cached_max, max(fetch_to, today))
        if not refresh.empty:
            pieces.append(refresh)

    merged = pd.concat(pieces) if len(pieces) > 1 else cached
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _write_cache(path, merged)
    return merged[
        (merged.index.normalize() >= pd.Timestamp(warmup_from))
        & (merged.index.normalize() <= pd.Timestamp(fetch_to))
    ]


def _load_or_fetch_daily(symbol: str, warmup_from: dt.date, fetch_to: dt.date) -> pd.DataFrame:
    """Daily candles for `symbol`, cached to disk. A cache whose range
    already fully covers [warmup_from, fetch_to] -- and whose last
    cached day is genuinely in the past, not today -- needs no fetch at
    all; otherwise re-fetches `days` back from today (cheap: daily
    candles have no 100-day chunk limit) and merges it in."""
    path = _cache_path("daily", symbol)
    cached = _read_cache(path)
    today = dt.date.today()

    if not cached.empty:
        cached_min, cached_max = cached.index.min().date(), cached.index.max().date()
        if cached_min <= warmup_from and cached_max >= fetch_to and cached_max < today:
            return cached

    days = (today - warmup_from).days + 5
    fresh = kite_client.fetch_daily_candles(symbol, days=days)
    if fresh.empty:
        return cached
    merged = pd.concat([cached, fresh]) if not cached.empty else fresh
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _write_cache(path, merged)
    return merged


def _fetch_universe(
    symbols: list[str],
    candles5: dict,
    daily: dict,
    warmup_from: dt.date,
    fetch_to: dt.date,
    tick=None,
    stage: str = "Fetching candles",
) -> None:
    """Loads (from disk cache, fetching only what's missing) 5-min +
    daily candles for every symbol in `symbols` not already present in
    `candles5`, mutating both dicts in place. `tick`, if given, is
    called as tick(local_frac) -- a 0..1 fraction of THIS fetch loop's
    own progress -- once per symbol, both so a UI progress bar moves
    smoothly across a ~200-symbol fetch and so a background job's
    cooperative cancellation (raised from inside that callback) is
    checked often enough to actually feel responsive."""
    todo = [s for s in symbols if s not in candles5]
    for i, sym in enumerate(todo):
        try:
            candles5[sym] = _load_or_fetch_5min(sym, warmup_from, fetch_to)
            daily[sym] = _load_or_fetch_daily(sym, warmup_from, fetch_to)
        except Exception as e:
            print(f"[intraday_backtest] {sym}: candle fetch failed -- {e}")
            candles5[sym] = pd.DataFrame()
            daily[sym] = pd.DataFrame()
        if tick:
            tick((i + 1) / len(todo), f"{stage} ({i + 1}/{len(todo)})")


def run_backtest(start_date: dt.date, end_date: dt.date, capital: float, progress_cb=None) -> dict:
    """Runs the full day-by-day simulation over [start_date, end_date]
    (inclusive), compounding `capital` across trading days. `progress_cb`,
    if given, is called as progress_cb(stage: str, frac: float) -- frac
    in [0, 1] over the WHOLE run -- the same (stage, frac) shape
    background_jobs.start_background_job() already wraps for every other
    long-running job in this dashboard (Screener, Live Rebalance, the
    positional Backtest page), so this can be dropped into that same
    machinery (progress bar + cooperative Stop button) unchanged."""

    def _progress(stage: str, frac: float) -> None:
        print(f"[intraday_backtest] ({frac:.0%}) {stage}")
        if progress_cb:
            progress_cb(stage, frac)

    trading_days = _trading_days(start_date, end_date)
    empty = {
        "trades": pd.DataFrame(),
        "daily": pd.DataFrame(),
        "candidates": pd.DataFrame(),
        "skipped_days": pd.DataFrame(),
        "start_date": start_date,
        "end_date": end_date,
        "capital_start": capital,
        "capital_end": capital,
    }
    if not trading_days:
        return empty

    warmup_from = trading_days[0] - dt.timedelta(days=EMA_WARMUP_DAYS)
    fetch_to = trading_days[-1]

    # -- Phase A: universe candle fetch (NIFTY50 union F&O), ONE bulk
    # fetch per symbol over the whole [warmup_from, fetch_to] window --
    # never re-fetched per day (same perf discipline as intraday_engine.
    # py's own per-boundary refresh-window pattern, just at backtest scale).
    # Gets 0-70% of the overall bar -- by far the slowest phase (one Kite
    # historical-data call per symbol).
    _progress("Fetching NIFTY 50 + F&O universe constituents...", 0.0)
    nifty50 = mkt.fetch_nifty50_constituents()
    fno_syms = list(config.UNIVERSE)
    all_syms = sorted(set(nifty50) | set(fno_syms))

    candles5: dict[str, pd.DataFrame] = {}
    daily: dict[str, pd.DataFrame] = {}
    _fetch_stage = f"Fetching {len(all_syms)} symbols' 5-min history ({warmup_from} -> {fetch_to})"
    _progress(_fetch_stage, 0.02)
    _fetch_universe(
        all_syms,
        candles5,
        daily,
        warmup_from,
        fetch_to,
        tick=lambda f, s: _progress(s, 0.02 + f * 0.68),
        stage=_fetch_stage,
    )

    # -- Phase B: per-symbol continuous indicators, computed ONCE over
    # each symbol's whole multi-day series (Spec.md §1 -- never
    # cold-started per day).
    ema21_cache, atr14_cache, ema50_cache, ema10_cache = {}, {}, {}, {}
    for sym, df in candles5.items():
        if df is None or df.empty:
            continue
        ema21_cache[sym] = strat.ema21(df["close"])
        atr14_cache[sym] = strat.atr14(df)
        ema50_cache[sym] = strat.ema_n(df["close"], 50)
        ema10_cache[sym] = strat.ema_n(df["close"], strat.TRAIL_EMA_SLOW)

    # -- Phase C: day-by-day day-bias + candidate selection + signal
    # detection. Sector gate NOT applied yet -- which sectors are even
    # touched isn't known until this phase finishes (same two-phase
    # shape as the reference backtest script).
    _progress("Running day-bias + candidate selection + signal detection...", 0.70)
    by_day: dict[dt.date, list[dict]] = {}
    skipped_days: list[dict] = []
    candidate_rows: list[dict] = []

    for day_i, day in enumerate(trading_days):
        _progress(f"Scanning {day}...", 0.70 + (day_i / len(trading_days)) * 0.15)
        day_ts = pd.Timestamp(day)
        close_0925, prev_close_map = {}, {}
        for sym in all_syms:
            row = _candle_at(candles5, sym, day_ts, 9, 25)
            pc = _prev_close(daily, sym, day_ts)
            if row is not None:
                close_0925[sym] = float(row["close"])
            if pc is not None:
                prev_close_map[sym] = pc

        nifty_ratio, _ = mkt.compute_first15_breadth(nifty50, close_0925, prev_close_map)
        bias = strat.day_bias(nifty_ratio)
        if bias is None:
            skipped_days.append({"date": day, "reason": "no_day_bias", "nifty_ratio": nifty_ratio})
            continue

        fno_rets = {}
        for sym in fno_syms:
            c0925, pc = close_0925.get(sym), prev_close_map.get(sym)
            if c0925 is None or pc is None or pc == 0:
                continue
            fno_rets[sym] = strat.first15_return(c0925, pc)

        ranked_all = strat.select_candidates(
            pd.Series(fno_rets, dtype=float), bias, n=len(fno_rets)
        )
        accepted: list[tuple[str, float, float | None]] = []
        for sym, ret in ranked_all.items():
            c0915 = _candle_at(candles5, sym, day_ts, 9, 15)
            pc = prev_close_map.get(sym)
            gap = (float(c0915["open"]) - pc) / pc * 100.0 if (c0915 is not None and pc) else None
            if not strat.passes_gap_filter(gap):
                continue
            accepted.append((sym, float(ret), gap))
            if len(accepted) >= strat.TOP_N_CANDIDATES:
                break

        if not accepted:
            skipped_days.append(
                {"date": day, "reason": "no_candidates", "nifty_ratio": nifty_ratio}
            )
            continue

        for rank, (sym, ret, gap) in enumerate(accepted, start=1):
            candidate_rows.append(
                {
                    "date": day,
                    "symbol": sym,
                    "rank": rank,
                    "direction": bias,
                    "ret_first15_pct": round(ret, 3),
                    "gap_pct": gap,
                    "nifty_ratio": round(nifty_ratio, 3),
                }
            )
            df5 = candles5.get(sym)
            if df5 is None or df5.empty or sym not in ema21_cache:
                continue
            dsub = df5[df5.index.normalize() == day_ts]
            if dsub.empty:
                continue
            fc = dsub.iloc[0]
            first_low, first_high = float(fc["low"]), float(fc["high"])
            c20 = dsub[dsub.index == day_ts + pd.Timedelta(hours=9, minutes=20)]
            c25 = dsub[dsub.index == day_ts + pd.Timedelta(hours=9, minutes=25)]
            if c20.empty or c25.empty:
                continue  # one-sided signal gate fails closed without both reference candles
            sig_range_low = min(float(c20.iloc[0]["low"]), float(c25.iloc[0]["low"]))
            sig_range_high = max(float(c20.iloc[0]["high"]), float(c25.iloc[0]["high"]))
            fvg_lo, fvg_hi = strat.fair_value_gap(
                first_high, first_low, float(c25.iloc[0]["high"]), float(c25.iloc[0]["low"])
            )
            entry = strat.find_entry(
                dsub,
                bias,
                ema21_cache[sym],
                atr14_cache[sym],
                first_low,
                first_high,
                sig_range_low,
                sig_range_high,
                ema50_series=ema50_cache.get(sym),
                fvg_lo=fvg_lo,
                fvg_hi=fvg_hi,
            )
            if entry is None:
                continue
            risk = abs(entry["entry_price"] - entry["stop_price"])
            by_day.setdefault(day, []).append(
                {
                    "symbol": sym,
                    "direction": bias,
                    "rank": rank,
                    "dsub": dsub,
                    "entry": entry,
                    "risk": risk,
                }
            )

        # A day can clear day_bias and produce candidates (recorded in
        # candidate_rows above, visible in the "Daily candidates"
        # expander) yet still vanish from every OTHER output with no
        # explanation -- find_entry() returning None for every one of
        # them (no candle ever qualified as a signal, or none broke out)
        # is a perfectly normal, common outcome, not a bug, but leaving
        # it unrecorded here is exactly what made a legitimately quiet
        # stretch of days look like a mystery gap in the UI.
        if day not in by_day:
            skipped_days.append(
                {"date": day, "reason": "no_entry_triggered", "nifty_ratio": nifty_ratio}
            )

    n_pre_sector = sum(len(v) for v in by_day.values())
    _progress(f"{n_pre_sector} signal(s) across {len(by_day)} day(s) before the sector gate", 0.85)

    # -- Phase D: sector confirmation gate (v2 Spec §6) + sector-bias
    # annotation, resolved for EVERY ranked candidate (not just the ones
    # that went on to form a signal) -- so the "Daily candidates" table
    # can show each one's sector/sector-ratio/gate verdict, not just the
    # handful that actually traded. Fetches sector-constituent candle
    # data only for symbols not already covered by the universe fetch
    # above.
    all_cand_symbols = sorted({r["symbol"] for r in candidate_rows})
    sector_map: dict[str, str | None] = {}
    if all_cand_symbols:
        profiles = su.resolve_sector_profiles(all_cand_symbols)
        sector_map = {s: p.get("primary_sector") for s, p in profiles.items()}

    sectors_touched = {sector_map[s] for s in all_cand_symbols if sector_map.get(s)}
    catalog = su.fetch_index_constituents()
    sector_members = {sec: list(catalog.get(sec, {}).keys()) for sec in sectors_touched}
    all_sector_syms = sorted(set().union(*sector_members.values())) if sector_members else []
    new_sector_syms = [s for s in all_sector_syms if s not in candles5]
    if new_sector_syms:
        _sector_fetch_stage = (
            f"Fetching {len(new_sector_syms)} additional sector-constituent "
            f"symbol(s) for the sector gate"
        )
        _progress(_sector_fetch_stage, 0.86)
        _fetch_universe(
            new_sector_syms,
            candles5,
            daily,
            warmup_from,
            fetch_to,
            tick=lambda f, s: _progress(s, 0.86 + f * 0.03),
            stage=_sector_fetch_stage,
        )

    sector_ratio_cache: dict[tuple[str, dt.date], float] = {}

    def _sector_ratio(sec: str, day: dt.date) -> float:
        key = (sec, day)
        if key not in sector_ratio_cache:
            members = sector_members.get(sec, [])
            day_ts = pd.Timestamp(day)
            close_0925, prev_close_map = {}, {}
            for m in members:
                row = _candle_at(candles5, m, day_ts, 9, 25)
                pc = _prev_close(daily, m, day_ts)
                if row is not None:
                    close_0925[m] = float(row["close"])
                if pc is not None:
                    prev_close_map[m] = pc
            ratio, _ = mkt.compute_first15_breadth(members, close_0925, prev_close_map)
            sector_ratio_cache[key] = ratio
        return sector_ratio_cache[key]

    _progress("Resolving sector bias for every candidate...", 0.89)
    for row in candidate_rows:
        sec = sector_map.get(row["symbol"])
        if sec is None:
            row["sector"], row["sector_ratio"], row["sector_gate_pass"] = None, None, None
            continue
        ratio = _sector_ratio(sec, row["date"])
        row["sector"] = sec
        row["sector_ratio"] = round(ratio, 3)
        row["sector_gate_pass"] = strat.sector_gate_pass(ratio, row["direction"])

    gated_by_day: dict[dt.date, list[dict]] = {}
    n_dropped_no_sector = n_dropped_sector_fail = 0
    for day, cands in by_day.items():
        kept = []
        for c in cands:
            sec = sector_map.get(c["symbol"])
            if sec is None:
                n_dropped_no_sector += 1
                continue
            ratio = _sector_ratio(sec, day)  # already cached from the candidate_rows pass above
            if strat.sector_gate_pass(ratio, c["direction"]):
                c["sector"] = sec
                c["sector_ratio"] = ratio
                kept.append(c)
            else:
                n_dropped_sector_fail += 1
        if kept:
            gated_by_day[day] = kept
        else:
            # Same visibility gap as Phase C's no_entry_triggered above --
            # this day DID produce a triggered signal, but every one of
            # them lost the sector-confirmation gate, so it would
            # otherwise disappear from daily/trades/skipped_days alike.
            skipped_days.append(
                {"date": day, "reason": "all_sector_gate_failed", "nifty_ratio": None}
            )

    by_day = gated_by_day
    n_signals = sum(len(v) for v in by_day.values())
    _progress(
        f"{n_signals} signal(s) across {len(by_day)} day(s) after the sector gate "
        f"({n_dropped_no_sector} no primary sector, {n_dropped_sector_fail} sector ratio didn't confirm)",
        0.90,
    )

    # -- Phase E: CHRONO slot-filling + capital-compounding day simulation.
    trades: list[dict] = []
    daily_rows: list[dict] = []
    capital_cur = capital
    _sim_days = sorted(by_day.keys())
    for sim_i, day in enumerate(_sim_days):
        _progress(f"Simulating {day}...", 0.90 + (sim_i / max(len(_sim_days), 1)) * 0.09)
        cands = by_day[day]
        # CHRONO (v5.4 §2.3/§5.1): take entries strictly in the order they
        # actually trigger, ties at the exact same timestamp broken by
        # rank -- the only selection rule a live system can genuinely
        # execute, matching run_live()'s own same-boundary tiebreak.
        ordered = sorted(cands, key=lambda c: (c["entry"]["entry_time"], c["rank"]))
        sigs = ordered[: strat.MAX_TRADES_PER_DAY]

        capital_alloc = (capital_cur / strat.MAX_TRADES_PER_DAY) * strat.LEVERAGE
        risk_budget = capital_cur * strat.MAX_RISK_PCT_PER_TRADE
        day_pnl = 0.0
        capital_before = capital_cur

        for c in sigs:
            sym, direction, dsub, entry = c["symbol"], c["direction"], c["dsub"], c["entry"]
            qty = strat.position_size(
                capital_alloc, risk_budget, entry["entry_price"], entry["stop_price"]
            )
            if qty <= 0:
                continue
            ema10_series = ema10_cache.get(sym, pd.Series(dtype=float))
            legs = strat.simulate_exit_v54(
                dsub,
                entry["entry_time"],
                entry["entry_price"],
                entry["stop_price"],
                direction,
                ema10_series,
            )
            leg_qtys = strat.leg_quantities(qty, legs)
            side = 1 if direction == strat.LONG else -1
            position_id = f"{day}-{sym}-{entry['entry_time'].strftime('%H%M')}"
            n_legs = len(legs)
            for i, (leg, leg_qty) in enumerate(zip(legs, leg_qtys, strict=False), start=1):
                gross = (leg["exit_price"] - entry["entry_price"]) * leg_qty * side
                cost = strat.round_trip_cost(
                    entry["entry_price"], leg["exit_price"], leg_qty, direction
                )
                net = gross - cost
                day_pnl += net
                trades.append(
                    {
                        "position_id": position_id,
                        "leg": f"{i}/{n_legs}",
                        "date": day,
                        "symbol": sym,
                        "direction": direction,
                        "sector": c.get("sector"),
                        "rank": c["rank"],
                        "signal_time": entry["signal_time"],
                        "entry_time": entry["entry_time"],
                        "entry_price": round(entry["entry_price"], 2),
                        "stop_price": round(entry["stop_price"], 2),
                        "qty": leg_qty,
                        "exit_time": leg["exit_time"],
                        "exit_price": round(leg["exit_price"], 2),
                        "reason": leg["reason"],
                        "capital_open": round(capital_cur, 2),
                        "gross_pnl": round(gross, 2),
                        "cost": round(cost, 2),
                        "net_pnl": round(net, 2),
                    }
                )

        capital_cur += day_pnl
        daily_rows.append(
            {
                "date": day,
                "day_pnl": round(day_pnl, 2),
                "capital": round(capital_cur, 2),
                "return_pct": (day_pnl / capital_before * 100) if capital_before else 0.0,
                "n_trades": len(sigs),
            }
        )

    trades_df = pd.DataFrame(trades)
    daily_df = pd.DataFrame(daily_rows)
    candidates_df = pd.DataFrame(candidate_rows)
    n_positions = trades_df["position_id"].nunique() if not trades_df.empty else 0
    _progress(
        f"Done -- {n_positions} position(s), capital {capital:,.0f} -> {capital_cur:,.0f}", 1.0
    )

    return {
        "trades": trades_df,
        "daily": daily_df,
        "candidates": candidates_df,
        "skipped_days": pd.DataFrame(skipped_days),
        "start_date": start_date,
        "end_date": end_date,
        "capital_start": capital,
        "capital_end": capital_cur,
    }
