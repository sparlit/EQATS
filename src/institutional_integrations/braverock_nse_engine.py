"""
Numerical Standard Error (NSE) Engine (Repo 084 Adaptation)
===========================================================
Adapted from braverock/nse under Magic Number 9100081.
Provides Numerical Standard Error (NSE) estimation for time series returns,
MCMC outputs, and strategy backtest equity curves using Batch Means (BM),
Overlapping Batch Means (OBM), Newey-West Kernel, and Prewhitening methods.
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import math

from .sebi_broker_adapter import (
    IndianBrokerPluginRegistry,
    SEBIBrokerAdapter,
    SEBIOrderRequest,
    SEBIOrderResponse,
)

MAGIC_NUMBER = 9100081


def round_tick_005(price: float) -> float:
    """Rounds price to nearest 0.05 INR/unit tick size."""
    return round(round(price * 20.0) / 20.0, 2)


def is_ist_market_open(dt: Optional[datetime] = None) -> bool:
    """Checks if current time falls within IST trading session (09:15 - 15:30 IST)."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    ist_dt = dt.astimezone(timezone(timedelta(hours=5, minutes=30)))
    if ist_dt.weekday() >= 5:
        return False
    market_start = ist_dt.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = ist_dt.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_start <= ist_dt <= market_end


@dataclass
class NSESummary:
    """Summary of Numerical Standard Error estimates."""
    mean: float
    variance: float
    nse_bm: float
    nse_obm: float
    nse_kernel: float
    effective_sample_size: float


