import datetime
from decimal import ROUND_HALF_UP, Decimal

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    if dt is None:
        now = datetime.datetime.now(ist)
    elif dt.tzinfo is None:
        now = ist.localize(dt)
    else:
        now = dt.astimezone(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    tick = Decimal(str(tick_size))
    price_dec = Decimal(str(price))
    rounded = (price_dec / tick).quantize(Decimal(1), rounding=ROUND_HALF_UP) * tick
    return float(rounded.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


"""
RaptorBT - High-performance Rust backtesting engine.

Provides Python bindings for a Rust-based backtesting engine built for
production quantitative trading:
- Sub-millisecond execution on thousands of bars
- Disk footprint: <10MB, startup latency: <10ms
- 100% deterministic execution (no JIT cache)
- Native parallelism via Rayon + explicit SIMD
- Full tick-level simulation (no bar resampling required)
"""

try:
    from raptorbt._raptorbt import (
        IST_OFFSET_NS,
        SESSION_CDS,
        SESSION_CONTINUOUS,
        SESSION_MCX,
        SESSION_NSE,
        BacktestConfig,
        BacktestMetrics,
        BacktestResult,
        BarAggregator,
        BatchSingleItem,
        BatchSpreadItem,
        EngineEvent,
        Indicator,
        InstrumentConfig,
        InstrumentSpec,
        InstrumentSummary,
        KernelSession,
        OptimizationResult,
        OptimizeItem,
        OptimizerConfig,
        PortfolioResult,
        PortfolioSession,
        PositionSnapshot,
        RankIC,
        RebalanceSimResult,
        RiskContributions,
        RiskModel,
        StopConfig,
        TargetConfig,
        Trade,
        adx,
        aggregate_bars,
        atr,
        bars_from_ticks,
        batch_optimize_portfolios,
        batch_single_backtest,
        batch_spread_backtest,
        bollinger_bands,
        buy_sell_imbalance_delta,
        composite_scores,
        compute_risk_contributions,
        compute_tick_entry_signals,
        compute_tick_exit_signals,
        ema,
        estimate_covariance,
        indian_cost_schedule,
        macd,
        momentum_panel,
        oi_position_pct,
        optimize_portfolio,
        rank_ic,
        rank_panel,
        realized_vol_rolling,
        resolve_atr_period,
        return_window,
        rolling_max,
        rolling_min,
        rsi,
        run_basket_backtest,
        run_multi_backtest,
        run_options_backtest,
        run_pairs_backtest,
        run_portfolio_backtest,
    )
except ImportError:
    # Rust extension not built; provide stubs for type checking
    IST_OFFSET_NS = 19800000000000
    SESSION_CDS = "CDS"
    SESSION_CONTINUOUS = "CONTINUOUS"
    SESSION_MCX = "MCX"
    SESSION_NSE = "NSE"

    class BacktestConfig: ...

    class BacktestMetrics: ...

    class BacktestResult: ...

    class BarAggregator: ...

    class BatchSingleItem: ...

    class BatchSpreadItem: ...

    class EngineEvent: ...

    class Indicator: ...

    class InstrumentConfig: ...

    class InstrumentSpec: ...

    class InstrumentSummary: ...

    class KernelSession: ...

    class OptimizationResult: ...

    class OptimizeItem: ...

    class OptimizerConfig: ...

    class PortfolioResult: ...

    class PortfolioSession: ...

    class PositionSnapshot: ...

    class RankIC: ...

    class RebalanceSimResult: ...

    class RiskContributions: ...

    class RiskModel: ...

    class StopConfig: ...

    class TargetConfig: ...

    class Trade: ...

    def adx(*args, **kwargs): ...
    def aggregate_bars(*args, **kwargs): ...
    def atr(*args, **kwargs): ...
    def bars_from_ticks(*args, **kwargs): ...
    def batch_optimize_portfolios(*args, **kwargs): ...
    def batch_single_backtest(*args, **kwargs): ...
    def batch_spread_backtest(*args, **kwargs): ...
    def bollinger_bands(*args, **kwargs): ...
    def buy_sell_imbalance_delta(*args, **kwargs): ...
    def composite_scores(*args, **kwargs): ...
    def compute_risk_contributions(*args, **kwargs): ...
    def compute_tick_entry_signals(*args, **kwargs): ...
    def compute_tick_exit_signals(*args, **kwargs): ...
    def ema(*args, **kwargs): ...
    def estimate_covariance(*args, **kwargs): ...
    def indian_cost_schedule(*args, **kwargs): ...
    def macd(*args, **kwargs): ...
    def momentum_panel(*args, **kwargs): ...
    def oi_position_pct(*args, **kwargs): ...
    def optimize_portfolio(*args, **kwargs): ...
    def rank_ic(*args, **kwargs): ...
    def rank_panel(*args, **kwargs): ...
    def realized_vol_rolling(*args, **kwargs): ...
    def resolve_atr_period(*args, **kwargs): ...
    def return_window(*args, **kwargs): ...
    def rolling_max(*args, **kwargs): ...
    def rolling_min(*args, **kwargs): ...
    def rsi(*args, **kwargs): ...
    def run_basket_backtest(*args, **kwargs): ...
    def run_multi_backtest(*args, **kwargs): ...
    def run_options_backtest(*args, **kwargs): ...
    def run_pairs_backtest(*args, **kwargs): ...
    def run_portfolio_backtest(*args, **kwargs): ...
