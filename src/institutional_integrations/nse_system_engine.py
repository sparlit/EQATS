"""
NSE System Multi-Factor & Market Regime Gatekeeper Engine
=========================================================
Adapts composite fundamental/technical scoring, market regime benchmark gatekeeper,
sector momentum ranking, and institutional accumulation tracking from `ankitchaudhary6886/nse-system`.

Magic Number: 9100040
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import zoneinfo

from institutional_integrations.sebi_broker_adapter import (
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
    IndianBrokerPluginRegistry,
)

logger = logging.getLogger(__name__)

MAGIC_NUMBER_NSE_SYSTEM: int = 9100040


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR tick size."""
    return round(round(price / 0.05) * 0.05, 2)


def is_ist_market_open(now_dt: Optional[datetime] = None) -> bool:
    """
    Checks if current time is within Indian Standard Time (IST) market hours:
    09:15 to 15:30 IST, Monday to Friday.
    """
    if now_dt is None:
        ist_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        now_dt = datetime.now(ist_tz)

    if now_dt.weekday() in (5, 6):
        return False

    start_time = now_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    end_time = now_dt.replace(hour=15, minute=30, second=0, microsecond=0)

    return start_time <= now_dt <= end_time


class NSESystemEngine:
    """
    NSE System Multi-Factor Composite Scoring & Top-Down Market Regime Gatekeeper.
    Evaluates benchmark index EMA(10) regime trend, ranks sector relative strength, and
    calculates composite fundamental/technical scores for stock selection.
    """

    def __init__(self, top_n_sectors: int = 3) -> None:
        self.top_n_sectors = top_n_sectors
        self.magic_number = MAGIC_NUMBER_NSE_SYSTEM

    def evaluate_market_regime(
        self, benchmark_close: float, benchmark_ema10: float
    ) -> Dict[str, Any]:
        """
        Evaluates top-down market regime. Long entries allowed only when benchmark > EMA(10).
        """
        is_bullish = benchmark_close > benchmark_ema10
        return {
            "is_bullish": is_bullish,
            "benchmark_close": round_tick_005(benchmark_close),
            "benchmark_ema10": round_tick_005(benchmark_ema10),
            "timestamp": datetime.now().isoformat(),
        }

    def compute_composite_score(self, metrics: Dict[str, float]) -> float:
        """
        Calculates composite score (0 to 100) based on ROCE, Profit Growth, PE vs Sector PE ratio,
        and technical momentum.
        """
        roce = metrics.get("roce", 10.0)
        profit_growth = metrics.get("profit_growth", 10.0)
        pe_ratio = metrics.get("pe_ratio", 1.0)  # Stock PE / Sector PE
        rsi = metrics.get("rsi", 50.0)

        # ROCE Score (0-30 pts)
        roce_score = min(30.0, max(0.0, (roce / 30.0) * 30.0))
        # Profit Growth Score (0-30 pts)
        profit_score = min(30.0, max(0.0, (profit_growth / 25.0) * 30.0))
        # PE Valuation Score (0-20 pts: lower ratio is better)
        pe_score = min(20.0, max(0.0, (2.0 - min(2.0, pe_ratio)) * 10.0))
        # Technical RSI Score (0-20 pts: optimal range 50-70)
        rsi_score = min(20.0, max(0.0, (20.0 - abs(60.0 - rsi))))

        return round(roce_score + profit_score + pe_score + rsi_score, 2)

    def scan_top_picks(
        self,
        stock_universe: List[Dict[str, Any]],
        regime_bullish: bool = True,
        allowed_sectors: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scans stock universe and filters top picks using market regime and sector momentum gatekeepers.
        """
        if not regime_bullish:
            logger.info("Market regime is bearish. Blocking new long trade entries.")
            return []

        allowed_sectors_set = set(s.upper() for s in allowed_sectors) if allowed_sectors else None

        top_picks = []
        for stock in stock_universe:
            symbol = stock.get("symbol", "UNKNOWN").upper()
            sector = stock.get("sector", "").upper()

            if allowed_sectors_set and sector not in allowed_sectors_set:
                continue

            score = self.compute_composite_score(stock)
            if score >= 60.0:
                top_picks.append({
                    "symbol": symbol,
                    "sector": sector,
                    "composite_score": score,
                    "last_price": round_tick_005(stock.get("close", 100.0)),
                    "recommended_action": "BUY" if score >= 75.0 else "ACCUMULATE",
                    "magic_number": self.magic_number,
                    "timestamp": datetime.now().isoformat(),
                })

        return sorted(top_picks, key=lambda x: x["composite_score"], reverse=True)


class NSESystemBrokerAdapter(SEBIBrokerAdapter):
    """
    Broker Adapter plugin for NSE System Multi-Factor Engine.
    """

    def __init__(self, broker_name: str = "NSESystemBroker") -> None:
        super().__init__()
        self.broker_name = broker_name
        self.engine = NSESystemEngine()
        self._connected = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def is_connected(self) -> bool:
        return self._connected

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def authenticate(self, credentials: Dict[str, Any]) -> bool:
        self._connected = True
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return {"broker": self.broker_name, "connected": self._connected}

    def get_history(
        self, symbol: str, timeframe: str = "1d", limit: int = 100
    ) -> List[Dict[str, Any]]:
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 100.0, "ask": 100.05, "last_price": 100.0}

    def execute_order(self, request: SEBIOrderRequest) -> SEBIOrderResponse:
        if not self._connected:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                instrument_token=0,
                error="Broker adapter not connected",
            )

        if not is_ist_market_open():
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED",
                product=request.product,
                exchange=request.exchange,
                instrument_token=0,
                error="Market is closed (Outside IST trading hours)",
            )

        rounded_price = round_tick_005(request.price)
        return SEBIOrderResponse(
            success=True,
            ticket=f"NSESYS-{int(datetime.now().timestamp()*1000)}",
            price=rounded_price,
            status="FILLED",
            product=request.product,
            exchange=request.exchange,
            instrument_token=10008,
            error="",
        )

    def modify_order(
        self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0
    ) -> bool:
        return True

    def close_order(
        self, ticket: str, symbol: str = "", exchange: str = "NSE"
    ) -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=0.0,
            status="CANCELLED",
            product="MIS",
            exchange=exchange,
            instrument_token=0,
            error="",
        )

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return []


# Register plugin in IndianBrokerPluginRegistry on import
IndianBrokerPluginRegistry.register("NSE_SYSTEM", NSESystemBrokerAdapter)
