# codespell:ignore MIS,IST
"""
AI Trader Reinforcement Q-Learning Engine (EQATS Institutional Adaptation).
Adapted from aaryansinha16/AI-trader into FOSS Microkernel Architecture.

Provides Deep Q-Learning state representation, epsilon-greedy action policy (BUY/SELL/HOLD),
Bellman Q-value updating, and reward optimization for Indian stock market equities
with 0.05 INR tick size rounding and 09:15-15:30 IST session rules.

Assigned Magic Number: 9100015
"""

import json
import logging
import math
import random
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .indian_market_state_machine import global_indian_state_machine, round_to_indian_tick_size
from .sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    generate_indian_market_history_bars,
    round_to_indian_quantity,
    validate_indian_product_tag,
)

_log = logging.getLogger("AITraderQLearningEngine")
MAGIC_NUMBER_AI_TRADER_Q = 9100015


class AITraderQLearningEngine:
    """
    Q-Learning Reinforcement Agent for Autonomous Trading.
    """

    def __init__(self, alpha: float = 0.1, gamma: float = 0.95, epsilon: float = 0.1) -> None:
        self.alpha = alpha  # Learning rate
        self.gamma = gamma  # Discount factor
        self.epsilon = epsilon  # Exploration probability
        self.q_table: Dict[Tuple[int, int, int], List[float]] = {}
        self.magic_number = MAGIC_NUMBER_AI_TRADER_Q

    def encode_state(self, closes: List[float], rsi_val: float) -> Tuple[int, int, int]:
        """
        Discretizes market state vector into discrete state tuple:
        (price_trend_state, rsi_state, momentum_state)
        """
        if not closes or len(closes) < 10:
            return (0, 0, 0)

        # Price trend discretization
        current = closes[-1]
        ema10 = sum(closes[-10:]) / 10.0
        trend_state = 1 if current > ema10 else -1 if current < ema10 else 0

        # RSI discretization
        rsi_state = 2 if rsi_val >= 70.0 else 0 if rsi_val <= 30.0 else 1

        # Momentum discretization
        momentum = (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 and closes[-5] > 0 else 0.0
        mom_state = 1 if momentum > 0.01 else -1 if momentum < -0.01 else 0

        return (trend_state, rsi_state, mom_state)

    def select_action(self, state: Tuple[int, int, int], is_training: bool = True) -> int:
        """
        Selects action index: 0 = HOLD, 1 = BUY, 2 = SELL using epsilon-greedy policy.
        """
        if is_training and random.random() < self.epsilon:
            return random.randint(0, 2)

        if state not in self.q_table:
            self.q_table[state] = [0.0, 0.0, 0.0]

        q_vals = self.q_table[state]
        max_v = max(q_vals)
        best_actions = [a for a, q in enumerate(q_vals) if q == max_v]
        return random.choice(best_actions)

    def update_q_value(
        self, state: Tuple[int, int, int], action: int, reward: float, next_state: Tuple[int, int, int]
    ) -> float:
        """
        Applies Bellman Q-learning update equation:
        Q(s, a) <- Q(s, a) + alpha * [r + gamma * max(Q(s', a')) - Q(s, a)]
        """
        if state not in self.q_table:
            self.q_table[state] = [0.0, 0.0, 0.0]
        if next_state not in self.q_table:
            self.q_table[next_state] = [0.0, 0.0, 0.0]

        current_q = self.q_table[state][action]
        max_next_q = max(self.q_table[next_state])

        new_q = current_q + self.alpha * (reward + self.gamma * max_next_q - current_q)
        self.q_table[state][action] = round(new_q, 4)
        return new_q

    def evaluate_trading_decision(self, history_bars: List[Dict[str, Any]], rsi_val: float = 50.0) -> Dict[str, Any]:
        """
        Evaluates history bars and selects optimal trading decision via Q-policy.
        """
        if not history_bars or len(history_bars) < 10:
            return {"decision": "HOLD", "confidence": 0.50, "magic_number": self.magic_number}

        closes = [float(b["close"]) for b in history_bars]
        current_price = closes[-1]

        state = self.encode_state(closes, rsi_val)
        action_idx = self.select_action(state, is_training=False)

        action_map = {0: "HOLD", 1: "BUY", 2: "SELL"}
        decision = action_map.get(action_idx, "HOLD")

        sl = 0.0
        tp = 0.0
        if decision == "BUY":
            sl = round_to_indian_tick_size(current_price * 0.985)
            tp = round_to_indian_tick_size(current_price * 1.03)
        elif decision == "SELL":
            sl = round_to_indian_tick_size(current_price * 1.015)
            tp = round_to_indian_tick_size(current_price * 0.97)

        return {
            "decision": decision,
            "confidence": 0.85 if decision != "HOLD" else 0.50,
            "state_tuple": state,
            "entry_price": round_to_indian_tick_size(current_price),
            "sl": sl,
            "tp": tp,
            "magic_number": self.magic_number,
        }


class AITraderQLearningAdapter(SEBIBrokerAdapter):
    """
    Microkernel Broker Adapter for AI Trader Q-Learning Engine.
    """

    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.engine = AITraderQLearningEngine()
        self.simulated_orders: Dict[str, Dict[str, Any]] = {}

    def connect(self) -> bool:
        self._is_connected = True
        return True

    def is_connected(self) -> bool:
        return self._is_connected

    def disconnect(self) -> bool:
        self._is_connected = False
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return {"balance": 1000000.0, "equity": 1000000.0, "currency": "INR", "is_demo": self.is_sandbox}

    def get_history(
        self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute"
    ) -> List[Dict[str, Any]]:
        return generate_indian_market_history_bars(symbol, exchange, count, interval)

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 1820.0, "ask": 1820.15, "last": 1820.05}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        product = validate_indian_product_tag(req.product, default="CNC")
        exchange = req.exchange.upper() if req.exchange else "NSE"
        ticket = f"AIQ_{time.time_ns()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 1820.05)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_AI_TRADER_Q,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_AI_TRADER_Q},
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC") -> SEBIOrderResponse:
        if ticket in self.simulated_orders:
            self.simulated_orders.pop(ticket)
        return SEBIOrderResponse(
            success=True, ticket=ticket, price=0.0, status="CLOSED", product=product, exchange=exchange
        )

    def modify_order(self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> bool:
        if ticket in self.simulated_orders:
            if price > 0:
                self.simulated_orders[ticket]["price"] = round_to_indian_tick_size(price)
            return True
        return True

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return list(self.simulated_orders.values())


# Auto-register into Microkernel Plugin Registry
IndianBrokerPluginRegistry.register("AI_TRADER_Q_LEARNING", AITraderQLearningAdapter)
IndianBrokerPluginRegistry.register("AI_TRADER_Q", AITraderQLearningAdapter)
