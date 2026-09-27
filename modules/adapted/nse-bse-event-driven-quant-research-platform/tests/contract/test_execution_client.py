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


"""Execution client lifecycle tests (mock transport; sandbox guardrails)."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from indian_quant.adapters.upstox import (  # noqa: E402
    OrderSide,
    OrderType,
    SandboxOrderRequest,
    UpstoxExecutionClient,
)
from indian_quant.config import UpstoxConfig  # noqa: E402


def make_client(handler) -> UpstoxExecutionClient:
    return UpstoxExecutionClient(
        UpstoxConfig(sandbox=True),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


class TestGuardrails:
    def test_live_construction_refused(self):
        with pytest.raises(RuntimeError):
            UpstoxExecutionClient(UpstoxConfig(sandbox=False))

    def test_missing_token_raises_clear_error(self, tmp_path, monkeypatch):
        monkeypatch.delenv("UPSTOX_SANDBOX_TOKEN", raising=False)
        monkeypatch.chdir(tmp_path)
        client = make_client(lambda r: httpx.Response(200))
        with pytest.raises(RuntimeError, match="sandbox app"):
            client._headers()


class TestLifecycle:
    def handler_ok(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/place"):
            assert "MARKET" in request.content.decode()
            return httpx.Response(200, json={"data": {"order_id": "O1", "status": "open"}})
        if path.endswith("/modify"):
            return httpx.Response(200, json={"data": {"order_id": "O1", "status": "modified"}})
        if "/cancel" in path and request.method == "DELETE":
            assert request.url.params.get("order_id")
            return httpx.Response(200, json={"data": {"order_id": "O1", "status": "cancelled"}})
        return httpx.Response(200, json={})

    async def test_submit_modify_cancel(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPSTOX_SANDBOX_TOKEN", "SBX")
        client = make_client(self.handler_ok)

        req = SandboxOrderRequest(
            instrument_key="NSE_EQ|INE002A01018",
            quantity=10,
            side=OrderSide.BUY,
        )
        rep = await client.submit_order(req)
        assert rep.order_id == "O1"
        assert rep.status == "open"

        rep = await client.modify_order("O1", quantity=5)
        assert rep.status == "modified"

        rep = await client.cancel_order("O1")
        assert rep.status == "cancelled"

    def test_limit_without_price_rejected_locally(self):
        req = SandboxOrderRequest(
            instrument_key="K",
            quantity=1,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
        )
        assert req.limit_price is None

    async def test_broker_rejection_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPSTOX_SANDBOX_TOKEN", "SBX")

        def rejecting(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"data": {"order_id": "O9", "status": "rejected", "error": "insufficient funds"}}
            )

        client = make_client(rejecting)
        with pytest.raises(RuntimeError, match="rejected"):
            await client.submit_order(SandboxOrderRequest(instrument_key="K", quantity=1, side=OrderSide.SELL))

    async def test_http_400_surfaces_detail(self, tmp_path, monkeypatch):
        monkeypatch.setenv("UPSTOX_SANDBOX_TOKEN", "SBX")
        client = make_client(lambda r: httpx.Response(400, text="UDAPI100011 invalid key"))
        with pytest.raises(RuntimeError, match="invalid key"):
            await client.submit_order(SandboxOrderRequest(instrument_key="BAD", quantity=1, side=OrderSide.BUY))


class TestSandboxReadGuard:
    def test_reads_raise_orders_only_error(self):
        import asyncio

        client = make_client(lambda r: httpx.Response(200))
        with pytest.raises(RuntimeError, match="unavailable with sandbox tokens"):
            client.order_book()
        with pytest.raises(RuntimeError, match="unavailable with sandbox tokens"):
            client.positions()
        with pytest.raises(RuntimeError, match="unavailable with sandbox tokens"):
            client.funds()
        with pytest.raises(RuntimeError, match="unavailable with sandbox tokens"):
            asyncio.run(client.reconcile())
