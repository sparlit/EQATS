"""
CryptoTrader V2 Engine (EQATS Institutional Adaptation)
Adapted from mathish06/crypto_trader_V2

Provides:
- High-Frequency Order Book Imbalance (OBI) Ratio Scalper Engine
- AI Oracle Market Psychology & News Sentiment Evaluator
- Sub-100ms SL/TP State Machine & Paper Execution Emulator
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class OBISignalType(str, Enum):
    NONE = "NONE"
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class OrderBookLevel:
    price: float
    quantity: float


@dataclass
class OrderBookDepthPayload:
    symbol: str
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]


@dataclass
class SentimentResult:
    score: float
    classification: str
    signal: OBISignalType
    reasoning: str


@dataclass
class OBIScalperState:
    position_open: bool = False
    entry_price: float = 0.0
    quantity: float = 0.0
    unrealized_pnl_pct: float = 0.0


class CryptoTraderV2Engine:
    """CryptoTrader V2 Engine."""

    def __init__(
        self,
        obi_buy_threshold: float = 0.75,
        obi_sell_threshold: float = 0.25,
        take_profit_pct: float = 0.2,
        stop_loss_pct: float = 0.15,
    ) -> None:
        self.obi_buy_threshold = obi_buy_threshold
        self.obi_sell_threshold = obi_sell_threshold
        self.take_profit_pct = take_profit_pct
        self.stop_loss_pct = stop_loss_pct
        self.state = OBIScalperState()

    def calculate_obi_ratio(self, bids: list[OrderBookLevel], asks: list[OrderBookLevel]) -> float:
        """
        Calculates Order Book Imbalance (OBI) ratio.
        OBI = total_bid_vol / (total_bid_vol + total_ask_vol)
        """
        total_bid_vol = sum(b.quantity for b in bids)
        total_ask_vol = sum(a.quantity for a in asks)
        total_vol = total_bid_vol + total_ask_vol
        if total_vol <= 0:
            return 0.5
        return total_bid_vol / total_vol

    def evaluate_order_book_tick(self, payload: OrderBookDepthPayload) -> tuple[OBISignalType, float, str]:
        """Evaluates top depth order book levels and returns signal decisions."""
        if not payload.bids or not payload.asks:
            return (OBISignalType.NONE, 0.0, "Empty order book depth")
        best_bid = payload.bids[0].price
        best_ask = payload.asks[0].price
        mid_price = (best_bid + best_ask) / 2.0
        obi_ratio = self.calculate_obi_ratio(payload.bids, payload.asks)
        if self.state.position_open:
            pnl_pct = (best_bid - self.state.entry_price) / self.state.entry_price * 100.0
            self.state.unrealized_pnl_pct = pnl_pct
            if pnl_pct >= self.take_profit_pct:
                self.state.position_open = False
                return (OBISignalType.SELL, best_bid, f"Take Profit Hit (+{pnl_pct:.2f}%)")
            if pnl_pct <= -self.stop_loss_pct:
                self.state.position_open = False
                return (OBISignalType.SELL, best_bid, f"Stop Loss Hit ({pnl_pct:.2f}%)")
            return (OBISignalType.NONE, best_bid, f"Holding position (PnL: {pnl_pct:.2f}%)")
        if obi_ratio >= self.obi_buy_threshold:
            self.state.position_open = True
            self.state.entry_price = best_ask
            self.state.quantity = 1.0
            return (OBISignalType.BUY, best_ask, f"OBI Buy Signal (Ratio: {obi_ratio:.3f} >= {self.obi_buy_threshold})")
        return (OBISignalType.NONE, mid_price, f"Balanced Order Book (OBI: {obi_ratio:.3f})")

    def evaluate_market_sentiment(self, score: float, headlines: list[str]) -> SentimentResult:
        """
        Evaluates Gemini/Oracle Market Sentiment Score (0 to 100 scale).
        Score < 20: Capitulation / Panic -> Contrarian BUY
        Score > 80: Euphoria / FOMO -> Contrarian SELL
        """
        if score < 20.0:
            return SentimentResult(
                score=score,
                classification="CAPITULATION / EXTREME PANIC",
                signal=OBISignalType.BUY,
                reasoning=f"Sentiment score {score:.1f} < 20.0: Extreme panic buy opportunity",
            )
        if score > 80.0:
            return SentimentResult(
                score=score,
                classification="EUPHORIA / FOMO BUBBLE",
                signal=OBISignalType.SELL,
                reasoning=f"Sentiment score {score:.1f} > 80.0: Extreme euphoria sell opportunity",
            )
        return SentimentResult(
            score=score,
            classification="NEUTRAL / MIXED",
            signal=OBISignalType.NONE,
            reasoning=f"Sentiment score {score:.1f} in neutral range (20-80)",
        )
