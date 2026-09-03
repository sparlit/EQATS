"""
Institutional Smart Money Concepts (SMC) & Inner Circle Trader (ICT) Market Structure Engine.
Analyzes Order Blocks (OB), Fair Value Gaps (FVG), Market Structure Shifts (MSS / CHOCH),
and Liquidity Sweeps (BSL / SSL) with 0% mock stubs.
"""

from typing import Any

import indicators


def detect_order_blocks(opens: Any, highs: Any, lows: Any, closes: Any, lookback: Any = 30) -> Any:
    """
    Detects institutional Order Blocks (OB) and verifies mitigation state.
    Bullish OB: The last down-candle prior to a strong bullish displacement move.
    Bearish OB: The last up-candle prior to a strong bearish displacement move.
    """
    if not closes or len(closes) < min(lookback, 10):
        return {"bullish_ob": None, "bearish_ob": None}
    start_idx = max(0, len(closes) - lookback)
    bullish_ob = None
    bearish_ob = None
    curr_price = closes[-1]
    for i in range(start_idx + 2, len(closes) - 1):
        bodies = [abs(closes[j] - opens[j]) for j in range(max(0, i - 10), i)]
        avg_body = sum(bodies) / float(len(bodies)) if bodies else 1e-05
        curr_body = abs(closes[i] - opens[i])
        if curr_body >= avg_body * 1.4:
            if closes[i] > opens[i] and closes[i - 1] < opens[i - 1]:
                ob_high = highs[i - 1]
                ob_low = lows[i - 1]
                mitigated = any(lows[k] < ob_low for k in range(i, len(closes)))
                bullish_ob = {
                    "high": ob_high,
                    "low": ob_low,
                    "open": opens[i - 1],
                    "close": closes[i - 1],
                    "idx": i - 1,
                    "mitigated": mitigated,
                    "fresh": not mitigated and curr_price >= ob_low,
                }
            elif closes[i] < opens[i] and closes[i - 1] > opens[i - 1]:
                ob_high = highs[i - 1]
                ob_low = lows[i - 1]
                mitigated = any(highs[k] > ob_high for k in range(i, len(closes)))
                bearish_ob = {
                    "high": ob_high,
                    "low": ob_low,
                    "open": opens[i - 1],
                    "close": closes[i - 1],
                    "idx": i - 1,
                    "mitigated": mitigated,
                    "fresh": not mitigated and curr_price <= ob_high,
                }
    return {"bullish_ob": bullish_ob, "bearish_ob": bearish_ob}


def detect_fair_value_gaps(highs: Any, lows: Any, closes: Any, lookback: Any = 20) -> Any:
    """
    Detects Fair Value Gaps (FVG) / 3-candle price imbalances.
    Bullish FVG: Candle 1 High < Candle 3 Low (Gap zone: [Candle 1 High, Candle 3 Low]).
    Bearish FVG: Candle 1 Low > Candle 3 High (Gap zone: [Candle 3 High, Candle 1 Low]).
    """
    if not closes or len(closes) < 5:
        return {"bullish_fvgs": [], "bearish_fvgs": []}
    start_idx = max(2, len(closes) - lookback)
    bullish_fvgs = []
    bearish_fvgs = []
    curr_price = closes[-1]
    for i in range(start_idx, len(closes)):
        c1_high = highs[i - 2]
        c1_low = lows[i - 2]
        c3_high = highs[i]
        c3_low = lows[i]
        if c3_low > c1_high:
            gap_bottom = c1_high
            gap_top = c3_low
            gap_size = gap_top - gap_bottom
            mitigated = any(lows[k] <= gap_bottom for k in range(i, len(closes)))
            bullish_fvgs.append(
                {
                    "bottom": gap_bottom,
                    "top": gap_top,
                    "size": gap_size,
                    "idx": i,
                    "mitigated": mitigated,
                    "fresh": not mitigated and curr_price >= gap_bottom,
                },
            )
        elif c1_low > c3_high:
            gap_bottom = c3_high
            gap_top = c1_low
            gap_size = gap_top - gap_bottom
            mitigated = any(highs[k] >= gap_top for k in range(i, len(closes)))
            bearish_fvgs.append(
                {
                    "bottom": gap_bottom,
                    "top": gap_top,
                    "size": gap_size,
                    "idx": i,
                    "mitigated": mitigated,
                    "fresh": not mitigated and curr_price <= gap_top,
                },
            )
    return {"bullish_fvgs": bullish_fvgs[-3:], "bearish_fvgs": bearish_fvgs[-3:]}


def detect_market_structure_shift(highs: Any, lows: Any, closes: Any, lookback: Any = 30) -> Any:
    """
    Detects Market Structure Shift (MSS) / Change of Character (CHOCH) using Williams Fractals.
    BULLISH_MSS: Current close breaks above recent swing high.
    BEARISH_MSS: Current close breaks below recent swing low.
    """
    if not closes or len(closes) < 15:
        return {"mss_status": "NEUTRAL", "break_level": None}
    swings = indicators.calculate_swing_points(highs, lows, window=2)
    swing_high = swings.get("last_swing_high")
    swing_low = swings.get("last_swing_low")
    if swing_high is None or swing_low is None:
        return {"mss_status": "NEUTRAL", "break_level": None}
    curr_close = closes[-1]
    if curr_close > swing_high:
        return {"mss_status": "BULLISH_MSS", "break_level": swing_high}
    if curr_close < swing_low:
        return {"mss_status": "BEARISH_MSS", "break_level": swing_low}
    return {"mss_status": "NEUTRAL", "break_level": None}


