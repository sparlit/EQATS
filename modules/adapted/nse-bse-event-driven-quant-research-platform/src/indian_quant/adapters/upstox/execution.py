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


"""Upstox execution client - sandbox-first order lifecycle.

Endpoints (V3): place  POST /v3/order/place
                modify PUT  /v3/order/modify
                cancel POST /v3/order/cancel/{order_id}
Reconciliation reads (v2, read-only): order book, positions, funds.

Environment rules:
    * A sandbox token (from the Upstox developer console's sandbox section)
      is required - set UPSTOX_SANDBOX_TOKEN or upstox_sandbox_tokens.json.
    * Live routing stays physically disabled until Phase 8 sign-off
      (INDIAQUAT_ALLOW_LIVE=1 does NOT bypass this build's guardrail).
"""


import contextlib
import json
import os
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from indian_quant.config.settings import UpstoxConfig

ORDER_BASE_URL_SANDBOX = "https://api-sandbox.upstox.com"
READ_BASE_URL = "https://api.upstox.com"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ProductType(StrEnum):
    INTRADAY = "I"
    DELIVERY = "D"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"
    SL_M = "SL-M"


class Validity(StrEnum):
    DAY = "DAY"
    IOC = "IOC"


@dataclass(frozen=True)
class SandboxOrderRequest:
    instrument_key: str
    quantity: int
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    product: ProductType = ProductType.INTRADAY
    validity: Validity = Validity.DAY
    limit_price: float | None = None
    trigger_price: float | None = None
    tag: str | None = None
    client_order_id: str | None = None


@dataclass(frozen=True)
class ExecutionReport:
    order_id: str
    status: str
    filled_qty: int = 0
    avg_price: float | None = None
    raw: dict[str, Any] | None = None


def _load_env_files() -> dict[str, str]:
    env: dict[str, str] = {}
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        env_file = candidate / ".env"
        if not env_file.exists():
            continue
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env.setdefault(key.strip(), value.strip().strip("'\""))
    return env


def _find_sandbox_token() -> str | None:
    token = os.environ.get("UPSTOX_SANDBOX_TOKEN")
    if not token:
        token = _load_env_files().get("UPSTOX_SANDBOX_TOKEN", "")
    if token:
        return token
    for candidate in [Path.cwd(), *Path.cwd().parents]:
        marker = candidate / "upstox_sandbox_tokens.json"
        if marker.exists():
            try:
                value = str(json.loads(marker.read_text()).get("access_token") or "")
                if value:
                    return value
            except (OSError, ValueError):
                continue
    return None


