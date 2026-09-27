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


"""Point-in-time fundamental gate for 6M and 12M promotion."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class FundamentalSnapshot:
    symbol: str
    as_of_date: str
    revenue_growth_pct: float
    profit_growth_pct: float
    roe_pct: float
    debt_to_equity: float
    operating_cash_flow_positive: bool
    promoter_pledge_pct: float
    governance_flag: bool = False
    sector_type: str = "NON_FINANCIAL"


@dataclass(frozen=True)
class FundamentalGate:
    passed: bool
    score: int
    reasons_for: tuple[str, ...]
    reasons_against: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate_fundamentals(snapshot: FundamentalSnapshot) -> FundamentalGate:
    checks = {
        "revenue_growth_positive": snapshot.revenue_growth_pct > 0,
        "profit_growth_positive": snapshot.profit_growth_pct > 0,
        "roe_at_least_12": snapshot.roe_pct >= 12,
        "operating_cash_flow_positive": snapshot.operating_cash_flow_positive,
        "promoter_pledge_at_most_10": snapshot.promoter_pledge_pct <= 10,
    }
    financial = snapshot.sector_type.upper() in {"BANK", "NBFC", "INSURANCE", "FINANCIAL"}
    if not financial:
        checks["debt_to_equity_at_most_1"] = snapshot.debt_to_equity <= 1
    critical = []
    if snapshot.governance_flag:
        critical.append("governance_risk_flag")
    if snapshot.promoter_pledge_pct > 25:
        critical.append("critical_promoter_pledge")
    if not financial and snapshot.debt_to_equity > 2:
        critical.append("critical_leverage")
    score = sum(checks.values())
    reasons_for = tuple(name for name, passed in checks.items() if passed)
    reasons_against = tuple([name for name, passed in checks.items() if not passed] + critical)
    return FundamentalGate(not critical and score >= 5, score, reasons_for, reasons_against)
