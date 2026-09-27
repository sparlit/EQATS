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
Walk-forward backtesting engine.

For each day in the date range, for each symbol:
    1. Fetch 5m candles (cached in SQLite after first fetch)
    2. Fetch 3 prior days for indicator warm-up (fixes ADX/ATR convergence)
    3. Compute all indicators on warm-up + current day
    4. Classify regime from first 30-min window (9:15–9:45) — now with converged ADX
    5. Select strategy based on regime
    6. Simulate bar-by-bar with ATR-based SL/TP, short support, and min-hold rules
    7. Log every trade to SQLite

No lookahead: indicators are causal (ewm/rolling), regime is determined
before trading starts, signals only reference past bars.
"""

import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import selector as sel
import yfinance as yf
from daystate import apply_cross_sectional_ranks, compute_day_state
from engine import fetch, fetch_intraday
from regime import classify
from risk import RiskConfig, RiskManager
from store import init_db, load_candles, save_candles, save_daily_summary, save_trades
from strategies import STRATEGY_REGISTRY, apply_orb, get_strategy_fn
from universe import SCAN_UNIVERSE, get_ticker

from indicators import compute_all

IST = ZoneInfo("Asia/Kolkata")

# Market hours
_MARKET_OPEN = (9, 15)
_OBS_END_TIME = (9, 45)  # regime classification window ends here
_MARKET_CLOSE = (15, 15)  # square off all positions by 15:15 IST (NSE MIS buffer)

# Slippage: half-spread estimate in basis points (1 bp = 0.01%)
_SLIPPAGE_BPS = 4

# Minimum bars to hold a position before a signal-based exit is allowed.
# Prevents getting whipsawed out in the first 1-2 bars after entry.
_MIN_HOLD_BARS = 3  # 15 min at 5m resolution

# Entry quality filters
_MIN_REL_STRENGTH_PCT = 0.20  # stock move must exceed Nifty proxy by this much
_GAP_ALIGNMENT_PCT = 0.20  # only enforce gap alignment when opening gap is meaningful

# Trade management
# Disabled: breakeven and trail stops were cutting winners short (~1:1 realized R:R
# instead of the designed 2.5:1). Full backtest showed avg_win ≈ avg_loss across all years.
# Let SL/TP do their job cleanly.
_BREAKEVEN_TRIGGER_R = 999.0  # effectively disabled
_TRAIL_TRIGGER_R = 999.0  # effectively disabled

# NSE holidays (approximate — update annually).
# Weekdays on this list are skipped by _trading_days().
_NSE_HOLIDAYS = {
    # 2025
    "2025-02-26",
    "2025-03-14",
    "2025-04-14",
    "2025-04-18",
    "2025-05-01",
    "2025-08-15",
    "2025-10-02",
    "2025-10-20",
    "2025-10-21",
    "2025-11-05",
    "2025-12-25",
    # 2026
    "2026-01-26",
    "2026-02-16",
    "2026-03-02",
    "2026-04-02",
    "2026-04-03",
    "2026-04-14",
    "2026-05-01",
    "2026-08-15",
    "2026-10-02",
    "2026-12-25",
}


def _trade_costs(qty: int, entry: float, exit_price: float) -> float:
    """
    Realistic NSE intraday round-trip costs.

    Breakdown per trade:
        Brokerage   ₹20 × 2 orders (flat fee, Zerodha / Groww model)
        STT         0.025% on sell-side turnover (intraday equity)
        Transaction 0.00335% per side (NSE + exchange)
        SEBI        0.0001% per side
        GST         18% on (brokerage + transaction + SEBI)
        Stamp       0.003% on buy-side turnover
        Slippage    4 bps on both sides (spread + impact)
    """
    buy_val = qty * entry
    sell_val = qty * exit_price

    brokerage = 20.0 * 2
    stt = sell_val * 0.00025
    txn = (buy_val + sell_val) * 0.0000335
    sebi = (buy_val + sell_val) * 0.000001
    gst = (brokerage + txn + sebi) * 0.18
    stamp = buy_val * 0.00003
    slippage = (buy_val + sell_val) * (_SLIPPAGE_BPS / 10_000)

    return round(brokerage + stt + txn + sebi + gst + stamp + slippage, 2)


@dataclass
class BacktestTrade:
    date: str
    symbol: str
    regime: str
    strategy: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    sl_price: float
    tp_price: float
    shares: int
    pnl: float
    pnl_pct: float
    exit_reason: str
    entry_reason: str
    confidence: int = 75
    side: str = "LONG"


@dataclass
class PreparedSymbolDay:
    symbol: str
    trade_date: str
    regime_info: dict
    strategy_id: str
    strategy_name: str
    confidence: int
    atr_pct: float
    vwap_dev: float
    df_signals: pd.DataFrame
    gap_pct: float
    decision: dict = None  # selector output: expectancy per arm, reason


# ── Daily simulation ──────────────────────────────────────────────────────────


def _simulate_day(
    df: pd.DataFrame,
    symbol: str,
    trade_date: str,
    regime_info: dict,
    strategy: str,
    risk_mgr: RiskManager,
    capital: float,
    market_df: pd.DataFrame = None,
    nifty_bias: str = "neutral",
) -> list[BacktestTrade]:
    """
    Simulate one trading day bar-by-bar.

    df must already have signals applied (strategy_fn was called in run()).
    Supports both long (signal=1) and short (signal=-1) entries.

    market_df: optional Nifty 5m bars with 'vwap' column. When provided,
    entries are only taken if the Nifty direction aligns with the trade direction
    (long only when Nifty > its VWAP; short only when Nifty < its VWAP).
    This is the single biggest WR lever for NSE stocks.
    """
    trades = []
    cash = capital

    position = 0  # quantity (always positive)
    side = 0  # 1 = long, -1 = short, 0 = flat
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_time = None
    entry_bar = 0
    entry_risk = 0.0
    bar_idx = 0
    trade_done = False  # one round-trip per day max

    regime = regime_info["regime"]

    first_ist = df.index[0].astimezone(IST)
    obs_end = first_ist.replace(hour=_OBS_END_TIME[0], minute=_OBS_END_TIME[1], second=0, microsecond=0)
    close_bar = first_ist.replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1], second=0, microsecond=0)

    for ts, row in df.iterrows():
        bar_idx += 1
        if ts <= obs_end:
            continue

        price = float(row["close"])
        signal = int(row.get("signal", 0))
        atr = float(row["atr"])

        exit_reason = None
        bar_idx - entry_bar

        if side != 0 and entry_risk > 0:
            if side == 1:
                if price - entry_price >= entry_risk * _BREAKEVEN_TRIGGER_R:
                    sl_price = max(sl_price, round(entry_price, 2))
                if price - entry_price >= entry_risk * _TRAIL_TRIGGER_R:
                    trail_ref = max(float(row.get("ema20", entry_price)), float(row.get("vwap", entry_price)))
                    sl_price = max(sl_price, round(trail_ref, 2))
            else:
                if entry_price - price >= entry_risk * _BREAKEVEN_TRIGGER_R:
                    sl_price = min(sl_price, round(entry_price, 2))
                if entry_price - price >= entry_risk * _TRAIL_TRIGGER_R:
                    trail_ref = min(float(row.get("ema20", entry_price)), float(row.get("vwap", entry_price)))
                    sl_price = min(sl_price, round(trail_ref, 2))

        # ── Exit checks ───────────────────────────────────────────────────────
        if side == 1:  # long
            if price <= sl_price:
                exit_reason = "stop_loss"
            elif price >= tp_price:
                exit_reason = "take_profit"
            elif ts >= close_bar:
                exit_reason = "eod"

        elif side == -1:  # short
            if price >= sl_price:
                exit_reason = "stop_loss"
            elif price <= tp_price:
                exit_reason = "take_profit"
            elif ts >= close_bar:
                exit_reason = "eod"

        if exit_reason:
            # Use the actual SL/TP level as fill price, not bar close.
            # In reality a stop order fills at/near the stop price, not the bar close
            # (which can be far past the stop on a big candle, overstating losses).
            if exit_reason == "stop_loss":
                fill = sl_price
            elif exit_reason == "take_profit":
                fill = tp_price
            else:
                fill = price  # EOD: fill at close
            gross = side * (fill - entry_price) * position
            costs = _trade_costs(position, entry_price, fill)
            pnl = round(gross - costs, 2)
            pnl_pct = round(pnl / (entry_price * position) * 100, 2)
            risk_mgr.record_trade(pnl, ts)
            trades.append(
                BacktestTrade(
                    date=trade_date,
                    symbol=symbol,
                    regime=regime,
                    strategy=strategy,
                    entry_time=str(entry_time),
                    exit_time=str(ts),
                    entry_price=round(entry_price, 2),
                    exit_price=round(fill, 2),
                    sl_price=sl_price,
                    tp_price=tp_price,
                    shares=position,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    exit_reason=exit_reason,
                    entry_reason=f"regime={regime}",
                    side="LONG" if side == 1 else "SHORT",
                )
            )
            cash += position * entry_price + gross
            position = 0
            side = 0
            entry_risk = 0.0
            trade_done = True

        # ── Entry ─────────────────────────────────────────────────────────────
        if position == 0 and not trade_done and ts < close_bar:
            new_side = 0
            if signal == 1:
                new_side = 1
            elif signal == -1:
                new_side = -1

            if new_side != 0:
                if new_side == 1 and nifty_bias == "bearish":
                    continue
                if new_side == -1 and nifty_bias == "bullish":
                    continue

                gap_pct = float(row.get("gap_pct", 0.0))
                if strategy.lower() == "orb" and abs(gap_pct) >= _GAP_ALIGNMENT_PCT:
                    if new_side == 1 and gap_pct < 0:
                        continue
                    if new_side == -1 and gap_pct > 0:
                        continue

                # ── Intraday Nifty direction filter ───────────────────────────
                # Only enter if the broad market (Nifty 50) is moving in the
                # same direction as the trade intraday.
                if market_df is not None and not market_df.empty:
                    try:
                        nearest_idx = market_df.index.get_indexer([ts], method="nearest")[0]
                        nifty_row = market_df.iloc[nearest_idx]
                        nifty_bullish = float(nifty_row["close"]) > float(nifty_row["vwap"])
                        market_open = float(market_df.iloc[0]["open"])
                        market_move_pct = (
                            ((float(nifty_row["close"]) - market_open) / market_open * 100) if market_open else 0.0
                        )
                        stock_open = float(df.iloc[0]["open"])
                        stock_move_pct = ((price - stock_open) / stock_open * 100) if stock_open else 0.0
                        rel_strength = stock_move_pct - market_move_pct
                        if new_side == 1 and not nifty_bullish:
                            continue  # don't go long when Nifty is below its VWAP
                        if new_side == -1 and nifty_bullish:
                            continue  # don't go short when Nifty is above its VWAP
                        if new_side == 1 and rel_strength < _MIN_REL_STRENGTH_PCT:
                            continue
                        if new_side == -1 and rel_strength > -_MIN_REL_STRENGTH_PCT:
                            continue
                    except Exception:
                        pass  # if Nifty data is missing, proceed without filter

                allowed, _ = risk_mgr.can_trade(ts)
                if allowed:
                    sl = risk_mgr.sl_price(price, atr, new_side)
                    tp = risk_mgr.tp_price(price, atr, new_side)
                    qty = risk_mgr.position_size(cash, price, sl)

                    if qty > 0 and cash >= qty * price:
                        position = qty
                        side = new_side
                        entry_price = price
                        sl_price = sl
                        tp_price = tp
                        entry_time = ts
                        entry_bar = bar_idx
                        entry_risk = abs(entry_price - sl_price)
                        cash -= qty * price

    return trades


def _strategy_meta_name(strategy_id: str, fallback: str) -> str:
    return STRATEGY_REGISTRY.get(strategy_id, {}).get("name", fallback)


def _build_day_context(symbol: str, day: date, interval: str, df: pd.DataFrame = None):
    """
    Fetch + enrich one (symbol, day); compute the 9:45 day-state, replay every
    strategy arm counterfactually, and return everything the selector and the
    simulator need. Returns (context dict, None) or (None, marker).

    df: pre-fetched bars for the day (live mode passes these to bypass the
    cache — a partial day must never be cached).
    """
    ticker = get_ticker(symbol)
    day_str = day.strftime("%Y-%m-%d")

    if df is None:
        df = _fetch_day(ticker, symbol, day_str, interval)
    if df is None or len(df) < 10:
        return None, "."

    warmup = _fetch_warmup(ticker, symbol, day, interval, n_days=10)
    if warmup is not None and not warmup.empty:
        full_df = pd.concat([warmup, df])
        full_df = full_df[~full_df.index.duplicated(keep="last")].sort_index()
    else:
        full_df = df

    try:
        enriched = compute_all(full_df)
    except Exception:
        return None, "x"

    idx_ist = enriched.index.tz_convert(IST)
    today_mask = pd.Series([ts.date() == day for ts in idx_ist], index=enriched.index)
    df_today = enriched[today_mask].copy()
    if df_today.empty or len(df_today) < 5:
        return None, "."

    first_ist = df_today.index[0].astimezone(IST)
    obs_end = first_ist.replace(hour=9, minute=45, second=0, microsecond=0)
    obs_window = df_today[df_today.index <= obs_end]
    if obs_window.empty:
        return None, "."

    # Prior-close context — needed by the gap-fade arm and the gap filter
    idx_before = enriched.index[~today_mask]
    gap_pct = 0.0
    if not idx_before.empty:
        prev_close_val = float(enriched.loc[idx_before].iloc[-1]["close"])
        today_open_val = float(df_today.iloc[0]["open"])
        gap_pct = round((today_open_val - prev_close_val) / prev_close_val * 100, 3) if prev_close_val else 0.0
        df_today["prev_close"] = prev_close_val
    df_today["gap_pct"] = gap_pct

    # Noise bands (Zarattini/Aziz-style): for each bar position i, the average
    # |move from open| at that time of day over the prior sessions. Price outside
    # open ± noise(i) marks a genuine demand/supply imbalance — the MOMO arm's gate.
    if warmup is not None and not warmup.empty:
        moves = []
        for _, wd in warmup.groupby(warmup.index.date):
            w_open = float(wd.iloc[0]["open"])
            if w_open:
                moves.append((wd["close"] / w_open - 1).abs().reset_index(drop=True))
        if moves:
            noise = pd.concat(moves, axis=1).mean(axis=1)
            today_open = float(df_today.iloc[0]["open"])
            nv = noise.reindex(range(len(df_today))).ffill().bfill().values
            df_today["noise_up"] = today_open * (1 + nv)
            df_today["noise_dn"] = today_open * (1 - nv)

    # Day-state features (causal: observation window + prior raw sessions
    # + market-level state from the Nifty proxy's first 30 minutes)
    market_obs = None
    try:
        if day == datetime.now(IST).date():
            # live: fetch fresh, never cache a partial day
            nifty_df = fetch_intraday(_NIFTY_TICKER, interval=interval)
            nifty_df = nifty_df[[ts.date() == day for ts in nifty_df.index]]
        else:
            nifty_df = _fetch_day(_NIFTY_TICKER, _NIFTY_SYMBOL, day_str, interval)
        if nifty_df is not None and not nifty_df.empty:
            market_obs = nifty_df[nifty_df.index <= obs_end]
    except Exception:
        pass
    features = compute_day_state(obs_window, warmup, market_obs)
    if features is None:
        return None, "."

    # Counterfactual replay: every arm's signals + single-trade outcome
    arm_frames: dict = {}
    arm_results: dict = {}
    for arm_id, meta in STRATEGY_REGISTRY.items():
        try:
            arm_df = meta["fn"](df_today)
        except Exception:
            continue
        arm_frames[arm_id] = arm_df
        arm_results[arm_id] = sel.replay_arm(arm_df)
    if not arm_frames:
        return None, "x"

    regime_info = classify(obs_window)
    last_obs = obs_window.iloc[-1]
    atr_last = float(last_obs.get("atr", 0))
    vwap_last = float(last_obs.get("vwap", last_obs["close"]))
    close_last = float(last_obs["close"])

    return {
        "day_str": day_str,
        "df_today": df_today,
        "features": features,
        "arm_frames": arm_frames,
        "arm_results": arm_results,
        "regime_info": regime_info,
        "gap_pct": gap_pct,
        "atr_pct": round(atr_last / close_last * 100, 2) if close_last else 0.0,
        "vwap_dev": round((close_last - vwap_last) / vwap_last * 100, 2) if vwap_last else 0.0,
    }, None


def _prepare_symbol_day(
    symbol: str,
    day: date,
    interval: str,
    force_strategy,
    enabled_strategies,
    regime_stats: dict,
    day_regimes: list[dict],
):
    ctx, mark = _build_day_context(symbol, day, interval)
    if ctx is None:
        return None, mark

    day_str = ctx["day_str"]
    regime_info = ctx["regime_info"]
    regime = regime_info["regime"]
    confidence = round(max(regime_info["trend_prob"], regime_info["sideways_prob"], regime_info["highvol_prob"]) * 100)
    regime_stats[regime]["days"] += 1

    # Record today's counterfactual outcomes for future selection.
    # choose() only reads rows with date < today, so this never leaks forward.
    sel.record_day(day_str, symbol, ctx["features"], ctx["arm_results"])

    # ── The decision: best arm conditional on today's day-state ──────────────
    if force_strategy:
        strategy_id = force_strategy.upper()
        decision = {"arm": strategy_id, "expectancy": {}, "reason": "forced"}
    else:
        decision = sel.choose(ctx["features"], day_str, allowed_arms=enabled_strategies)
        strategy_id = decision["arm"]

    if strategy_id == sel.NO_TRADE or strategy_id not in ctx["arm_frames"]:
        df_signals = ctx["df_today"].copy()
        df_signals["signal"] = 0
        strategy_id = sel.NO_TRADE
        strategy_name = "No Trade"
    else:
        df_signals = ctx["arm_frames"][strategy_id]
        strategy_name = _strategy_meta_name(strategy_id, strategy_id)

    prepared = PreparedSymbolDay(
        symbol=symbol,
        trade_date=day_str,
        regime_info=regime_info,
        strategy_id=strategy_id,
        strategy_name=strategy_name,
        confidence=confidence,
        atr_pct=ctx["atr_pct"],
        vwap_dev=ctx["vwap_dev"],
        df_signals=df_signals,
        gap_pct=ctx["gap_pct"],
        decision=decision,
    )
    day_regimes.append(
        {
            "date": day_str,
            "symbol": symbol.replace(".NS", ""),
            "regime": regime,
            "confidence": confidence,
            "adx": regime_info["adx"],
            "atr_pct": ctx["atr_pct"],
            "vwap_dev": ctx["vwap_dev"],
            "gap_pct": ctx["gap_pct"],
            "strategy": strategy_name,
            "expectancy": decision.get("expectancy", {}),
            "score": decision.get("score", {}),
            "risk": decision.get("risk", {}),
            "decision_reason": decision.get("reason", ""),
        }
    )
    return prepared, None


def _record_scan_day(symbols: list[str], day: date, interval: str) -> dict:
    """
    Build day contexts for every symbol, apply cross-sectional in-play ranks,
    and record arm_history rows for the day. Returns {symbol: ctx} for symbols
    with usable data. Idempotent per (symbol, day).
    """
    day_str = day.strftime("%Y-%m-%d")
    ctxs: dict = {}
    for symbol in symbols:
        ctx, _ = _build_day_context(symbol, day, interval)
        if ctx is not None:
            ctxs[symbol] = ctx
    apply_cross_sectional_ranks({s: c["features"] for s, c in ctxs.items()})
    for symbol in symbols:
        if sel.has_day(day_str, symbol):
            continue
        if symbol in ctxs:
            sel.record_day(day_str, symbol, ctxs[symbol]["features"], ctxs[symbol]["arm_results"])
        else:
            sel.record_no_data(day_str, symbol)
    return ctxs


def _scan_symbol_list(user_symbols: list[str]) -> list[str]:
    """Scan universe ∪ user's symbols, normalized to the cache's SYM.NS keys."""
    syms = {s if s.endswith(".NS") else f"{s}.NS" for s in user_symbols}
    syms |= {f"{s}.NS" for s in SCAN_UNIVERSE}
    return sorted(syms)


def _prepare_scan_day(
    scan_syms: list[str],
    day: date,
    interval: str,
    enabled_strategies,
    max_positions: int,
    regime_stats: dict,
    day_regimes: list[dict],
) -> list[PreparedSymbolDay]:
    """
    Cross-sectional mode: scan the whole universe at 9:45, record every
    symbol's counterfactuals, then trade only the selector's top in-play picks.
    """
    day_str = day.strftime("%Y-%m-%d")
    ctxs = _record_scan_day(scan_syms, day, interval)
    if not ctxs:
        return []

    plan = sel.choose_day(
        {s: c["features"] for s, c in ctxs.items()},
        day_str,
        allowed_arms=enabled_strategies,
        top_n=max_positions + 2,
    )

    prepared_days: list[PreparedSymbolDay] = []
    for pick in plan["picks"]:
        symbol = pick["symbol"]
        ctx = ctxs[symbol]
        arm = pick["arm"]
        if arm not in ctx["arm_frames"]:
            continue
        regime_info = ctx["regime_info"]
        confidence = round(
            max(regime_info["trend_prob"], regime_info["sideways_prob"], regime_info["highvol_prob"]) * 100
        )
        regime_stats[regime_info["regime"]]["days"] += 1
        prepared_days.append(
            PreparedSymbolDay(
                symbol=symbol,
                trade_date=day_str,
                regime_info=regime_info,
                strategy_id=arm,
                strategy_name=_strategy_meta_name(arm, arm),
                confidence=confidence,
                atr_pct=ctx["atr_pct"],
                vwap_dev=ctx["vwap_dev"],
                df_signals=ctx["arm_frames"][arm],
                gap_pct=ctx["gap_pct"],
                decision=pick["decision"],
            )
        )
        day_regimes.append(
            {
                "date": day_str,
                "symbol": symbol.replace(".NS", ""),
                "regime": regime_info["regime"],
                "confidence": confidence,
                "adx": regime_info["adx"],
                "atr_pct": ctx["atr_pct"],
                "vwap_dev": ctx["vwap_dev"],
                "gap_pct": ctx["gap_pct"],
                "strategy": _strategy_meta_name(arm, arm),
                "expectancy": pick["decision"].get("expectancy", {}),
                "score": pick["decision"].get("score", {}),
                "risk": pick["decision"].get("risk", {}),
                "decision_reason": f"in play ({len(plan['in_play'])}/{plan['n_scanned']} scanned): "
                + pick["decision"].get("reason", ""),
            }
        )
    if not plan["picks"]:
        day_regimes.append(
            {
                "date": day_str,
                "symbol": "SCAN",
                "regime": "sideways",
                "confidence": 0,
                "adx": 0.0,
                "atr_pct": 0.0,
                "vwap_dev": 0.0,
                "gap_pct": 0.0,
                "strategy": "No Trade",
                "expectancy": {},
                "score": {},
                "risk": {},
                "decision_reason": f"no in-play pick cleared the margin "
                f"({len(plan['in_play'])}/{plan['n_scanned']} in play)",
            }
        )
    return prepared_days


def ensure_history(symbols: list[str], before: str, interval: str, n_days: int = 60) -> int:
    """
    Bootstrap the arm-history table with counterfactual replays for up to
    n_days trading days strictly before `before`. Idempotent — already-recorded
    (symbol, day) pairs are skipped. Returns the number of new day-states added.

    Cross-sectional ranks need every symbol's context for the day, so a day is
    rebuilt whole if any symbol is missing.
    """
    sel.init_history()
    added = 0
    cur = datetime.strptime(before, "%Y-%m-%d").date() - timedelta(days=1)
    scanned = 0
    while scanned < n_days and cur > date(2023, 1, 1):
        if cur.weekday() >= 5 or cur.strftime("%Y-%m-%d") in _NSE_HOLIDAYS:
            cur -= timedelta(days=1)
            continue
        scanned += 1
        day_str = cur.strftime("%Y-%m-%d")
        missing = [s for s in symbols if not sel.has_day(day_str, s)]
        if missing:
            ctxs = _record_scan_day(symbols, cur, interval)
            added += len([s for s in missing if s in ctxs])
        cur -= timedelta(days=1)
    return added


# ── Live mode (signals only) ──────────────────────────────────────────────────


def live_decision(symbols: list[str], interval: str = "5m", history_days: int = 60) -> dict:
    """
    Run the exact same decision pipeline on today's live data.

    Timeline (IST):
        before 9:15  → pre_open (nothing to do)
        9:15–9:45    → observing (measuring day-state, trading forbidden)
        after 9:45   → decision per symbol: chosen arm + entry/SL/TP if a
                       signal has fired on the bars so far.

    Signals only — no orders are placed. Today's partial bars are fetched
    fresh and never cached or recorded into selector history.
    """
    now = datetime.now(IST)
    today = now.date()
    day_str = today.strftime("%Y-%m-%d")
    base = {"date": day_str, "time": now.strftime("%H:%M IST")}

    if today.weekday() >= 5 or day_str in _NSE_HOLIDAYS:
        return {
            **base,
            "status": "market_closed",
            "detail": "Market holiday/weekend — use a past date to backtest.",
            "symbols": [],
        }

    open_t = now.replace(hour=9, minute=15, second=0, microsecond=0)
    obs_end = now.replace(hour=9, minute=45, second=0, microsecond=0)
    close_t = now.replace(hour=15, minute=30, second=0, microsecond=0)

    if now < open_t:
        return {
            **base,
            "status": "pre_open",
            "detail": "Market opens 9:15 IST. The algorithm observes 9:15–9:45, then decides.",
            "symbols": [],
        }

    # Learn from history through yesterday before deciding anything today.
    sel.init_history()
    ensure_history(symbols, day_str, interval, n_days=history_days)

    if now < obs_end:
        mins = int((obs_end - now).total_seconds() // 60)
        return {
            **base,
            "status": "observing",
            "detail": f"Observation window 9:15–9:45 — decision in {mins} min.",
            "symbols": [],
        }

    results = []
    for symbol in symbols:
        entry_res = {"symbol": symbol.replace(".NS", "")}
        try:
            ticker = get_ticker(symbol)
            df = fetch_intraday(ticker, interval=interval)
            df = df[[ts.date() == today for ts in df.index]]
            # Drop the still-forming last bar (its 5m window includes "now")
            bar_min = int(interval.rstrip("m")) if interval.endswith("m") else 5
            if not df.empty and (now - df.index[-1]).total_seconds() < bar_min * 60:
                df = df.iloc[:-1]
        except Exception as e:
            results.append({**entry_res, "status": "no_data", "detail": str(e)})
            continue

        ctx, _ = _build_day_context(symbol, today, interval, df=df)
        if ctx is None:
            results.append({**entry_res, "status": "no_data", "detail": "insufficient bars for today yet"})
            continue

        decision = sel.choose(ctx["features"], day_str)
        arm = decision["arm"]
        out = {
            **entry_res,
            "status": "decided",
            "arm": arm,
            "arm_name": _strategy_meta_name(arm, "No Trade"),
            "expectancy": decision["expectancy"],
            "score": decision.get("score", {}),
            "risk": decision.get("risk", {}),
            "reason": decision["reason"],
            "regime": ctx["regime_info"]["regime"],
            "features": ctx["features"],
            "signal": None,
        }
        if arm in ctx["arm_frames"]:
            frame = ctx["arm_frames"][arm]
            sig_rows = frame[frame["signal"] != 0]
            if not sig_rows.empty:
                row = sig_rows.iloc[0]
                side = int(row["signal"])
                out["signal"] = {
                    "side": "LONG" if side == 1 else "SHORT",
                    "time": sig_rows.index[0].astimezone(IST).strftime("%H:%M"),
                    "entry": round(float(row["close"]), 2),
                    "sl": round(float(row["sl_hint"]), 2)
                    if not math.isnan(float(row.get("sl_hint", float("nan"))))
                    else None,
                    "tp": round(float(row["tp_hint"]), 2)
                    if not math.isnan(float(row.get("tp_hint", float("nan"))))
                    else None,
                    "last_price": round(float(frame.iloc[-1]["close"]), 2),
                }
        results.append(out)

    return {**base, "status": "open" if now <= close_t else "after_close", "symbols": results}


def _entry_signal_score(prepared: PreparedSymbolDay, row: pd.Series, rel_strength: float) -> tuple:
    """Rank simultaneous candidates. Higher tuple wins."""
    signal = int(row.get("signal", 0))
    direction_bias = rel_strength if signal == 1 else -rel_strength
    decision = prepared.decision or {}
    expectancy = float(decision.get("expectancy", {}).get(prepared.strategy_id, 0.0))
    ml_score = float(decision.get("score", {}).get(prepared.strategy_id, expectancy))
    risk = decision.get("risk", {}).get(prepared.strategy_id, {})
    loss_prob = float(risk.get("loss_prob", 0.5))
    downside = float(risk.get("downside", 0.0))
    body = abs(float(row["close"]) - float(row["open"]))
    rng = max(float(row["high"]) - float(row["low"]), 0.01)
    body_ratio = body / rng
    return (
        round(ml_score, 4),
        round(expectancy, 4),
        round(-loss_prob, 4),
        round(-downside, 4),
        round(direction_bias, 4),
        prepared.confidence,
        round(body_ratio, 4),
        round(prepared.atr_pct, 4),
    )


def _simulate_portfolio_day(
    prepared_days: list[PreparedSymbolDay],
    risk_mgr: RiskManager,
    equity: float,
    market_df: pd.DataFrame,
    nifty_bias: str,
    max_positions: int = 1,
) -> tuple[list[BacktestTrade], float]:
    """Simulate one trading day across all symbols using one pooled account."""
    if not prepared_days:
        return [], equity

    trades: list[BacktestTrade] = []
    cash = equity
    traded_symbols: set[str] = set()
    {p.symbol: p for p in prepared_days}
    all_ts = sorted({ts for p in prepared_days for ts in p.df_signals.index})
    close_bar = (
        all_ts[0].astimezone(IST).replace(hour=_MARKET_CLOSE[0], minute=_MARKET_CLOSE[1], second=0, microsecond=0)
    )

    positions: dict[str, dict] = {}  # symbol → open position

    for ts in all_ts:
        for sym in list(positions.keys()):
            position = positions[sym]
            p = position["prepared"]
            if ts in p.df_signals.index:
                row = p.df_signals.loc[ts]
                price = float(row["close"])
                signal = int(row.get("signal", 0))
                bars_held = position["bars_held"] + 1
                position["bars_held"] = bars_held

                if position["entry_risk"] > 0:
                    if position["side"] == 1:
                        if price - position["entry_price"] >= position["entry_risk"] * _BREAKEVEN_TRIGGER_R:
                            position["sl_price"] = max(position["sl_price"], round(position["entry_price"], 2))
                        if price - position["entry_price"] >= position["entry_risk"] * _TRAIL_TRIGGER_R:
                            trail_ref = max(
                                float(row.get("ema20", position["entry_price"])),
                                float(row.get("vwap", position["entry_price"])),
                            )
                            position["sl_price"] = max(position["sl_price"], round(trail_ref, 2))
                    else:
                        if position["entry_price"] - price >= position["entry_risk"] * _BREAKEVEN_TRIGGER_R:
                            position["sl_price"] = min(position["sl_price"], round(position["entry_price"], 2))
                        if position["entry_price"] - price >= position["entry_risk"] * _TRAIL_TRIGGER_R:
                            trail_ref = min(
                                float(row.get("ema20", position["entry_price"])),
                                float(row.get("vwap", position["entry_price"])),
                            )
                            position["sl_price"] = min(position["sl_price"], round(trail_ref, 2))

                # Ratchet SL along strategy trail levels (e.g. MOMO's band/VWAP trail)
                trailed = False
                if position["side"] == 1 and "trail_long" in row.index:
                    tl = float(row["trail_long"])
                    if not math.isnan(tl) and tl > position["sl_price"]:
                        position["sl_price"] = round(tl, 2)
                    trailed = True
                elif position["side"] == -1 and "trail_short" in row.index:
                    tsh = float(row["trail_short"])
                    if not math.isnan(tsh) and tsh < position["sl_price"]:
                        position["sl_price"] = round(tsh, 2)
                    trailed = True

                exit_reason = None
                if position["side"] == 1:
                    if price <= position["sl_price"]:
                        exit_reason = "stop_loss"
                    elif price >= position["tp_price"]:
                        exit_reason = "take_profit"
                    elif ts >= close_bar:
                        exit_reason = "eod"
                elif price >= position["sl_price"]:
                    exit_reason = "stop_loss"
                elif price <= position["tp_price"]:
                    exit_reason = "take_profit"
                elif ts >= close_bar:
                    exit_reason = "eod"

                if exit_reason:
                    if exit_reason == "stop_loss":
                        # trail stops evaluate on close → fill at close (conservative);
                        # hard stops are resting orders → fill at the level
                        fill = price if trailed else position["sl_price"]
                    elif exit_reason == "take_profit":
                        fill = position["tp_price"]
                    else:
                        fill = price
                    gross = position["side"] * (fill - position["entry_price"]) * position["qty"]
                    costs = _trade_costs(position["qty"], position["entry_price"], fill)
                    pnl = round(gross - costs, 2)
                    pnl_pct = round(pnl / (position["entry_price"] * position["qty"]) * 100, 2)
                    cash += position["qty"] * position["entry_price"] + gross
                    del positions[sym]
                    equity = round(cash + sum(o["qty"] * o["entry_price"] for o in positions.values()), 2)
                    risk_mgr.record_trade(pnl, ts)
                    risk_mgr.set_capital(equity)
                    trades.append(
                        BacktestTrade(
                            date=p.trade_date,
                            symbol=p.symbol,
                            regime=p.regime_info["regime"],
                            strategy=p.strategy_name,
                            entry_time=str(position["entry_time"]),
                            exit_time=str(ts),
                            entry_price=round(position["entry_price"], 2),
                            exit_price=round(price, 2),
                            sl_price=position["sl_price"],
                            tp_price=position["tp_price"],
                            shares=position["qty"],
                            pnl=pnl,
                            pnl_pct=pnl_pct,
                            exit_reason=exit_reason,
                            entry_reason=f"regime={p.regime_info['regime']}",
                            confidence=p.confidence,
                            side="LONG" if position["side"] == 1 else "SHORT",
                        )
                    )
                    traded_symbols.add(p.symbol)

        if len(positions) >= max_positions or ts >= close_bar:
            continue

        candidates = []
        for p in prepared_days:
            if p.symbol in traded_symbols or p.symbol in positions or ts not in p.df_signals.index:
                continue
            row = p.df_signals.loc[ts]
            signal = int(row.get("signal", 0))
            if signal == 0:
                continue

            # No directional vetoes here: the selector's expectancy estimates come
            # from replays without them — execution must match what was estimated.
            # Relative strength vs Nifty is still computed for ranking candidates.
            rel_strength = 0.0
            if market_df is not None and not market_df.empty:
                try:
                    nearest_idx = market_df.index.get_indexer([ts], method="nearest")[0]
                    nifty_row = market_df.iloc[nearest_idx]
                    market_open = float(market_df.iloc[0]["open"])
                    market_move_pct = (
                        ((float(nifty_row["close"]) - market_open) / market_open * 100) if market_open else 0.0
                    )
                    stock_open = float(p.df_signals.iloc[0]["open"])
                    price = float(row["close"])
                    stock_move_pct = ((price - stock_open) / stock_open * 100) if stock_open else 0.0
                    rel_strength = stock_move_pct - market_move_pct
                except Exception:
                    pass

            allowed, _ = risk_mgr.can_trade(ts)
            if not allowed:
                continue

            price = float(row["close"])
            atr = float(row["atr"])
            # Use strategy-provided SL/TP hints when available (e.g. ORB injects
            # OR-range-based levels). Fall back to ATR-based for all other strategies.
            sl_hint = row.get("sl_hint", float("nan"))
            tp_hint = row.get("tp_hint", float("nan"))
            if not math.isnan(sl_hint) and not math.isnan(tp_hint):
                sl, tp = float(sl_hint), float(tp_hint)
            else:
                sl = risk_mgr.sl_price(price, atr, signal)
                tp = risk_mgr.tp_price(price, atr, signal)
            qty = risk_mgr.position_size(cash, price, sl)
            # Conviction-scaled sizing: stronger predicted edge risks more, but
            # high modeled loss-risk dials size back before the hard NO_TRADE gate.
            exp_map = p.decision.get("expectancy", {}) if p.decision else {}
            score_map = p.decision.get("score", {}) if p.decision else {}
            risk_map = p.decision.get("risk", {}) if p.decision else {}
            best_exp = exp_map.get(p.strategy_id, 0.0)
            best_score = score_map.get(p.strategy_id, best_exp)
            loss_prob = risk_map.get(p.strategy_id, {}).get("loss_prob", 0.5)
            factor = max(0.4, min(1.5, max(best_score, 0.0) / 0.18))
            factor *= max(0.55, 1 - max(loss_prob - 0.45, 0.0))
            qty = min(int(qty * factor), int(cash // price)) if price else 0
            if qty <= 0 or cash < qty * price:
                continue
            candidates.append(
                {
                    "prepared": p,
                    "row": row,
                    "signal": signal,
                    "price": price,
                    "sl": sl,
                    "tp": tp,
                    "qty": qty,
                    "rel_strength": rel_strength,
                    "score": _entry_signal_score(p, row, rel_strength),
                }
            )

        if not candidates:
            continue

        # Fill available slots in score order. Sizing used the cash available
        # when candidates were built, so re-clamp later fills to remaining cash.
        for best in sorted(candidates, key=lambda c: c["score"], reverse=True):
            if len(positions) >= max_positions:
                break
            qty = min(best["qty"], int(cash // best["price"])) if best["price"] else 0
            if qty <= 0:
                continue
            cash -= qty * best["price"]
            positions[best["prepared"].symbol] = {
                "prepared": best["prepared"],
                "side": best["signal"],
                "qty": qty,
                "entry_price": best["price"],
                "sl_price": best["sl"],
                "tp_price": best["tp"],
                "entry_time": ts,
                "entry_risk": abs(best["price"] - best["sl"]),
                "bars_held": 0,
            }

    return trades, equity


# ── Core runner ───────────────────────────────────────────────────────────────


def run(
    symbols: list[str],
    start_date: str,
    end_date: str,
    capital: float = 100_000,
    risk_config: RiskConfig = None,
    interval: str = "5m",
    save_to_db: bool = True,
    force_strategy=None,  # override strategy id (for experimentation)
    enabled_strategies=None,  # restrict the selector's arms (None = all)
    history_days: int = 60,  # bootstrap depth for the selector's table
    scan_universe: bool = False,  # cross-sectional "stocks in play" mode
    max_positions: int = 3,  # concurrent positions in scan mode
) -> dict:
    """
    Walk-forward backtest over a date range and list of symbols.

    For each day, 3 prior trading days are fetched to warm up ADX/ATR/EMA.
    Before the loop, the selector's arm-history table is bootstrapped with
    counterfactual replays of the `history_days` trading days preceding
    start_date, so even a 1-day backtest decides from a learned table.
    """
    if save_to_db:
        init_db()
    sel.init_history()

    scan_syms = _scan_symbol_list(symbols) if scan_universe else None

    if not force_strategy:
        boot = ensure_history(scan_syms if scan_universe else symbols, start_date, interval, n_days=history_days)
        if boot:
            print(f"  Bootstrapped {boot} day-states into selector history")

    all_trades: list[BacktestTrade] = []
    regime_stats: dict = {
        "trending": {"trades": 0, "wins": 0, "pnl": 0.0, "days": 0},
        "sideways": {"trades": 0, "wins": 0, "pnl": 0.0, "days": 0},
        "high_vol": {"trades": 0, "wins": 0, "pnl": 0.0, "days": 0},
    }
    daily_pnl: dict = {}
    day_regimes: list[dict] = []

    trading_days = _trading_days(start_date, end_date)
    print(f"\n  Backtest: {len(symbols)} symbols × {len(trading_days)} days  [{start_date} → {end_date}]\n")

    account_equity = float(capital)
    risk_mgr = RiskManager(account_equity, risk_config)
    print(f"  Symbols: {', '.join(symbols)}", end="", flush=True)

    for day in trading_days:
        day_str = day.strftime("%Y-%m-%d")
        risk_mgr.set_capital(account_equity)
        risk_mgr.reset_daily()

        prepared_days: list[PreparedSymbolDay] = []
        day_marks = []
        if scan_universe:
            prepared_days = _prepare_scan_day(
                scan_syms=scan_syms,
                day=day,
                interval=interval,
                enabled_strategies=enabled_strategies,
                max_positions=max_positions,
                regime_stats=regime_stats,
                day_regimes=day_regimes,
            )
        else:
            for symbol in symbols:
                prepared, mark = _prepare_symbol_day(
                    symbol=symbol,
                    day=day,
                    interval=interval,
                    force_strategy=force_strategy,
                    enabled_strategies=enabled_strategies,
                    regime_stats=regime_stats,
                    day_regimes=day_regimes,
                )
                day_marks.append(mark or "·")
                if prepared is not None:
                    prepared_days.append(prepared)

        nifty_df = _fetch_nifty_day(day_str, interval)
        nifty_daily_bias = _nifty_daily_bias(day_str)
        day_trades, account_equity = _simulate_portfolio_day(
            prepared_days=prepared_days,
            risk_mgr=risk_mgr,
            equity=account_equity,
            market_df=nifty_df,
            nifty_bias=nifty_daily_bias,
            max_positions=max_positions if scan_universe else 1,
        )
        all_trades.extend(day_trades)

        day_pnl = sum(t.pnl for t in day_trades)
        daily_pnl[day_str] = day_pnl

        for t in day_trades:
            rs = regime_stats[t.regime]
            rs["trades"] += 1
            rs["pnl"] += t.pnl
            if t.pnl > 0:
                rs["wins"] += 1

        marker = "+" if day_pnl > 0 else ("-" if day_pnl < 0 else ".")
        print(f"{marker}", end="", flush=True)

    print()

    if save_to_db and all_trades:
        save_trades([_trade_to_dict(t) for t in all_trades])

    return _build_summary(all_trades, daily_pnl, regime_stats, capital, day_regimes)


# ── Utilities ─────────────────────────────────────────────────────────────────


def _fetch_day(ticker: str, symbol: str, day_str: str, interval: str):
    """Try SQLite cache → Upstox → yfinance (in that order)."""
    cached = load_candles(symbol, day_str, interval)
    if cached is not None:
        return cached
    if os.getenv("ALGO_CACHE_ONLY") == "1":
        return None

    # Try Upstox first (2 years of history vs yfinance's 60 days)
    try:
        from upstox_data import fetch_upstox, is_configured

        if is_configured():
            end_buf = (datetime.strptime(day_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            clean = symbol.replace(".NS", "")
            df = fetch_upstox(clean, start=day_str, end=end_buf, interval=interval)
            if not df.empty:
                save_candles(symbol, interval, df)
                return df
    except Exception:
        pass  # fall through to yfinance

    # Fallback: yfinance (limited to last 60 days for intraday)
    try:
        end_buf = (datetime.strptime(day_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        df, _ = fetch(ticker, start=day_str, end=end_buf, interval=interval)
        if not df.empty:
            save_candles(symbol, interval, df)
        return df if not df.empty else None
    except Exception:
        return None


# Use NIFTYBEES as the Nifty 50 proxy for both intraday and daily market bias.
# Upstox can serve its full 1-minute history, unlike Yahoo's old 5-minute ^NSEI.
_NIFTY_TICKER = "NIFTYBEES.NS"
_NIFTY_SYMBOL = "NIFTYBEES"


_nifty_daily_cache: dict = {}


def _nifty_daily_bias(day_str: str) -> str:
    """
    Returns 'bullish', 'bearish', or 'neutral' based on whether the Nifty proxy
    closed higher or lower than 3 trading days ago.

    'bearish' → block new long ORB entries for the day (market in short-term downtrend).
    'bullish' → block new short ORB entries.
    'neutral' → allow both directions (not enough data or inconclusive).
    """
    global _nifty_daily_cache
    if day_str in _nifty_daily_cache:
        return _nifty_daily_cache[day_str]

    if os.getenv("ALGO_CACHE_ONLY") == "1":
        _nifty_daily_cache[day_str] = "neutral"
        return "neutral"

    try:
        end_buf = (datetime.strptime(day_str, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        start_buf = (datetime.strptime(day_str, "%Y-%m-%d") - timedelta(days=14)).strftime("%Y-%m-%d")
        df = yf.Ticker(_NIFTY_TICKER).history(start=start_buf, end=end_buf, interval="1d", auto_adjust=True)
        if len(df) < 4:
            _nifty_daily_cache[day_str] = "neutral"
            return "neutral"
        closes = df["Close"].values
        today_close = closes[-1]
        three_ago = closes[-4]  # 3 sessions ago
        bias = "bullish" if today_close > three_ago else "bearish"
        _nifty_daily_cache[day_str] = bias
        return bias
    except Exception:
        _nifty_daily_cache[day_str] = "neutral"
        return "neutral"


def _fetch_nifty_day(day_str: str, interval: str) -> pd.DataFrame:
    """
    Fetch Nifty proxy 5m bars for the given day and compute VWAP.
    Used as a market-direction filter: trade a stock only when Nifty
    is on the same side of its own VWAP as the intended trade direction.
    Returns None if data is unavailable (filter is skipped gracefully).
    """
    df = _fetch_day(_NIFTY_TICKER, _NIFTY_SYMBOL, day_str, interval)
    if df is None or df.empty:
        return None
    df = df.copy()
    if df["volume"].sum() > 0:
        # ETF or liquid instrument — compute proper VWAP
        from indicators import vwap as _vwap

        df["vwap"] = _vwap(df)
    else:
        # Index (^NSEI has no volume) — EMA(20) serves as the neutral reference.
        # close > EMA → bullish bias; same directional signal as VWAP, no volume needed.
        df["vwap"] = df["close"].ewm(span=20, adjust=False).mean()
    return df


def _fetch_warmup(ticker: str, symbol: str, day: date, interval: str, n_days: int = 3):
    """
    Fetch n_days of prior-session candles for indicator warm-up.
    Returns a concatenated DataFrame (oldest→newest) or None.
    ADX(14) requires ~128 bars to converge; 3×75=225 bars is sufficient.
    """
    frames = []
    cur = day - timedelta(days=1)
    limit = n_days * 5  # scan up to 5× days to skip weekends/holidays

    while len(frames) < n_days and limit > 0:
        limit -= 1
        if cur.weekday() >= 5 or cur.strftime("%Y-%m-%d") in _NSE_HOLIDAYS:
            cur -= timedelta(days=1)
            continue
        df = _fetch_day(ticker, symbol, cur.strftime("%Y-%m-%d"), interval)
        if df is not None and len(df) > 5:
            frames.append(df)
        cur -= timedelta(days=1)

    if not frames:
        return None
    return pd.concat(list(reversed(frames)))  # oldest first


def _trading_days(start: str, end: str) -> list[date]:
    """Weekdays between start and end (inclusive), excluding NSE holidays."""
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    days = []
    cur = s
    while cur <= e:
        if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in _NSE_HOLIDAYS:
            days.append(cur)
        cur += timedelta(days=1)
    return days


def _trade_to_dict(t: BacktestTrade) -> dict:
    return {
        "date": t.date,
        "symbol": t.symbol,
        "regime": t.regime,
        "strategy": t.strategy,
        "entry_time": t.entry_time,
        "exit_time": t.exit_time,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "sl_price": t.sl_price,
        "tp_price": t.tp_price,
        "shares": t.shares,
        "pnl": t.pnl,
        "pnl_pct": t.pnl_pct,
        "exit_reason": t.exit_reason,
        "entry_reason": t.entry_reason,
    }


def _build_summary(trades, daily_pnl, regime_stats, total_capital, day_regimes=None) -> dict:
    if not trades:
        return {
            "trades": [],
            "daily_pnl": {},
            "regime_stats": regime_stats,
            "day_regimes": day_regimes or [],
            "summary": {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "pnl": 0.0,
                "return_pct": 0.0,
                "profit_factor": 0.0,
                "expectancy": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "max_drawdown": 0.0,
                "sharpe": 0.0,
                "start_eq": total_capital,
                "end_eq": total_capital,
            },
        }

    total_pnl = sum(t.pnl for t in trades)
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_sum = sum(t.pnl for t in wins)
    loss_sum = abs(sum(t.pnl for t in losses))

    n = len(trades)
    wr = len(wins) / n if n else 0
    avg_w = (win_sum / len(wins)) if wins else 0.0
    avg_l = (loss_sum / len(losses)) if losses else 0.0
    expectancy = round(wr * avg_w - (1 - wr) * avg_l, 2)

    for rs in regime_stats.values():
        rs["win_rate"] = round(rs["wins"] / rs["trades"] * 100, 1) if rs["trades"] else 0

    if len(daily_pnl) >= 5:
        sorted_days = sorted(daily_pnl.keys())
        daily_returns = [daily_pnl[d] / total_capital for d in sorted_days]
        mean_r = np.mean(daily_returns)
        std_r = np.std(daily_returns)
        sharpe = round((mean_r / std_r) * np.sqrt(252), 2) if std_r > 0 else 0.0
    else:
        sharpe = 0.0  # not enough days for a meaningful estimate

    eq = total_capital
    peak = total_capital
    max_dd = 0.0
    for d in sorted(daily_pnl.keys()):
        eq += daily_pnl[d]
        peak = max(peak, eq)
        dd = (eq - peak) / peak * 100
        max_dd = min(max_dd, dd)

    return {
        "trades": trades,
        "daily_pnl": daily_pnl,
        "regime_stats": regime_stats,
        "day_regimes": day_regimes or [],
        "summary": {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
            "pnl": round(total_pnl, 2),
            "return_pct": round(total_pnl / total_capital * 100, 2),
            "profit_factor": round(win_sum / loss_sum, 2) if loss_sum else 99.99,
            "expectancy": expectancy,
            "avg_win": round(avg_w, 2),
            "avg_loss": round(-avg_l, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe": sharpe,
            "start_eq": total_capital,
            "end_eq": round(total_capital + total_pnl, 2),
        },
    }
