"""
Prediction Market Arbitrage Engine (Polymarket & Kalshi).
Calculates cross-venue probability arbitrage, complementary binary outcome spreads,
fee deductions, and depth-weighted probability edges.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class MarketQuote:
    venue: str
    market_id: str
    yes_bid: float
    yes_ask: float
    no_bid: float
    no_ask: float
    yes_ask_depth: float
    no_ask_depth: float
    magic_number: int = 9200001


@dataclass
class ArbitrageOpportunity:
    market_id: str
    outcome_target: str
    buy_venue: str
    sell_venue: str
    buy_price: float
    sell_price: float
    gross_spread: float
    fee_deduction: float
    net_profit_per_share: float
    max_executable_volume: float
    expected_net_profit: float
    implied_probability_edge: float


class PolymarketKalshiArbEngine:
    """
    Arbitrage Engine evaluating mispricings across Polymarket, Kalshi, and binary prediction markets.
    """

    def __init__(
        self, polymarket_fee_pct: float = 0.0, kalshi_fee_pct: float = 0.0075, min_net_profit_threshold: float = 0.01,
    ) -> None:
        self.polymarket_fee_pct: float = polymarket_fee_pct
        self.kalshi_fee_pct: float = kalshi_fee_pct
        self.min_net_profit_threshold: float = min_net_profit_threshold

    def evaluate_cross_venue_arbitrage(
        self, poly_quote: MarketQuote, kalshi_quote: MarketQuote,
    ) -> list[ArbitrageOpportunity]:
        opportunities: list[ArbitrageOpportunity] = []
        if poly_quote.yes_ask > 0 and kalshi_quote.yes_bid > 0:
            gross_spread = kalshi_quote.yes_bid - poly_quote.yes_ask
            poly_fee = poly_quote.yes_ask * self.polymarket_fee_pct
            kalshi_fee = kalshi_quote.yes_bid * self.kalshi_fee_pct
            total_fee = poly_fee + kalshi_fee
            net_profit = gross_spread - total_fee
            if net_profit >= self.min_net_profit_threshold:
                max_vol = min(poly_quote.yes_ask_depth, 10000.0)
                opportunities.append(
                    ArbitrageOpportunity(
                        market_id=poly_quote.market_id,
                        outcome_target="YES",
                        buy_venue="POLYMARKET",
                        sell_venue="KALSHI",
                        buy_price=poly_quote.yes_ask,
                        sell_price=kalshi_quote.yes_bid,
                        gross_spread=gross_spread,
                        fee_deduction=total_fee,
                        net_profit_per_share=net_profit,
                        max_executable_volume=max_vol,
                        expected_net_profit=net_profit * max_vol,
                        implied_probability_edge=net_profit,
                    ),
                )
        if kalshi_quote.yes_ask > 0 and poly_quote.yes_bid > 0:
            gross_spread = poly_quote.yes_bid - kalshi_quote.yes_ask
            kalshi_fee = kalshi_quote.yes_ask * self.kalshi_fee_pct
            poly_fee = poly_quote.yes_bid * self.polymarket_fee_pct
            total_fee = kalshi_fee + poly_fee
            net_profit = gross_spread - total_fee
            if net_profit >= self.min_net_profit_threshold:
                max_vol = min(kalshi_quote.yes_ask_depth, 10000.0)
                opportunities.append(
                    ArbitrageOpportunity(
                        market_id=poly_quote.market_id,
                        outcome_target="YES",
                        buy_venue="KALSHI",
                        sell_venue="POLYMARKET",
                        buy_price=kalshi_quote.yes_ask,
                        sell_price=poly_quote.yes_bid,
                        gross_spread=gross_spread,
                        fee_deduction=total_fee,
                        net_profit_per_share=net_profit,
                        max_executable_volume=max_vol,
                        expected_net_profit=net_profit * max_vol,
                        implied_probability_edge=net_profit,
                    ),
                )
        for quote in [poly_quote, kalshi_quote]:
            fee_pct = self.polymarket_fee_pct if quote.venue == "POLYMARKET" else self.kalshi_fee_pct
            combined_cost = quote.yes_ask + quote.no_ask
            if 0 < combined_cost < 1.0:
                fee = combined_cost * fee_pct
                payout = 1.0
                net_profit = payout - combined_cost - fee
                if net_profit >= self.min_net_profit_threshold:
                    max_vol = min(quote.yes_ask_depth, quote.no_ask_depth)
                    opportunities.append(
                        ArbitrageOpportunity(
                            market_id=quote.market_id,
                            outcome_target="BINARY_PAIR",
                            buy_venue=quote.venue,
                            sell_venue="SETTLEMENT_PAYOUT",
                            buy_price=combined_cost,
                            sell_price=1.0,
                            gross_spread=1.0 - combined_cost,
                            fee_deduction=fee,
                            net_profit_per_share=net_profit,
                            max_executable_volume=max_vol,
                            expected_net_profit=net_profit * max_vol,
                            implied_probability_edge=net_profit,
                        ),
                    )
        return opportunities

    def calculate_depth_weighted_probability(self, asks: list[tuple[float, float]]) -> float:
        """
        Derives probability estimate from depth-weighted asks [(price, volume), ...].
        """
        if not asks:
            return 0.5
        total_vol = sum((v for _, v in asks))
        if total_vol <= 0:
            return asks[0][0]
        weighted_price = sum((p * v for p, v in asks)) / total_vol
        return max(0.0, min(1.0, weighted_price))
