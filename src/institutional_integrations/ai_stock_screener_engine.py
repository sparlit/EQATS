"""
AI Stock Screener Engine (Animesh4002/ai-stock-screener Adaptation)
===================================================================

Target Integration: Animesh4002/ai-stock-screener
Magic Number: 9100026

Provides multi-factor AI stock screening, fundamental and technical composite ranking,
0.05 INR price tick rounding, IST market session validation, and microkernel plugin binding.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)
from institutional_integrations.indian_market_state_machine import IndianMarketStateMachine

MAGIC_NUMBER: int = 9100026


class AIStockScreenerEngine:
    """
    AI Stock Screener Engine for Indian equity markets (NSE/BSE).
    """

    def __init__(self, min_composite_score: float = 0.65) -> None:
        self.min_composite_score = min_composite_score
        self.market_state = IndianMarketStateMachine()

    def screen_stock(
        self,
        symbol: str,
        pe_ratio: float,
        pb_ratio: float,
        roe_pct: float,
        momentum_score: float,
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates stock composite fundamental/technical score and screens for top trade candidates.
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_price = round_to_indian_tick_size(current_price)

        if not session_valid:
            return {
                "symbol": symbol,
                "composite_score": 0.0,
                "passed": False,
                "price": rounded_price,
                "reason": "Market session closed",
                "magic_number": MAGIC_NUMBER,
            }

        # Value score: PE < 25 and PB < 4
        val_score = min(1.0, (25.0 / (pe_ratio + 1e-6)) * 0.5 + (4.0 / (pb_ratio + 1e-6)) * 0.5)
        # Profitability score: ROE > 15%
        prof_score = min(1.0, roe_pct / 15.0)
        # Tech momentum score normalized 0.0 to 1.0
        mom_score = max(0.0, min(1.0, momentum_score))

        composite_score = float((val_score * 0.35) + (prof_score * 0.35) + (mom_score * 0.30))
        passed = composite_score >= self.min_composite_score

        return {
            "symbol": symbol,
            "composite_score": round(composite_score, 4),
            "val_score": round(val_score, 2),
            "prof_score": round(prof_score, 2),
            "mom_score": round(mom_score, 2),
            "passed": passed,
            "price": rounded_price,
            "reason": "Qualified high-rank composite candidate" if passed else "Composite score below threshold",
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("animesh4002_ai_screener", AIStockScreenerEngine)
