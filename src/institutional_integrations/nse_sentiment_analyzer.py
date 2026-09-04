"""
NSE Sentiment Analyzer Engine (AshayK003/nse-sentiment-analyzer Adaptation)
========================================================================

Target Integration: AshayK003/nse-sentiment-analyzer
Magic Number: 9100028

Provides news headline sentiment polarity aggregation for NSE symbols,
0.05 INR price tick rounding, IST market session validation, and microkernel plugin binding.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime

from institutional_integrations.sebi_broker_adapter import (
    round_to_indian_tick_size,
    round_to_indian_quantity,
    IndianBrokerPluginRegistry,
)
from institutional_integrations.indian_market_state_machine import IndianMarketStateMachine

MAGIC_NUMBER: int = 9100028


class NSESentimentAnalyzer:
    """
    NSE Sentiment Analyzer for Indian financial news headlines.
    """

    BULLISH_KEYWORDS = {
        "profit",
        "growth",
        "record",
        "surge",
        "gain",
        "dividend",
        "upgrade",
        "bullish",
        "outperform",
        "expansion",
    }
    BEARISH_KEYWORDS = {
        "loss",
        "decline",
        "drop",
        "slump",
        "downgrade",
        "bearish",
        "underperform",
        "default",
        "cut",
        "fall",
    }

    def __init__(self, sentiment_threshold: float = 0.25) -> None:
        self.sentiment_threshold = sentiment_threshold
        self.market_state = IndianMarketStateMachine()

    def analyze_headline(self, headline: str) -> float:
        words = headline.lower().split()
        if not words:
            return 0.0
        bull_count = sum(1 for w in words if w in self.BULLISH_KEYWORDS)
        bear_count = sum(1 for w in words if w in self.BEARISH_KEYWORDS)
        total = bull_count + bear_count
        if total == 0:
            return 0.0
        return float((bull_count - bear_count) / total)

    def evaluate_sentiment(
        self,
        symbol: str,
        headlines: List[str],
        current_price: float,
        timestamp: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Evaluates sentiment polarity score across news headlines for a symbol.
        """
        now = timestamp or datetime.now()
        session_valid = self.market_state.is_market_open(now)

        rounded_price = round_to_indian_tick_size(current_price)

        if not session_valid or not headlines:
            return {
                "symbol": symbol,
                "sentiment_score": 0.0,
                "sentiment_label": "NEUTRAL",
                "price": rounded_price,
                "confidence": 0.0,
                "reason": "Market closed or no headlines",
                "magic_number": MAGIC_NUMBER,
            }

        scores = [self.analyze_headline(h) for h in headlines]
        avg_score = float(sum(scores) / len(scores)) if scores else 0.0

        if avg_score >= self.sentiment_threshold:
            label = "BULLISH"
            reason = f"Positive news headline sentiment score ({avg_score:.2f} >= {self.sentiment_threshold})"
        elif avg_score <= -self.sentiment_threshold:
            label = "BEARISH"
            reason = f"Negative news headline sentiment score ({avg_score:.2f} <= -{self.sentiment_threshold})"
        else:
            label = "NEUTRAL"
            reason = f"Neutral headline sentiment score ({avg_score:.2f})"

        return {
            "symbol": symbol,
            "sentiment_score": round(avg_score, 4),
            "sentiment_label": label,
            "price": rounded_price,
            "headline_count": len(headlines),
            "confidence": round(abs(avg_score), 2),
            "reason": reason,
            "magic_number": MAGIC_NUMBER,
        }


# Dynamic Microkernel Plugin Registration
IndianBrokerPluginRegistry.register("ashayk003_nse_sentiment", NSESentimentAnalyzer)
