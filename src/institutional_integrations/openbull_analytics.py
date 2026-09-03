"""
OpenBull Analytics Engine.
Provides Options Max Pain Strike Engine and Synthetic Futures Pricing (Put-Call Parity).
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("OpenBullAnalytics")


def calculate_max_pain(option_chain: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Computes Max Pain strike (strike where total option-buyer dollar loss is maximized / writer loss is minimized).
    option_chain: list of dicts with keys 'strike', 'ce_oi', 'pe_oi'.
    """
    if not option_chain:
        return {"max_pain_strike": 0.0, "pcr_oi": 0.0, "chain_pain": []}
    strikes = sorted(list(set(row["strike"] for row in option_chain if "strike" in row)))
    if not strikes:
        return {"max_pain_strike": 0.0, "pcr_oi": 0.0, "chain_pain": []}
    ce_oi_map = {row["strike"]: float(row.get("ce_oi", 0.0)) for row in option_chain if "strike" in row}
    pe_oi_map = {row["strike"]: float(row.get("pe_oi", 0.0)) for row in option_chain if "strike" in row}
    total_ce_oi = sum(ce_oi_map.values())
    total_pe_oi = sum(pe_oi_map.values())
    pcr_oi = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0.0
    pain_curve = []
    for candidate in strikes:
        total_pain = 0.0
        for held_strike in strikes:
            if candidate > held_strike:
                total_pain += (candidate - held_strike) * ce_oi_map[held_strike]
            if candidate < held_strike:
                total_pain += (held_strike - candidate) * pe_oi_map[held_strike]
        pain_curve.append(
            {
                "strike": candidate,
                "ce_oi": ce_oi_map[candidate],
                "pe_oi": pe_oi_map[candidate],
                "total_pain": round(total_pain, 2),
            },
        )
    max_pain_row = min(pain_curve, key=lambda r: r["total_pain"])
    return {
        "max_pain_strike": max_pain_row["strike"],
        "min_pain_amount": max_pain_row["total_pain"],
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "pcr_oi": pcr_oi,
        "chain_pain": pain_curve,
    }


def calculate_synthetic_future_price(
    atm_strike: float, call_ltp: float, put_ltp: float, spot_price: float,
) -> dict[str, float]:
    """
    Computes Synthetic Future Price via Put-Call Parity:
    Synthetic Price = Strike + Call LTP - Put LTP
    Basis = Synthetic Price - Spot Price (Cost of carry indicator)
    """
    synth_price = atm_strike + call_ltp - put_ltp
    basis = synth_price - spot_price
    return {
        "atm_strike": round(atm_strike, 2),
        "synthetic_future_price": round(synth_price, 2),
        "basis": round(basis, 2),
        "spot_price": round(spot_price, 2),
    }
