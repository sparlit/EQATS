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


"""Daily selected-profile scoring and isolated forward PAPER accounting."""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from portfolio_accounting.adapters import ladder_candidates
from portfolio_accounting.service import market_bars
from v2.database import V2Database

from old_nse_hull.discovery import load_market_data
from old_nse_hull.engine import _tradeable_prices
from old_nse_hull.multi_horizon.scoring import HORIZONS, score
from old_nse_hull.multi_horizon.trade_levels import build_levels

from .features import latest_context
from .ledger import advance
from .profile import CONFIG, EXCLUDED_SYMBOLS, PROFILE_ID


def selected_scores(features, blocked=()):
    f = features.copy()
    f["delivery_pct"] = np.nan
    f["delivery_median60"] = np.nan
    d = score(f, blocked_symbols=set(blocked) | set(f.loc[~f.quality_window_ok, "symbol"]))
    delta = 10 * (
        d.volume.ge(1.8 * d.volume_sma20).astype(int)
        - d.volume.ge(1.2 * d.volume_sma20).astype(int)
    )
    delta += 8 * (d.rsi14.between(50, 70).astype(int) - d.rsi14.between(50, 75).astype(int))
    columns = ["score_" + h.lower() for h in HORIZONS]
    d[columns] = d[columns].add(delta, axis=0).round(2)
    d["primary_score"] = d[columns].max(axis=1)
    d["qualified"] = d.eligible & d.primary_score.ge(65) & d.recent_cross
    d["confluence_score"] = d[columns].ge(55).sum(axis=1) / 4 * 100
    d["confirming_horizons"] = [
        [h for h in HORIZONS if row["score_" + h.lower()] >= 55 and h != row["primary_horizon"]]
        for row in d.to_dict("records")
    ]
    d["principal_bucket"] = np.where(d.qualified, "NEWLY_QUALIFIED", "RADAR")
    return d


def run_day(database, prices, ledger_path):
    prices = prices.loc[~prices.symbol.isin(EXCLUDED_SYMBOLS)].copy()
    features, calendar = latest_context(prices)
    if features.empty or len(calendar) < 320:
        raise ValueError("Final Ladder requires at least320 market sessions")
    day = calendar[-1]
    allowed, gate = _tradeable_prices(prices, database.path)
    blocked = set(features.symbol) - set(allowed.symbol)
    scored = selected_scores(features, blocked)
    accepted = scored.loc[scored.qualified].sort_values(
        ["primary_score", "symbol"], ascending=[False, True]
    )
    rows = []
    for r in accepted.to_dict("records"):
        levels = build_levels(r)
        if not levels["eligible_for_paper"]:
            continue
        rows.append(
            {
                "symbol": r["symbol"],
                "close": float(r["close"]),
                "primary_score": float(r["primary_score"]),
                "primary_horizon": r["primary_horizon"],
                "trade_levels": levels,
                "discovery_score": float(r["primary_score"]),
                "hull_state": "READY",
                "entry_low": levels["entry_trigger"],
                "entry_high": round(levels["entry_trigger"] * 1.03, 2),
                "stop": levels["stop"],
                "target1": levels["target_1"],
                "target2": levels["target_2"],
                "reason": "EMA14/21 recent crossover; score65+; wait for planned entry",
            }
        )
    candidates = ladder_candidates({"candidates": rows})
    bars = market_bars(database, day)
    context = {r["symbol"]: r for r in features.to_dict("records")}
    for symbol, bar in bars.items():
        r = context.get(symbol)
        if not r:
            bar["entry_allowed"] = False
            bar["prior_trend"] = False
            # Held symbol without usable features must be reviewed, not silently left untrailed.
            bar["review_required"] = True
            continue
        bar.update(
            atr=float(r["atr"]) if pd.notna(r["atr"]) else 0.0,
            prior_10_low=float(r["previous_10d_low"]) if pd.notna(r["previous_10d_low"]) else 0.0,
            prior_trend=bool(r["prior_trend"]),
        )
        bar["entry_allowed"] = bool(
            bar["entry_allowed"] and r["quality_window_ok"] and symbol not in blocked
        )
        bar["review_required"] = bool(bar["review_required"] or r["action_review_now"])
    snapshot = advance(
        ledger_path,
        "Momentum Ladder",
        day,
        bars,
        candidates,
        config=CONFIG,
        provenance=PROFILE_ID,
        previous_session=calendar[-2],
    )
    snapshot["strategy_profile"] = PROFILE_ID
    return {
        "system": "MOMENTUM_LADDER_FINAL",
        "strategy_profile": PROFILE_ID,
        "mode": "PAPER",
        "as_of_date": day,
        "eligible": int(scored.eligible.sum()),
        "qualified": len(rows),
        "shortlist": rows,
        "multi_horizon_shadow": {"candidates": rows, "strategy_profile": PROFILE_ID},
        "uniform_portfolio": snapshot,
        "tradeability": gate,
        "policy": {
            "score": 65,
            "ema": [14, 21],
            "expiry_sessions": 5,
            "volume_multiple": 1.8,
            "rsi": [50, 70],
            "trail": "Prior10 low minus0.25ATR after TP1",
            "fixed_tp2_exit": False,
        },
        "note": "New forward PAPER cohort. Previous Ladder ledger retained separately. Daily NSE inputs may differ from historical FYERS inputs.",
    }


def run(database_path, ledger_path, as_of=None):
    database = V2Database(database_path)
    prices = load_market_data(database_path, as_of)
    if prices.empty:
        raise ValueError("No daily data")
    days = sorted(prices.trade_date.dt.strftime("%Y-%m-%d").unique())
    last = None
    if Path(ledger_path).exists():
        with sqlite3.connect(ledger_path) as conn:
            row = conn.execute("SELECT payload FROM ledger WHERE id=1").fetchone()
            if row:
                last = json.loads(row[0])["last_date"]
    if last and last not in days:
        raise ValueError("Ledger date outside restored history; explicit recovery required")
    if last and last > days[-1]:
        raise ValueError("Cannot run older data against final ledger")
    todo = [d for d in days if last and d > last] or [days[-1]]
    for day in todo:
        report = run_day(database, prices.loc[prices.trade_date <= pd.Timestamp(day)], ledger_path)
    return report
