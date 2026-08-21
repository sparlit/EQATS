"""
Institutional Smart Money Concepts (SMC) & Inner Circle Trader (ICT) Market Structure Engine.
Analyzes Order Blocks (OB), Fair Value Gaps (FVG), Market Structure Shifts (MSS / CHOCH),
and Liquidity Sweeps (BSL / SSL) with 0% mock stubs.
"""


def detect_order_blocks(opens, highs, lows, closes, lookback=30):
    """
    Detects institutional Order Blocks (OB).
    Bullish OB: The last down-candle prior to a strong bullish displacement move.
    Bearish OB: The last up-candle prior to a strong bearish displacement move.
    """
    if len(closes) < min(lookback, 10):
        return {"bullish_ob": None, "bearish_ob": None}

    start_idx = max(0, len(closes) - lookback)
    bullish_ob = None
    bearish_ob = None

    for i in range(start_idx + 2, len(closes) - 1):
        # Displacement check: current move is >= 1.5x average candle body
        avg_body = sum(abs(closes[j] - opens[j]) for j in range(max(0, i - 10), i)) / 10.0
        curr_body = abs(closes[i] - opens[i])

        if curr_body >= avg_body * 1.5:
            # Bullish displacement
            if closes[i] > opens[i] and closes[i-1] < opens[i-1]:
                bullish_ob = {
                    "high": highs[i-1],
                    "low": lows[i-1],
                    "open": opens[i-1],
                    "close": closes[i-1],
                    "idx": i-1
                }
            # Bearish displacement
            elif closes[i] < opens[i] and closes[i-1] > opens[i-1]:
                bearish_ob = {
                    "high": highs[i-1],
                    "low": lows[i-1],
                    "open": opens[i-1],
                    "close": closes[i-1],
                    "idx": i-1
                }

    return {
        "bullish_ob": bullish_ob,
        "bearish_ob": bearish_ob
    }

def detect_fair_value_gaps(highs, lows, closes, lookback=20):
    """
    Detects Fair Value Gaps (FVG) / 3-candle price imbalances.
    Bullish FVG: Candle 1 High < Candle 3 Low (Gap zone: [Candle 1 High, Candle 3 Low]).
    Bearish FVG: Candle 1 Low > Candle 3 High (Gap zone: [Candle 3 High, Candle 1 Low]).
    """
    if len(closes) < 5:
        return {"bullish_fvgs": [], "bearish_fvgs": []}

    start_idx = max(2, len(closes) - lookback)
    bullish_fvgs = []
    bearish_fvgs = []

    for i in range(start_idx, len(closes)):
        c1_high = highs[i-2]
        c1_low = lows[i-2]
        c3_high = highs[i]
        c3_low = lows[i]

        # Bullish FVG
        if c3_low > c1_high:
            gap_size = c3_low - c1_high
            bullish_fvgs.append({
                "bottom": c1_high,
                "top": c3_low,
                "size": gap_size,
                "idx": i
            })
        # Bearish FVG
        elif c1_low > c3_high:
            gap_size = c1_low - c3_high
            bearish_fvgs.append({
                "bottom": c3_high,
                "top": c1_low,
                "size": gap_size,
                "idx": i
            })

    return {
        "bullish_fvgs": bullish_fvgs[-3:],
        "bearish_fvgs": bearish_fvgs[-3:]
    }

def detect_market_structure_shift(highs, lows, closes, lookback=30):
    """
    Detects Market Structure Shift (MSS) / Change of Character (CHOCH).
    BULLISH_MSS: Price breaks above recent swing high.
    BEARISH_MSS: Price breaks below recent swing low.
    """
    if len(closes) < 15:
        return {"mss_status": "NEUTRAL", "break_level": None}

    recent_highs = highs[-lookback:-5] if len(highs) >= lookback else highs[:-5]
    recent_lows = lows[-lookback:-5] if len(lows) >= lookback else lows[:-5]

    if not recent_highs or not recent_lows:
        return {"mss_status": "NEUTRAL", "break_level": None}

    swing_high = max(recent_highs)
    swing_low = min(recent_lows)
    curr_close = closes[-1]

    if curr_close > swing_high:
        return {"mss_status": "BULLISH_MSS", "break_level": swing_high}
    elif curr_close < swing_low:
        return {"mss_status": "BEARISH_MSS", "break_level": swing_low}

    return {"mss_status": "NEUTRAL", "break_level": None}

