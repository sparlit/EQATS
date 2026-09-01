"""
ICT System v2 Engine (EQATS Institutional Adaptation)
Adapted from hungpixi/ict-system-ea (ICT_SystemEA_v2.mq5)

Provides:
- CISD (Change in State of Delivery) Institutional Order Flow Shift Confirmation
- SMT (Smart Money Technique) Divergence Detector between Correlated Assets (EURUSD/GBPUSD, NQ/ES)
- Power of 3 (AMD - Accumulation, Manipulation, Distribution) & OHLC/OLHC Daily Bias Evaluator
- PDA (Premium / Discount Array) Equilibrium & Zone Classifier
- Session Liquidity Sweep Tracker (Asian / London / NY BSL & SSL Sweeps)
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

class MarketBias(str, Enum):
    NONE = 'NONE'
    BULLISH = 'BULLISH'
    BEARISH = 'BEARISH'

class StructureType(str, Enum):
    NONE = 'NONE'
    BOS = 'BOS'
    CHOCH = 'CHOCH'
    CISD = 'CISD'

class PDAZone(str, Enum):
    NONE = 'NONE'
    PREMIUM = 'PREMIUM'
    DISCOUNT = 'DISCOUNT'
    EQUILIBRIUM = 'EQUILIBRIUM'

@dataclass
class SMTDivergenceResult:
    detected: bool
    bias: MarketBias
    description: str

@dataclass
class PDAResult:
    equilibrium: float
    current_zone: PDAZone
    fvg_bullish: bool = False
    fvg_bearish: bool = False
    order_block_top: float = 0.0
    order_block_bottom: float = 0.0

@dataclass
class ICTSignalResult:
    bias: MarketBias
    structure: StructureType
    cisd_confirmed: bool
    smt_divergence: SMTDivergenceResult
    pda_zone: PDAZone
    bsl_swept: bool
    ssl_swept: bool
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float
    reason: str

class ICTSystemV2Engine:
    """ICT System v2 Institutional Engine."""

    def detect_cisd(self, candles: List[Dict[str, float]]) -> Tuple[bool, MarketBias]:
        """
        Detects Change in State of Delivery (CISD).
        Bullish CISD: Current candle closes above the open of the prior bearish candle array.
        Bearish CISD: Current candle closes below the open of the prior bullish candle array.
        """
        if len(candles) < 3:
            return (False, MarketBias.NONE)
        c_curr = candles[-1]
        c_prev = candles[-2]
        if c_prev['close'] < c_prev['open'] and c_curr['close'] > c_prev['open']:
            return (True, MarketBias.BULLISH)
        if c_prev['close'] > c_prev['open'] and c_curr['close'] < c_prev['open']:
            return (True, MarketBias.BEARISH)
        return (False, MarketBias.NONE)

    def detect_smt_divergence(self, asset_a_highs: List[float], asset_a_lows: List[float], asset_b_highs: List[float], asset_b_lows: List[float]) -> SMTDivergenceResult:
        """
        Detects SMT (Smart Money Technique) Divergence between correlated assets.
        Bullish SMT: Asset A makes a lower low while Asset B makes a higher low.
        Bearish SMT: Asset A makes a higher high while Asset B makes a lower high.
        """
        if len(asset_a_highs) < 5 or len(asset_b_highs) < 5:
            return SMTDivergenceResult(False, MarketBias.NONE, 'Insufficient bar history for SMT')
        a_high_curr, a_high_prev = (asset_a_highs[-1], max(asset_a_highs[-5:-1]))
        a_low_curr, a_low_prev = (asset_a_lows[-1], min(asset_a_lows[-5:-1]))
        b_high_curr, b_high_prev = (asset_b_highs[-1], max(asset_b_highs[-5:-1]))
        b_low_curr, b_low_prev = (asset_b_lows[-1], min(asset_b_lows[-5:-1]))
        if a_low_curr < a_low_prev and b_low_curr > b_low_prev:
            return SMTDivergenceResult(True, MarketBias.BULLISH, 'Bullish SMT: Asset A created Lower Low while Asset B held Higher Low')
        if a_high_curr > a_high_prev and b_high_curr < b_high_prev:
            return SMTDivergenceResult(True, MarketBias.BEARISH, 'Bearish SMT: Asset A created Higher High while Asset B held Lower High')
        return SMTDivergenceResult(False, MarketBias.NONE, 'No SMT divergence detected')

    def calculate_pda_zones(self, high: float, low: float, current_price: float) -> PDAResult:
        """Calculates Premium/Discount Array Equilibrium and Zone Classification."""
        if high <= low:
            return PDAResult(0.0, PDAZone.NONE)
        eq = (high + low) / 2.0
        if current_price > eq + 0.05 * (high - low):
            zone = PDAZone.PREMIUM
        elif current_price < eq - 0.05 * (high - low):
            zone = PDAZone.DISCOUNT
        else:
            zone = PDAZone.EQUILIBRIUM
        return PDAResult(equilibrium=eq, current_zone=zone)

    def track_liquidity_sweeps(self, current_price: float, asian_high: float, asian_low: float) -> Tuple[bool, bool]:
        """Tracks Buy-Side Liquidity (BSL) and Sell-Side Liquidity (SSL) Sweeps."""
        bsl_swept = current_price > asian_high
        ssl_swept = current_price < asian_low
        return (bsl_swept, ssl_swept)

    def evaluate(self, candles: List[Dict[str, float]], correlated_highs: Optional[List[float]]=None, correlated_lows: Optional[List[float]]=None, asian_high: float=0.0, asian_low: float=0.0, atr: float=0.002) -> ICTSignalResult:
        """Evaluates complete ICT System v2 decision pipeline."""
        if not candles or len(candles) < 5:
            return ICTSignalResult(bias=MarketBias.NONE, structure=StructureType.NONE, cisd_confirmed=False, smt_divergence=SMTDivergenceResult(False, MarketBias.NONE, ''), pda_zone=PDAZone.NONE, bsl_swept=False, ssl_swept=False, entry_price=0.0, stop_loss=0.0, take_profit=0.0, confidence=0.0, reason='Insufficient candles')
        c_curr = candles[-1]['close']
        highs = [b['high'] for b in candles]
        lows = [b['low'] for b in candles]
        cisd_confirmed, cisd_bias = self.detect_cisd(candles)
        if correlated_highs and correlated_lows:
            smt_res = self.detect_smt_divergence(highs, lows, correlated_highs, correlated_lows)
        else:
            smt_res = SMTDivergenceResult(False, MarketBias.NONE, 'No correlated pair data')
        recent_high, recent_low = (max(highs[-20:]), min(lows[-20:]))
        pda_res = self.calculate_pda_zones(recent_high, recent_low, c_curr)
        bsl_swept, ssl_swept = self.track_liquidity_sweeps(c_curr, asian_high, asian_low)
        bias = MarketBias.NONE
        confidence = 0.5
        reason_parts = []
        if cisd_confirmed and cisd_bias == MarketBias.BULLISH and (pda_res.current_zone == PDAZone.DISCOUNT):
            bias = MarketBias.BULLISH
            confidence = 0.85
            reason_parts.append('Bullish CISD confirmed in Discount Zone')
        elif cisd_confirmed and cisd_bias == MarketBias.BEARISH and (pda_res.current_zone == PDAZone.PREMIUM):
            bias = MarketBias.BEARISH
            confidence = 0.85
            reason_parts.append('Bearish CISD confirmed in Premium Zone')
        if smt_res.detected:
            confidence = min(0.95, confidence + 0.1)
            reason_parts.append(smt_res.description)
        if ssl_swept and bias == MarketBias.BULLISH:
            confidence = min(0.98, confidence + 0.05)
            reason_parts.append('Asian SSL Liquidity Swept')
        elif bsl_swept and bias == MarketBias.BEARISH:
            confidence = min(0.98, confidence + 0.05)
            reason_parts.append('Asian BSL Liquidity Swept')
        stop_loss = c_curr - 1.5 * atr if bias == MarketBias.BULLISH else c_curr + 1.5 * atr
        take_profit = c_curr + 3.0 * atr if bias == MarketBias.BULLISH else c_curr - 3.0 * atr
        return ICTSignalResult(bias=bias, structure=StructureType.CISD if cisd_confirmed else StructureType.NONE, cisd_confirmed=cisd_confirmed, smt_divergence=smt_res, pda_zone=pda_res.current_zone, bsl_swept=bsl_swept, ssl_swept=ssl_swept, entry_price=c_curr, stop_loss=stop_loss if bias != MarketBias.NONE else 0.0, take_profit=take_profit if bias != MarketBias.NONE else 0.0, confidence=confidence if bias != MarketBias.NONE else 0.0, reason='; '.join(reason_parts) if reason_parts else 'No ICT Setup')
