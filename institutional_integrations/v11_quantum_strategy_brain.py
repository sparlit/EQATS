"""
EQATS Version 11.0.0 Master Strategy Genome & Multi-Asset Horizon Engine.

Decouples Strategy Type from Trading Horizon into independent composable dimensions:
  - 26 Strategy Genome Families (Trend, Momentum, Breakout, Reversal, Mean Reversion, Range, Relative Value, Arbitrage, Spread, Carry, Volatility, Options/Derivatives, Order Flow, Market Structure, Event, News, Fundamental, Macro, Seasonality, Sentiment, Quant, ML, RL, Adaptive, Bowtie/Hourglass, Hybrid)
  - 8 Independent Trading Horizons (HFT, Scalp, Intraday, Day, Short Swing, Swing, Position, Long-Term)
  - Multi-Asset Mapping covering Forex, Precious Metals, Oil/Energy, Stocks, Indices, Crypto, and Indian Venues (NSE, BSE, MSE, MCX, NCDEX).
"""

import math
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("v11_quantum_strategy_brain")


class StrategyFamily:
    TREND = "TREND_FOLLOWING"
    MOMENTUM = "MOMENTUM"
    BREAKOUT = "BREAKOUT"
    REVERSAL = "REVERSAL"
    MEAN_REVERSION = "MEAN_REVERSION"
    RANGE = "RANGE_TRADING"
    RELATIVE_VALUE = "RELATIVE_VALUE"
    ARBITRAGE = "ARBITRAGE"
    SPREAD = "SPREAD_TRADING"
    CARRY = "CARRY_TRADE"
    VOLATILITY = "VOLATILITY"
    OPTIONS = "OPTIONS_DERIVATIVES"
    ORDER_FLOW = "ORDER_FLOW"
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    EVENT_DRIVEN = "EVENT_DRIVEN"
    NEWS = "NEWS_TRADING"
    FUNDAMENTAL = "FUNDAMENTAL"
    MACRO = "MACRO"
    SEASONALITY = "SEASONALITY"
    SENTIMENT = "SENTIMENT"
    QUANTITATIVE = "QUANTITATIVE"
    MACHINE_LEARNING = "MACHINE_LEARNING"
    REINFORCEMENT_LEARNING = "REINFORCEMENT_LEARNING"
    ADAPTIVE_REGIME = "ADAPTIVE_REGIME"
    BOWTIE_HOURGLASS = "BOWTIE_HOURGLASS"
    HYBRID = "HYBRID"


class TradingHorizon:
    HFT = "HFT"                  # Microseconds -> Seconds
    SCALP = "SCALP"              # Seconds -> Minutes
    INTRADAY = "INTRADAY"        # Minutes -> Hours
    DAY = "DAY_TRADING"          # Session Open -> Close
    SHORT_SWING = "SHORT_SWING"  # 1 -> 5 Days
    SWING = "SWING"              # Days -> Weeks
    POSITION = "POSITION"        # Weeks -> Months
    LONG_TERM = "LONG_TERM"      # Months -> Years


class AssetClass:
    FOREX = "FOREX"
    PRECIOUS_METALS = "PRECIOUS_METALS"
    OIL_ENERGY = "OIL_ENERGY"
    EQUITIES = "EQUITIES"
    INDICES = "INDICES"
    CRYPTO = "CRYPTO"
    INDIAN_NSE = "INDIAN_NSE"
    INDIAN_BSE = "INDIAN_BSE"
    INDIAN_MSE = "INDIAN_MSE"
    INDIAN_MCX = "INDIAN_MCX"
    INDIAN_NCDEX = "INDIAN_NCDEX"


class StrategyGenomeInstance:
    """
    Standardized Strategy Genome representation as defined in the taxonomy specification.
    """

    def __init__(
        self,
        strategy_id: str,
        family: str,
        horizon: str,
        asset_class: str,
        exchange: str,
        symbol: str,
        timeframe: str = "M15"
    ):
        self.strategy_id = strategy_id
        self.family = family
        self.horizon = horizon
        self.asset_class = asset_class
        self.exchange = exchange
        self.symbol = symbol
        self.timeframe = timeframe
        self.confidence_score = 0.50
        self.validation_state = "CANDIDATE"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "family": self.family,
            "horizon": self.horizon,
            "asset_class": self.asset_class,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "confidence_score": round(self.confidence_score, 2),
            "validation_state": self.validation_state,
        }


