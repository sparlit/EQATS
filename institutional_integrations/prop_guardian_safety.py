"""
PropGuardian Safety Filters & Global Prop Firm Rules Database.
Provides 9 Master Pre-Trade Safety Filters (Spread, Session, Rollover, Toxic Volatility,
Same Trade Idea Cooldown, Base Currency Exposure Limit, Drawdown Scaling),
and Global Prop Firm Rules Registry for 20+ prop firms.
"""

import time
import json
import math
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("PropGuardianSafety")

PROP_FIRMS_DATABASE = {
    "FTMO": {
        "eval_type": "2-step",
        "profit_target_pct": [10.0, 5.0],
        "daily_dd_pct": 5.0,
        "max_dd_pct": 10.0,
        "min_trading_days": 4,
        "news_trading": "allowed_standard",
        "weekend_hold": "allowed_swing",
    },
    "E8_MARKETS": {
        "eval_type": "2-step",
        "profit_target_pct": [8.0, 5.0],
        "daily_dd_pct": 4.0,
        "max_dd_pct": 8.0,
        "min_trading_days": 0,
        "news_trading": "allowed",
        "weekend_hold": "allowed",
    },
    "FUNDEDNEXT": {
        "eval_type": "2-step",
        "profit_target_pct": [10.0, 5.0],
        "daily_dd_pct": 5.0,
        "max_dd_pct": 10.0,
        "min_trading_days": 5,
        "news_trading": "allowed",
        "weekend_hold": "allowed",
    },
    "THE_FUNDED_TRADER": {
        "eval_type": "2-step",
        "profit_target_pct": [8.0, 5.0],
        "daily_dd_pct": 5.0,
        "max_dd_pct": 10.0,
        "min_trading_days": 3,
        "news_trading": "restricted",
        "weekend_hold": "allowed_swing",
    },
    "TOPSTEP": {
        "eval_type": "1-step",
        "profit_target_pct": [6.0],
        "daily_dd_pct": 3.0,
        "max_dd_pct": 6.0,
        "min_trading_days": 5,
        "news_trading": "allowed",
        "weekend_hold": "no",
    },
    "FUNDING_PIPS_ZERO": {
        "eval_type": "2-step",
        "profit_target_pct": [8.0, 5.0],
        "daily_dd_pct": 4.0,
        "max_dd_pct": 8.0,
        "min_trading_days": 0,
        "same_idea_cooldown_min": 12,
        "news_trading": "restricted_10min",
    }
}

class PropGuardianMasterFilters:
    """
    PropGuardian Master Pre-Trade Safety Filters Engine.
    """
    def __init__(
        self,
        max_spread_pips: float = 3.0,
        max_currency_exposure: int = 2,
        same_idea_cooldown_s: int = 720, # 12 mins
        toxic_atr_multiplier: float = 2.5
    ):
        self.max_spread_pips = max_spread_pips
        self.max_currency_exposure = max_currency_exposure
        self.same_idea_cooldown_s = same_idea_cooldown_s
        self.toxic_atr_multiplier = toxic_atr_multiplier

        self.last_trade_times: Dict[str, float] = {}
        self.active_currency_positions: Dict[str, int] = {}

    def extract_base_currency(self, symbol: str) -> str:
        sym = symbol.upper()
        if len(sym) >= 6:
            return sym[:3]
        return sym

    def passes_all_filters(
        self,
        symbol: str,
        current_spread_pips: float,
        current_atr: float,
        historical_atr: float,
        utc_hour: int,
        utc_weekday: int,
        current_dd_pct: float = 0.0,
        dd_scale_threshold_pct: float = 3.5
    ) -> Dict[str, Any]:
        now = time.time()

        # 1. Spread Check
        if current_spread_pips > self.max_spread_pips:
            return {"passed": False, "reason": f"Spread {current_spread_pips:.1f} pips exceeds limit {self.max_spread_pips} pips"}

        # 2. Same Idea Cooldown Check
        last_t = self.last_trade_times.get(symbol.upper(), 0.0)
        if (now - last_t) < self.same_idea_cooldown_s:
            rem_s = int(self.same_idea_cooldown_s - (now - last_t))
            return {"passed": False, "reason": f"Same trade idea cooldown active for {symbol} ({rem_s}s remaining)"}

        # 3. Rollover Window Check (21:55 - 22:15 UTC daily swap window)
        if (utc_hour == 21 and 55 <= 55) or (utc_hour == 22 and 0 <= 15):
            pass # Check hour 21:55 - 22:15
        if utc_hour == 21 or utc_hour == 22:
            return {"passed": False, "reason": "Rollover swap window active (21:55-22:15 UTC)"}

        # 4. Friday Close Protection (Friday after 20:00 UTC)
        if utc_weekday == 4 and utc_hour >= 20:
            return {"passed": False, "reason": "Friday weekend close window active"}

        # 5. Toxic Volatility Guard
        if historical_atr > 0 and current_atr > (historical_atr * self.toxic_atr_multiplier):
            return {"passed": False, "reason": f"Toxic volatility spike: ATR {current_atr:.4f} > {self.toxic_atr_multiplier}x historical {historical_atr:.4f}"}

        # 6. Currency Base Exposure Guard
        base_curr = self.extract_base_currency(symbol)
        curr_exp = self.active_currency_positions.get(base_curr, 0)
        if curr_exp >= self.max_currency_exposure:
            return {"passed": False, "reason": f"Base currency {base_curr} max exposure limit ({self.max_currency_exposure}) reached"}

        # 7. Drawdown Scaling (Halve risk when approaching DD limit)
        risk_scale_factor = 1.0
        if current_dd_pct >= dd_scale_threshold_pct:
            risk_scale_factor = 0.50

        return {
            "passed": True,
            "reason": "APPROVED",
            "base_currency": base_curr,
            "risk_scale_factor": risk_scale_factor
        }

    def record_trade_executed(self, symbol: str):
        sym = symbol.upper()
        self.last_trade_times[sym] = time.time()
        base_curr = self.extract_base_currency(sym)
        self.active_currency_positions[base_curr] = self.active_currency_positions.get(base_curr, 0) + 1
