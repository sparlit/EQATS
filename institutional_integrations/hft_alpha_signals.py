"""
High-Frequency Microstructure Alpha Signal Generator.
Calculates sub-second tick momentum, detects iceberg order refills,
and computes composite order flow toxicity indices.
"""

import math
import time

def compute_microstructure_momentum(ticks_series, window_ms=500):
    """
    Calculates high-frequency tick momentum over sub-second windows.
    ticks_series: list of dicts {'price', 'volume', 'timestamp_ms'}
    """
    if not ticks_series or len(ticks_series) < 2:
        return {"momentum": 0.0, "signal": "NEUTRAL"}

    now_ms = ticks_series[-1].get("timestamp_ms", int(time.time() * 1000))
    cutoff_ms = now_ms - window_ms

    recent_ticks = [t for t in ticks_series if t.get("timestamp_ms", now_ms) >= cutoff_ms]
    if len(recent_ticks) < 2:
        recent_ticks = ticks_series[-5:]

    delta_p = recent_ticks[-1]['price'] - recent_ticks[0]['price']
    total_vol = sum(t.get('volume', 1.0) for t in recent_ticks)

    momentum_score = (delta_p / recent_ticks[0]['price']) * math.log(1.0 + total_vol) * 10000.0
    signal = "BULLISH_BURST" if momentum_score > 0.5 else ("BEARISH_BURST" if momentum_score < -0.5 else "NEUTRAL")

    return {
        "momentum_score": round(momentum_score, 4),
        "tick_count_window": len(recent_ticks),
        "signal": signal
    }

def detect_iceberg_liquidity_refill(tape_prints, dom_depth):
    """Identifies hidden institutional iceberg orders refilling at price levels."""
    if not tape_prints or not dom_depth:
        return {"iceberg_detected": False, "iceberg_price": 0.0, "side": "NONE"}

    # Detect price level with volume prints exceeding DOM queue depth
    for print_item in tape_prints[-10:]:
        p = print_item.get('price', 0.0)
        v = print_item.get('volume', 0.0)
        side = print_item.get('side', 'BUY')

        dom_queue = dom_depth.get('asks', []) if side == 'BUY' else dom_depth.get('bids', [])
        level_qty = sum(q for price, q in dom_queue if abs(price - p) < 0.0001)

        if v > level_qty * 1.5 and level_qty > 0:
            return {
                "iceberg_detected": True,
                "iceberg_price": round(p, 5),
                "side": side,
                "estimated_hidden_qty": round(v - level_qty, 2)
            }

    return {"iceberg_detected": False, "iceberg_price": 0.0, "side": "NONE"}

def score_order_flow_toxicity_index(vpin_score, dom_imbalance_ratio):
    """Combines VPIN toxicity score and DOM imbalance ratio into unified flow toxicity index."""
    combined_toxicity = vpin_score * 0.6 + abs(dom_imbalance_ratio) * 0.4
    risk_level = "EXTREME_TOXICITY" if combined_toxicity > 0.65 else ("MODERATE_TOXICITY" if combined_toxicity > 0.40 else "BENIGN_FLOW")

    return {
        "flow_toxicity_index": round(combined_toxicity, 4),
        "risk_level": risk_level,
        "action": "HALT_MARKET_MAKING" if combined_toxicity > 0.70 else "PROCEED"
    }
