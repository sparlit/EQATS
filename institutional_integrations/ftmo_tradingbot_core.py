"""
FTMO TradingBot Execution & Risk Intelligence Core.
Provides Scale-On-Profit (Pyramiding) rules, Dynamic ATR Trailing Stops,
Consensus Sizing Modulators, and Combined Exposure Cap Guards.
"""

import math
import logging
from typing import Dict, Any, List, Optional, Sequence

logger = logging.getLogger("FTMOTradingBotCore")

class ScaleOnProfitEngine:
    """
    Scale-On-Profit (Pyramiding) Add-On Engine.
    Validates entry distance (+N ATR profit), sizes add-on position fraction,
    and sets add-on stop to main entry price (protecting main entry break-even).
    """
    def should_trigger_addon(
        self,
        direction: str,
        entry_price: float,
        current_price: float,
        atr_at_entry: float,
        threshold_atr_multiplier: float = 1.0,
        has_active_addon: bool = False
    ) -> bool:
        if has_active_addon or atr_at_entry <= 0:
            return False

        profit_dist = (current_price - entry_price) if direction.upper() == "BUY" else (entry_price - current_price)
        required_dist = atr_at_entry * threshold_atr_multiplier
        return profit_dist >= required_dist

    def calculate_addon_params(
        self,
        direction: str,
        main_entry_price: float,
        main_lot_size: float,
        addon_fraction: float = 0.5
    ) -> Dict[str, Any]:
        addon_lot = round(max(0.01, main_lot_size * addon_fraction), 2)
        # Add-on stop sits at the MAIN position's entry price
        addon_sl = main_entry_price
        return {
            "addon_lot_size": addon_lot,
            "addon_stop_loss": addon_sl,
            "main_entry_protected": True
        }

class FTMODynamicStopEngine:
    """
    Dynamic ATR Trailing Stop & Partial Profit Engine.
    """
    def evaluate_trailing_stop(
        self,
        direction: str,
        entry_price: float,
        current_price: float,
        current_sl: float,
        atr_val: float,
        trail_atr_multiplier: float = 2.0
    ) -> Dict[str, Any]:
        pip_size = 0.01 if "JPY" in str(direction) else 0.0001
        trail_dist = max(atr_val * trail_atr_multiplier, pip_size * 10.0)

        should_update = False
        new_sl = current_sl

        if direction.upper() == "BUY":
            proposed_sl = current_price - trail_dist
            if proposed_sl > current_sl and current_price > entry_price:
                new_sl = round(proposed_sl, 5)
                should_update = True
        else:
            proposed_sl = current_price + trail_dist
            if (proposed_sl < current_sl or current_sl == 0) and current_price < entry_price:
                new_sl = round(proposed_sl, 5)
                should_update = True

        return {
            "should_update": should_update,
            "new_stop_loss": new_sl,
            "trail_distance": round(trail_dist, 5)
        }

class ConsensusSizingModulator:
    """
    Cross-Bot Consensus Sizing Modulator.
    Scales new trade lot size based on multi-strategy directional agreement score.
    """
    def compute_consensus_multiplier(self, bot_directions: List[int], this_direction: int) -> float:
        if not bot_directions:
            return 1.0

        all_dirs = list(bot_directions) + [this_direction]
        agreement_score = sum(all_dirs)
        num_bots = len(all_dirs)

        abs_score = abs(agreement_score)
        if abs_score == num_bots:
            return 1.0 # 100% agreement -> full size
        elif abs_score >= 1:
            return 0.75 # Partial agreement -> 75% size
        else:
            return 0.50 # Disagreement/neutral -> 50% defensive size

class CombinedExposureCapGuard:
    """
    Combined Notional Exposure Cap Guard across multi-strategy accounts.
    """
    def check_exposure_cap(
        self,
        open_positions_notional: List[float],
        proposed_trade_notional: float,
        current_equity: float,
        max_exposure_cap_pct: float = 40.0
    ) -> Dict[str, Any]:
        if current_equity <= 0:
            return {"allowed": False, "reason": "Invalid account equity"}

        total_notional = sum(open_positions_notional) + proposed_trade_notional
        total_exposure_pct = (total_notional / current_equity) * 100.0

        allowed = total_exposure_pct <= max_exposure_cap_pct
        return {
            "allowed": allowed,
            "total_exposure_pct": round(total_exposure_pct, 2),
            "max_exposure_cap_pct": max_exposure_cap_pct,
            "reason": "APPROVED" if allowed else f"Combined exposure {total_exposure_pct:.1f}% exceeds cap {max_exposure_cap_pct}%"
        }
