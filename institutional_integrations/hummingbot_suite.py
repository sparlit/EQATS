"""
Hummingbot Suite (EQATS Institutional Adaptation)
Adapted from hummingbot/hummingbot (strategy/avellaneda_market_making, pure_market_making, cross_exchange_market_making)

Provides:
- AvellanedaStoikovMarketMakingEngine: Optimal Control Theory reservation prices & spreads
- PureMarketMakingInventorySkewEngine: Dynamic inventory-skewed quoting
- CrossExchangeArbitrageEngine: Maker/Taker order book arbitrage evaluator
"""
from dataclasses import dataclass
from typing import Optional, Tuple, Any
import math

@dataclass
class AvellanedaQuote:
    reservation_price: float
    bid_price: float
    ask_price: float
    half_spread: float
    spread_pct: float

@dataclass
class SkewedSpreads:
    bid_spread: float
    ask_spread: float
    skew_factor: float

@dataclass
class ArbitrageOpportunity:
    opportunity_found: bool
    direction: str
    gross_spread_pct: float
    net_profit_pct: float
    buy_price: float
    sell_price: float

class AvellanedaStoikovMarketMakingEngine:
    """Avellaneda-Stoikov High-Frequency Market Making Engine based on Optimal Control Theory."""

    def compute_quotes(self, mid_price: float, inventory: float, target_inventory: float=0.0, volatility: float=0.02, risk_aversion: float=0.1, liquidity_density: float=1.5, time_horizon: float=1.0) -> AvellanedaQuote:
        """Calculates optimal reservation price and bid/ask quote prices."""
        if mid_price <= 0:
            return AvellanedaQuote(0.0, 0.0, 0.0, 0.0, 0.0)
        inv_delta = inventory - target_inventory
        reservation_price = mid_price - inv_delta * risk_aversion * volatility ** 2 * time_horizon
        term1 = risk_aversion * volatility ** 2 * time_horizon
        term2 = 2.0 / max(1e-05, risk_aversion) * math.log(1.0 + risk_aversion / max(1e-05, liquidity_density))
        half_spread = (term1 + term2) / 2.0
        bid_price = max(0.01, reservation_price - half_spread)
        ask_price = reservation_price + half_spread
        spread_pct = (ask_price - bid_price) / mid_price * 100.0
        return AvellanedaQuote(reservation_price=round(reservation_price, 4), bid_price=round(bid_price, 4), ask_price=round(ask_price, 4), half_spread=round(half_spread, 4), spread_pct=round(spread_pct, 4))

class PureMarketMakingInventorySkewEngine:
    """Inventory Skew Engine for Pure Market Making."""

    def compute_skewed_spreads(self, base_bid_spread: float=0.005, base_ask_spread: float=0.005, current_inventory_pct: float=0.7, target_inventory_pct: float=0.5, skew_sensitivity: float=2.0) -> SkewedSpreads:
        """Adjusts bid and ask spreads proportionally to inventory bias from target."""
        inventory_delta = current_inventory_pct - target_inventory_pct
        skew_factor = max(-1.0, min(1.0, inventory_delta * skew_sensitivity))
        bid_spread = base_bid_spread * (1.0 + skew_factor)
        ask_spread = base_ask_spread * (1.0 - skew_factor * 0.5)
        return SkewedSpreads(bid_spread=round(max(0.0001, bid_spread), 6), ask_spread=round(max(0.0001, ask_spread), 6), skew_factor=round(skew_factor, 4))

class CrossExchangeArbitrageEngine:
    """Cross-Exchange Market Making & Arbitrage Evaluator."""

    def evaluate_arbitrage(self, maker_ask: float, maker_bid: float, taker_ask: float, taker_bid: float, maker_fee_pct: float=0.001, taker_fee_pct: float=0.002, min_profitability_pct: float=0.002) -> ArbitrageOpportunity:
        """Evaluates arbitrage profitability between Maker and Taker order books."""
        taker_buy_cost = taker_ask * (1.0 + taker_fee_pct)
        maker_sell_revenue = maker_bid * (1.0 - maker_fee_pct)
        net_profit_a = (maker_sell_revenue - taker_buy_cost) / taker_ask
        if net_profit_a >= min_profitability_pct:
            gross_spread = (maker_bid - taker_ask) / taker_ask
            return ArbitrageOpportunity(opportunity_found=True, direction='TAKER_BUY_MAKER_SELL', gross_spread_pct=round(gross_spread * 100.0, 4), net_profit_pct=round(net_profit_a * 100.0, 4), buy_price=taker_ask, sell_price=maker_bid)
        maker_buy_cost = maker_ask * (1.0 + maker_fee_pct)
        taker_sell_revenue = taker_bid * (1.0 - taker_fee_pct)
        net_profit_b = (taker_sell_revenue - maker_buy_cost) / maker_ask
        if net_profit_b >= min_profitability_pct:
            gross_spread = (taker_bid - maker_ask) / maker_ask
            return ArbitrageOpportunity(opportunity_found=True, direction='MAKER_BUY_TAKER_SELL', gross_spread_pct=round(gross_spread * 100.0, 4), net_profit_pct=round(net_profit_b * 100.0, 4), buy_price=maker_ask, sell_price=taker_bid)
        return ArbitrageOpportunity(opportunity_found=False, direction='NONE', gross_spread_pct=0.0, net_profit_pct=0.0, buy_price=0.0, sell_price=0.0)
