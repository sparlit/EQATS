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


"""Immutable content-addressed raw storage.

Every upstream response is persisted exactly as received, keyed by hash,
before any parsing happens. This is the ground truth for reproducibility.
"""


import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class RawStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _path_for(self, source: str, tool: str, day: str, digest: str, ext: str) -> Path:
        return self.root / source.lower() / tool / day / f"{digest}.{ext}"

    def save(
        self,
        *,
        source: str,
        tool: str,
        payload: bytes,
        ext: str = "json",
        request_meta: dict | None = None,
        observed_at: datetime | None = None,
    ) -> tuple[Path, str]:
        """Persist a raw payload; returns (path, sha256). Idempotent by hash."""
        digest = sha256_bytes(payload)
        ts = observed_at or datetime.now(UTC)
        day = ts.strftime("%Y-%m-%d")
        path = self._path_for(source, tool, day, digest, ext)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            meta_path = path.with_suffix(".meta.json")
            meta = {
                "source": source,
                "tool": tool,
                "sha256": digest,
                "bytes": len(payload),
                "observed_at": ts.isoformat(),
                "request": request_meta or {},
            }
            meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True))
        return path, digest

    def exists(self, digest: str, *, source: str, tool: str, day: str, ext: str = "json") -> bool:
        return self._path_for(source, tool, day, digest, ext).exists()

    def load(self, path: Path | str) -> bytes:
        return Path(path).read_bytes()

    def iter_records(self, source: str | None = None):
        pattern = f"{source.lower() if source else '*'}/**/*.json"
        for meta_file in sorted(self.root.glob(pattern)):
            if meta_file.name.endswith(".meta.json"):
                continue
            yield meta_file
