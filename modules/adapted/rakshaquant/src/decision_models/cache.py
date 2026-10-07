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
Decision-model response cache (plan M8.5): live runs record every answer keyed by
``sha256(model, checkpoint, state, questions)`` in the event store's ``kv_state``; a replay serves
them back (``replay_only``: a miss is a model error → ABSTAIN, never a fresh, different answer), so a
replayed day reproduces the live decisions.
"""


import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from src.decision_models.base import Answer, DecisionModel, DecisionModelError, Question
from src.llm.router import ResponseCache


def cache_key(name: str, checkpoint: str, state: Mapping[str, str],
              questions: Mapping[str, Question]) -> str:  # fmt: skip
    body = json.dumps([name, checkpoint, dict(state), {q: v.wire() for q, v in questions.items()}],
                      sort_keys=True, ensure_ascii=False)  # fmt: skip
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _dump(answers: Mapping[str, Answer]) -> str:
    return json.dumps({n: {"type": a.type, "value": a.value, "probabilities": dict(a.probabilities),
                           "confidence": a.confidence, "model": a.model,
                           "calibrated": a.calibrated} for n, a in answers.items()},
                      sort_keys=True)  # fmt: skip


def _load(text: str) -> dict[str, Answer]:
    data: dict[str, dict[str, Any]] = json.loads(text)
    return {n: Answer(a["type"], a["value"], a["probabilities"], a["confidence"], a["model"],
                      a["calibrated"]) for n, a in data.items()}  # fmt: skip


class CachedDecisionModel:
    def __init__(self, model: DecisionModel, cache: ResponseCache, *, replay_only: bool = False):
        self._model = model
        self._cache = cache
        self.replay_only = replay_only

    @property
    def name(self) -> str:
        return self._model.name

    @property
    def checkpoint(self) -> str:
        return self._model.checkpoint

    @property
    def context_tokens(self) -> int | None:
        return self._model.context_tokens

    @property
    def device(self) -> str | None:
        return getattr(self._model, "device", None)

    async def decide(
        self, state: Mapping[str, str], questions: Mapping[str, Question]
    ) -> dict[str, Answer]:
        key = cache_key(self.name, self.checkpoint, state, questions)
        hit = self._cache.get(key)
        if hit is not None:
            return _load(hit)
        if self.replay_only:
            raise DecisionModelError(f"{self.name}: not in the replay cache")
        answers = await self._model.decide(state, questions)
        self._cache.put(key, _dump(answers), datetime.now(UTC))
        return answers


class ReplayStub:
    """Stands in for a model that is not loaded during a replay (its name and checkpoint key
    the cache)."""

    def __init__(self, name: str, checkpoint: str, context_tokens: int | None) -> None:
        self.name, self.checkpoint, self.context_tokens = name, checkpoint, context_tokens

    async def decide(
        self, state: Mapping[str, str], questions: Mapping[str, Question]
    ) -> dict[str, Answer]:
        raise DecisionModelError(f"{self.name} is not loaded in a replay")
