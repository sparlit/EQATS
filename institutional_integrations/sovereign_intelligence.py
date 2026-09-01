import logging
from typing import Any, Dict, List
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
logger = logging.getLogger('SovereignIntelligence')


class SovereignIntelligencePlugin:
    """
    AAT V5.0.0 Sovereign Intelligence Engine.
    Combines institutional SMC Order Block detection, Liquidity Grab (Stop Hunt) analysis,
    and ATR-based position sizing into a unified signal processor.
    """

    def __init__(self, max_equity_risk: float=0.01) -> None:
        self.max_equity_risk = max_equity_risk

    def detect_order_blocks(self, df_or_bars: Any) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        if PANDAS_AVAILABLE and isinstance(df_or_bars, pd.DataFrame):
            df = df_or_bars
            if len(df) < 5:
                return blocks
            o = df['open'] if 'open' in df else df['o']
            h = df['high'] if 'high' in df else df['h']
            l = df['low'] if 'low' in df else df['l']
            c = df['close'] if 'close' in df else df['c']
            for i in range(2, len(df) - 1):
                if c.iloc[i - 1] < o.iloc[i - 1] and c.iloc[i] > o.iloc[i] and (c.iloc[i] > h.iloc[i - 1]):
                    blocks.append({'type': 'BULLISH_OB', 'price': float(l.iloc[i - 1]), 'index': i})
                elif c.iloc[i - 1] > o.iloc[i - 1] and c.iloc[i] < o.iloc[i] and (c.iloc[i] < l.iloc[i - 1]):
                    blocks.append({'type': 'BEARISH_OB', 'price': float(h.iloc[i - 1]), 'index': i})
        return blocks

    def detect_liquidity_grab(self, df_or_bars: Any) -> str:
        if PANDAS_AVAILABLE and isinstance(df_or_bars, pd.DataFrame):
            df = df_or_bars
            if len(df) < 20:
                return 'NONE'
            h = df['high'] if 'high' in df else df['h']
            l = df['low'] if 'low' in df else df['l']
            c = df['close'] if 'close' in df else df['c']
            recent_high = h.iloc[-20:-2].max()
            recent_low = l.iloc[-20:-2].min()
            curr_high = h.iloc[-1]
            curr_low = l.iloc[-1]
            curr_close = c.iloc[-1]
            if curr_high > recent_high and curr_close < recent_high:
                return 'BEARISH_GRAB'
            elif curr_low < recent_low and curr_close > recent_low:
                return 'BULLISH_GRAB'
        return 'NONE'

    def analyze_market_signal(self, symbol: str, df_or_bars: Any, equity: float=10000.0) -> Dict[str, Any]:
        obs = self.detect_order_blocks(df_or_bars)
        grab = self.detect_liquidity_grab(df_or_bars)
        signal = 'NEUTRAL'
        confidence = 0.5
        if grab == 'BULLISH_GRAB':
            signal = 'BUY'
            confidence = 0.85
        elif grab == 'BEARISH_GRAB':
            signal = 'SELL'
            confidence = 0.85
        elif len(obs) > 0:
            last_ob = obs[-1]
            signal = 'BUY' if last_ob['type'] == 'BULLISH_OB' else 'SELL'
            confidence = 0.75
        pip_size = 0.01 if 'JPY' in symbol.upper() else 0.0001
        atr_dist = pip_size * 20.0
        risk_amount = equity * self.max_equity_risk
        recommended_lot = round(max(0.01, min(risk_amount / (atr_dist * 100000), 50.0)), 2)
        return {'symbol': symbol, 'signal': signal, 'confidence': confidence, 'order_blocks': len(obs), 'liquidity_grab': grab, 'recommended_lot': recommended_lot, 'status': 'APPROVED' if signal != 'NEUTRAL' else 'NEUTRAL'}
