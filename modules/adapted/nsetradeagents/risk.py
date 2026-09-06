import structlog
from app.core.config import settings
from app.portfolio.exits import stop_pct, target_pct

logger = structlog.get_logger()


def run_risk_check(
    ticker: str,
    current_price: float,
    portfolio_cash: float,
    open_positions: int,
    atr_pct: float | None = None,
    ticker_sector: str = "Unknown",
    open_position_sectors: list[str] | None = None,
) -> dict:
    """Apply the hard risk gates and size the position.

    Gates, in order: portfolio already full, price too high or position too
    small to be worth taking, and more than two positions in one sector.
    Sizing is a fixed fraction of starting capital, with an ATR-based stop.

    Returns {approved, block_reasons, quantity, position_size_inr,
    stop_loss, take_profit, notes}.
    """
    logger.info("risk_start", ticker=ticker, price=current_price)

    if current_price <= 0:
        logger.warning("risk_invalid_price", ticker=ticker, price=current_price)
        return {
            "approved": False,
            "block_reasons": ["invalid price — technical agent likely failed"],
            "quantity": 0,
            "position_size_inr": 0,
            "stop_loss": 0,
            "take_profit": 0,
            "notes": "",
        }

    block_reasons = []
    max_position_value = settings.starting_capital * settings.max_position_pct

    # Gate 1: max open positions
    if open_positions >= settings.max_positions:
        block_reasons.append(
            f"max positions reached ({open_positions}/{settings.max_positions})"
        )

    # Gate 2: can we afford at least 1 share within position limits,
    # and will the resulting position be meaningful (>= ₹5,000)?
    if current_price > max_position_value:
        block_reasons.append(
            f"stock price (₹{current_price}) exceeds max position size (₹{max_position_value:.0f})"
        )
    elif max_position_value < 5000:
        block_reasons.append(
            f"position size too small to be meaningful (₹{max_position_value:.0f} < ₹5,000)"
        )

    # Gate 3: max 2 positions per sector to ensure diversification
    if ticker_sector != "Unknown" and open_position_sectors:
        sector_count = open_position_sectors.count(ticker_sector)
        if sector_count >= 2:
            block_reasons.append(
                f"sector concentration limit reached ({ticker_sector}: {sector_count}/2)"
            )

    if block_reasons:
        logger.info("risk_blocked", ticker=ticker, reasons=block_reasons)
        return {
            "approved": False,
            "block_reasons": block_reasons,
            "quantity": 0,
            "position_size_inr": 0,
            "stop_loss": 0,
            "take_profit": 0,
            "notes": "",
        }

    # Position sizing — capped at max_position_pct of cash
    quantity = int(max_position_value / current_price)
    actual_position_value = quantity * current_price

    # Stop loss and take profit
    pct = stop_pct(atr_pct)
    stop_loss = round(current_price * (1 - pct), 2)
    take_profit = round(current_price * (1 + target_pct(atr_pct)), 2)
    risk_reward = round(target_pct(atr_pct) / pct, 2)

    notes = (
        f"Position: ₹{actual_position_value:.0f} ({actual_position_value/settings.starting_capital*100:.1f}% of portfolio) | "
        f"Risk/Reward: {risk_reward}x | "
        f"Stop: ₹{stop_loss} | Target: ₹{take_profit}"
    )

    logger.info(
        "risk_approved",
        ticker=ticker,
        quantity=quantity,
        position_value=actual_position_value,
        stop_loss=stop_loss,
    )

    return {
        "approved": True,
        "block_reasons": [],
        "quantity": quantity,
        "position_size_inr": actual_position_value,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "notes": notes,
    }
