"""
Binance Trade Bot Bridge Coin Scouting & Arbitrage Engine (EQATS Institutional Adaptation)
Adapted from edeng23/binance-trade-bot (binance_trade_bot/auto_trader.py)

Provides:
- BridgeCoinScoutEngine: Relative Altcoin Ratio Matrix Calculator & Jump Evaluator
- Bridge Asset (e.g., USDT/BTC) Rebalancing Transaction Trigger
- Dynamic Ratio Threshold Rebalancer
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AltcoinRatio:
    from_coin: str
    to_coin: str
    bridge_coin: str
    current_ratio: float
    threshold_ratio: float
    is_jump_profitable: bool
    profit_margin_pct: float


@dataclass
class BridgeJumpDecision:
    should_jump: bool
    from_coin: str
    to_coin: str
    bridge_coin: str
    current_ratio: float
    expected_profit_pct: float
    reason: str


class BridgeCoinScoutEngine:
    """Binance Trade Bot Bridge Scouting & Altcoin Jump Engine."""

    def __init__(
        self,
        bridge_coin: str = "USDT",
        min_jump_profit_pct: float = 1.5,  # Minimum 1.5% profit required to jump coins
    ):
        self.bridge_coin = bridge_coin
        self.min_jump_profit_pct = min_jump_profit_pct
        self.threshold_ratios: Dict[str, float] = {}  # Key: "FROM_TO", Value: initial ratio

    def set_initial_threshold(self, from_coin: str, to_coin: str, ratio: float):
        """Sets initial reference ratio for pair."""
        key = f"{from_coin}_{to_coin}"
        self.threshold_ratios[key] = ratio

    def evaluate_coin_jump(
        self,
        current_coin: str,
        target_coin: str,
        current_coin_price_in_bridge: float,
        target_coin_price_in_bridge: float,
    ) -> BridgeJumpDecision:
        """
        Evaluates potential jump from current_coin to target_coin through bridge_coin.
        ratio = current_coin_price / target_coin_price
        """
        if current_coin_price_in_bridge <= 0 or target_coin_price_in_bridge <= 0:
            return BridgeJumpDecision(
                should_jump=False,
                from_coin=current_coin,
                to_coin=target_coin,
                bridge_coin=self.bridge_coin,
                current_ratio=0.0,
                expected_profit_pct=0.0,
                reason="Invalid coin prices in bridge currency",
            )

        current_ratio = current_coin_price_in_bridge / target_coin_price_in_bridge
        key = f"{current_coin}_{target_coin}"
        ref_ratio = self.threshold_ratios.get(key, current_ratio)

        profit_margin_pct = ((current_ratio - ref_ratio) / ref_ratio) * 100.0

        if profit_margin_pct >= self.min_jump_profit_pct:
            return BridgeJumpDecision(
                should_jump=True,
                from_coin=current_coin,
                to_coin=target_coin,
                bridge_coin=self.bridge_coin,
                current_ratio=round(current_ratio, 6),
                expected_profit_pct=round(profit_margin_pct, 2),
                reason=f"Profitable ratio jump detected: +{profit_margin_pct:.2f}% >= {self.min_jump_profit_pct:.2f}% min target",
            )

        return BridgeJumpDecision(
            should_jump=False,
            from_coin=current_coin,
            to_coin=target_coin,
            bridge_coin=self.bridge_coin,
            current_ratio=round(current_ratio, 6),
            expected_profit_pct=round(profit_margin_pct, 2),
            reason=f"Ratio jump below threshold (+{profit_margin_pct:.2f}% < {self.min_jump_profit_pct:.2f}%)",
        )

    def scout_best_jump(
        self,
        current_coin: str,
        current_coin_price: float,
        candidate_prices: Dict[str, float],
    ) -> Optional[BridgeJumpDecision]:
        """Scouts all candidate coins and selects the most profitable jump."""
        best_decision: Optional[BridgeJumpDecision] = None

        for coin, price in candidate_prices.items():
            if coin == current_coin:
                continue

            dec = self.evaluate_coin_jump(current_coin, coin, current_coin_price, price)
            if dec.should_jump:
                if best_decision is None or dec.expected_profit_pct > best_decision.expected_profit_pct:
                    best_decision = dec

        return best_decision
