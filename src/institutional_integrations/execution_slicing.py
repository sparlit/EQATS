"""
Institutional Algorithmic Order Slicing Engines.
Provides TWAP, VWAP, Iceberg, and Implementation Shortfall order slicing algorithms
to minimize market impact and execution slippage across ECN venues.
"""

import math
from typing import Any


class ExecutionSlicer:
    """Institutional execution slicing algorithms manager."""

    @staticmethod
    def slice_twap(total_qty: Any, duration_seconds: Any = 60, num_slices: Any = 5) -> Any:
        """
        Time-Weighted Average Price (TWAP) order slicing.
        Splits total quantity uniformly over time intervals.
        """
        if num_slices <= 0:
            num_slices = 1
        qty_per_slice = round(total_qty / num_slices, 2)
        interval_sec = duration_seconds / num_slices
        slices = []
        for i in range(num_slices):
            slices.append(
                {"slice_id": i + 1, "qty": qty_per_slice, "delay_sec": round(interval_sec * i, 2), "type": "TWAP"},
            )
        return slices

    @staticmethod
    def slice_vwap(total_qty: Any, volume_profile: Any = None) -> Any:
        """
        Volume-Weighted Average Price (VWAP) order slicing.
        Splits order proportional to historical intraday volume profile.
        """
        if not volume_profile:
            volume_profile = [0.25, 0.15, 0.1, 0.1, 0.15, 0.25]
        total_weight = sum(volume_profile)
        slices = []
        for idx, w in enumerate(volume_profile):
            slice_qty = round(total_qty * (w / total_weight), 2)
            slices.append(
                {
                    "slice_id": idx + 1,
                    "qty": slice_qty,
                    "weight_pct": round(w / total_weight * 100.0, 1),
                    "type": "VWAP",
                },
            )
        return slices

    @staticmethod
    def slice_iceberg(total_qty: Any, visible_qty: Any = 0.01) -> Any:
        """
        Iceberg Order execution.
        Displays only a small visible tranche while keeping hidden balance.
        """
        visible_qty = max(0.01, visible_qty)
        num_tranches = math.ceil(total_qty / visible_qty)
        tranches = []
        remaining = total_qty
        for i in range(num_tranches):
            tranche = min(visible_qty, round(remaining, 2))
            remaining -= tranche
            tranches.append(
                {
                    "tranche_id": i + 1,
                    "visible_qty": tranche,
                    "hidden_qty_left": round(max(0.0, remaining), 2),
                    "type": "ICEBERG",
                },
            )
        return tranches

    @staticmethod
    def calculate_implementation_shortfall(
        decision_price: Any, arrival_price: Any, execution_price: Any, total_qty: Any, fees: Any = 0.0,
    ) -> Any:
        """
        Calculates Implementation Shortfall (IS) transaction cost attribution.
        Measures total slippage, market impact, and delay costs.
        """
        explicit_cost = fees
        execution_drag = (execution_price - arrival_price) * total_qty
        opportunity_cost = (arrival_price - decision_price) * total_qty
        total_shortfall = explicit_cost + execution_drag + opportunity_cost
        shortfall_bps = (
            total_shortfall / (decision_price * total_qty) * 10000.0 if decision_price * total_qty > 0 else 0.0
        )
        return {
            "total_shortfall_usd": round(total_shortfall, 4),
            "shortfall_bps": round(shortfall_bps, 2),
            "execution_drag_usd": round(execution_drag, 4),
            "opportunity_cost_usd": round(opportunity_cost, 4),
        }
