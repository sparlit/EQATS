import structlog
from app.core.config import settings

logger = structlog.get_logger()

FINANCIAL_SECTORS = {"Financial Services", "Banking"}


def run_fundamental_check(ticker: str, ticker_info: dict | None) -> dict:
    """Reject structurally broken companies before they reach scoring.

    Checks market cap, debt/equity (skipped for financials, where leverage
    is normal) and return on equity. Weak revenue growth is flagged but
    never blocks. Missing data approves — an unknown company is not a
    rejected one.

    Returns {approved, block_reasons, notes}.
    """
    logger.info("fundamental_start", ticker=ticker)

    if not ticker_info:
        logger.warning("fundamental_no_data", ticker=ticker)
        return {"approved": True, "block_reasons": [], "notes": "No data - skipping"}

    block_reasons = []
    flags = []
    sector = ticker_info.get("sector") or ""
    is_financial = sector in FINANCIAL_SECTORS

    # Market cap - avoid micro-caps that are illiquid and manipulation-prone
    market_cap = ticker_info.get("marketCap")
    if market_cap is not None and market_cap < settings.min_market_cap:
        block_reasons.append(
            f"Market cap is too small (₹{market_cap / 1_00_00_000:.0f} Cr) — micro-cap risk"
        )

    # Debt/equity - skip for financial sector (banks leverage by nature)
    if not is_financial:
        de = ticker_info.get("debtToEquity")  # yfinance returns as %, 200 = 2.0x
        if de is not None and de > settings.max_debt_to_equity:
            block_reasons.append(f"high debt/equity ({de / 100:.1f}x) - overleveraged")

    # Return on equity
    roe = ticker_info.get("returnOnEquity")
    if roe is not None:
        if roe < 0:
            block_reasons.append(
                f"negative ROE ({roe:.1%}) - destroying shareholder value"
            )
        elif roe < settings.min_roe:
            flags.append(f"low ROE ({roe:.1%})")

    # Revenue growth - soft flag only, don't block (swing trade, not value investing)
    rev_growth = ticker_info.get("revenueGrowth")
    if rev_growth is not None and rev_growth < settings.max_revenue_decline_pct:
        flags.append(f"declining revenue ({rev_growth:.1%} YoY)")

    # P/E - flag extreme overvaluation only
    pe = ticker_info.get("trailingPE")
    if pe is not None and pe > settings.max_pe_ratio:
        flags.append(f"stretched valuation (P/E {pe:.0f}x)")

    approved = len(block_reasons) == 0
    notes = "Flags: " + " | ".join(flags) if flags else "clean"

    if approved:
        logger.info("fundamental_approved", ticker=ticker, notes=notes)
    else:
        logger.info("fundamental_blocked", ticker=ticker, reasons=block_reasons)

    return {"approved": approved, "block_reasons": block_reasons, "notes": notes}
