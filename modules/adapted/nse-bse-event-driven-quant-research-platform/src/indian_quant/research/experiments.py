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


"""Experiment registry: every research result is reproducible or it doesn't count."""


import hashlib
import json
import uuid
from typing import Any

from indian_quant.storage.metadata import MetadataStore


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


class ExperimentTracker:
    def __init__(self, metadata: MetadataStore) -> None:
        self.metadata = metadata

    def record(
        self,
        *,
        kind: str,
        config: dict[str, Any],
        dataset_hash: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> str:
        run_id = f"{kind}-{config_hash(config)}-{uuid.uuid4().hex[:8]}"
        self.metadata.record_run(
            run_id,
            kind=kind,
            config_hash=config_hash(config),
            dataset_hash=dataset_hash,
            metrics=metrics,
        )
        return run_id
