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
Memory Injection Module

Provides logic for injecting relevant lessons into agent context.
Coordinates between the memory database and agent orchestration.
"""

import logging
from dataclasses import dataclass
from typing import Any

from .classifier import ClassifiedMistake
from .database import AgentMemoryDB

logger = logging.getLogger(__name__)


@dataclass
class MemoryInjector:
    """
    Injects relevant lessons into agent trading state.

    Coordinates with the memory database to:
    - Retrieve context-relevant lessons
    - Format lessons for agent consumption
    - Track usage for feedback loop
    """

    memory_db: AgentMemoryDB = None
    max_lessons: int = 5

    def __post_init__(self):
        if self.memory_db is None:
            self.memory_db = AgentMemoryDB()

    def inject_lessons(
        self,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Inject relevant lessons into trading state.

        Called at the beginning of each trading cycle to provide
        agents with context from past mistakes.

        Args:
            state: Current trading state

        Returns:
            State with memory_lessons field populated
        """
        try:
            # Get current context from state
            regime = state.get("regime", "unknown")
            active_strategies = state.get("active_strategies", [])

            # Retrieve relevant lessons
            lessons = self.memory_db.get_top_lessons_for_context(
                regime=regime,
                strategies=active_strategies,
                n=self.max_lessons,
            )

            if lessons:
                logger.info(f"Injected {len(lessons)} lessons into trading state")

                # Mark lessons as used
                for lesson in lessons:
                    self.memory_db.mark_used(lesson.get("lesson_id"))

            # Return updated state
            return {
                "memory_lessons": lessons,
            }

        except Exception as e:
            logger.exception(f"Lesson injection failed: {e}")
            return {"memory_lessons": []}

    def get_lessons_for_category(
        self,
        category: str,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Get lessons for a specific mistake category."""
        return self.memory_db.get_lessons(category=category, limit=limit)

    def store_from_classifier(
        self,
        mistake: ClassifiedMistake,
    ) -> bool:
        """
        Store a classified mistake as a lesson.

        Args:
            mistake: Classified mistake from the classifier

        Returns:
            True if stored successfully
        """
        return self.memory_db.store_lesson(
            lesson_id=mistake.lesson_id,
            category=mistake.category,
            severity=mistake.severity,
            description=mistake.description,
            lesson=mistake.lesson,
            trade_id=mistake.trade_id,
            strategy=mistake.trade_context.get("strategy"),
            regime=mistake.trade_context.get("regime"),
            symbol=mistake.trade_context.get("symbol"),
            context_factors=mistake.context_factors,
        )

    def mark_lesson_successful(
        self,
        lesson_id: str,
    ) -> None:
        """
        Mark a lesson as having contributed to a successful trade.

        Called when a trade that had injected lessons turns out profitable.
        Boosts the lesson's relevance score.
        """
        self.memory_db.mark_used(lesson_id, was_successful=True)
        logger.info(f"Marked lesson {lesson_id} as successful")

    def format_lessons_for_agent(
        self,
        lessons: list[dict[str, Any]],
    ) -> str:
        """
        Format lessons as a string for agent prompt injection.

        Args:
            lessons: List of lesson dictionaries

        Returns:
            Formatted string for agent context
        """
        if not lessons:
            return "No relevant lessons from past trades."

        lines = ["## Past Trading Lessons (Learn from these mistakes)\n"]

        for i, lesson in enumerate(lessons, 1):
            severity = lesson.get("severity", "medium").upper()
            category = lesson.get("category", "unknown").replace("_", " ").title()

            lines.append(f"### Lesson {i}: [{severity}] {category}")
            lines.append(f"**What went wrong:** {lesson.get('description', 'N/A')}")
            lines.append(f"**Lesson:** {lesson.get('lesson', 'N/A')}")

            if lesson.get("strategy"):
                lines.append(
                    f"*Context: {lesson.get('strategy')} strategy in {lesson.get('regime', 'unknown')} market*"
                )

            lines.append("")  # Empty line between lessons

        return "\n".join(lines)


def create_feedback_loop(
    trade_outcomes: list,
    classifier,
    memory_db: AgentMemoryDB,
) -> int:
    """
    Process trade outcomes through the full feedback loop.

    1. Analyze outcomes
    2. Classify mistakes
    3. Store lessons

    Args:
        trade_outcomes: List of TradeOutcome objects
        classifier: MistakeClassifier instance
        memory_db: AgentMemoryDB instance

    Returns:
        Number of lessons generated
    """
    injector = MemoryInjector(memory_db=memory_db)
    lessons_created = 0

    for outcome in trade_outcomes:
        mistake = classifier.classify(outcome)

        if mistake:
            success = injector.store_from_classifier(mistake)
            if success:
                lessons_created += 1
                logger.info(f"Created lesson from trade {outcome.trade_id}: [{mistake.severity}] {mistake.category}")

    return lessons_created


def memory_injection_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    LangGraph node for memory injection.

    Can be added to the trading graph to inject lessons
    before the decision-making agents run.
    """
    injector = MemoryInjector()
    return injector.inject_lessons(state)
