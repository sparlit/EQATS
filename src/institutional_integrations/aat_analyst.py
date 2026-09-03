import logging
import time
from typing import Any, Dict, List

try:
    import numpy as np
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
logger = logging.getLogger("AAT_Analyst")


class MacroAnalyst:
    """External Macro Economic & Sentiment Analyst."""

    def __init__(self) -> None:
        self.sentiment_score = 0.5
        self.last_update = 0.0

    def update_sentiment(self, score: float) -> float:
        self.sentiment_score = max(0.0, min(1.0, score))
        self.last_update = time.time()
        return self.sentiment_score

    def get_impact_weight(self, symbol: str) -> float:
        sym_upper = symbol.upper()
        if "USD" in sym_upper:
            return 1.15 if self.sentiment_score > 0.6 else 0.85 if self.sentiment_score < 0.4 else 1.0
        return 1.0


class SMCAnalyst:
    """Smart Money Concepts & Price Action Structure Analyst."""

    def detect_market_structure(self, df_or_bars: Any) -> dict[str, Any]:
        if PANDAS_AVAILABLE and isinstance(df_or_bars, pd.DataFrame):
            df = df_or_bars
            if len(df) < 15:
                return {"trend": "NEUTRAL", "choch": False, "sweep": False, "swing_h": None, "swing_l": None}
            h_col = "high" if "high" in df else ("h" if "h" in df else "c")
            l_col = "low" if "low" in df else ("l" if "l" in df else "c")
            c_col = "close" if "close" in df else ("c" if "c" in df else "h")

            h = df[h_col].values
            l = df[l_col].values
            c = df[c_col].values
            pivot_h_mask = (h[2:-2] > h[0:-4]) & (h[2:-2] > h[1:-3]) & (h[2:-2] > h[3:-1]) & (h[2:-2] > h[4:])
            pivot_l_mask = (l[2:-2] < l[0:-4]) & (l[2:-2] < l[1:-3]) & (l[2:-2] < l[3:-1]) & (l[2:-2] < l[4:])
            pivot_h_idx = np.where(pivot_h_mask)[0] + 2
            pivot_l_idx = np.where(pivot_l_mask)[0] + 2
            highs = h[pivot_h_idx][-3:] if len(pivot_h_idx) > 0 else np.array([])
            lows = l[pivot_l_idx][-3:] if len(pivot_l_idx) > 0 else np.array([])

            sweep: Any = False
            if len(highs) >= 2:
                if h[-1] > highs[-2] and c[-1] < highs[-2]:
                    sweep = "BEARISH_SWEEP"
            if not sweep and len(lows) >= 2:
                if l[-1] < lows[-2] and c[-1] > lows[-2]:
                    sweep = "BULLISH_SWEEP"
            trend = "NEUTRAL"
            if len(highs) >= 2 and len(lows) >= 2:
                if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                    trend = "BULLISH"
                elif highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                    trend = "BEARISH"
            choch = False
            if (trend == "BULLISH" and len(lows) > 0 and (c[-1] < lows[-1])) or (trend == "BEARISH" and len(highs) > 0 and (c[-1] > highs[-1])):
                choch = True

            return {
                "trend": trend,
                "choch": choch,
                "sweep": sweep,
                "swing_h": float(highs[-1]) if len(highs) > 0 else None,
                "swing_l": float(lows[-1]) if len(lows) > 0 else None,
            }
        return {"trend": "NEUTRAL", "choch": False, "sweep": False, "swing_h": None, "swing_l": None}

    def detect_fvg(self, df_or_bars: Any) -> list[dict[str, Any]]:
        if PANDAS_AVAILABLE and isinstance(df_or_bars, pd.DataFrame):
            df = df_or_bars
            if len(df) < 3:
                return []
            h_col = "high" if "high" in df else ("h" if "h" in df else "c")
            l_col = "low" if "low" in df else ("l" if "l" in df else "c")

            h = df[h_col].values
            l = df[l_col].values
            fvgs = []
            for i in range(2, len(df)):
                if h[i - 2] < l[i]:
                    fvgs.append({"type": "BULLISH", "top": float(l[i]), "bottom": float(h[i - 2]), "index": i - 1})
                elif l[i - 2] > h[i]:
                    fvgs.append({"type": "BEARISH", "top": float(l[i - 2]), "bottom": float(h[i]), "index": i - 1})

            return fvgs[-5:]
        return []


class VolatilityAnalyst:
    """Market Regime & Volatility Analysis."""

    def get_regime(self, df_or_bars: Any) -> str:
        if PANDAS_AVAILABLE and isinstance(df_or_bars, pd.DataFrame):
            df = df_or_bars
            if len(df) < 20:
                return "NORMAL"
            c_col = "close" if "close" in df else ("c" if "c" in df else "h")
            h_col = "high" if "high" in df else ("h" if "h" in df else "c")
            l_col = "low" if "low" in df else ("l" if "l" in df else "c")

            c = df[c_col]
            h = df[h_col]
            l = df[l_col]
            atr = (h - l).rolling(20).mean()
            curr_atr = atr.iloc[-1]
            avg_atr = atr.mean()
            price_delta = c.iloc[-1] - c.iloc[-20]
            abs_delta = abs(price_delta)
            vol_adjusted_move = abs_delta / (curr_atr * np.sqrt(20)) if curr_atr > 0 else 0.0
            if curr_atr > avg_atr * 2.0:
                return "HIGH_VOLATILITY"
            if vol_adjusted_move > 2.0:
                return "TRENDING_FAST"
            if vol_adjusted_move > 1.0:
                return "TRENDING_SLOW"
            if curr_atr < avg_atr * 0.6:
                return "RANGING_TIGHT"
            return "NORMAL"
        return "NORMAL"
