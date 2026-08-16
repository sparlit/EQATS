"""
Order Book Cross-Impact & Almgren-Chriss Optimal Execution Engine.
Calculates cross-asset price decay, Almgren-Chriss optimal execution trajectories,
and LOB queue position fill delays.
"""

import math

def calculate_cross_asset_order_impact(order_size, liquidity_matrix=None):
    """
    Measures cross-impact price decay across correlated instruments.
    order_size: float
    liquidity_matrix: dict of symbol -> cross-impact factor
    """
    if not liquidity_matrix:
        liquidity_matrix = {"EURUSD": 0.0001, "GBPUSD": 0.00015, "USDCHF": -0.00012}

    impacts = {}
    for sym, factor in liquidity_matrix.items():
        impact_bps = math.sqrt(order_size) * factor * 10000.0
        impacts[sym] = round(impact_bps, 2)

    return impacts

def optimize_almgren_chriss_execution(total_shares, duration_periods=5, risk_aversion=1e-6, volatility=0.01, eta=2e-6):
    """
    Solves the Almgren-Chriss optimal execution trajectory.
    Balances market impact against volatility risk over discrete trading intervals.
    """
    if duration_periods <= 0:
        duration_periods = 1

    tau = 1.0  # Normalized time step
    kappa_sq = (risk_aversion * volatility ** 2) / eta if eta > 0 else 0.01
    kappa = math.sqrt(max(1e-6, kappa_sq))

    trajectory = []
    remaining = total_shares

    for t in range(duration_periods):
        time_left = duration_periods - t
        if math.sinh(kappa * duration_periods) != 0:
            slice_shares = total_shares * (math.sinh(kappa * time_left) - math.sinh(kappa * (time_left - 1))) / math.sinh(kappa * duration_periods)
        else:
            slice_shares = total_shares / duration_periods

        slice_shares = round(max(0.0, slice_shares), 2)
        remaining -= slice_shares
        trajectory.append({
            "period": t + 1,
            "shares_to_sell": slice_shares,
            "remaining_inventory": round(max(0.0, remaining), 2)
        })

    return trajectory

def estimate_queue_position_delay(book_depth_ahead, cancel_rate_per_sec=0.05, fill_rate_per_sec=10.0):
    """Computes expected fill delay in a Limit Order Book (LOB) queue."""
    effective_rate = fill_rate_per_sec + (book_depth_ahead * cancel_rate_per_sec)
    expected_delay_sec = book_depth_ahead / effective_rate if effective_rate > 0 else 999.0
    return {
        "depth_ahead": book_depth_ahead,
        "expected_delay_sec": round(expected_delay_sec, 2),
        "fill_probability_10s": round(min(1.0, 10.0 / max(0.1, expected_delay_sec)), 2)
    }
