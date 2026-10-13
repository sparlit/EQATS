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


"""Kelly criterion position sizing for conviction-scored signals.

Half-Kelly is used by default for safety margin.
"""


def kelly_fraction(
    win_rate: float, avg_win_bps: float, avg_loss_bps: float, fraction: float = 0.5
) -> float:
    """Compute fractional Kelly bet size.

    f* = (p * b - q) / b
    where p = win_rate, b = avg_win / avg_loss, q = 1 - p.

    Args:
        win_rate: historical win probability (0-1)
        avg_win_bps: average winning trade in bps
        avg_loss_bps: average losing trade in bps (positive value)
        fraction: Kelly fraction (0.5 = half-Kelly)

    Returns:
        Fraction of capital to risk per trade (0.0 if inputs invalid).
    """
    if avg_loss_bps <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    b = avg_win_bps / avg_loss_bps
    q = 1.0 - win_rate
    full_kelly = (win_rate * b - q) / b
    if full_kelly <= 0:
        return 0.0
    return round(full_kelly * fraction, 6)


def kelly_position(
    capital: float, risk_pct: float, entry_px: float, stop_pct: float, kelly_frac: float
) -> int:
    """Convert Kelly fraction to share count.

    Position size = (capital × kelly_frac × risk_pct) / (entry_px × stop_pct)

    Args:
        capital: total portfolio capital in INR
        risk_pct: max risk per trade as fraction (e.g. 0.02 = 2%)
        entry_px: expected entry price
        stop_pct: stop-loss as fraction (e.g. 0.07 = 7%)
        kelly_frac: output from kelly_fraction()

    Returns:
        Number of shares (rounded down, min 1).
    """
    if entry_px <= 0 or stop_pct <= 0 or kelly_frac <= 0:
        return 1
    risk_amount = capital * kelly_frac * risk_pct
    per_share_risk = entry_px * stop_pct
    shares = int(risk_amount / per_share_risk)
    return max(shares, 1)


# Default parameters for Indian equities
DEFAULT_WIN_RATE = 0.43
DEFAULT_AVG_WIN_BPS = 250.0
DEFAULT_AVG_LOSS_BPS = 165.0
DEFAULT_KELLY_FRAC = 0.5


def dynamic_kelly_params(engine) -> tuple[float, float, float]:
    """Compute Kelly parameters from actual settled paper trades.

    Returns (win_rate, avg_win_bps, avg_loss_bps).
    Falls back to defaults if fewer than 20 settled trades.
    """
    import sqlalchemy as sa

    try:
        with engine.connect() as conn:
            r = (
                conn.execute(
                    sa.text("""
                SELECT
                    COUNT(*) as n,
                    AVG(CASE WHEN realized_net_bps > 0 THEN realized_net_bps END) as avg_win,
                    AVG(CASE WHEN realized_net_bps <= 0 THEN ABS(realized_net_bps) END) as avg_loss,
                    SUM(CASE WHEN realized_net_bps > 0 THEN 1 ELSE 0 END)::float /
                        NULLIF(COUNT(*), 0) as win_rate
                FROM paper_signals
                WHERE status = 'SETTLED' AND realized_net_bps IS NOT NULL
            """)
                )
                .mappings()
                .fetchone()
            )
        n = r["n"] or 0
        if n < 20 or not r["win_rate"]:
            return DEFAULT_WIN_RATE, DEFAULT_AVG_WIN_BPS, DEFAULT_AVG_LOSS_BPS
        return (
            float(r["win_rate"]),
            float(r["avg_win"] or DEFAULT_AVG_WIN_BPS),
            float(r["avg_loss"] or DEFAULT_AVG_LOSS_BPS),
        )
    except Exception:
        return DEFAULT_WIN_RATE, DEFAULT_AVG_WIN_BPS, DEFAULT_AVG_LOSS_BPS
