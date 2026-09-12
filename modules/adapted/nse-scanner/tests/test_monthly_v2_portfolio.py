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


from v2.horizon_promotion import PromotionDecision
from v2.monthly_portfolio import render_monthly_portfolio_message
from v2.portfolio_performance import PortfolioSnapshot


def test_monthly_message_labels_model_pnl_and_promotion():
    snapshot = PortfolioSnapshot("2026-08-31", 300000, 60000, 64000, 2500, 1500, 4000, 1.3333, 3000, 800, 1, 0)
    decision = PromotionDecision(
        "id",
        "ABC",
        "SWING_1_3M",
        "POSITIONAL_3_6M",
        "PROMOTE",
        24,
        1.2,
        True,
        True,
        True,
        False,
        False,
        ("all_carry_forward_rules_passed",),
    )
    message = render_monthly_portfolio_message("2026-08-31", snapshot, [decision])
    assert "Model portfolio - not broker-account P&L" in message
    assert "ABC" in message
    assert "PROMOTE -> Positional (3-6M)" in message
    assert "never widens a stop" in message
