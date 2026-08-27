"""
Institutional Options & Derivatives Engine.
Adapted from Fincept Terminal options/derivatives code (ft.txt).
Provides high-precision Black-Scholes-Merton pricing, full Option Greeks suite,
Implied Volatility Surface modeling, Gamma Exposure (GEX) analytics, and Options Strategy Simulation.
"""

import math
import logging
from typing import Dict, List, Any, Tuple
import numpy as np

_log = logging.getLogger(__name__)

# Cumulative Distribution Function for Normal Distribution
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

# Probability Density Function for Normal Distribution
def _norm_pdf(x: float) -> float:
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


class OptionsPricingEngine:
    """
    Black-Scholes-Merton Option Pricing & Implied Volatility Solver Engine.
    """

    @staticmethod
    def black_scholes(
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        volatility: float,
        dividend_yield: float = 0.0,
        option_type: str = "call"
    ) -> float:
        """
        Calculates Black-Scholes-Merton option price for Call or Put.
        """
        if time_to_expiry <= 0.0 or volatility <= 0.0 or spot <= 0.0 or strike <= 0.0:
            if option_type.lower() == "call":
                return max(0.0, spot - strike)
            else:
                return max(0.0, strike - spot)

        S = float(spot)
        K = float(strike)
        T = float(time_to_expiry)
        r = float(risk_free_rate)
        v = float(volatility)
        q = float(dividend_yield)

        d1 = (math.log(S / K) + (r - q + 0.5 * v * v) * T) / (v * math.sqrt(T))
        d2 = d1 - v * math.sqrt(T)

        if option_type.lower() in ["call", "c"]:
            price = S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
        else:
            price = K * math.exp(-r * T) * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)

        return float(price)

    @staticmethod
    def calculate_greeks(
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        volatility: float,
        dividend_yield: float = 0.0,
        option_type: str = "call"
    ) -> Dict[str, float]:
        """
        Calculates full suite of 1st, 2nd, and 3rd order Option Greeks.
        Returns: Delta, Gamma, Theta, Vega, Rho, Vanna, Charm, Speed, Zomma, Color.
        """
        if time_to_expiry <= 0.0001 or volatility <= 0.0001 or spot <= 0.0 or strike <= 0.0:
            is_call = option_type.lower() in ["call", "c"]
            delta = 1.0 if (is_call and spot > strike) else (-1.0 if (not is_call and spot < strike) else 0.0)
            return {
                "delta": delta, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0,
                "vanna": 0.0, "charm": 0.0, "speed": 0.0, "zomma": 0.0, "color": 0.0
            }

        S = float(spot)
        K = float(strike)
        T = float(time_to_expiry)
        r = float(risk_free_rate)
        v = float(volatility)
        q = float(dividend_yield)
        is_call = option_type.lower() in ["call", "c"]

        sqrt_T = math.sqrt(T)
        d1 = (math.log(S / K) + (r - q + 0.5 * v * v) * T) / (v * sqrt_T)
        d2 = d1 - v * sqrt_T

        pdf_d1 = _norm_pdf(d1)
        cdf_d1 = _norm_cdf(d1)
        cdf_d2 = _norm_cdf(d2)
        cdf_neg_d1 = _norm_cdf(-d1)
        cdf_neg_d2 = _norm_cdf(-d2)

        exp_qT = math.exp(-q * T)
        exp_rT = math.exp(-r * T)

        # 1st Order Greeks
        if is_call:
            delta = exp_qT * cdf_d1
            rho = K * T * exp_rT * cdf_d2 / 100.0
        else:
            delta = -exp_qT * cdf_neg_d1
            rho = -K * T * exp_rT * cdf_neg_d2 / 100.0

        gamma = (exp_qT * pdf_d1) / (S * v * sqrt_T)
        vega = (S * exp_qT * pdf_d1 * sqrt_T) / 100.0

        # Theta (1-day theta)
        theta_call = (- (S * v * exp_qT * pdf_d1) / (2.0 * sqrt_T)
                      + q * S * exp_qT * cdf_d1
                      - r * K * exp_rT * cdf_d2) / 365.0
        theta_put = (- (S * v * exp_qT * pdf_d1) / (2.0 * sqrt_T)
                     - q * S * exp_qT * cdf_neg_d1
                     + r * K * exp_rT * cdf_neg_d2) / 365.0
        theta = theta_call if is_call else theta_put

        # 2nd Order & Higher Order Greeks
        vanna = -exp_qT * pdf_d1 * (d2 / v)
        if is_call:
            charm = q * exp_qT * cdf_d1 - exp_qT * pdf_d1 * (2.0 * (r - q) * T - d2 * v * sqrt_T) / (2.0 * T * v * sqrt_T)
        else:
            charm = -q * exp_qT * cdf_neg_d1 - exp_qT * pdf_d1 * (2.0 * (r - q) * T - d2 * v * sqrt_T) / (2.0 * T * v * sqrt_T)

        speed = -gamma / S * (d1 / (v * sqrt_T) + 1.0)
        zomma = gamma * (d1 * d2 - 1.0) / v
        color = -gamma / (2.0 * T) * (1.0 + d1 * (2.0 * (r - q) * T - d2 * v * sqrt_T) / (v * sqrt_T))

        return {
            "delta": float(delta),
            "gamma": float(gamma),
            "theta": float(theta),
            "vega": float(vega),
            "rho": float(rho),
            "vanna": float(vanna),
            "charm": float(charm),
            "speed": float(speed),
            "zomma": float(zomma),
            "color": float(color)
        }

    @staticmethod
    def implied_volatility(
        market_price: float,
        spot: float,
        strike: float,
        time_to_expiry: float,
        risk_free_rate: float,
        dividend_yield: float = 0.0,
        option_type: str = "call"
    ) -> float:
        """
        Solves for Implied Volatility using Newton-Raphson with Bisection fallback.
        """
        if market_price <= 0.0 or time_to_expiry <= 0.0:
            return 0.0

        is_call = option_type.lower() in ["call", "c"]
        intrinsic = max(0.0, spot - strike) if is_call else max(0.0, strike - spot)
        if market_price < intrinsic:
            return 0.0

        vol = 0.25  # initial guess 25%
        for _ in range(50):
            price = OptionsPricingEngine.black_scholes(spot, strike, time_to_expiry, risk_free_rate, vol, dividend_yield, option_type)
            greeks = OptionsPricingEngine.calculate_greeks(spot, strike, time_to_expiry, risk_free_rate, vol, dividend_yield, option_type)
            vega = greeks["vega"] * 100.0  # raw vega
            diff = price - market_price

            if abs(diff) < 1e-6:
                return float(vol)

            if abs(vega) > 1e-8:
                vol -= diff / vega
                if vol <= 0.001 or vol > 5.0:
                    break
            else:
                break

        # Bisection fallback
        low, high = 0.0001, 5.0
        for _ in range(60):
            mid = 0.5 * (low + high)
            p = OptionsPricingEngine.black_scholes(spot, strike, time_to_expiry, risk_free_rate, mid, dividend_yield, option_type)
            if abs(p - market_price) < 1e-5:
                return float(mid)
            if p > market_price:
                high = mid
            else:
                low = mid

        return float(0.5 * (low + high))


