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


"""
AXIOM Risk Calculator — position sizing and trade validation.
Rules per CLAUDE.md:
  - Never risk > 2% capital per trade
  - Max 4% daily (2 positions)
  - Min R:R 2:1 (BULLISH), 2.5:1 (NEUTRAL)
  - Never average down
"""

from dataclasses import dataclass

from config import CAPITAL_RISK_PCT, MAX_DAILY_RISK_PCT


@dataclass
class RiskResult:
    symbol: str
    entry: float
    stop: float
    target: float
    capital: float
    shares: int
    risk_amount: float  # ₹ at risk
    risk_pct: float  # % of capital
    reward: float  # ₹ potential reward
    rr_ratio: float  # reward:risk
    passed: bool  # cleared all checks
    verdict: str  # APPROVED / REJECTED
    rejection_reasons: list[str]
    warnings: list[str]


def calculate_position(
    entry: float,
    stop: float,
    target: float,
    capital: float,
    symbol: str = "",
    regime: str = "BULLISH",
) -> RiskResult:
    """
    Calculate position size and validate against all risk rules.

    Formula: shares = (capital × 0.02) / (entry - stop)
    """
    rejections: list[str] = []
    warnings: list[str] = []

    # ── Input validation ──
    if entry <= 0:
        rejections.append("Entry price must be > 0")
    if stop <= 0:
        rejections.append("Stop price must be > 0")
    if stop >= entry:
        rejections.append(f"Stop ({stop:.2f}) must be below entry ({entry:.2f})")
    if capital <= 0:
        rejections.append("Capital must be > 0")

    if rejections:
        return RiskResult(
            symbol=symbol,
            entry=entry,
            stop=stop,
            target=target,
            capital=capital,
            shares=0,
            risk_amount=0,
            risk_pct=0,
            reward=0,
            rr_ratio=0,
            passed=False,
            verdict="REJECTED",
            rejection_reasons=rejections,
            warnings=warnings,
        )

    risk_per_share = entry - stop
    max_risk_amt = capital * CAPITAL_RISK_PCT  # 2% of capital
    shares = int(max_risk_amt / risk_per_share)
    risk_amount = shares * risk_per_share
    risk_pct = (risk_amount / capital) * 100

    reward = shares * (target - entry) if target > entry else 0.0
    rr_ratio = round((target - entry) / risk_per_share, 2) if target > entry else 0.0

    # ── Hard rejection rules ──
    if risk_pct > 2.05:  # small float buffer
        rejections.append(f"Risk {risk_pct:.2f}% exceeds 2% limit")

    if shares <= 0:
        rejections.append("Position size rounds to 0 shares — stop too wide")

    # Min R:R by regime
    min_rr = 2.5 if regime == "NEUTRAL" else 2.0
    if target > entry and rr_ratio < min_rr:
        rejections.append(f"R:R {rr_ratio:.2f} below minimum {min_rr} for {regime} regime")

    # ── Soft warnings ──
    if risk_pct < 1.0:
        warnings.append(f"Risk {risk_pct:.2f}% is low — consider wider stop or more capital")
    if target <= entry:
        warnings.append("No target set — R:R cannot be calculated")
    if (entry - stop) / entry > 0.05:
        warnings.append(f"Stop is {(entry - stop) / entry * 100:.1f}% below entry — unusually wide")

    passed = len(rejections) == 0
    verdict = "APPROVED ✓" if passed else "REJECTED ✗"

    return RiskResult(
        symbol=symbol,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2),
        capital=round(capital, 2),
        shares=shares,
        risk_amount=round(risk_amount, 2),
        risk_pct=round(risk_pct, 2),
        reward=round(reward, 2),
        rr_ratio=rr_ratio,
        passed=passed,
        verdict=verdict,
        rejection_reasons=rejections,
        warnings=warnings,
    )


def validate_risk(entry: float, stop: float, capital: float) -> bool:
    """Quick boolean check — is this trade within 2% risk?"""
    if stop >= entry or capital <= 0:
        return False
    risk = (entry - stop) * int((capital * CAPITAL_RISK_PCT) / (entry - stop))
    return (risk / capital) <= CAPITAL_RISK_PCT
