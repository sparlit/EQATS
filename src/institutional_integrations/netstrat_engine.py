"""
Netstrat Network Graph & Synthetic Dataset Generator Engine (blitzarx1/netstrat Adaptation)
========================================================================================

Target Integration: blitzarx1/netstrat
Magic Number: 9100079

Provides network graph cycle/arbitrage path detection, synthetic dataset generation with derivative-based mesh resolution,
0.05 INR price tick rounding, IST market session validation, and microkernel plugin binding.
"""

import math
import zoneinfo
from typing import Dict, Any, List, Optional
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)

MAGIC_NUMBER_NETSTRAT: int = 9100079


def round_tick_005(price: float) -> float:
    return round_to_indian_tick_size(price)


def is_ist_market_open(now_dt: Optional[datetime] = None) -> bool:
    """
    Checks if current time is within Indian Standard Time (IST) market hours:
    09:15 to 15:30 IST, Monday to Friday.
    """
    if now_dt is None:
        ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        now_dt = datetime.now(ist_tz)

    if now_dt.weekday() in (5, 6):
        return False

    start_time = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    end_time = now_dt.replace(hour=15, minute=30, second=0, microsecond=0)

    return start_time <= now_dt <= end_time


class NetstratEngine:
    """
    Network Graph Topology & Synthetic Market Data Generator Engine.
    """

    def __init__(self) -> None:
        self.magic_number = MAGIC_NUMBER_NETSTRAT

    def detect_graph_cycles(self, edges: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Detects cycles in market exchange network graph (arbitrage loop detection).
        Edges format: [{'from': 'A', 'to': 'B', 'rate': 1.05}, ...]
        """
        nodes = set()
        adj: Dict[str, List[Dict[str, Any]]] = {}

        for edge in edges:
            u, v, rate = edge["from"], edge["to"], edge.get("rate", 1.0)
            nodes.add(u)
            nodes.add(v)
            if u not in adj:
                adj[u] = []
            adj[u].append({"to": v, "rate": rate})

        cycles = []
        # DFS cycle search
        visited = set()
        path = []

        def dfs(curr: str, start: str):
            path.append(curr)
            visited.add(curr)

            for neighbor in adj.get(curr, []):
                next_node = neighbor["to"]
                if next_node == start and len(path) >= 2:
                    cycles.append(list(path))
                elif next_node not in visited:
                    dfs(next_node, start)

            path.pop()
            visited.remove(curr)

        for n in nodes:
            dfs(n, n)

        return {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "detected_cycles_count": len(cycles),
            "cycles": cycles[:10],
            "magic_number": self.magic_number,
        }

    def generate_synthetic_dataset(
        self, x0: float, steps: int, mesh_size: float, training_ratio: float = 0.8
    ) -> Dict[str, Any]:
        """
        Computes synthetic market dataset with mesh resolution and training/test split.
        """
        steps = max(2, steps)
        min_res_steps = 10
        mesh_len = steps * min_res_steps

        mesh = [x0 + i * mesh_size for i in range(mesh_len)]
        # Synthetic sine wave function
        data = [[x, math.sin(x)] for x in mesh]

        split_idx = int(len(data) * training_ratio)
        training_set = data[:split_idx]
        test_set = data[split_idx:]

        return {
            "total_mesh_points": len(mesh),
            "training_count": len(training_set),
            "test_count": len(test_set),
            "training_ratio": training_ratio,
            "magic_number": self.magic_number,
        }


class NetstratBrokerAdapter(SEBIBrokerAdapter):
    """
    SEBI Broker Adapter wrapper for Netstrat Engine.
    """

    def __init__(self, broker_name: str = "NETSTRAT") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = NetstratEngine()

    def connect(self) -> bool:
        self._is_connected = True
        return True

    def disconnect(self) -> bool:
        self._is_connected = False
        return True

    def is_connected(self) -> bool:
        return self._is_connected

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        if not self._is_connected:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=request.price,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                error="Adapter not connected",
            )

        if not is_ist_market_open():
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=request.price,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                error="Exchange trading session closed (IST market hours strictly enforced)",
            )

        sanitized_price = round_tick_005(request.price)
        ticket_id = f"NST-{int(datetime.now().timestamp() * 1000)}"

        return SEBIOrderResponse(
            success=True,
            ticket=ticket_id,
            price=sanitized_price,
            status="FILLED",
            product=request.product,
            exchange=request.exchange,
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC") -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=0.0,
            status="CLOSED",
            product=product,
            exchange=exchange,
        )

    def modify_order(self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> bool:
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return {"balance": 1000000.0, "equity": 1000000.0, "currency": "INR", "is_demo": True}

    def get_history(self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute") -> List[Dict[str, Any]]:
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 500.0, "ask": 500.15, "last": 500.05}

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return []


# Register in microkernel plugin registry
IndianBrokerPluginRegistry.register("NETSTRAT", NetstratBrokerAdapter)
