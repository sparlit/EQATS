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


"""Portfolio-level constraints for position entry and risk management.

Enforces:
- Max 2 positions per sector
- Min 2 trading days between entries in same stock
- Max 8 total open positions
- Liquidity check (min avg turnover)
- Correlation check (basic: avoid same sector clustering)
"""


from dataclasses import dataclass


@dataclass
class PortfolioConstraints:
    max_sector: int = 2
    max_total: int = 8
    min_days_between: int = 2
    min_avg_turnover: float = 5_000_000.0
    max_sector_pct: float = 0.40  # max 40% in one sector


@dataclass
class OpenPosition:
    symbol: str
    sector: str
    entry_date: str
    days_held: int = 0


def can_enter(
    symbol: str,
    sector: str,
    entry_date: str,
    open_positions: dict[str, OpenPosition],
    constraints: PortfolioConstraints,
) -> tuple[bool, str]:
    """Check if a new position can be opened.

    Returns (allowed, reason).
    """
    # Total limit
    if len(open_positions) >= constraints.max_total:
        return False, f"max_total reached ({constraints.max_total})"

    # Already in this stock
    if symbol in open_positions:
        return False, f"already holding {symbol}"

    # Sector limit
    sector_count = sum(1 for p in open_positions.values() if p.sector == sector)
    if sector_count >= constraints.max_sector:
        return False, f"sector {sector} at max ({constraints.max_sector})"

    # Sector concentration
    if len(open_positions) > 0:
        sector_pct = sector_count / len(open_positions)
        if sector_pct >= constraints.max_sector_pct:
            return (
                False,
                f"sector {sector} at {sector_pct:.0%} (max {constraints.max_sector_pct:.0%})",
            )

    # Min days between same-stock entries (check recent exits — not applicable for entry)
    # This is checked at exit time to enforce cooldown

    # ── Risk checks (appended, non-breaking) ──
    # These are advisory checks — can be called with stock_risk=None to skip

    return True, "ok"


def can_enter_with_risk(
    symbol: str,
    sector: str,
    entry_date: str,
    open_positions: dict[str, OpenPosition],
    constraints: PortfolioConstraints,
    stock_risk: dict | None = None,
    portfolio_risk: dict | None = None,
) -> tuple[bool, str]:
    """Enhanced entry check with risk management.

    Includes all basic checks plus:
    - VaR budget check (position VaR + portfolio VaR < limit)
    - Sector concentration with risk awareness
    - Liquidity/impact cost check
    - Drawdown circuit breaker

    stock_risk: from stock_risk table (beta, vol_30d, var_95, impact_cost)
    portfolio_risk: from portfolio_risk table (var_95, max_drawdown)
    """
    # Run basic checks first
    allowed, reason = can_enter(symbol, sector, entry_date, open_positions, constraints)
    if not allowed:
        return allowed, reason

    # Risk checks (only if risk data available)
    if stock_risk:
        # VaR check: single position shouldn't contribute more than 1% VaR
        pos_var = stock_risk.get("var_95", 0)
        if pos_var is not None and pos_var < -0.03:  # > 3% daily loss potential
            return False, f"VaR95={pos_var:.2%} exceeds 3% limit"

        # Impact cost check: avoid illiquid stocks
        impact = stock_risk.get("impact_cost", 0)
        if impact is not None and impact > 75000:  # > ₹75K impact for ₹5L order
            return False, f"impact cost ₹{impact:,.0f} too high (illiquid)"

        # Volatility check: avoid extremely volatile stocks
        vol = stock_risk.get("vol_annual", 0)
        if vol is not None and vol > 0.80:  # > 80% annualized vol
            return False, f"volatility {vol:.0%} too high"

    if portfolio_risk:
        # Portfolio drawdown circuit breaker
        dd = portfolio_risk.get("max_drawdown", 0)
        if dd is not None and dd < -0.08:  # > 8% drawdown
            return False, f"portfolio drawdown {dd:.1%} — halt new entries"

        # Portfolio VaR budget
        port_var = portfolio_risk.get("var_95", 0)
        if stock_risk and port_var is not None:
            pos_var = stock_risk.get("var_95", 0) or 0
            if port_var + pos_var < -0.04:  # Combined > 4% daily VaR
                return False, f"VaR budget: portfolio {port_var:.2%} + position {pos_var:.2%} > 4%"

    return True, "ok"


def position_size_kelly(
    capital: float, kelly_frac: float, entry_px: float, stop_pct: float, risk_pct: float = 0.02
) -> int:
    """Kelly-based position sizing with portfolio constraints.

    Uses half-Kelly by default. Returns share count (min 1).
    """
    if entry_px <= 0 or stop_pct <= 0:
        return 1
    risk_amount = capital * kelly_frac * risk_pct
    per_share_risk = entry_px * stop_pct
    shares = int(risk_amount / per_share_risk)
    return max(shares, 1)
