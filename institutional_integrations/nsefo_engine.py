"""
NSEFO Derivatives & Probability Synthesis Engine (EQATS Institutional Adaptation).
Adapted from sparlit/nsefo (NSE Futures & Options Core Architecture)

Provides:
- NSeFoOptionGreeksCalculator: Pure Black-Scholes Greeks calculation (Delta, Gamma, Theta, Vega)
- NSeFoProbabilitySynthesis: Multi-factor conviction score probability synthesis
- NSeFoNlpCommandParser: Natural language regex parser for F&O order commands
"""

import re
import math
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

logger = logging.getLogger("NSeFoEngine")


@dataclass
class NSeFoGreeksResult:
    delta: float
    gamma: float
    theta: float
    vega: float


@dataclass
class NSeFoParsedNlpCommand:
    action: str  # BUY or SELL
    symbol: str
    strike: float
    option_type: str  # CE or PE
    raw_command: str


class NSeFoOptionGreeksCalculator:
    """
    Computes Black-Scholes Option Greeks without external heavy library dependencies.
    """

    def _norm_cdf(self, x: float) -> float:
        """Standard normal cumulative distribution function approximation."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    def _norm_pdf(self, x: float) -> float:
        """Standard normal probability density function."""
        return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)

    def calculate_greeks(
        self,
        spot: float,
        strike: float,
        time_to_expiry_years: float,
        risk_free_rate: float = 0.0695,  # Default 6.95%
        volatility_iv: float = 0.18,  # Default 18% IV
        option_type: str = "CE",
    ) -> NSeFoGreeksResult:
        """Computes Delta, Gamma, Theta, and Vega."""
        if spot <= 0 or strike <= 0 or time_to_expiry_years <= 0 or volatility_iv <= 0:
            return NSeFoGreeksResult(0.0, 0.0, 0.0, 0.0)

        s = float(spot)
        k = float(strike)
        t = float(time_to_expiry_years)
        r = float(risk_free_rate)
        sigma = float(volatility_iv)

        d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))
        d2 = d1 - sigma * math.sqrt(t)

        opt_type = option_type.upper()
        if opt_type in ("CE", "CALL"):
            delta = self._norm_cdf(d1)
            theta = (
                -(s * self._norm_pdf(d1) * sigma) / (2.0 * math.sqrt(t))
                - r * k * math.exp(-r * t) * self._norm_cdf(d2)
            ) / 365.0
        else:  # PE / PUT
            delta = self._norm_cdf(d1) - 1.0
            theta = (
                -(s * self._norm_pdf(d1) * sigma) / (2.0 * math.sqrt(t))
                + r * k * math.exp(-r * t) * self._norm_cdf(-d2)
            ) / 365.0

        gamma = self._norm_pdf(d1) / (s * sigma * math.sqrt(t))
        vega = (s * self._norm_pdf(d1) * math.sqrt(t)) / 100.0  # Vega per 1% IV change

        return NSeFoGreeksResult(
            delta=round(delta, 4),
            gamma=round(gamma, 6),
            theta=round(theta, 4),
            vega=round(vega, 4),
        )


class NSeFoProbabilitySynthesis:
    """
    Synthesizes multi-factor indicator conviction scores into a 0.0 to 1.0 probability.
    """

    def calculate_winning_probability(
        self,
        trend_score: float,  # +1.0 (UP) or -1.0 (DOWN)
        momentum_score: float,  # +1.0 (BULL) or -1.0 (BEAR)
        volatility_factor: float = 1.0,
    ) -> float:
        """Computes weighted conviction probability clamped between 0.0 and 1.0."""
        base_score = (trend_score * 0.5) + (momentum_score * 0.3)
        normalized = (base_score + 0.8) / 1.6  # Maps [-0.8, +0.8] -> [0.0, 1.0]
        final_prob = max(0.0, min(1.0, normalized * volatility_factor))
        return round(final_prob, 4)


class NSeFoNlpCommandParser:
    """
    Parses natural language trading instructions into structured F&O commands.
    """

    def parse_command(self, text: str) -> Optional[NSeFoParsedNlpCommand]:
        """Parses natural language order instructions (e.g., 'Buy Nifty 24500 ce')."""
        if not text or not text.strip():
            return None

        clean = text.strip().upper()

        pattern = r"^(BUY|SELL|LONG|SHORT)\s+([A-Z]+)\s+([0-9]+)\s+(CE|PE|CALL|PUT)$"
        match = re.search(pattern, clean)

        if not match:
            return None

        action_raw = match.group(1)
        symbol = match.group(2)
        strike = float(match.group(3))
        opt_raw = match.group(4)

        action = "BUY" if action_raw in ("BUY", "LONG") else "SELL"
        opt_type = "CE" if opt_raw in ("CE", "CALL") else "PE"

        return NSeFoParsedNlpCommand(
            action=action,
            symbol=symbol,
            strike=strike,
            option_type=opt_type,
            raw_command=text,
        )