class GammaExposureAnalyzer:
    """
    Gamma Exposure (GEX) & Market Maker Hedging Dynamics Analyzer.
    Identifies market maker gamma positioning, zero gamma flip level, and volatility regime.
    """

    @staticmethod
    def calculate_gex_profile(
        spot_price: float,
        option_chain: List[Dict[str, Any]],
        risk_free_rate: float = 0.05
    ) -> Dict[str, Any]:
        """
        Calculates aggregate GEX, Call GEX, Put GEX, and locates the Gamma Flip Level.
        option_chain expected item format:
          {'strike': float, 'type': 'call'/'put', 'open_interest': float, 'iv': float, 'expiry_days': float}
        """
        if not option_chain or spot_price <= 0.0:
            return {
                "total_gex": 0.0, "call_gex": 0.0, "put_gex": 0.0,
                "gamma_flip_level": spot_price, "regime": "NEUTRAL"
            }

        total_gex = 0.0
        call_gex = 0.0
        put_gex = 0.0
        strike_gex_map: Dict[float, float] = {}

        for opt in option_chain:
            strike = float(opt.get("strike", spot_price))
            opt_type = str(opt.get("type", "call")).lower()
            oi = float(opt.get("open_interest", 0.0))
            iv = float(opt.get("iv", 0.20))
            days = float(opt.get("expiry_days", 30.0))
            T = max(days / 365.0, 0.001)

            greeks = OptionsPricingEngine.calculate_greeks(
                spot=spot_price, strike=strike, time_to_expiry=T,
                risk_free_rate=risk_free_rate, volatility=iv, option_type=opt_type
            )
            gamma = greeks["gamma"]

            # Standard GEX formula: Gamma * OI * Contract Multiplier (100) * Spot * Spot * 0.01
            # Call OI is long market maker (+), Put OI is short market maker (-)
            contract_gex = gamma * oi * 100.0 * spot_price * spot_price * 0.01
            if opt_type in ["call", "c"]:
                call_gex += contract_gex
                strike_gex_map[strike] = strike_gex_map.get(strike, 0.0) + contract_gex
            else:
                put_gex -= contract_gex
                strike_gex_map[strike] = strike_gex_map.get(strike, 0.0) - contract_gex

        total_gex = call_gex + put_gex

        # Find Zero Gamma Flip Level using price sweep
        test_spots = np.linspace(spot_price * 0.7, spot_price * 1.3, 100)
        net_gex_sweep = []
        for s in test_spots:
            gex_at_s = 0.0
            for opt in option_chain:
                stk = float(opt.get("strike", spot_price))
                op_t = str(opt.get("type", "call")).lower()
                oi = float(opt.get("open_interest", 0.0))
                iv = float(opt.get("iv", 0.20))
                T = max(float(opt.get("expiry_days", 30.0)) / 365.0, 0.001)

                gm = OptionsPricingEngine.calculate_greeks(
                    spot=s, strike=stk, time_to_expiry=T,
                    risk_free_rate=risk_free_rate, volatility=iv, option_type=op_t
                )["gamma"]
                cgex = gm * oi * 100.0 * s * s * 0.01
                gex_at_s += cgex if op_t in ["call", "c"] else -cgex
            net_gex_sweep.append(gex_at_s)

        # Interpolate flip level where net GEX crosses 0
        gamma_flip_level = spot_price
        for i in range(len(net_gex_sweep) - 1):
            if (net_gex_sweep[i] <= 0 and net_gex_sweep[i+1] >= 0) or (net_gex_sweep[i] >= 0 and net_gex_sweep[i+1] <= 0):
                gamma_flip_level = float(test_spots[i])
                break

        regime = "LONG_GAMMA_SUPPRESSION" if total_gex > 0 else "SHORT_GAMMA_VOLATILITY"

        return {
            "total_gex": float(total_gex),
            "call_gex": float(call_gex),
            "put_gex": float(put_gex),
            "gamma_flip_level": float(gamma_flip_level),
            "regime": regime
        }


