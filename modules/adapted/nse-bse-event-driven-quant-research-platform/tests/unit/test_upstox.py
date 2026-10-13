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


"""Upstox adapter tests: REST parsing, execution guardrails."""


import pytest
from indian_quant.adapters.upstox import (
    OrderSide,
    SandboxOrderRequest,
    UpstoxExecutionClient,
    UpstoxRestClient,
)
from indian_quant.config import UpstoxConfig
from indian_quant.schemas import Timeframe

CANDLE_PAYLOAD = {
    "status": "success",
    "data": {
        "candles": [
            ["2025-01-01T00:00:00+05:30", 53.1, 53.95, 51.6, 52.05, 235519861, 0],
            ["2025-02-01T00:00:00+05:30", 50.35, 56.85, 49.35, 52.8, 1004998611, 0],
        ]
    },
}


class TestUpstoxRest:
    def test_candles_to_bars(self):
        client = UpstoxRestClient(access_token="t")
        bars = client.candles_to_bars(
            CANDLE_PAYLOAD,
            instrument_id="NSE_EQ|INE848E01016",
            exchange="NSE",
            timeframe=Timeframe.DAY,
        )
        assert len(bars) == 2
        first = bars[0]
        assert first.open == pytest.approx(53.1)
        assert first.close == pytest.approx(52.05)
        assert first.volume == pytest.approx(235519861)
        assert first.timestamp.utcoffset() is not None

    def test_unit_mapping(self):
        from indian_quant.adapters.upstox.rest import UNIT_FOR_TIMEFRAME

        assert UNIT_FOR_TIMEFRAME[Timeframe.MIN_5] == ("minutes", 5)
        assert UNIT_FOR_TIMEFRAME[Timeframe.DAY] == ("days", 1)


class TestUpstoxExecutionGuardrails:
    def test_submit_without_token_raises_guidance(self, monkeypatch, tmp_path):
        monkeypatch.delenv("UPSTOX_SANDBOX_TOKEN", raising=False)
        monkeypatch.chdir(tmp_path)
        import asyncio

        client = UpstoxExecutionClient(UpstoxConfig(sandbox=True))
        with pytest.raises(RuntimeError, match="sandbox app"):
            asyncio.run(
                client.submit_order(
                    SandboxOrderRequest(
                        instrument_key="NSE_EQ|INE002A01018", quantity=1, side=OrderSide.BUY
                    )
                )
            )

    def test_live_refused(self):
        with pytest.raises(RuntimeError):
            UpstoxExecutionClient(UpstoxConfig(sandbox=False))
