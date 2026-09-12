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


"""Opt-in orchestrator for comparison-only multi-horizon scanning."""


from typing import TYPE_CHECKING

import pandas as pd

from .comparison import update_summary
from .data_health import evaluate as evaluate_data_health
from .features import latest_features
from .lifecycle import record
from .market_context import load_context
from .paper_lifecycle import update as update_paper_lifecycle
from .scoring import score
from .trade_levels import build_levels

if TYPE_CHECKING:
    from pathlib import Path


def run_shadow(
    prices: pd.DataFrame,
    db_path: str | Path,
    baseline_symbols: list[str] | None = None,
    comparison_state_path: str | Path | None = None,
    paper_state_path: str | Path | None = None,
) -> dict:
    """Run the upgrade beside baseline and return data only; never sends Telegram."""
    features = latest_features(prices)
    health = evaluate_data_health(db_path, features)
    context = load_context(db_path, features)
    scored = score(
        features,
        context.get("benchmark_returns"),
        context.get("regime", "AWAITING_DATA"),
        set(health["blocked_symbols"]),
    )
    if scored.empty:
        return {"mode": "SHADOW", "candidates": [], "eligible": 0, "qualified": 0, "comparison": {}}
    completed_dates = pd.to_datetime(prices["trade_date"]).dropna().sort_values().unique()
    prior_scored = pd.DataFrame()
    if len(completed_dates) >= 2:
        prior_prices = prices[pd.to_datetime(prices["trade_date"]) < completed_dates[-1]]
        prior_features = latest_features(prior_prices)
        prior_context = load_context(db_path, prior_features)
        prior_health = evaluate_data_health(db_path, prior_features)
        prior_scored = score(
            prior_features,
            prior_context.get("benchmark_returns"),
            prior_context.get("regime", "AWAITING_DATA"),
            set(prior_health["blocked_symbols"]),
        )
    observed = record(db_path, scored, prior_scored)
    # SQLite round-trips INTEGER flags, so make the selection explicitly
    # boolean rather than relying on pandas label-vs-mask inference.
    # Lifecycle storage serializes confirmation lists for SQLite; join feature
    # values back only by the stable session/symbol identity.
    feature_columns = [
        column for column in scored.columns if column not in observed.columns or column.startswith("score_")
    ]
    enriched = observed.merge(
        scored[["as_of_date", "symbol", *feature_columns]],
        on=["as_of_date", "symbol"],
        how="left",
        suffixes=("", "_feature"),
    )
    candidates = (
        enriched[enriched["qualified"].astype(bool)]
        .sort_values(["primary_score", "symbol"], ascending=[False, True])
        .copy()
    )
    candidates["trade_levels"] = candidates.apply(lambda row: build_levels(row.to_dict()), axis=1)
    payload = {
        "mode": "SHADOW",
        "as_of_date": str(scored["as_of_date"].iloc[0]),
        "eligible": int(scored["eligible"].sum()),
        "qualified": int(scored["qualified"].sum()),
        "candidates": candidates.to_dict(orient="records"),
        "comparison": {
            "observed_symbols": len(scored),
            "principal_buckets": scored["principal_bucket"].value_counts().to_dict(),
        },
        "market_context": context,
        "data_health": health,
    }
    if comparison_state_path:
        payload["comparison_summary"] = update_summary(
            comparison_state_path, payload["as_of_date"], baseline_symbols or [], payload["candidates"]
        )
    if paper_state_path:
        payload["paper_lifecycle"] = update_paper_lifecycle(
            paper_state_path, payload["as_of_date"], payload["candidates"], enriched.to_dict(orient="records")
        )
    return payload