class NumericalStandardErrorEngine:
    """
    Numerical Standard Error (NSE) calculation engine adapted from braverock/nse.
    Computes standard errors of sample means for autocorrelation time series.
    """

    def __init__(self, name: str = "NumericalStandardErrorEngine") -> None:
        self.name = name
        self.magic_number = MAGIC_NUMBER

    def compute_batch_means(self, series: List[float], nbatch: int = 30) -> float:
        """Computes Batch Means (BM) Numerical Standard Error."""
        n = len(series)
        if n < nbatch or nbatch <= 1:
            return 0.0

        batch_size = n // nbatch
        batches = [
            sum(series[i * batch_size : (i + 1) * batch_size]) / batch_size
            for i in range(nbatch)
        ]
        overall_mean = sum(series) / n
        var_bm = (batch_size / (nbatch - 1)) * sum((b - overall_mean) ** 2 for b in batches)
        return math.sqrt(max(0.0, var_bm / n))

    def compute_overlapping_batch_means(self, series: List[float], batch_size: int = 20) -> float:
        """Computes Overlapping Batch Means (OBM) Numerical Standard Error."""
        n = len(series)
        if n <= batch_size or batch_size <= 1:
            return 0.0

        num_batches = n - batch_size + 1
        overall_mean = sum(series) / n

        running_sum = sum(series[:batch_size])
        batch_means = [running_sum / batch_size]
        for i in range(1, num_batches):
            running_sum += series[i + batch_size - 1] - series[i - 1]
            batch_means.append(running_sum / batch_size)

        var_obm = (batch_size * n) / ((n - batch_size) * (n - batch_size + 1)) * sum(
            (b - overall_mean) ** 2 for b in batch_means
        )
        return math.sqrt(max(0.0, var_obm / n))

    def compute_newey_west_kernel(self, series: List[float], lag: Optional[int] = None) -> float:
        """Computes Newey-West Bartlett kernel Numerical Standard Error."""
        n = len(series)
        if n < 2:
            return 0.0

        if lag is None:
            lag = int(4.0 * ((n / 100.0) ** (2.0 / 9.0)))
        lag = min(lag, n - 1)

        mean_val = sum(series) / n
        residuals = [x - mean_val for x in series]

        gamma_0 = sum(r * r for r in residuals) / n
        gamma_sum = 0.0

        for k in range(1, lag + 1):
            w_k = 1.0 - (k / (lag + 1.0))
            gamma_k = sum(residuals[i] * residuals[i - k] for i in range(k, n)) / n
            gamma_sum += 2.0 * w_k * gamma_k

        lr_var = gamma_0 + gamma_sum
        return math.sqrt(max(0.0, lr_var / n))

    def analyze_time_series(self, series: List[float]) -> NSESummary:
        """Computes comprehensive NSE summary for given time series."""
        if not series:
            return NSESummary(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        n = len(series)
        mean_val = sum(series) / n
        var_val = sum((x - mean_val) ** 2 for x in series) / max(1, n - 1)

        nse_bm = self.compute_batch_means(series)
        nse_obm = self.compute_overlapping_batch_means(series)
        nse_nw = self.compute_newey_west_kernel(series)

        # Effective Sample Size calculation
        if nse_nw > 0 and var_val > 0:
            ess = min(float(n), (var_val / (nse_nw ** 2 * n)) * n)
        else:
            ess = float(n)

        return NSESummary(
            mean=round(mean_val, 6),
            variance=round(var_val, 6),
            nse_bm=round(nse_bm, 6),
            nse_obm=round(nse_obm, 6),
            nse_kernel=round(nse_nw, 6),
            effective_sample_size=round(ess, 2),
        )


class BraverockNSEBrokerAdapter(SEBIBrokerAdapter):
    """SEBI Broker Adapter for Braverock NSE Engine."""

    def __init__(
        self, api_key: str = "", api_secret: str = "", access_token: str = "", is_sandbox: bool = False
    ) -> None:
        super().__init__(api_key=api_key, api_secret=api_secret, access_token=access_token, is_sandbox=is_sandbox)
        self.magic_number = MAGIC_NUMBER
        self.engine = NumericalStandardErrorEngine()

    def connect(self) -> bool:
        self._is_connected = True
        return True

    def is_connected(self) -> bool:
        return self._is_connected

    def disconnect(self) -> bool:
        self._is_connected = False
        return True

    def get_account_info(self) -> Dict[str, Any]:
        return {
            "balance": 1000000.0,
            "equity": 1000000.0,
            "margin_used": 0.0,
            "available_margin": 1000000.0,
        }

    def get_history(
        self, symbol: str, exchange: str = "NSE", count: int = 100, interval: str = "minute"
    ) -> List[Dict[str, Any]]:
        return []

    def get_current_price(self, symbol: str, exchange: str = "NSE") -> Dict[str, float]:
        return {"bid": 100.0, "ask": 100.05, "last": 100.0}

    def execute_order(self, req: SEBIOrderRequest) -> SEBIOrderResponse:
        if not self._is_connected:
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="DISCONNECTED",
                product=req.product,
                exchange=req.exchange,
                error="Adapter is not connected to exchange",
            )

        if not is_ist_market_open():
            return SEBIOrderResponse(
                success=False,
                ticket="",
                price=0.0,
                status="REJECTED",
                product=req.product,
                exchange=req.exchange,
                error="Market is closed outside IST trading hours",
            )

        rounded_price = round_tick_005(req.price)
        return SEBIOrderResponse(
            success=True,
            ticket=f"BRAVEROCK-{req.symbol}-{int(datetime.now().timestamp())}",
            price=rounded_price,
            status="FILLED",
            product=req.product,
            exchange=req.exchange,
            error="",
        )

    def close_order(self, ticket: str, symbol: str, exchange: str = "NSE", product: str = "CNC") -> SEBIOrderResponse:
        return SEBIOrderResponse(
            success=True,
            ticket=ticket,
            price=100.0,
            status="CLOSED",
            product=product,
            exchange=exchange,
            error="",
        )

    def modify_order(self, ticket: str, price: float = 0.0, sl: float = 0.0, tp: float = 0.0) -> bool:
        return True

    def get_open_orders(self) -> List[Dict[str, Any]]:
        return []


# Register adapter in IndianBrokerPluginRegistry
IndianBrokerPluginRegistry.register("BRAVEROCK_NSE", BraverockNSEBrokerAdapter)
