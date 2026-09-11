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


"""Shared point-in-time pre-scan tradeability gateway."""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Mapping

FALSE_VALUES = {"", "0", "0.0", "false", "no", "n", "inactive"}
TERMINAL_TYPES = {
    "AMALGAMATION": "TERMINAL_MERGER",
    "MERGER": "TERMINAL_MERGER",
    "DELISTING": "DELISTED_SECURITY",
    "DISSOLUTION": "DELISTED_SECURITY",
}


@dataclass(frozen=True)
class TradeabilityResult:
    symbol: str
    eligible: bool
    reason_code: str
    stage: str
    symbol_last_date: str | None = None
    staleness_sessions: int | None = None
    successor_symbol: str | None = None
    entry_blocked: bool = False
    detail: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _active(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() not in FALSE_VALUES


def _is_etf(symbol: str, master_row: Mapping[str, object]) -> bool:
    """Reject exchange-traded funds even when an upstream master labels them EQ.

    NSE equity-series metadata alone is not enough to distinguish all ETFs.
    Prefer an explicit instrument classification when supplied, then use the
    security name and conventional NSE ETF ticker conventions as conservative
    fallbacks.  This gateway is shared by every scanner.
    """
    fields = ("instrument_type", "instrument", "security_type", "asset_type")
    explicit = " ".join(str(master_row.get(field) or "") for field in fields).upper()
    name = str(master_row.get("company_name") or master_row.get("name") or "").upper()
    ticker = symbol.upper()
    # A small group of NSE ETFs use provider/index shorthand rather than an
    # ETF suffix (for example HDFCNIFIT and MOMENTUM50).  These are stable
    # product-code families, unlike generic short prefixes.
    etf_prefixes = ("HDFCNIF", "HDFCPVT", "MOSMALL", "MOMENTUM")
    return "ETF" in explicit or "ETF" in name or ticker.endswith(("ETF", "BEES")) or ticker.startswith(etf_prefixes)


def evaluate_tradeability(
    symbol: str,
    frame: pd.DataFrame,
    *,
    market_date: str,
    master_row: Mapping[str, object] | None,
    restricted_reason: str | None = None,
    lifecycle_event: Mapping[str, object] | None = None,
    session_calendar: tuple[str, ...] = (),
    max_staleness_sessions: int = 0,
    require_metadata: bool = True,
) -> TradeabilityResult:
    """Apply terminal-event, metadata, restriction and freshness rules.

    Corporate lifecycle is checked first so a merged security reports its real
    cause rather than the secondary symptom of missing metadata or stale data.
    """
    symbol = str(symbol).upper()
    event = lifecycle_event or {}
    last_trade = str(event.get("last_trading_date") or "")
    effective = str(event.get("effective_date") or "")
    terminal_from = last_trade or effective
    terminal_on = (
        bool(terminal_from and market_date > terminal_from)
        if last_trade
        else bool(effective and market_date >= effective)
    )
    if _active(event.get("terminal")) and terminal_on:
        event_type = str(event.get("event_type") or "").upper()
        return TradeabilityResult(
            symbol,
            False,
            TERMINAL_TYPES.get(event_type, "TERMINAL_CORPORATE_EVENT"),
            "CORPORATE_LIFECYCLE",
            successor_symbol=str(event.get("successor_symbol") or "") or None,
            entry_blocked=True,
            detail=str(event.get("notes") or event_type),
        )

    if master_row is None and require_metadata:
        return TradeabilityResult(symbol, False, "NOT_IN_CURRENT_NSE_UNIVERSE", "SECURITY_MASTER", entry_blocked=True)
    if master_row is None:
        master_row = {"series": "EQ", "active": 1}
    if _is_etf(symbol, master_row):
        return TradeabilityResult(symbol, False, "ETF_SECURITY", "SECURITY_MASTER", entry_blocked=True)
    series = str(master_row.get("series") or "").upper()
    if series != "EQ":
        return TradeabilityResult(symbol, False, "NON_EQ_SERIES", "SECURITY_MASTER", entry_blocked=True, detail=series)
    if not _active(master_row.get("active")):
        return TradeabilityResult(symbol, False, "INACTIVE_SECURITY", "SECURITY_MASTER", entry_blocked=True)
    delisting = str(master_row.get("delisting_date") or "")
    if delisting and delisting.lower() != "nan" and market_date >= delisting:
        return TradeabilityResult(symbol, False, "DELISTED_SECURITY", "CORPORATE_LIFECYCLE", entry_blocked=True)
    if restricted_reason:
        return TradeabilityResult(
            symbol, False, "RESTRICTED_SECURITY", "REGULATORY", entry_blocked=True, detail=str(restricted_reason)
        )

    ordered = frame.sort_values("trade_date")
    if ordered.empty:
        return TradeabilityResult(symbol, False, "NO_PRICE_HISTORY", "DATA_QUALITY", entry_blocked=True)
    latest = pd.Timestamp(ordered["trade_date"].iloc[-1]).date().isoformat()
    if latest > market_date:
        return TradeabilityResult(symbol, False, "INVALID_LATEST_ROW", "DATA_QUALITY", latest, entry_blocked=True)
    calendar = tuple(day for day in session_calendar if day <= market_date)
    staleness = sum(day > latest for day in calendar)
    if staleness > max_staleness_sessions:
        return TradeabilityResult(
            symbol, False, "STALE_SYMBOL_PRICE", "DATA_QUALITY", latest, staleness, entry_blocked=True
        )
    latest_row = ordered.iloc[-1]
    values = pd.to_numeric(latest_row[["open", "high", "low", "close", "volume"]], errors="coerce")
    if values.isna().any() or (values[["open", "high", "low", "close"]] <= 0).any() or values["volume"] < 0:
        return TradeabilityResult(
            symbol, False, "INVALID_LATEST_ROW", "DATA_QUALITY", latest, staleness, entry_blocked=True
        )
    pending = str(event.get("status") or "").upper() in {"ANNOUNCED", "APPROVED"}
    return TradeabilityResult(
        symbol,
        True,
        "TRADEABLE",
        "COMPLETE",
        latest,
        staleness,
        successor_symbol=str(event.get("successor_symbol") or "") or None,
        entry_blocked=pending,
        detail="MATERIAL_CORPORATE_ACTION_REVIEW" if pending else None,
    )


def summarize(results: Mapping[str, TradeabilityResult]) -> dict:
    reasons: dict[str, int] = {}
    terminal: dict[str, dict] = {}
    for symbol, result in results.items():
        if not result.eligible:
            reasons[result.reason_code] = reasons.get(result.reason_code, 0) + 1
        if result.reason_code.startswith("TERMINAL_") or result.reason_code == "DELISTED_SECURITY":
            terminal[symbol] = result.to_dict()
    return {
        "evaluated": len(results),
        "eligible": sum(r.eligible for r in results.values()),
        "rejected": sum(not r.eligible for r in results.values()),
        "entry_blocked": sum(r.entry_blocked for r in results.values()),
        "rejection_counts": dict(sorted(reasons.items())),
        "terminal_detail": terminal,
    }
