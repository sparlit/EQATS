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


"""Closed-bar Pine Hull core, paper portfolio and Telegram-ready reports.

This module deliberately excludes intraday POC/VAH/VAL, lower-timeframe volume
profile, ZigZag/order-block imports and chart-only visuals.  It never writes to
V2 tables or state files.
"""

import json
from dataclasses import asdict, dataclass
from datetime import date
from math import floor
from pathlib import Path
from uuid import uuid4

import numpy as np
import pandas as pd
from v2.database import V2Database
from v2.indicators import atr, hma, kama, wma
from v2.tradeability import evaluate_tradeability
from v2.tradeability import summarize as summarize_tradeability

from .opportunity_lifecycle import timing_state as lifecycle_timing_state
from .opportunity_lifecycle import weekly_transition

STATE_VERSION = 1


@dataclass(frozen=True)
class PineConfig:
    capital_base: float = 300_000.0
    risk_per_trade_pct: float = 0.01
    max_position_pct: float = 0.20
    max_open_positions: int = 8
    max_new_positions: int = 3
    atr_multiplier: float = 3.5


def _number(value: object, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return parsed if np.isfinite(parsed) else default
    except (TypeError, ValueError):
        return default


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
    relative = gain / loss.replace(0, np.nan)
    return 100.0 - 100.0 / (1.0 + relative)


def _adx(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    atr14 = atr(frame, length).replace(0, np.nan)
    plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr14
    minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr14
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def pine_metrics(frame: pd.DataFrame, *, atr_multiplier: float = 3.5) -> dict[str, float | bool | str]:
    """Return the EOD-safe, fixed-parameter Pine Hull metrics for one symbol."""
    data = frame.sort_values("trade_date").copy().reset_index(drop=True)
    needed = {"open", "high", "low", "close", "volume"}
    if data.empty or needed.difference(data.columns) or len(data) < 300:
        return {"available": False, "state": "INSUFFICIENT_HISTORY", "timing_state": "WEAK", "htf_state": "NEUTRAL"}

    close = pd.to_numeric(data["close"], errors="coerce")
    volume = pd.to_numeric(data["volume"], errors="coerce").fillna(0.0)
    hull_base = wma(close, 55)
    hybrid_hull = 2.0 * wma(hull_base, 27) - wma(hull_base, 55)
    hull_slope = hybrid_hull.diff()
    hma21, hma51 = hma(close, 21), hma(close, 51)
    kama30 = kama(close, 30)
    atr14 = atr(data, 14)
    ema20, ema50, ema200 = (
        close.ewm(span=20, adjust=False).mean(),
        close.ewm(span=50, adjust=False).mean(),
        close.ewm(span=200, adjust=False).mean(),
    )
    rsi14, adx14 = _rsi(close), _adx(data)
    vol_ma = volume.rolling(20, min_periods=20).mean()

    weekly_close = data.set_index(pd.to_datetime(data["trade_date"]))["close"].resample("W-FRI").last().dropna()
    weekly21, weekly51 = hma(weekly_close, 21), hma(weekly_close, 51)
    values = [
        hybrid_hull.iloc[-1],
        hybrid_hull.iloc[-2],
        hma21.iloc[-1],
        hma51.iloc[-1],
        kama30.iloc[-1],
        kama30.iloc[-2],
        atr14.iloc[-1],
    ]
    if any(pd.isna(value) for value in values):
        return {"available": False, "state": "INSUFFICIENT_HISTORY", "timing_state": "WEAK", "htf_state": "NEUTRAL"}

    last_close, last_atr = float(close.iloc[-1]), float(atr14.iloc[-1])
    distance_atr = (last_close - float(hybrid_hull.iloc[-1])) / last_atr if last_atr > 0 else 0.0
    hull_speed = abs(float(hull_slope.iloc[-1])) / max(last_atr, 1.0)
    # KAMA remains diagnostic only. Chop is derived from price/Hull behaviour.
    price_band = (close.tail(20).max() - close.tail(20).min()) / max(last_close, 1.0)
    no_impulse = abs(float(hull_slope.iloc[-1])) < last_atr * 0.08
    band_compressed = price_band < 0.025
    rotational = abs(distance_atr) < 0.4 and abs(float(hull_slope.iloc[-1])) < abs(float(hull_slope.iloc[-2])) * 1.1
    chop = (int(no_impulse) + int(band_compressed)) >= 2
    daily_bullish = last_close > float(hybrid_hull.iloc[-1]) and float(hull_slope.iloc[-1]) > 0.0
    above_hull_5 = close.tail(5).reset_index(drop=True) > hybrid_hull.tail(5).reset_index(drop=True)
    hull_up_5 = hybrid_hull.diff().tail(5)
    hull_slope_improving = bool((hull_up_5 >= 0).sum() >= 2 and hybrid_hull.iloc[-1] >= hybrid_hull.iloc[-3])
    daily_persistent = bool(above_hull_5.sum() >= 3 and hull_slope_improving)
    htf_state, htf_metrics = weekly_transition(weekly21, weekly51)
    weekly_bullish = htf_state == "BULLISH"
    kama_rising = float(kama30.iloc[-1]) > float(kama30.iloc[-2])
    hma_aligned = float(hma21.iloc[-1]) > float(hma51.iloc[-1])
    trend_commitment = abs(float(hull_slope.iloc[-1])) > abs(float(hull_slope.iloc[-2]))
    overextended = distance_atr > 1.25
    volume_ratio = (
        float(volume.iloc[-1] / vol_ma.iloc[-1]) if pd.notna(vol_ma.iloc[-1]) and vol_ma.iloc[-1] > 0 else 0.0
    )
    adx_value = _number(adx14.iloc[-1])
    rsi_value = _number(rsi14.iloc[-1])
    score = 0.0
    score += (
        25
        if last_close > float(ema50.iloc[-1]) and adx_value >= 30
        else 15
        if last_close > float(ema50.iloc[-1]) and adx_value >= 20
        else 8
        if last_close > float(ema50.iloc[-1])
        else 0
    )
    score += 10 if 50 <= rsi_value <= 70 else 0
    score += 10 if volume_ratio > 1.5 else 0
    score += 10 if abs(last_close - float(ema20.iloc[-1])) / max(float(ema20.iloc[-1]), 1.0) <= 0.02 else 0
    score += 5 if volume_ratio <= 1.5 else 0
    score += 5 if not overextended else 0
    score += 5 if last_atr / max(last_close, 1.0) < 0.03 else 0
    score += 10 if 3.0 * last_atr / max(last_close, 1.0) < 0.10 else 0
    score += 10 if float(ema50.iloc[-1]) > float(ema200.iloc[-1]) else 0
    score += 5 if last_close > float(ema200.iloc[-1]) else 0
    score += 5 if daily_bullish else 0
    adx_confirmed = bool(
        adx_value >= 22 or (len(adx14.dropna()) >= 2 and adx_value >= 18 and adx_value > _number(adx14.iloc[-2]))
    )
    ready = bool(
        daily_persistent
        and hma_aligned
        and trend_commitment
        and adx_confirmed
        and not chop
        and not rotational
        and not overextended
        and score >= 75
    )
    state = "READY" if ready else "BLOCKED" if chop or rotational or overextended else "WATCH"
    opportunity_state = lifecycle_timing_state(
        daily_bullish=daily_bullish,
        daily_persistent=daily_persistent,
        hma_aligned=hma_aligned,
        kama_rising=kama_rising,
        trend_commitment=trend_commitment,
        chop=chop,
        rotational=rotational,
        overextended=overextended,
        score=score,
        htf_state=htf_state,
        adx_confirmed=adx_confirmed,
    )
    initial_stop = float(data["high"].rolling(22, min_periods=22).max().iloc[-1]) - last_atr * atr_multiplier
    t2_base = (
        3.0
        if last_atr > float(atr14.rolling(50).mean().iloc[-1]) * 1.15
        else 2.0
        if last_atr < float(atr14.rolling(50).mean().iloc[-1]) * 0.85
        else 2.5
    )
    hull_speed_mult = max(0.8, min(1.4, max(0.5, min(2.0, hull_speed * 10.0))))
    return {
        "available": True,
        "state": state,
        "timing_state": opportunity_state,
        "htf_state": htf_state,
        "score": round(score, 2),
        "daily_bullish": daily_bullish,
        "weekly_bullish": weekly_bullish,
        "daily_persistent": daily_persistent,
        "hull_above_sessions_5": int(above_hull_5.sum()),
        "hull_slope_improving": hull_slope_improving,
        "adx_confirmed": adx_confirmed,
        "hma_aligned": hma_aligned,
        "kama_rising": kama_rising,
        "trend_commitment": trend_commitment,
        "chop": chop,
        "rotational": rotational,
        "overextended": overextended,
        "close": round(last_close, 2),
        "atr14": round(last_atr, 2),
        "hybrid_hull": round(float(hybrid_hull.iloc[-1]), 2),
        "hma21": round(float(hma21.iloc[-1]), 2),
        "hma51": round(float(hma51.iloc[-1]), 2),
        "distance_atr": round(distance_atr, 2),
        "volume_ratio": round(volume_ratio, 2),
        "rsi14": round(rsi_value, 2),
        "adx14": round(adx_value, 2),
        "initial_stop": round(initial_stop, 2),
        "target1": round(last_close + last_atr * 1.5, 2),
        "target2": round(last_close + last_atr * t2_base * hull_speed_mult, 2),
        "trail_base": round(initial_stop, 2),
        **htf_metrics,
    }


def _blank_state(config: PineConfig) -> dict:
    return {
        "version": STATE_VERSION,
        "capital_base": config.capital_base,
        "positions": [],
        "events": [],
        "last_run": None,
    }


def load_state(path: str | Path, config: PineConfig = PineConfig()) -> dict:
    target = Path(path)
    if not target.exists():
        return _blank_state(config)
    try:
        state = json.loads(target.read_text(encoding="utf-8"))
        if state.get("version") != STATE_VERSION:
            msg = "unsupported state version"
            raise ValueError(msg)
        state.setdefault("positions", [])
        state.setdefault("events", [])
        return state
    except (ValueError, json.JSONDecodeError):
        return _blank_state(config)


def save_state(state: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _active(position: dict) -> bool:
    return position.get("state") in {"OPEN", "TRAILING"}


def _allocation(entry: float, stop: float, positions: list[dict], config: PineConfig) -> int:
    active = [position for position in positions if _active(position)]
    if len(active) >= config.max_open_positions or entry <= stop:
        return 0
    used = sum(_number(position.get("entry")) * int(position.get("quantity", 0)) for position in active)
    per_share_risk = entry - stop
    limits = [
        floor(config.capital_base * config.risk_per_trade_pct / per_share_risk),
        floor(config.capital_base * config.max_position_pct / entry),
        floor(max(0.0, config.capital_base - used) / entry),
    ]
    return max(0, min(limits))


def _position_event(state: dict, trade_date: str, position: dict, event: str) -> None:
    state["events"].append(
        {
            "date": trade_date,
            "event": event,
            "trade_id": position["trade_id"],
            "symbol": position["symbol"],
            "state": position["state"],
        }
    )
    state["events"] = state["events"][-1000:]


def _update_position(
    position: dict, frame: pd.DataFrame, metrics: dict, trade_date: str, state: dict, config: PineConfig
) -> None:
    last = frame.sort_values("trade_date").iloc[-1]
    high, low, close = _number(last["high"]), _number(last["low"]), _number(last["close"])
    position["last_price"] = round(close, 2)
    position["htf_weekly_bullish"] = bool(metrics.get("weekly_bullish"))
    position["htf_state"] = str(metrics.get("htf_state", "NEUTRAL"))
    position["timing_state"] = str(metrics.get("timing_state", "WEAK"))
    position["daily_hull_bullish"] = bool(metrics.get("daily_bullish"))
    stop = _number(position["stop"])
    if low <= stop:
        position.update(
            {"state": "CLOSED", "exit_date": trade_date, "exit_price": round(stop, 2), "exit_reason": "TRAILING_STOP"}
        )
        position["realised_pnl"] = round((stop - _number(position["entry"])) * int(position["quantity"]), 2)
        _position_event(state, trade_date, position, "EXIT_STOP")
        return
    if close < _number(metrics["hma51"]) and _number(metrics["hma21"]) <= _number(
        position.get("prior_hma21", metrics["hma21"])
    ):
        position.update(
            {
                "state": "CLOSED",
                "exit_date": trade_date,
                "exit_price": round(close, 2),
                "exit_reason": "HULL_STRUCTURE_EXIT",
            }
        )
        position["realised_pnl"] = round((close - _number(position["entry"])) * int(position["quantity"]), 2)
        _position_event(state, trade_date, position, "EXIT_HULL")
        return
    if high >= _number(position["target1"]):
        position["t1_hit"] = True
    if position.get("t1_hit") and high >= _number(position["target2"]):
        position["t2_hit"] = True
    trail = _number(metrics["trail_base"])
    if position.get("t1_hit"):
        trail = max(trail, _number(position["entry"]))
    if position.get("t2_hit"):
        trail = max(trail, _number(position["target1"]))
    position["stop"] = round(max(stop, trail), 2)
    position["prior_hma21"] = _number(metrics["hma21"])
    position["state"] = "TRAILING" if position["stop"] > _number(position["initial_stop"]) else "OPEN"


def run_daily(
    db_path: str | Path = "nse_scanner.db",
    *,
    state_path: str | Path = "pine_hull_state.json",
    as_of: str | None = None,
    config: PineConfig = PineConfig(),
) -> dict:
    database = V2Database(db_path)
    prices = database.load_prices(end_date=as_of, min_sessions=300)
    if prices.empty:
        msg = "No Pine-compatible daily price history"
        raise RuntimeError(msg)
    trade_date = pd.Timestamp(prices["trade_date"].max()).date().isoformat()
    state = load_state(state_path, config)
    master = database.load_symbol_master(trade_date)
    metadata = {str(row["symbol"]): row.to_dict() for _, row in master.iterrows()} if not master.empty else {}
    restricted = database.load_restricted_symbols(trade_date)
    lifecycle_registry = database.load_lifecycle_registry()
    session_calendar = tuple(sorted(pd.to_datetime(prices["trade_date"]).dt.date.astype(str).unique()))
    all_frames = {str(symbol): frame.sort_values("trade_date").copy() for symbol, frame in prices.groupby("symbol")}
    gateway = {
        symbol: evaluate_tradeability(
            symbol,
            frame,
            market_date=trade_date,
            master_row=metadata.get(symbol),
            restricted_reason=restricted.get(symbol),
            lifecycle_event=lifecycle_registry.get(symbol),
            session_calendar=session_calendar,
            require_metadata=bool(metadata),
        )
        for symbol, frame in all_frames.items()
    }
    frames = {
        symbol: frame
        for symbol, frame in all_frames.items()
        if gateway[symbol].eligible and not gateway[symbol].entry_blocked
    }
    for position in state["positions"]:
        gate = gateway.get(str(position.get("symbol")))
        if _active(position) and gate and (not gate.eligible or gate.entry_blocked):
            position["state"] = "CORPORATE_ACTION_REVIEW"
            position["review_reason"] = gate.reason_code
            position["successor_symbol"] = gate.successor_symbol
            _position_event(state, trade_date, position, "CORPORATE_ACTION_REVIEW")
    metrics = {symbol: pine_metrics(frame, atr_multiplier=config.atr_multiplier) for symbol, frame in frames.items()}
    for position in state["positions"]:
        if _active(position) and position["symbol"] in frames:
            _update_position(
                position, frames[position["symbol"]], metrics[position["symbol"]], trade_date, state, config
            )

    active_symbols = {position["symbol"] for position in state["positions"] if _active(position)}
    candidates = []
    for symbol, row in metrics.items():
        if (
            row.get("state") == "READY"
            and symbol not in active_symbols
            and _number(row.get("initial_stop")) < _number(row.get("close"))
        ):
            candidates.append((symbol, row))
    candidates.sort(key=lambda item: (-_number(item[1].get("score")), item[0]))
    created: list[dict] = []
    for symbol, row in candidates[: config.max_new_positions]:
        quantity = _allocation(_number(row["close"]), _number(row["initial_stop"]), state["positions"], config)
        if quantity <= 0:
            continue
        position = {
            "trade_id": f"PINE-{trade_date.replace('-', '')}-{uuid4().hex[:8].upper()}",
            "symbol": symbol,
            "state": "OPEN",
            "entry_date": trade_date,
            "entry": _number(row["close"]),
            "initial_stop": _number(row["initial_stop"]),
            "stop": _number(row["initial_stop"]),
            "target1": _number(row["target1"]),
            "target2": _number(row["target2"]),
            "quantity": quantity,
            "last_price": _number(row["close"]),
            "t1_hit": False,
            "t2_hit": False,
            "prior_hma21": _number(row["hma21"]),
            "realised_pnl": 0.0,
            "htf_weekly_bullish": bool(row["weekly_bullish"]),
            "htf_state": row.get("htf_state", "NEUTRAL"),
            "timing_state": row.get("timing_state", "WEAK"),
            "daily_hull_bullish": bool(row["daily_bullish"]),
            "score": _number(row.get("score")),
        }
        state["positions"].append(position)
        created.append(position)
        _position_event(state, trade_date, position, "ENTRY")

    state["last_run"] = trade_date
    save_state(state, state_path)
    open_positions = [position for position in state["positions"] if _active(position)]
    closed_positions = [position for position in state["positions"] if position.get("state") == "CLOSED"]
    realised = sum(_number(position.get("realised_pnl")) for position in closed_positions)
    unrealised = sum(
        (_number(position.get("last_price")) - _number(position.get("entry"))) * int(position.get("quantity", 0))
        for position in open_positions
    )
    watch = sorted(
        (
            (symbol, row)
            for symbol, row in metrics.items()
            if row.get("timing_state") in {"EARLY", "EXTENDED"} and symbol not in active_symbols
        ),
        key=lambda item: (-_number(item[1].get("score")), item[0]),
    )[:12]
    return {
        "trade_date": trade_date,
        "created": created,
        "watch": [{"symbol": symbol, **row} for symbol, row in watch],
        "positions": state["positions"],
        "open_positions": open_positions,
        "realised_pnl": round(realised, 2),
        "unrealised_pnl": round(unrealised, 2),
        "total_pnl": round(realised + unrealised, 2),
        "evaluated": len(metrics),
        "state_path": str(state_path),
        "tradeability": summarize_tradeability(gateway),
        "corporate_action_reviews": [p for p in state["positions"] if p.get("state") == "CORPORATE_ACTION_REVIEW"],
    }


def _price(value: object) -> str:
    return f"₹{_number(value):,.2f}"


def render_daily_signals(result: dict) -> str:
    created = result["created"]
    watch = result["watch"]
    early_count = sum(1 for row in created if row.get("timing_state") == "EARLY") + sum(
        1 for row in watch if row.get("timing_state") == "EARLY"
    )
    ready_count = sum(1 for row in created if row.get("timing_state") == "READY")
    extended_count = sum(1 for row in watch if row.get("timing_state") == "EXTENDED")
    lines = [
        "📐 PINE HULL — DAILY WATCHLIST",
        "SIMULATED WATCHLIST • NO LIVE ORDERS",
        f"Data: {result['trade_date']} close",
        "Hull55 • HMA21/51 • KAMA30 • ATR14×3.5",
        "",
        f"🟠 EARLY {early_count} | 🟢 READY {ready_count} | 🔴 EXTENDED {extended_count}",
        f"New simulated positions: {len(created)} | Watchlist setups: {len(watch)}",
    ]
    if not created:
        lines.extend(["", "No new simulated position met the confirmed end-of-day rules today."])
    for index, position in enumerate(created, 1):
        badge = {1: "🥇", 2: "🥈", 3: "🥉"}.get(index, f"#{index}")
        timing = str(position.get("timing_state", "READY"))
        lines.extend(
            [
                "",
                "━━━━━━━━━━━━━━━━━━",
                f"{badge} {position['symbol']}",
                f"PINE HULL • {timing.replace('_', ' ')}",
                f"Weekly HTF  {position.get('htf_state', 'NEUTRAL')}",
                "",
                f"Entry       {_price(position['entry'])}",
                f"SL          {_price(position['initial_stop'])}",
                f"T1          {_price(position['target1'])}",
                f"T2          {_price(position['target2'])}",
                "",
                "✓ Daily Hull bullish",
                "✓ HMA21 > HMA51",
                "✓ KAMA30 rising",
                "✓ Trend commitment confirmed",
                "",
                "The simulated entry was recorded after the end-of-day signal.",
            ]
        )
    if watch:
        lines.extend(["", "🟡 PINE WATCH — EARLY / EXTENDED"])
        for item in watch:
            timing = str(item.get("timing_state", "WEAK"))
            if timing == "EARLY":
                action = "watch for HTF confirmation / continued commitment"
            else:
                action = "do not chase; wait for reset toward structure"
            lines.append(
                f"• {item['symbol']} | {timing} | Score {item['score']:.0f} | HTF {item.get('htf_state', 'NEUTRAL')} | {action}"
            )
    return "\n".join(lines)


def render_portfolio_message(result: dict) -> str:
    lines = [
        "📈 PINE HULL — PORTFOLIO",
        "SIMULATED PORTFOLIO • NO LIVE ORDERS",
        f"Data through: {result['trade_date']} close",
        f"Open: {len(result['open_positions'])} | Total result: {_price(result['total_pnl'])}",
        f"Closed-position result: {_price(result['realised_pnl'])} | Open-position result: {_price(result['unrealised_pnl'])}",
        "",
    ]
    if not result["open_positions"]:
        return "\n".join([*lines, "No simulated Pine Hull positions are open."])
    for position in result["open_positions"]:
        return_pct = (
            ((_number(position["last_price"]) / _number(position["entry"])) - 1.0) * 100
            if _number(position["entry"])
            else 0.0
        )
        htf = position.get("htf_state") or ("BULLISH" if position.get("htf_weekly_bullish") else "NEUTRAL")
        timing = position.get("timing_state", "HOLD_TREND")
        lines.extend(
            [
                f"{position['symbol']} — {position['state']} | Timing {timing}",
                f"Entry {_price(position['entry'])} → Close {_price(position['last_price'])} ({return_pct:+.2f}%)",
                f"SL {_price(position['stop'])} | T1 {_price(position['target1'])}{' ✅' if position.get('t1_hit') else ''} | T2 {_price(position['target2'])}{' ✅' if position.get('t2_hit') else ''}",
                f"Weekly trend: {htf}",
                "Action: Hold only while price stays above the current trailing stop.",
                "",
            ]
        )
    return "\n".join(lines).strip()


def render_period_message(state_path: str | Path, *, period: str) -> str:
    state = load_state(state_path)
    positions = state.get("positions", [])
    closed = [position for position in positions if position.get("state") == "CLOSED"]
    active = [position for position in positions if _active(position)]
    realised = sum(_number(position.get("realised_pnl")) for position in closed)
    title = "📅 HULL SCANNER — WEEKLY REVIEW" if period == "weekly" else "📆 HULL SCANNER — MONTHLY REVIEW"
    lines = [
        title,
        "SIMULATED PORTFOLIO REVIEW • NO LIVE ORDERS",
        f"Latest scanner run: {state.get('last_run') or 'No completed run recorded'}",
        f"Open positions: {len(active)} | Closed positions: {len(closed)}",
        f"Result from closed positions: {_price(realised)}",
        "",
    ]
    if active:
        lines.append("Open positions")
        for position in active[:12]:
            entry = _number(position.get("entry"))
            current = _number(position.get("last_price"), entry)
            move = ((current / entry) - 1.0) * 100 if entry else 0.0
            symbol = position["symbol"]
            link = f'<a href="https://www.tradingview.com/chart/?symbol=NSE%3A{symbol}">{symbol}</a>'
            lines.extend(
                [
                    "━━━━━━━━━━━━━━",
                    f"📂 {link} — OPEN POSITION",
                    f"Entry {_price(entry)} → Latest {_price(current)}",
                    f"Price move so far: {move:+.2f}%",
                    f"Protect below: {_price(position['stop'])}",
                    "Next: Continue only while price stays above this level.",
                ]
            )
    else:
        lines.extend(
            ["No simulated positions are open.", "Next: Keep watching until a new entry trigger is confirmed."]
        )
    lines.extend(["", "This is a simulated research portfolio, not investment advice."])
    return "\n".join(lines)
