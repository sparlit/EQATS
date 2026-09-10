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
Runtime learning feedback.

Closes the learn-from-losses loop at trade-close time: turn a just-closed position into a
TradeOutcome, classify it into a lesson, and store it; and mark the lessons that were active
when the trade was opened as successful/unsuccessful based on the result.

The audit found the analyzer/classifier/injector existed but were never called at runtime —
these helpers are the missing wiring. They are failure-isolated: a learning error must never
disrupt trading.
"""


import logging
from typing import TYPE_CHECKING, Any

from src.memory.analyzer import TradeOutcome, compute_outcome

if TYPE_CHECKING:
    from src.memory.classifier import ClassifiedMistake, MistakeClassifier
    from src.memory.database import AgentMemoryDB
    from src.memory.injection import MemoryInjector

logger = logging.getLogger(__name__)


def build_outcome(
    *,
    trade_id: str,
    symbol: str,
    strategy: str,
    regime: str,
    side: str,
    entry_price: float,
    exit_price: float,
    stop_loss: float,
    target_price: float,
    pnl: float,
    pnl_pct: float,
    mae: float = 0.0,
    mfe: float = 0.0,
    hold_minutes: int = 0,
) -> TradeOutcome | None:
    """Build a TradeOutcome from a just-closed position's fields."""
    return compute_outcome(
        {
            "trade_id": trade_id,
            "symbol": symbol,
            "strategy": strategy,
            "regime": regime,
            "side": side,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "stop_loss": stop_loss,
            "target_price": target_price,
            "profit_loss": pnl,
            "profit_loss_pct": pnl_pct,
            "mae": mae,
            "mfe": mfe,
            "hold_duration_minutes": hold_minutes,
        }
    )


def learn_from_outcome(
    injector: MemoryInjector,
    classifier: MistakeClassifier,
    outcome: TradeOutcome | None,
) -> ClassifiedMistake | None:
    """
    Classify a trade outcome into a lesson and store it. Returns the lesson (or None).

    Never raises — learning must not disrupt trading.
    """
    if outcome is None:
        return None
    try:
        mistake = classifier.classify(outcome)
        if mistake is not None:
            injector.store_from_classifier(mistake)
            logger.info(
                "Lesson learned from %s: [%s] %s",
                outcome.trade_id,
                mistake.severity,
                mistake.category,
            )
        return mistake
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Learning from outcome failed (non-fatal): %s", e)
        return None


def mark_lessons_outcome(memory_db: AgentMemoryDB, lesson_ids: list[str] | None, was_successful: bool) -> int:
    """
    Mark the lessons that were active for a trade as successful/unsuccessful.

    This is the measurement half of the loop — it lets lesson relevance reflect whether
    acting on a lesson actually helped. Returns the count marked. Never raises.
    """
    count = 0
    for lesson_id in lesson_ids or []:
        if not lesson_id:
            continue
        try:
            memory_db.mark_used(lesson_id, was_successful=was_successful)
            count += 1
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("mark_used failed for %s: %s", lesson_id, e)
    return count


def lesson_ids(lessons: list[dict[str, Any]] | None) -> list[str]:
    """Extract lesson IDs from a list of injected lesson dicts."""
    return [lesson_id for ls in (lessons or []) if (lesson_id := ls.get("lesson_id"))]
