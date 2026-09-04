# codespell:ignore MIS,IST
"""
BSC Volume Bundler & Stealth Trading Engine (EQATS Institutional Adaptation).
Adapted from 0xRustPro/Stealth-BSC-BNB-create-devbuy-volume-bundler-trading-bot into FOSS Microkernel Architecture.

Features multi-wallet transaction bundling, 5% inventory buffer retention, anti-MEV randomized execution delays,
0.05 INR price tick rounding, and SEBIBrokerAdapter integration.

Assigned Magic Number: 9100030
"""

import logging
import math
import random
import uuid
from typing import Any, Dict, List, Optional

from .indian_market_state_machine import round_to_indian_tick_size
from .sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    generate_indian_market_history_bars,
    validate_indian_product_tag,
)

_log = logging.getLogger("BSCVolumeBundlerEngine")
MAGIC_NUMBER_BSC_VOLUME_BUNDLER = 9100030


class BSCVolumeBundlerStrategy:
    """
    Multi-Wallet Volume Generation & Inventory Buffer Strategy Engine.
    Executes coordinated buy/sell loops across multi-wallet pools while maintaining
    a strict minimum 5% inventory buffer to avoid total token liquidation.
    """

    def __init__(
        self,
        symbol: str = "BNB",
        volume_loops: int = 10,
        buy_amount: float = 0.01,
        sell_percentage: float = 0.95,
        trading_interval: int = 30,
    ) -> None:
        self.symbol = symbol.upper()
        self.volume_loops = volume_loops
        self.buy_amount = buy_amount
        self.sell_percentage = min(sell_percentage, 0.95)  # Enforce max 95% sell (5% buffer)
        self.trading_interval = trading_interval
        self.magic_number = MAGIC_NUMBER_BSC_VOLUME_BUNDLER

    def calculate_bundle_distribution(self, total_bnb: float, num_wallets: int) -> List[float]:
        """
        Calculates randomized stealth buy distribution across bundle wallets.
        """
        if num_wallets <= 0 or total_bnb <= 0:
            return []
        weights = [random.uniform(0.8, 1.2) for _ in range(num_wallets)]
        weight_sum = sum(weights)
        return [round(total_bnb * (w / weight_sum), 4) for w in weights]

    def evaluate_strategy(
        self,
        history_bars: List[Dict[str, Any]],
        wallet_balances: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        if not history_bars:
            return {
                "symbol": self.symbol,
                "decision": "HOLD",
                "quantity": 0,
                "explanation": "No history bars provided for volume bundler.",
                "magic_number": self.magic_number,
            }

        last_close = float(history_bars[-1]["close"])
        wallet_balances = wallet_balances or [0.05, 0.05, 0.05, 0.05]

        # Check solvency across bundle wallets
        min_balance_threshold = 0.002
        solvent_wallets = [b for b in wallet_balances if b >= min_balance_threshold]

        if len(solvent_wallets) < len(wallet_balances) * 0.5:
            return {
                "symbol": self.symbol,
                "decision": "HOLD",
                "quantity": 0,
                "explanation": "Inadequate BNB balance across bundle wallets (solvency check failed).",
                "magic_number": self.magic_number,
            }

        # Anti-MEV randomized delay interval
        jitter_interval = self.trading_interval + random.randint(-5, 5)

        return {
            "symbol": self.symbol,
            "decision": "BUY",
            "quantity": 100,
            "sell_ratio_capped": self.sell_percentage,
            "inventory_buffer_pct": 5.0,
            "buy_amount_bnb": self.buy_amount,
            "jitter_interval_sec": jitter_interval,
            "solvent_wallets_count": len(solvent_wallets),
            "explanation": f"Volume Loop Active: Executing bundle buy with {self.sell_percentage*100:.0f}% sell cap & 5% inventory buffer.",
            "magic_number": self.magic_number,
        }


class BSCVolumeBundlerAdapter(SEBIBrokerAdapter):
    """
    Microkernel Broker Adapter wrapper for BSC Volume Bundler & Stealth Engine.
    """

    def __init__(self, api_key: str = "", access_token: str = "", is_sandbox: bool = False) -> None:
        super().__init__(api_key=api_key, access_token=access_token, is_sandbox=is_sandbox)
        self.strategy = BSCVolumeBundlerStrategy()
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
        return {"bid": 500.0, "ask": 500.10, "last": 500.05}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        product = validate_indian_product_tag(req.product, default="MIS")
        exchange = req.exchange.upper() if req.exchange else "NSE"
        ticket = f"BSCBUNDLE_{uuid.uuid4().hex[:12].upper()}"
        price = round_to_indian_tick_size(req.price if req.price > 0 else 500.05)

        order_record = {
            "ticket": ticket,
            "symbol": req.symbol,
            "quantity": req.quantity,
            "price": price,
            "product": product,
            "exchange": exchange,
            "status": "OPEN",
            "magic_number": MAGIC_NUMBER_BSC_VOLUME_BUNDLER,
        }
        self.simulated_orders[ticket] = order_record
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=price,
            status="COMPLETE",
            product=product,
            exchange=exchange,
            raw_response={"status": True, "ticket": ticket, "magic_number": MAGIC_NUMBER_BSC_VOLUME_BUNDLER},
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "MIS") -> SEBIOrderResponse:
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


IndianBrokerPluginRegistry.register("BSC_VOLUME_BUNDLER", BSCVolumeBundlerAdapter)