class QuantumStrategyGenomeBrain:
    """
    Master Strategy Genome Brain for EQATS Version 11.0.0.
    Evaluates signal candidates across composable strategy families and trading horizons.
    """

    def __init__(self):
        self.version = "11.0.0"
        self.registered_genomes: Dict[str, StrategyGenomeInstance] = {}

    def classify_asset_class(self, symbol: str) -> str:
        sym = symbol.upper()
        if ":" in sym:
            exch, symbol_code = sym.split(":", 1)
            if exch in ["NSE", "NFO"]:
                return AssetClass.INDIAN_NSE
            elif exch == "BSE":
                return AssetClass.INDIAN_BSE
            elif exch == "MCX":
                return AssetClass.INDIAN_MCX
            elif exch == "NCDEX":
                return AssetClass.INDIAN_NCDEX

        if any(m in sym for m in ["XAU", "GOLD", "XAG", "SILVER", "PLATINUM"]):
            return AssetClass.PRECIOUS_METALS
        elif any(e in sym for e in ["WTI", "BRENT", "OIL", "USOIL", "UKOIL", "NATGAS"]):
            return AssetClass.OIL_ENERGY
        elif any(c in sym for c in ["BTC", "ETH", "SOL", "XRP", "LTC", "DOGE"]):
            return AssetClass.CRYPTO
        elif any(idx in sym for idx in ["US30", "NAS100", "SPX500", "GER40", "UK100", "NIFTY", "BANKNIFTY"]):
            return AssetClass.INDICES
        else:
            return AssetClass.FOREX

    def generate_strategy_genome(
        self,
        symbol: str,
        family: str,
        horizon: str,
        timeframe: str = "M15"
    ) -> StrategyGenomeInstance:
        asset_cls = self.classify_asset_class(symbol)
        exchange = symbol.split(":")[0] if ":" in symbol else "GLOBAL_INTERBANK"
        strat_id = f"V11_GENOME_{family}_{horizon}_{symbol.replace(':', '_')}"

        genome = StrategyGenomeInstance(
            strategy_id=strat_id,
            family=family,
            horizon=horizon,
            asset_class=asset_cls,
            exchange=exchange,
            symbol=symbol,
            timeframe=timeframe
        )
        self.registered_genomes[strat_id] = genome
        return genome

    def evaluate_bowtie_hourglass_strategy(
        self,
        symbol: str,
        current_price: float,
        atr_val: float,
        regime: str = "TRENDING"
    ) -> Dict[str, Any]:
        """
        Evaluates the Bowtie / Hourglass conditional breakout & position construction model.
        Sets pending buy-stop and sell-stop structures around the current price axis.
        """
        buy_entry_trigger = current_price + (atr_val * 0.5)
        sell_entry_trigger = current_price - (atr_val * 0.5)
        buy_sl = current_price - (atr_val * 1.5)
        sell_sl = current_price + (atr_val * 1.5)

        decision = "HOLD"
        if regime == "TRENDING":
            decision = "BUY_PENDING_STOP" if current_price >= buy_entry_trigger else "SELL_PENDING_STOP" if current_price <= sell_entry_trigger else "HOLD"

        return {
            "strategy": StrategyFamily.BOWTIE_HOURGLASS,
            "symbol": symbol,
            "decision": decision,
            "buy_trigger": round(buy_entry_trigger, 5),
            "sell_trigger": round(sell_entry_trigger, 5),
            "buy_sl": round(buy_sl, 5),
            "sell_sl": round(sell_sl, 5),
            "explanation": f"Bowtie/Hourglass conditional structure set around LTP {current_price:.5f} (ATR={atr_val:.5f})",
        }


global_v11_quantum_strategy_brain = QuantumStrategyGenomeBrain()
