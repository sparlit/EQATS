"""
OpenAlgo Integration Engine.
Provides Smart Order Slicing / Iceberg Order Splitter, GTT Trigger Manager,
and Intra-day Session Auto Square-Off Execution.
"""

import time
import math
import threading
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("OpenAlgoEngine")

class OpenAlgoSmartOrderSplitter:
    """
    Smart Order Slicing & Iceberg Order Execution Engine.
    Splits large order volumes exceeding max_lot_size into smaller, venue-compliant sub-orders.
    """
    def __init__(self, max_slice_lot: float = 5.0):
        self.max_slice_lot = max_slice_lot

    def slice_order(self, symbol: str, action: str, total_volume: float, max_lot: Optional[float] = None) -> List[Dict[str, Any]]:
        limit_lot = max_lot if max_lot and max_lot > 0 else self.max_slice_lot
        vol = round(float(total_volume), 2)
        if vol <= 0:
            return []

        slices = []
        remaining = vol

        while remaining > 0:
            current_slice = round(min(remaining, limit_lot), 2)
            slices.append({
                "symbol": symbol,
                "action": action.upper(),
                "volume": current_slice,
                "slice_index": len(slices) + 1,
                "status": "READY"
            })
            remaining = round(remaining - current_slice, 2)

        return slices

class OpenAlgoSessionSquareOffManager:
    """
    Session Boundary Auto Square-Off Manager.
    Closes intra-day positions ahead of market session close.
    """
    def __init__(self):
        self._lock = threading.Lock()
        self.squareoff_triggered = False

    def check_squareoff_required(self, current_hour: int, current_minute: int, close_hour: int = 16, close_minute: int = 55) -> bool:
        with self._lock:
            if current_hour > close_hour or (current_hour == close_hour and current_minute >= close_minute):
                self.squareoff_triggered = True
                return True
            return False

    def reset(self):
        with self._lock:
            self.squareoff_triggered = False