def detect_liquidity_sweeps(highs: Any, lows: Any, closes: Any, lookback: Any = 20) -> Any:
    """
    Detects Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) sweeps.
    BSL Sweep: High exceeds recent swing high, but close reclaims inside (rejection wick).
    SSL Sweep: Low pierces below recent swing low, but close reclaims inside (rejection wick).
    """
    if not closes or len(closes) < 10:
        return {"bsl_sweep": False, "ssl_sweep": False}
    swings = indicators.calculate_swing_points(highs[:-1], lows[:-1], window=2)
    recent_high = swings.get("last_swing_high") or max(highs[-lookback:-2])
    recent_low = swings.get("last_swing_low") or min(lows[-lookback:-2])
    curr_high = highs[-1]
    curr_low = lows[-1]
    curr_close = closes[-1]
    bsl_sweep = curr_high > recent_high and curr_close < recent_high
    ssl_sweep = curr_low < recent_low and curr_close > recent_low
    return {"bsl_sweep": bsl_sweep, "ssl_sweep": ssl_sweep, "bsl_level": recent_high, "ssl_level": recent_low}


class FVGCacheEngine:
    """Active Fair Value Gap Ring-Buffer Cache Engine."""

    def __init__(self, max_capacity: Any = 50) -> None:
        self.max_capacity = max_capacity
        self.bullish_cache = []
        self.bearish_cache = []
        self.last_bar_count = 0

    def update_incremental(self, highs: Any, lows: Any, closes: Any) -> None:
        """Incrementally checks for new FVGs or mitigations on bar close."""
        if not closes or len(closes) < 3:
            return
        c1_h, c1_l = (highs[-3], lows[-3])
        c3_h, c3_l = (highs[-1], lows[-1])
        if c3_l > c1_h:
            gap = {"bottom": c1_h, "top": c3_l, "idx": len(closes) - 1, "mitigated": False}
            if not any(g["idx"] == gap["idx"] for g in self.bullish_cache):
                self.bullish_cache.append(gap)
        if c1_l > c3_h:
            gap = {"bottom": c3_h, "top": c1_l, "idx": len(closes) - 1, "mitigated": False}
            if not any(g["idx"] == gap["idx"] for g in self.bearish_cache):
                self.bearish_cache.append(gap)
        curr_p = closes[-1]
        for g in self.bullish_cache:
            if curr_p <= g["bottom"]:
                g["mitigated"] = True
        for g in self.bearish_cache:
            if curr_p >= g["top"]:
                g["mitigated"] = True
        self.bullish_cache = [g for g in self.bullish_cache if not g["mitigated"]][-self.max_capacity :]
        self.bearish_cache = [g for g in self.bearish_cache if not g["mitigated"]][-self.max_capacity :]


class SmartMoneyConceptsEngine:
    """Consolidated SMC/ICT Analysis Engine."""

    def __init__(self) -> None:
        self.engine_version = "3.1.0"
        self.fvg_cache = FVGCacheEngine()

    def analyze(self, history_bars: Any) -> Any:
        """
        Analyzes historical bars and returns complete SMC/ICT market structure signature.
        history_bars: list of dicts with 'open', 'high', 'low', 'close'
        """
        if not history_bars or len(history_bars) < 10:
            return {
                "order_blocks": {"bullish_ob": None, "bearish_ob": None},
                "fvgs": {"bullish_fvgs": [], "bearish_fvgs": []},
                "mss": {"mss_status": "NEUTRAL", "break_level": None},
                "liquidity_sweeps": {"bsl_sweep": False, "ssl_sweep": False},
                "bias": "NEUTRAL",
                "confluence_score": 50.0,
            }
        opens = [b["open"] for b in history_bars]
        highs = [b["high"] for b in history_bars]
        lows = [b["low"] for b in history_bars]
        closes = [b["close"] for b in history_bars]
        obs = detect_order_blocks(opens, highs, lows, closes)
        fvgs = detect_fair_value_gaps(highs, lows, closes)
        mss = detect_market_structure_shift(highs, lows, closes)
        sweeps = detect_liquidity_sweeps(highs, lows, closes)
        bullish_points = 0
        bearish_points = 0
        if mss["mss_status"] == "BULLISH_MSS":
            bullish_points += 2.5
        elif mss["mss_status"] == "BEARISH_MSS":
            bearish_points += 2.5
        if sweeps["ssl_sweep"]:
            bullish_points += 2.0
        if sweeps["bsl_sweep"]:
            bearish_points += 2.0
        bull_ob = obs.get("bullish_ob")
        if bull_ob and bull_ob.get("fresh"):
            bullish_points += 1.5
        bear_ob = obs.get("bearish_ob")
        if bear_ob and bear_ob.get("fresh"):
            bearish_points += 1.5
        fresh_bull_fvgs = [g for g in fvgs.get("bullish_fvgs", []) if g.get("fresh")]
        if fresh_bull_fvgs:
            bullish_points += 1.0
        fresh_bear_fvgs = [g for g in fvgs.get("bearish_fvgs", []) if g.get("fresh")]
        if fresh_bear_fvgs:
            bearish_points += 1.0
        bias = "NEUTRAL"
        if bullish_points > bearish_points:
            bias = "BULLISH"
        elif bearish_points > bullish_points:
            bias = "BEARISH"
        diff = bullish_points - bearish_points
        score = min(95.0, max(30.0, 50.0 + diff * 8.0))
        return {
            "order_blocks": obs,
            "fvgs": fvgs,
            "mss": mss,
            "liquidity_sweeps": sweeps,
            "bias": bias,
            "confluence_score": round(score, 1),
        }


global_smc_engine = SmartMoneyConceptsEngine()
