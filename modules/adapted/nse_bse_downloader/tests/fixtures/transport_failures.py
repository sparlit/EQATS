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


"""Deterministic Phase 7.0 transport/failure fixtures.

These are data-only fixtures for classification and harness tests; they never
contact NSE/BSE and therefore cannot modify a user's data directory.
"""


import io
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass

FAILURE_CASES = (
    "timeout",
    "slow_response",
    "reset",
    "html_200",
    "empty_zip",
    "crc",
    "403",
    "404",
    "429",
    "500",
    "cancel",
)


@dataclass(frozen=True)
class FixtureResponse:
    case: str
    status: int = 200
    body: bytes = b""
    retry_after: str | None = None


class DeterministicFixtureTransport:
    """A scripted async transport for offline attempt/harness tests."""

    def __init__(self, responses: Iterable[FixtureResponse]):
        self.responses = list(responses)
        self.calls = 0

    async def request(self) -> FixtureResponse:
        if self.calls >= len(self.responses):
            raise AssertionError("fixture transport exhausted")
        response = self.responses[self.calls]
        self.calls += 1
        if response.case in {"timeout", "reset", "cancel"}:
            raise TimeoutError(response.case)
        return response


def _zip_payload(content: bytes = b"SYMBOL,DATE\nABC,20260804\n") -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.csv", content)
    return stream.getvalue()


def fixture_response(case: str) -> FixtureResponse:
    if case not in FAILURE_CASES:
        raise ValueError(f"Unknown deterministic failure fixture: {case}")
    if case == "timeout":
        return FixtureResponse(case)
    if case == "slow_response":
        return FixtureResponse(case, body=b"slow-chunk")
    if case == "reset":
        return FixtureResponse(case)
    if case == "html_200":
        return FixtureResponse(case, body=b"<!doctype html><html>blocked</html>")
    if case == "empty_zip":
        return FixtureResponse(case, body=_zip_payload(b""))
    if case == "crc":
        payload = bytearray(_zip_payload())
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            info = archive.infolist()[0]
        name_length = int.from_bytes(
            payload[info.header_offset + 26 : info.header_offset + 28], "little"
        )
        extra_length = int.from_bytes(
            payload[info.header_offset + 28 : info.header_offset + 30], "little"
        )
        data_offset = info.header_offset + 30 + name_length + extra_length
        payload[data_offset] ^= 0xFF
        return FixtureResponse(case, body=bytes(payload))
    if case == "cancel":
        return FixtureResponse(case)
    status = int(case)
    return FixtureResponse(case, status=status, retry_after="7" if status == 429 else None)
