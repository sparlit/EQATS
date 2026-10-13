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


"""Quantity-based accounting contract shared by all four scanners."""

from math import isfinite


def number(value: object, *, default: float | None = None) -> float:
    if value is None and default is not None:
        return default
    parsed = float(value)
    if not isfinite(parsed):
        raise ValueError("Non-finite portfolio amount")
    return parsed


def build_snapshot(
    scanner: str,
    as_of: str,
    capital: float,
    positions: list[dict],
    pending: list[dict] | None = None,
    *,
    legacy: list[dict] | None = None,
    provenance: str = "RECORDED_PAPER",
    execution_model: str = "RECORDED_FILLS",
) -> dict:
    """Realised P&L is gross. Fees are deducted exactly once from cash/equity.

    Positions must include closed trades and booked partial exits. Pending orders
    never consume cash or contribute market value/P&L. No leverage or cash flows
    are silently inferred. Prices retain precision until the reporting boundary.
    """
    capital = number(capital)
    if capital <= 0:
        raise ValueError("Starting capital must be positive")
    rows, seen = [], set()
    for original in positions:
        row = dict(original)
        identity = str(row["trade_id"])
        if identity in seen:
            raise ValueError(f"Duplicate trade: {identity}")
        seen.add(identity)
        quantity, remaining = number(row["quantity"]), number(row["remaining_quantity"])
        entry = number(row["entry"])
        mark = number(row.get("last_price"), default=entry)
        realised = number(row.get("realised_pnl"), default=0)
        fees = number(row.get("fees"), default=0)
        if quantity <= 0 or not 0 <= remaining <= quantity or entry <= 0 or mark <= 0 or fees < 0:
            raise ValueError(f"Invalid position amounts: {identity}")
        if row.get("status") == "CLOSED" and remaining:
            raise ValueError(f"Closed trade retains quantity: {identity}")
        if row.get("status") in {"PENDING", "WATCH", "READY", "CANCELLED"}:
            raise ValueError("Unfilled setup cannot be a position")
        unrealised = remaining * (mark - entry)
        row.update(
            quantity=quantity,
            remaining_quantity=remaining,
            entry=entry,
            last_price=mark,
            invested_capital=remaining * entry,
            market_value=remaining * mark,
            realised_pnl=realised,
            unrealised_pnl=unrealised,
            fees=fees,
            total_pnl=realised + unrealised - fees,
            return_pct=(realised + unrealised - fees) / (quantity * entry) * 100,
        )
        rows.append(row)
    invested = sum(r["invested_capital"] for r in rows)
    market = sum(r["market_value"] for r in rows)
    realised = sum(r["realised_pnl"] for r in rows)
    unrealised = sum(r["unrealised_pnl"] for r in rows)
    fees = sum(r["fees"] for r in rows)
    cash = capital + realised - fees - invested
    equity = cash + market
    total = realised + unrealised - fees
    pending = pending or []
    reserved = sum(number(p.get("reserved_capital"), default=0) for p in pending)
    stale = [r["symbol"] for r in rows if r["remaining_quantity"] and r.get("mark_date") != as_of]
    warnings = []
    if cash < -0.01:
        warnings.append("Recorded positions imply negative cash; reconcile historical allocations.")
    if stale:
        warnings.append("Some holdings use an older or undated mark; valuation is provisional.")
    if legacy:
        warnings.append(
            "Legacy records without sufficient accounting evidence are excluded from totals."
        )
    if any(r.get("status") == "REVIEW" for r in rows):
        warnings.append(
            "Review holdings remain invested; no unverified corporate-action conversion is assumed."
        )
    residual = equity - (capital + total)
    if abs(residual) > 0.01:
        raise ValueError("Portfolio reconciliation failed")
    return {
        "schema_version": 1,
        "scanner": scanner,
        "mode": "PAPER",
        "as_of_date": as_of,
        "provenance": provenance,
        "execution_model": execution_model,
        "starting_capital": capital,
        "available_cash": cash,
        "invested_capital": invested,
        "reserved_capital": reserved,
        "market_value": market,
        "realised_pnl": realised,
        "unrealised_pnl": unrealised,
        "fees": fees,
        "total_pnl": total,
        "equity": equity,
        "return_pct": total / capital * 100,
        "open_positions": sum(r["remaining_quantity"] > 0 for r in rows),
        "closed_positions": sum(r["remaining_quantity"] == 0 for r in rows),
        "pending_setups": len(pending),
        "positions": rows,
        "pending": pending,
        "legacy_records": legacy or [],
        "warnings": warnings,
        "reconciliation_residual": residual,
        "cost_basis": "NET_OF_RECORDED_FEES" if fees else "GROSS — fees not modelled or recorded",
    }
