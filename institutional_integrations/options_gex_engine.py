"""
Options Analytics & Market Maker Gamma Exposure (GEX) Engine.
Calculates Black-Scholes Greeks, aggregate Market Maker Gamma Exposure (GEX),
and Zero-Gamma flip levels across strike prices.
"""

import math


<<<<<<< Updated upstream
def compute_black_scholes_greeks(spot, strike, tte_years, rate=0.04, iv=0.20, option_type="CALL"):
=======
def compute_black_scholes_greeks(
    spot, strike, tte_years, rate=0.04, iv=0.20, option_type="CALL"
):
>>>>>>> Stashed changes
    """Calculates Black-Scholes NPV, Delta, Gamma, Vega, Theta, and Rho."""
    if tte_years <= 0 or iv <= 0:
        return {
            "npv": max(0.0, spot - strike),
            "delta": 1.0 if spot > strike else 0.0,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
        }

    safe_strike = max(1e-5, strike)
    safe_tte = max(1e-5, tte_years)
    safe_iv = max(1e-5, iv)
    d1 = (math.log(spot / safe_strike) + (rate + 0.5 * safe_iv**2) * safe_tte) / (
        safe_iv * math.sqrt(safe_tte)
    )
    d2 = d1 - iv * math.sqrt(tte_years)

    # Standard normal CDF approximation
    def norm_cdf(x):
        return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

    # Standard normal PDF
    def norm_pdf(x):
        return math.exp(-0.5 * x**2) / math.sqrt(2.0 * math.pi)

    pdf_d1 = norm_pdf(d1)

    if option_type.upper() == "CALL":
        npv = spot * norm_cdf(d1) - strike * math.exp(-rate * tte_years) * norm_cdf(d2)
        delta = norm_cdf(d1)
    else:  # PUT
        npv = strike * math.exp(-rate * tte_years) * norm_cdf(-d2) - spot * norm_cdf(
            -d1
        )
        delta = norm_cdf(d1) - 1.0

    gamma = pdf_d1 / (spot * iv * math.sqrt(tte_years))
    vega = spot * pdf_d1 * math.sqrt(tte_years) / 100.0
    theta = (
        -spot * pdf_d1 * iv / (2 * math.sqrt(tte_years))
        - rate * strike * math.exp(-rate * tte_years) * norm_cdf(d2)
    ) / 365.0

    return {
        "npv": round(npv, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "vega": round(vega, 4),
        "theta": round(theta, 4),
    }


def calculate_aggregate_gex(option_chain):
    """
    Calculates total Market Maker Gamma Exposure (GEX) across option strike prices.
    option_chain: list of dicts {'strike', 'call_open_interest', 'put_open_interest', 'gamma'}
    """
    total_gex = 0.0
    gex_by_strike = {}

    for opt in option_chain:
        strike = opt["strike"]
        call_oi = opt.get("call_open_interest", 0)
        put_oi = opt.get("put_open_interest", 0)
        gamma = opt.get("gamma", 0.001)

        # Market makers are long calls (+GEX) and short puts (-GEX)
        strike_gex = (call_oi * gamma - put_oi * gamma) * strike * 100.0
        gex_by_strike[strike] = round(strike_gex, 2)
        total_gex += strike_gex

    return {
        "total_gex_usd": round(total_gex, 2),
        "regime": "LONG_GAMMA_STABILIZING"
        if total_gex >= 0
        else "SHORT_GAMMA_VOLATILITY",
        "gex_by_strike": gex_by_strike,
    }


def detect_gamma_flip_level(gex_profile):
    """Detects the exact strike price where aggregate dealer Gamma Exposure flips from positive to negative."""
    strikes = sorted(gex_profile.keys())
    if not strikes:
        return 0.0

    for i in range(len(strikes) - 1):
        s1, s2 = strikes[i], strikes[i + 1]
        g1, g2 = gex_profile[s1], gex_profile[s2]
        if (g1 >= 0 and g2 < 0) or (g1 <= 0 and g2 > 0):
            # Interpolate zero-crossing strike
            flip_strike = s1 + (s2 - s1) * (abs(g1) / (abs(g1) + abs(g2)))
            return round(flip_strike, 2)

    return round(strikes[len(strikes) // 2], 2)
