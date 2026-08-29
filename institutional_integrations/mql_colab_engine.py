import numpy as np
import threading
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("MQLColabEngine")

class SLTPEngine:
    """
    Advanced SL/TP Engine with SL Hunter Avoidance & Dynamic Trailing.
    Calculates ATR & Swing-based SL/TP, pads round numbers to evade stop liquidity sweeps,
    and calculates breakeven/trailing stops.
    """
    def __init__(self):
        self._lock = threading.Lock()

    def calculate_sl_tp(self, symbol: str, direction: str, entry_price: float, atr_val: float, swing_high: float = 0.0, swing_low: float = 0.0) -> Dict[str, float]:
        with self._lock:
            pip_size = 0.01 if "JPY" in symbol.upper() else 0.0001
            atr_dist = max(atr_val * 1.5, pip_size * 15.0)

            if direction.upper() == "BUY":
                raw_sl = (swing_low - pip_size * 3.0) if swing_low > 0 else (entry_price - atr_dist)
                sl = min(entry_price - pip_size * 10.0, raw_sl)
                tp = entry_price + (entry_price - sl) * 2.0
            else:
                raw_sl = (swing_high + pip_size * 3.0) if swing_high > 0 else (entry_price + atr_dist)
                sl = max(entry_price + pip_size * 10.0, raw_sl)
                tp = entry_price - (sl - entry_price) * 2.0

            # Round number avoidance (pad SL by 2 pips if sitting on round figure .00 or .50)
            round_mod = sl / (pip_size * 100)
            if abs(round_mod - round(round_mod)) < 0.05:
                sl += (-pip_size * 2.0) if direction.upper() == "BUY" else (pip_size * 2.0)

            return {
                "sl": round(sl, 5),
                "tp": round(tp, 5),
                "risk_distance": round(abs(entry_price - sl), 5)
            }

class CandlestickAIClassifier:
    """Classifies Candlestick Patterns & Price Action Triggers."""
    def classify_bars(self, history_bars: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not history_bars or len(history_bars) < 5:
            return []
        patterns = []
        last = history_bars[-1]
        prev = history_bars[-2]

        o = last.get("open", last.get("o", 0.0))
        h = last.get("high", last.get("h", 0.0))
        l = last.get("low", last.get("l", 0.0))
        c = last.get("close", last.get("c", 0.0))

        p_o = prev.get("open", prev.get("o", 0.0))
        p_c = prev.get("close", prev.get("c", 0.0))

        body = abs(c - o)
        prev_body = abs(p_c - p_o)
        total_range = h - l if h > l else 0.0001
        lower_wick = min(o, c) - l
        upper_wick = h - max(o, c)

        if body > prev_body * 1.5 and c > o and p_c < p_o:
            patterns.append({"pattern": "bullish_engulfing", "confidence": 0.85, "direction": "BUY"})
        if body > prev_body * 1.5 and c < o and p_c > p_o:
            patterns.append({"pattern": "bearish_engulfing", "confidence": 0.85, "direction": "SELL"})
        if lower_wick > body * 2.0 and upper_wick < body * 0.4:
            patterns.append({"pattern": "hammer_pinbar", "confidence": 0.75, "direction": "BUY"})
        if upper_wick > body * 2.0 and lower_wick < body * 0.4:
            patterns.append({"pattern": "shooting_star", "confidence": 0.75, "direction": "SELL"})

        return patterns

class LatencyArbitrage:
    """Lead-Lag & Microstructure Lead Detector."""
    def __init__(self):
        self.history = {}
        self._lock = threading.Lock()

    def record_tick(self, symbol: str, venue: str, price: float, timestamp: float):
        with self._lock:
            if symbol not in self.history:
                self.history[symbol] = {}
            if venue not in self.history[symbol]:
                self.history[symbol][venue] = []
            self.history[symbol][venue].append((timestamp, price))
            if len(self.history[symbol][venue]) > 100:
                self.history[symbol][venue].pop(0)

    def detect_lead_lag(self, symbol: str, venue1: str, venue2: str) -> Dict[str, Any]:
        with self._lock:
            v1 = self.history.get(symbol, {}).get(venue1, [])
            v2 = self.history.get(symbol, {}).get(venue2, [])
        if len(v1) < 10 or len(v2) < 10:
            return {"lead_lag": False, "spread": 0.0}
        p1 = v1[-1][1]
        p2 = v2[-1][1]
        diff = p1 - p2
        return {
            "lead_lag": abs(diff) > 0.0002,
            "lead_venue": venue1 if diff > 0 else venue2,
            "discrepancy": abs(diff)
        }