class OptionStrategySimulator:
    """
    Simulates payoff curves and risk characteristics for multi-leg option strategies:
    Straddles, Strangles, Iron Condors, Bull/Bear Spreads, Butterflies.
    """

    @staticmethod
    def simulate_strategy_payoff(
        legs: List[Dict[str, Any]],
        spot_range: Tuple[float, float],
        num_points: int = 50
    ) -> Dict[str, Any]:
        """
        legs format: [{'strike': float, 'type': 'call'/'put', 'action': 'buy'/'sell', 'premium': float, 'qty': int}]
        """
        spots = np.linspace(spot_range[0], spot_range[1], num_points)
        payoffs = np.zeros(num_points)
        initial_cost = 0.0

        for leg in legs:
            stk = float(leg["strike"])
            op_type = str(leg["type"]).lower()
            action = str(leg.get("action", "buy")).lower()
            premium = float(leg.get("premium", 0.0))
            qty = int(leg.get("qty", 1))

            mult = 1.0 if action in ["buy", "long"] else -1.0
            initial_cost += mult * premium * qty * 100.0

            if op_type in ["call", "c"]:
                leg_payoff = np.maximum(0.0, spots - stk) - premium
            else:
                leg_payoff = np.maximum(0.0, stk - spots) - premium

            payoffs += mult * leg_payoff * qty * 100.0

        max_profit = float(np.max(payoffs))
        max_loss = float(np.min(payoffs))

        return {
            "spots": spots.tolist(),
            "payoffs": payoffs.tolist(),
            "net_initial_cost": float(initial_cost),
            "max_profit": max_profit,
            "max_loss": max_loss
        }
