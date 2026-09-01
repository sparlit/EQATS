"""
Option Strategy Analytics & Analytical Greeks Engine.
Calculates Black-Scholes Greeks (Delta, Gamma, Theta, Vega, Rho, Vanna, Volga),
Implied Volatility Newton-Raphson/Bisection solver, and multi-leg option strategy risk profiles.
Adapted from OptionStratLib & OptionWorkstation.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any
import math

class OptionType(Enum):
    CALL = 'CALL'
    PUT = 'PUT'

@dataclass
class OptionGreeks:
    price: float
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    vanna: float
    volga: float

@dataclass
class OptionLeg:
    strike: float
    time_to_expiry_years: float
    option_type: OptionType
    implied_volatility: float
    quantity: float

def _norm_cdf(x: float) -> float:
    """Cumulative distribution function for standard normal distribution."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def _norm_pdf(x: float) -> float:
    """Probability density function for standard normal distribution."""
    return 1.0 / math.sqrt(2.0 * math.pi) * math.exp(-0.5 * x * x)

class OptionStratGreeksEngine:
    """
    Analytical Options Pricing and Risk Analytics Engine.
    """

    def __init__(self, risk_free_rate: float=0.05, magic_number: int=9400001) -> None:
        self.risk_free_rate: float = risk_free_rate
        self.magic_number: int = magic_number

    def calculate_greeks(self, spot: float, strike: float, time_to_expiry: float, iv: float, option_type: OptionType) -> OptionGreeks:
        if time_to_expiry <= 1e-06 or iv <= 1e-06 or spot <= 0 or (strike <= 0):
            if option_type == OptionType.CALL:
                payoff = max(0.0, spot - strike)
                delta = 1.0 if spot > strike else 0.0
            else:
                payoff = max(0.0, strike - spot)
                delta = -1.0 if strike > spot else 0.0
            return OptionGreeks(price=payoff, delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0, vanna=0.0, volga=0.0)
        r = self.risk_free_rate
        t = time_to_expiry
        sigma = max(0.0001, iv)
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)
        pdf_d1 = _norm_pdf(d1)
        cdf_d1 = _norm_cdf(d1)
        cdf_d2 = _norm_cdf(d2)
        cdf_neg_d1 = _norm_cdf(-d1)
        cdf_neg_d2 = _norm_cdf(-d2)
        if option_type == OptionType.CALL:
            price = spot * cdf_d1 - strike * math.exp(-r * t) * cdf_d2
            delta = cdf_d1
            theta = -(spot * pdf_d1 * sigma) / (2.0 * math.sqrt(t)) - r * strike * math.exp(-r * t) * cdf_d2
            rho = strike * t * math.exp(-r * t) * cdf_d2
        else:
            price = strike * math.exp(-r * t) * cdf_neg_d2 - spot * cdf_neg_d1
            delta = cdf_d1 - 1.0
            theta = -(spot * pdf_d1 * sigma) / (2.0 * math.sqrt(t)) + r * strike * math.exp(-r * t) * cdf_neg_d2
            rho = -strike * t * math.exp(-r * t) * cdf_neg_d2
        gamma = pdf_d1 / (spot * sigma * math.sqrt(t))
        vega = spot * pdf_d1 * math.sqrt(t) / 100.0
        vanna = -pdf_d1 * d2 / sigma
        volga = vega * d1 * d2 / sigma
        return OptionGreeks(price=price, delta=delta, gamma=gamma, theta=theta / 365.0, vega=vega, rho=rho, vanna=vanna, volga=volga)

    def solve_implied_volatility(self, target_market_price: float, spot: float, strike: float, time_to_expiry: float, option_type: OptionType, max_iterations: int=100, precision: float=1e-05) -> float:
        iv = 0.25
        for _ in range(max_iterations):
            greeks = self.calculate_greeks(spot, strike, time_to_expiry, iv, option_type)
            diff = greeks.price - target_market_price
            if abs(diff) < precision:
                return iv
            vega = greeks.vega * 100.0
            if abs(vega) < 1e-08:
                break
            iv -= diff / vega
            if iv <= 0.001 or iv > 5.0:
                break
        low_iv, high_iv = (0.001, 5.0)
        for _ in range(50):
            mid_iv = (low_iv + high_iv) / 2.0
            greeks = self.calculate_greeks(spot, strike, time_to_expiry, mid_iv, option_type)
            if abs(greeks.price - target_market_price) < precision:
                return mid_iv
            if greeks.price < target_market_price:
                low_iv = mid_iv
            else:
                high_iv = mid_iv
        return (low_iv + high_iv) / 2.0

    def evaluate_multi_leg_strategy(self, spot: float, legs: List[OptionLeg]) -> Dict[str, float]:
        net_price = 0.0
        net_delta = 0.0
        net_gamma = 0.0
        net_theta = 0.0
        net_vega = 0.0
        for leg in legs:
            g = self.calculate_greeks(spot, leg.strike, leg.time_to_expiry_years, leg.implied_volatility, leg.option_type)
            net_price += g.price * leg.quantity
            net_delta += g.delta * leg.quantity
            net_gamma += g.gamma * leg.quantity
            net_theta += g.theta * leg.quantity
            net_vega += g.vega * leg.quantity
        return {'net_premium_cost': net_price, 'net_delta': net_delta, 'net_gamma': net_gamma, 'net_theta': net_theta, 'net_vega': net_vega}