def detect_liquidity_sweeps(highs, lows, closes, lookback=20):
    """
    Detects Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) sweeps.
    BSL Sweep: High exceeds recent swing high, but close reclaims inside.
    SSL Sweep: Low pierces below recent swing low, but close reclaims inside.
    """
    if len(closes) < 10:
        return {"bsl_sweep": False, "ssl_sweep": False}

    recent_high = max(highs[-lookback:-2])
    recent_low = min(lows[-lookback:-2])

    curr_high = highs[-1]
    curr_low = lows[-1]
    curr_close = closes[-1]

    bsl_sweep = (curr_high > recent_high) and (curr_close < recent_high)
    ssl_sweep = (curr_low < recent_low) and (curr_close > recent_low)

    return {
        "bsl_sweep": bsl_sweep,
        "ssl_sweep": ssl_sweep,
        "bsl_level": recent_high,
        "ssl_level": recent_low
    }

class FVGCacheEngine:
    """Active Fair Value Gap Ring-Buffer Cache Engine."""
    def __init__(self, max_capacity=50):
        self.max_capacity = max_capacity
        self.bullish_cache = []
        self.bearish_cache = []
        self.last_bar_count = 0

    def update_incremental(self, highs, lows, closes):
        """Incrementally checks for new FVGs or mitigations on bar close."""
        if len(closes) < 3:
            return

        c1_h, c1_l = highs[-3], lows[-3]
        c3_h, c3_l = highs[-1], lows[-1]

        # Check Bullish FVG creation
        if c3_l > c1_h:
            gap = {"bottom": c1_h, "top": c3_l, "idx": len(closes)-1, "mitigated": False}
            if not any(g["idx"] == gap["idx"] for g in self.bullish_cache):
                self.bullish_cache.append(gap)

        # Check Bearish FVG creation
        if c1_l > c3_h:
            gap = {"bottom": c3_h, "top": c1_l, "idx": len(closes)-1, "mitigated": False}
            if not any(g["idx"] == gap["idx"] for g in self.bearish_cache):
                self.bearish_cache.append(gap)

        # Mitigate active gaps
        curr_p = closes[-1]
        for g in self.bullish_cache:
            if curr_p <= g["bottom"]:
                g["mitigated"] = True
        for g in self.bearish_cache:
            if curr_p >= g["top"]:
                g["mitigated"] = True

        # Ring buffer retention
        self.bullish_cache = [g for g in self.bullish_cache if not g["mitigated"]][-self.max_capacity:]
        self.bearish_cache = [g for g in self.bearish_cache if not g["mitigated"]][-self.max_capacity:]

class SmartMoneyConceptsEngine:
    """Consolidated SMC/ICT Analysis Engine."""

    def __init__(self):
        self.engine_version = "3.0.0"
        self.fvg_cache = FVGCacheEngine()

    def analyze(self, history_bars):
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
                "confluence_score": 50.0
            }

        opens = [b['open'] for b in history_bars]
        highs = [b['high'] for b in history_bars]
        lows = [b['low'] for b in history_bars]
        closes = [b['close'] for b in history_bars]

        obs = detect_order_blocks(opens, highs, lows, closes)
        fvgs = detect_fair_value_gaps(highs, lows, closes)
        mss = detect_market_structure_shift(highs, lows, closes)
        sweeps = detect_liquidity_sweeps(highs, lows, closes)

        # Calculate SMC Consensus Bias
        bullish_points = 0
        bearish_points = 0

        if mss['mss_status'] == "BULLISH_MSS": bullish_points += 2
        elif mss['mss_status'] == "BEARISH_MSS": bearish_points += 2

        if sweeps['ssl_sweep']: bullish_points += 2  # SSL Sweep = Liquidity taken before up move
        if sweeps['bsl_sweep']: bearish_points += 2  # BSL Sweep = Liquidity taken before down move

        if fvgs['bullish_fvgs']: bullish_points += 1
        if fvgs['bearish_fvgs']: bearish_points += 1

        bias = "NEUTRAL"
        if bullish_points > bearish_points: bias = "BULLISH"
        elif bearish_points > bullish_points: bias = "BEARISH"

        score = min(95.0, max(30.0, 50.0 + (bullish_points - bearish_points) * 10.0))

        return {
            "order_blocks": obs,
            "fvgs": fvgs,
            "mss": mss,
            "liquidity_sweeps": sweeps,
            "bias": bias,
            "confluence_score": round(score, 1)
        }

# Global Singleton Engine
global_smc_engine = SmartMoneyConceptsEngine()
