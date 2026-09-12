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


"""Monthly V2 model-portfolio review and one Telegram summary."""

from dataclasses import asdict, dataclass
from datetime import date
from typing import TYPE_CHECKING

import pandas as pd

from .database import V2Database
from .horizon_promotion import PromotionDecision, apply_monthly_promotions
from .portfolio_performance import PortfolioSnapshot, build_portfolio_snapshot
from .portfolio_risk import PortfolioConfig
from .portfolio_store import PortfolioStore

if TYPE_CHECKING:
    from pathlib import Path

HORIZON_LABELS = {
    "SWING_1_3M": "Swing (1-3M)",
    "POSITIONAL_3_6M": "Positional (3-6M)",
    "POSITIONAL_6_12M": "Long-term (6-12M)",
}


@dataclass(frozen=True)
class MonthlyPortfolioReview:
    review_date: str
    snapshot: PortfolioSnapshot
    decisions: tuple[PromotionDecision, ...]
    message: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["snapshot"] = self.snapshot.to_dict()
        return payload


def _money(value: float) -> str:
    return f"Rs {value:,.0f}"


def _action(d: PromotionDecision) -> str:
    if d.promoted and d.target_horizon:
        return f"PROMOTE -> {HORIZON_LABELS[d.target_horizon]}"
    if d.current_horizon == "POSITIONAL_6_12M":
        return "HOLD -> Long-term structure review"
    return "HOLD -> " + d.reasons[0].replace("_", " ")


def render_monthly_portfolio_message(
    review_date: str, snapshot: PortfolioSnapshot, decisions: list[PromotionDecision]
) -> str:
    lines = [
        "MONTHLY V2 PORTFOLIO REVIEW",
        f"Review date: {review_date}",
        "Model portfolio - not broker-account P&L",
        "",
        f"Capital base: {_money(snapshot.capital_base)}",
        f"Model capital committed: {_money(snapshot.committed_capital)}",
        f"Open positions: {snapshot.open_positions} | Pending setups: {snapshot.pending_setups}",
        f"Realised P&L: {_money(snapshot.realised_pnl)}",
        f"Unrealised P&L: {_money(snapshot.unrealised_pnl)}",
        f"Total model P&L: {_money(snapshot.total_pnl)} ({snapshot.portfolio_return_pct:+.2f}%)",
        f"Open risk to stops: {_money(snapshot.open_risk_to_stops)}",
        "",
        "--------------------",
        "HORIZON CARRY-FORWARD REVIEW",
    ]
    if not decisions:
        lines.append("No V2 model positions are eligible for a carry-forward review.")
    for d in decisions[:8]:
        current_r = "-" if d.current_r is None else f"{d.current_r:+.2f}R"
        lines += [
            "",
            f"{d.symbol} | {HORIZON_LABELS.get(d.current_horizon, d.current_horizon)}",
            f"Held: {d.sessions_held} sessions | Current R: {current_r}",
            f"Daily structure: {'Holding' if d.daily_bullish else 'Needs confirmation'} | Weekly: {'Up' if d.weekly_bullish else 'Not aligned'}",
            f"Action: {_action(d)}",
        ]
    lines += [
        "",
        "Promotion never widens a stop or creates an automatic trade.",
        "Daily V2 lifecycle stops and exits remain authoritative.",
    ]
    return "\n".join(lines)


def run_monthly_portfolio_review(
    db_path: str | Path, as_of: date | str | None = None, portfolio_config: PortfolioConfig = PortfolioConfig()
) -> MonthlyPortfolioReview:
    prices = V2Database(db_path).load_prices(end_date=str(as_of) if as_of else None, min_sessions=56)
    if prices.empty:
        msg = "No usable price history for monthly V2 review"
        raise RuntimeError(msg)
    review_date = pd.Timestamp(as_of).date() if as_of else pd.Timestamp(prices["trade_date"].max()).date()
    prices = prices[prices["trade_date"] <= pd.Timestamp(review_date)]
    store = PortfolioStore(db_path)
    store.initialize()
    decisions = apply_monthly_promotions(store, prices, review_date.isoformat())
    snapshot = build_portfolio_snapshot(store.all_positions(), review_date.isoformat(), portfolio_config.capital_base)
    store.save_portfolio_snapshot(snapshot)
    return MonthlyPortfolioReview(
        review_date.isoformat(),
        snapshot,
        tuple(decisions),
        render_monthly_portfolio_message(review_date.isoformat(), snapshot, decisions),
    )
