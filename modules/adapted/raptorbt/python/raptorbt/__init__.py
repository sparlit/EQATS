import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


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


from raptorbt._raptorbt import (
    IST_OFFSET_NS,
    SESSION_CDS,
    SESSION_CONTINUOUS,
    SESSION_MCX,
    # Session lengths (minutes) for BacktestConfig(session_minutes=...)
    SESSION_NSE,
    # Config classes
    BacktestConfig,
    BacktestMetrics,
    # Result classes
    BacktestResult,
    # Bar aggregation
    BarAggregator,
    # Batch backtest
    BatchSingleItem,
    BatchSpreadItem,
    EngineEvent,
    # Streaming indicators
    Indicator,
    InstrumentConfig,
    # Instrument market definitions
    InstrumentSpec,
    InstrumentSummary,
    # Per-bar strategy session (class-based strategy contract)
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
    # Portfolio math (covariance, optimizer, factor panels, risk
    # contributions, rebalance simulation, cost schedule)
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
    # Tick signal functions
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
    # Backtest functions
    run_single_backtest,
    run_spread_backtest,
    run_tick_backtest,
    # Monte Carlo simulation
    simulate_portfolio_mc,
    simulate_rebalance_policy,
    # Indicator functions
    sma,
    stochastic,
    supertrend,
    # Tick feature functions
    tick_spread_pct,
    tick_velocity,
    vwap,
    winsorize_panel,
    zscore_panel,
)
from raptorbt.strategy import (
    Bar,
    ClosePosition,
    MarketOrder,
    PortfolioContext,
    Strategy,
    StrategyConfig,
    StrategyContext,
    TickStrategyStream,
    run_portfolio_strategy,
    run_strategy_backtest,
    run_tick_strategy,
)

try:  # Python 3.8+
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("raptorbt")
except Exception:  # pragma: no cover - source checkout without install metadata
    __version__ = "unknown"

# Tell the log, at most once a day, if this install is behind the latest
# release. Runs on a daemon thread and swallows every failure, so it cannot
# delay or break this import. Opt out with RAPTORBT_NO_VERSION_CHECK=1.
from raptorbt.version_check import check_for_update as _check_for_update

_check_for_update(__version__)

__all__ = [
    "IST_OFFSET_NS",
    "SESSION_CDS",
    "SESSION_CONTINUOUS",
    "SESSION_MCX",
    # Session lengths
    "SESSION_NSE",
    # Config classes
    "BacktestConfig",
    "BacktestMetrics",
    "BacktestResult",
    # Class-based strategy contract
    "Bar",
    "BarAggregator",
    # Batch backtest
    "BatchSingleItem",
    "BatchSpreadItem",
    "ClosePosition",
    "EngineEvent",
    "Indicator",
    "InstrumentConfig",
    # Per-bar strategy session (class-based strategy contract)
    "InstrumentSpec",
    "InstrumentSummary",
    "KernelSession",
    "MarketOrder",
    "OptimizationResult",
    "OptimizeItem",
    "OptimizerConfig",
    "PortfolioContext",
    # Result classes
    "PortfolioResult",
    "PortfolioSession",
    "PositionSnapshot",
    "RankIC",
    "RebalanceSimResult",
    "RiskContributions",
    # Portfolio math
    "RiskModel",
    "StopConfig",
    "Strategy",
    "StrategyConfig",
    "StrategyContext",
    "TargetConfig",
    "TickStrategyStream",
    "Trade",
    "adx",
    "aggregate_bars",
    "atr",
    "bars_from_ticks",
    "batch_optimize_portfolios",
    "batch_single_backtest",
    "batch_spread_backtest",
    "bollinger_bands",
    "buy_sell_imbalance_delta",
    "composite_scores",
    "compute_risk_contributions",
    # Tick signal functions
    "compute_tick_entry_signals",
    "compute_tick_exit_signals",
    "ema",
    "estimate_covariance",
    "indian_cost_schedule",
    "macd",
    "momentum_panel",
    "oi_position_pct",
    "optimize_portfolio",
    "rank_ic",
    "rank_panel",
    "realized_vol_rolling",
    "resolve_atr_period",
    "return_window",
    "rolling_max",
    "rolling_min",
    "rsi",
    "run_basket_backtest",
    "run_multi_backtest",
    "run_options_backtest",
    "run_pairs_backtest",
    "run_portfolio_backtest",
    "run_portfolio_strategy",
    # Backtest functions
    "run_single_backtest",
    "run_spread_backtest",
    "run_strategy_backtest",
    "run_tick_backtest",
    "run_tick_strategy",
    # Monte Carlo simulation
    "simulate_portfolio_mc",
    "simulate_rebalance_policy",
    # Indicator functions
    "sma",
    "stochastic",
    "supertrend",
    # Tick feature functions
    "tick_spread_pct",
    "tick_velocity",
    "vwap",
    "winsorize_panel",
    "zscore_panel",
]
