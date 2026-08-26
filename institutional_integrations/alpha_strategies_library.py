"""
Institutional Advanced Trading Strategies & Alpha Models Library.
Adapted from Fincept Terminal strategies/alphas (ft.txt) including Greenblatt Magic Formula,
VIX Dual Thrust, Global Equity IBS Mean Reversion, Intraday Reversal Currency Alpha,
and Triple Leverage Volatility Decay Arbitrage.
"""

import math
import logging
from typing import Dict, List, Any, Optional, Tuple, Union
import numpy as np

_log = logging.getLogger(__name__)


class AlphaStrategyLibrary:
    """
    Quantitative Alpha Generation Models Engine.
    """

    @staticmethod
    def greenblatt_magic_formula_alpha(universe_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Ranks equity universe by Earnings Yield (EBIT / EV) and Return on Capital (EBIT / (Net Working Capital + Net Fixed Assets)).
        universe_data item expected format:
          {'symbol': str, 'ebit': float, 'enterprise_value': float, 'working_capital': float, 'fixed_assets': float}
        """
        ranked_list = []
        for stock in universe_data:
            sym = stock.get("symbol", "UNKNOWN")
            ebit = float(stock.get("ebit", 0.0))
            ev = float(stock.get("enterprise_value", 1e6))
            wc = float(stock.get("working_capital", 1e5))
            fa = float(stock.get("fixed_assets", 1e5))

            earnings_yield = ebit / ev if ev > 0 else -999.0
            roc = ebit / (wc + fa) if (wc + fa) > 0 else -999.0

            ranked_list.append({
                "symbol": sym,
                "earnings_yield": earnings_yield,
                "roc": roc
            })

        # Rank by Earnings Yield (descending)
        ranked_list.sort(key=lambda x: x["earnings_yield"], reverse=True)
        for idx, item in enumerate(ranked_list):
            item["ey_rank"] = idx + 1

        # Rank by ROC (descending)
        ranked_list.sort(key=lambda x: x["roc"], reverse=True)
        for idx, item in enumerate(ranked_list):
            item["roc_rank"] = idx + 1
            item["combined_rank"] = item["ey_rank"] + item["roc_rank"]

        # Final ranking by combined rank (ascending)
        ranked_list.sort(key=lambda x: x["combined_rank"])
        return ranked_list

    @staticmethod
    def vix_dual_thrust_alpha(
        prices_high: np.ndarray,
        prices_low: np.ndarray,
        prices_close: np.ndarray,
        vix_level: float = 20.0,
        k_upper: float = 0.5,
        k_lower: float = 0.5
    ) -> Dict[str, Any]:
        """
        Calculates Dual Thrust breakout levels dynamically adjusted by VIX regime.
        """
        if len(prices_close) < 5:
            return {"signal": "HOLD", "upper_trigger": 0.0, "lower_trigger": 0.0}

        hh = float(np.max(prices_high[-5:]))
        hc = float(np.max(prices_close[-5:]))
        lc = float(np.min(prices_close[-5:]))
        ll = float(np.min(prices_low[-5:]))

        range_val = max(hh - lc, hc - ll)
        vix_mult = max(0.8, min(1.5, vix_level / 20.0))

        open_price = float(prices_close[-1])
        upper_trigger = open_price + (k_upper * range_val * vix_mult)
        lower_trigger = open_price - (k_lower * range_val * vix_mult)

        last_close = float(prices_close[-1])
        if last_close > upper_trigger:
            signal = "BUY"
        elif last_close < lower_trigger:
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "signal": signal,
            "upper_trigger": upper_trigger,
            "lower_trigger": lower_trigger,
            "range": range_val,
            "vix_mult": vix_mult
        }

    @staticmethod
    def global_equity_ibs_alpha(
        close_price: float,
        high_price: float,
        low_price: float
    ) -> Dict[str, Any]:
        """
        Calculates Internal Bar Strength (IBS = (Close - Low) / (High - Low)).
        IBS < 0.2 indicates oversold mean-reversion BUY, IBS > 0.8 indicates overbought SELL.
        """
        if high_price <= low_price:
            return {"ibs": 0.5, "signal": "HOLD"}

        ibs = (close_price - low_price) / (high_price - low_price)
        if ibs < 0.20:
            signal = "BUY"
        elif ibs > 0.80:
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "ibs": float(ibs),
            "signal": signal,
            "rationale": f"IBS score={ibs:.3f}"
        }

    @staticmethod
    def triple_leverage_decay_arbitrage(
        bull_etf_price: float,
        bear_etf_price: float,
        volatility: float
    ) -> Dict[str, Any]:
        """
        Identifies volatility decay arbitrage opportunities in leveraged ETF pairs (e.g., TQQQ / SQQQ).
        """
        expected_decay_annual = 3.0 * (3.0 - 1.0) * 0.5 * (volatility ** 2)
        signal = "SHORT_BOTH_PAIR" if volatility > 0.25 else "HOLD"

        return {
            "annualized_expected_decay_pct": float(expected_decay_annual * 100.0),
            "volatility": float(volatility),
            "signal": signal,
            "pair_ratio": float(bull_etf_price / bear_etf_price) if bear_etf_price > 0 else 1.0
        }
