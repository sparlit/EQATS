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


"""Broker reconciliation: our state vs Upstox state -> halt on mismatch.

C1 principle: before any further complexity, the system must detect when
its internal view of orders/positions/funds diverges from the broker's and
BLOCK new trading until a human resolves it.
"""


from dataclasses import dataclass, field
from typing import Any

import httpx

BASE_URL = "https://api.upstox.com"


@dataclass
class ReconciliationReport:
    checked_at_iso: str
    orders_compared: int
    positions_compared: int
    funds_compared: bool
    mismatches: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at_iso,
            "orders_compared": self.orders_compared,
            "positions_compared": self.positions_compared,
            "funds_compared": self.funds_compared,
            "ok": self.ok,
            "mismatches": self.mismatches,
        }


class Reconciler:
    """Compares local (engine/OMS) snapshots against live broker state."""

    def __init__(
        self,
        access_token: str | None,
        *,
        http_client: httpx.Client | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._http = http_client or httpx.Client(timeout=30.0)
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token

    def _headers(self) -> dict[str, str]:
        if not self.access_token:
            raise RuntimeError("reconciler requires an access token")
        return {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}

    # ------------------------------------------------------------- broker IO
    def fetch_order_book(self) -> list[dict[str, Any]]:
        resp = self._http.get(f"{self.base_url}/v2/order/retrieve-all", headers=self._headers())
        resp.raise_for_status()
        data = resp.json().get("data") or {}
        if isinstance(data, dict) and "orders" in data:
            return list(data["orders"])
        return list(data.values()) if isinstance(data, dict) else list(data)

    def fetch_positions(self) -> list[dict[str, Any]]:
        resp = self._http.get(
            f"{self.base_url}/v2/portfolio/short-term-positions", headers=self._headers()
        )
        resp.raise_for_status()
        return list(resp.json().get("data") or [])

    def fetch_funds(self) -> dict[str, Any]:
        resp = self._http.get(
            f"{self.base_url}/v2/user/get-funds-and-margin", headers=self._headers()
        )
        resp.raise_for_status()
        return dict((resp.json().get("data") or {}).get("equity") or {})

    # ------------------------------------------------------------- comparison
    @staticmethod
    def compare_positions(
        local: dict[str, float],
        broker_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """local: {instrument_key: net_qty}; broker rows keyed by instrument."""
        broker: dict[str, float] = {}
        for row in broker_rows:
            key = str(row.get("instrument_key") or row.get("symbol") or "")
            if not key:
                continue
            qty = row.get("quantity")
            if qty is None:
                qty = row.get("net_quantity") or 0
            broker[key] = broker.get(key, 0.0) + float(qty)

        mismatches: list[dict[str, Any]] = []
        for key in sorted(set(local) | set(broker)):
            ours = float(local.get(key, 0.0))
            theirs = float(broker.get(key, 0.0))
            if abs(ours - theirs) > 1e-9:
                mismatches.append(
                    {
                        "kind": "POSITION",
                        "instrument": key,
                        "local_qty": ours,
                        "broker_qty": theirs,
                    }
                )
        return mismatches

    @staticmethod
    def compare_orders(
        local_open_ids: set[str],
        broker_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        open_statuses = {"open", "trigger pending", "modified"}
        broker_open = {
            str(o.get("order_id"))
            for o in broker_rows
            if str(o.get("status") or "").lower() in open_statuses
        }
        mismatches: list[dict[str, Any]] = []
        for order_id in sorted(local_open_ids - broker_open):
            mismatches.append(
                {
                    "kind": "ORDER_LOCAL_ONLY",
                    "order_id": order_id,
                    "detail": "locally open but absent/open-mismatch at broker",
                }
            )
        for order_id in sorted(broker_open - local_open_ids):
            mismatches.append(
                {
                    "kind": "ORDER_BROKER_ONLY",
                    "order_id": order_id,
                    "detail": "open at broker but unknown locally",
                }
            )
        return mismatches

    @staticmethod
    def compare_funds(
        local_available: float | None,
        broker_funds: dict[str, Any],
        *,
        tolerance: float = 1.0,
    ) -> list[dict[str, Any]]:
        broker_avail = broker_funds.get("available_margin") or broker_funds.get("net")
        if local_available is None or broker_avail is None:
            return []
        try:
            theirs = float(broker_avail)
        except (TypeError, ValueError):
            return []
        if abs(float(local_available) - theirs) > tolerance:
            return [
                {
                    "kind": "FUNDS",
                    "local_available": float(local_available),
                    "broker_available": theirs,
                }
            ]
        return []

    # ------------------------------------------------------------------ run
    def run(
        self,
        *,
        local_positions: dict[str, float] | None = None,
        local_open_orders: set[str] | None = None,
        local_available_funds: float | None = None,
        checked_at_iso: str,
    ) -> ReconciliationReport:
        from datetime import UTC, datetime

        broker_orders = self.fetch_order_book()
        broker_positions = self.fetch_positions()
        broker_funds = self.fetch_funds()

        mismatches: list[dict[str, Any]] = []
        mismatches += self.compare_orders(local_open_orders or set(), broker_orders)
        mismatches += self.compare_positions(local_positions or {}, broker_positions)
        mismatches += self.compare_funds(local_available_funds, broker_funds)

        return ReconciliationReport(
            checked_at_iso=checked_at_iso or datetime.now(UTC).isoformat(),
            orders_compared=len(broker_orders),
            positions_compared=len(broker_positions),
            funds_compared=bool(broker_funds),
            mismatches=mismatches,
        )


def should_halt(report: ReconciliationReport) -> bool:
    """Any mismatch blocks new trading until manually resolved."""
    return not report.ok