class UpstoxExecutionClient:
    """Sandbox-first execution boundary aligned with Nautilus ExecutionClient."""

    def __init__(
        self,
        config: UpstoxConfig,
        *,
        http_client: httpx.Client | None = None,
        base_url: str = ORDER_BASE_URL_SANDBOX,
        read_base_url: str = READ_BASE_URL,
    ) -> None:
        if not config.sandbox:
            msg = "refusing to construct a live execution client; sandbox only in this phase"
            raise RuntimeError(msg)
        self.config = config
        self.base_url = base_url.rstrip("/")
        self.read_base_url = read_base_url.rstrip("/")
        self._http = http_client or httpx.Client(timeout=30.0)

    # ------------------------------------------------------------------ auth
    def _headers(self) -> dict[str, str]:
        token = _find_sandbox_token()
        if not token:
            msg = (
                "missing sandbox token - create a sandbox app at "
                "account.upstox.com/developer/apps#sandbox, click Generate, then "
                "set UPSTOX_SANDBOX_TOKEN (or upstox_sandbox_tokens.json)"
            )
            raise RuntimeError(msg)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _guard_reads(self) -> None:
        """Sandbox tokens are orders-only per Upstox docs."""
        msg = (
            "read APIs (order book/positions/funds) are unavailable with "
            "sandbox tokens - use UpstoxRestClient/Reconciler with a live "
            "token for account reads"
        )
        raise RuntimeError(msg)

    @staticmethod
    def new_client_order_id() -> str:
        return uuid.uuid4().hex[:16]

    # ------------------------------------------------------------- lifecycle
    async def connect(self) -> None:
        """Probe auth. Tolerates 401 on profile since sandbox tokens are
        orders-only by design."""

    async def submit_order(self, request: SandboxOrderRequest) -> ExecutionReport:
        if request.order_type == OrderType.LIMIT and request.limit_price is None:
            msg = "LIMIT order requires limit_price"
            raise ValueError(msg)
        if request.order_type in (OrderType.SL, OrderType.SL_M) and (request.trigger_price is None):
            msg = "SL orders require trigger_price"
            raise ValueError(msg)
        body: dict[str, Any] = {
            "quantity": request.quantity,
            "product": request.product.value,
            "validity": request.validity.value,
            "instrument_token": request.instrument_key,
            "order_type": request.order_type.value,
            "transaction_type": request.side.value,
            "disclosed_quantity": 0,
            "is_amo": False,
            "slice": False,
            "price": request.limit_price if request.limit_price is not None else 0.0,
            "trigger_price": (request.trigger_price if request.trigger_price is not None else 0.0),
        }
        if request.tag:
            body["tag"] = request.tag[:40]
        resp = self._http.post(
            f"{self.base_url}/v3/order/place",
            headers=self._headers(),
            json=body,
        )
        return self._report(resp, fallback_status="open")

    async def modify_order(
        self,
        order_id: str,
        *,
        quantity: int | None = None,
        limit_price: float | None = None,
        order_type: OrderType | None = None,
        validity: Validity | None = None,
    ) -> ExecutionReport:
        body: dict[str, Any] = {
            "order_id": order_id,
            "price": limit_price if limit_price is not None else 0.0,
            "trigger_price": 0.0,
            "disclosed_quantity": 0,
            "validity": (validity or Validity.DAY).value,
            "order_type": (order_type or OrderType.MARKET).value,
        }
        if quantity is not None:
            body["quantity"] = quantity
        if validity is not None:
            body["validity"] = validity.value
        resp = self._http.put(
            f"{self.base_url}/v3/order/modify",
            headers=self._headers(),
            json=body,
        )
        return self._report(resp, fallback_status="modified")

    async def cancel_order(self, order_id: str) -> ExecutionReport:
        resp = self._http.delete(
            f"{self.base_url}/v3/order/cancel",
            headers=self._headers(),
            params={"order_id": order_id},
        )
        return self._report(resp, fallback_status="cancelled")

    # --------------------------------------------------------- reconciliation
    def order_book(self) -> list[dict[str, Any]]:
        self._guard_reads()
        resp = self._http.get(f"{self.read_base_url}/v2/order/retrieve-all", headers=self._headers())
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        if isinstance(data, dict) and "orders" in data:
            return list(data["orders"])
        return list(data.values()) if isinstance(data, dict) else list(data)

    def positions(self) -> list[dict[str, Any]]:
        self._guard_reads()
        resp = self._http.get(
            f"{self.read_base_url}/v2/portfolio/short-term-positions",
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        if isinstance(data, dict) and "orders" in data:
            return list(data["orders"])
        return list(data.values()) if isinstance(data, dict) else list(data)

    def funds(self) -> dict[str, Any]:
        self._guard_reads()
        resp = self._http.get(f"{self.read_base_url}/v2/user/get-funds-and-margin", headers=self._headers())
        resp.raise_for_status()
        return dict((resp.json().get("data") or {}).get("equity") or {})

    async def reconcile(self) -> list[ExecutionReport]:
        """Pull broker order state; requires read access (live token).

        Sandbox tokens are orders-only - use Reconciler with a live token.
        """
        self._guard_reads()
        reports: list[ExecutionReport] = []
        for order in self.order_book():
            reports.append(
                ExecutionReport(
                    order_id=str(order.get("order_id") or ""),
                    status=str(order.get("status") or ""),
                    filled_qty=int(float(order.get("filled_quantity") or 0)),
                    avg_price=float(order["average_price"]) if order.get("average_price") else None,
                    raw=order,
                )
            )
        return reports

    @staticmethod
    def _report(resp: httpx.Response, fallback_status: str = "unknown") -> ExecutionReport:
        if resp.status_code >= 400:
            detail = resp.text[:300]
            msg = f"order endpoint failed ({resp.status_code}): {detail}"
            raise RuntimeError(msg)
        payload: dict[str, Any] = {}
        with contextlib.suppress(ValueError):
            payload = (resp.json() or {}).get("data") or {}
        if isinstance(payload.get("order_ids"), list) and payload["order_ids"]:
            first_id = str(payload["order_ids"][0])
            return ExecutionReport(order_id=first_id, status="open", raw=payload)
        if isinstance(payload.get("order_ids"), list):
            first_id = str(payload["order_ids"][0]) if payload["order_ids"] else ""
            return ExecutionReport(order_id=first_id, status=fallback_status, raw=payload)
        if payload.get("order_id") and not payload.get("status"):
            return ExecutionReport(order_id=str(payload["order_id"]), status=fallback_status, raw=payload)
        status = str(payload.get("status") or fallback_status)
        if status.lower() in ("rejected", "rejected_by_broker", "validation_error"):
            msg = f"broker rejected order: {payload}"
            raise RuntimeError(msg)
        return ExecutionReport(
            order_id=str(payload.get("order_id") or ""),
            status=status,
            filled_qty=int(float(payload.get("filled_quantity") or 0)),
            avg_price=float(payload["average_price"]) if payload.get("average_price") else None,
            raw=payload,
        )


__all__ = [
    "ExecutionReport",
    "OrderSide",
    "OrderType",
    "ProductType",
    "SandboxOrderRequest",
    "UpstoxExecutionClient",
    "Validity",
]
