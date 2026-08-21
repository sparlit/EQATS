"""
Order Flow Toxicity & Market Microstructure Engine.
Calculates Volume-Synchronized Probability of Toxicity (VPIN), DOM depth imbalances,
and microsecond queue depletion pressure.
"""



def calculate_vpin(volume_buy_list, volume_sell_list, bucket_size=100.0):
    """
    Computes Volume-Synchronized Probability of Toxicity (VPIN).
    VPIN = sum(|V_buy - V_sell|) / (N * bucket_size)
    Returns: float [0.0, 1.0] where > 0.60 indicates extreme flow toxicity / liquidity crash risk.
    """
    n = min(len(volume_buy_list), len(volume_sell_list))
    if n == 0 or bucket_size <= 0:
        return 0.15

    total_abs_imbalance = sum(
        abs(volume_buy_list[i] - volume_sell_list[i]) for i in range(n)
    )
    vpin = total_abs_imbalance / (n * bucket_size)
    return round(min(1.0, max(0.0, vpin)), 4)


def detect_bid_ask_imbalance(order_book_depth):
    """
    Measures bid/ask depth volume delta ratio across DOM levels.
    order_book_depth: dict with {'bids': [(price, qty)], 'asks': [(price, qty)]}
    """
    bids = order_book_depth.get("bids", [])
    asks = order_book_depth.get("asks", [])

    total_bid_qty = sum(qty for _, qty in bids)
    total_ask_qty = sum(qty for _, qty in asks)

    total_qty = total_bid_qty + total_ask_qty
    if total_qty == 0:
        return {"imbalance_ratio": 0.0, "dominant_side": "NEUTRAL"}

    imbalance_ratio = (total_bid_qty - total_ask_qty) / total_qty
    dominant_side = (
        "BUY_DOMINANT"
        if imbalance_ratio > 0.20
        else ("SELL_DOMINANT" if imbalance_ratio < -0.20 else "NEUTRAL")
    )

    return {
        "imbalance_ratio": round(imbalance_ratio, 4),
        "dominant_side": dominant_side,
        "total_bid_qty": total_bid_qty,
        "total_ask_qty": total_ask_qty,
    }


def predict_short_term_book_pressure(
    bid_qty, ask_qty, cancel_rate_bid=0.05, cancel_rate_ask=0.05
):
    """Predicts microsecond price impact from order queue depletion and cancellation rates."""
    effective_bids = bid_qty * (1.0 - cancel_rate_bid)
    effective_asks = ask_qty * (1.0 - cancel_rate_ask)

    pressure = (effective_bids - effective_asks) / max(
        1.0, effective_bids + effective_asks
    )
    return {
        "pressure_score": round(pressure, 4),
        "expected_direction": "UPWARD_PRESSURE"
        if pressure > 0.15
        else ("DOWNWARD_PRESSURE" if pressure < -0.15 else "BALANCED"),
    }
