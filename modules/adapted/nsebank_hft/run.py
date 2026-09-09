from __future__ import annotations

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
run.py — CLI Entry Point
========================

Orchestrates the full end-to-end Monte Carlo pipeline:

  1. Load configuration from YAML
  2. Run data pipeline (fetch / cache / quality-check)
  3. Simulate all enabled models
  4. Compute risk metrics per model
  5. Run walk-forward backtest
  6. Generate all 8 charts (pop-up + PNG)
  7. Build and save HTML/PDF report
  8. Print summary to console

Usage
-----
  python -m monte_carlo.run --config config/default.yaml
  python -m monte_carlo.run --config config/default.yaml --no-plots
  python -m monte_carlo.run --config config/default.yaml --horizon 63
"""


import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import yaml


# ─── Logging setup (must happen before any module imports that use loggers) ──
def _setup_logging(log_level: str = "INFO") -> None:
    log_fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_fmt = "%Y-%m-%d %H:%M:%S"
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO), format=log_fmt, datefmt=date_fmt, stream=sys.stdout
    )
    # Suppress noisy third-party loggers
    for noisy in ["yfinance", "urllib3", "peewee", "requests"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("monte_carlo.run")


def load_config(config_path: str) -> dict:
    """Load and return YAML config from disk."""
    with open(config_path) as f:
        cfg = yaml.safe_load(f)
    logger.info("Config loaded from %s", config_path)
    return cfg


def _make_gbm_simulator(cfg: dict):
    """Return a simulator wrapper with the GBM signature expected by backtest."""
    from .models.gbm import simulate_gbm

    def fn(params, processed_df=None, n_steps=None, n_paths=None, seed=None, **_):
        return simulate_gbm(params, n_steps, n_paths, seed)

    return fn


def _make_bootstrap_simulator(cfg: dict):
    from .models.bootstrap import simulate_bootstrap

    block_size = cfg["simulation"]["block_size"]

    def fn(params, processed_df=None, n_steps=None, n_paths=None, seed=None, **_):
        return simulate_bootstrap(processed_df, params, n_steps, n_paths, block_size, seed)

    return fn


def _make_jump_simulator(cfg: dict):
    from .models.jump_diffusion import simulate_jump_diffusion

    sim_cfg = cfg["simulation"]

    def fn(params, processed_df=None, n_steps=None, n_paths=None, seed=None, **_):
        return simulate_jump_diffusion(
            params,
            n_steps,
            n_paths,
            seed,
            jump_intensity=sim_cfg["jump_intensity"],
            jump_mean=sim_cfg["jump_mean"],
            jump_vol=sim_cfg["jump_vol"],
        )

    return fn


def _make_garch_simulator(cfg: dict):
    from .models.garch_sim import simulate_garch

    def fn(params, processed_df=None, n_steps=None, n_paths=None, seed=None, **_):
        return simulate_garch(processed_df, params, n_steps, n_paths, seed)

    return fn


def run(config_path: str, override_horizon: int | None = None, no_plots: bool = False) -> None:
    """
    Full end-to-end pipeline execution.

    Parameters
    ----------
    config_path : str
        Path to the YAML config file.
    override_horizon : int, optional
        Override the primary simulation horizon (trading days).
    no_plots : bool
        If True, suppress matplotlib pop-up windows.
    """
    t_start = time.perf_counter()
    run_ts = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")

    cfg = load_config(config_path)

    if no_plots:
        cfg["reporting"]["show_plots"] = False

    # ── Determine primary horizon ─────────────────────────────────────────────
    horizons = cfg["simulation"]["horizons"]
    primary_horizon = override_horizon or horizons[-1]  # default 1Y

    n_paths = cfg["simulation"]["n_paths"]
    seed = cfg["simulation"]["seed"]
    sim_cfg = cfg["simulation"]

    logger.info("=" * 60)
    logger.info("  NIFTY BANK MONTE CARLO SIMULATION SYSTEM")
    logger.info("  Run: %s  |  Horizon: %d days  |  Paths: %d", run_ts, primary_horizon, n_paths)
    logger.info("=" * 60)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1: Data pipeline
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("STEP 1/7 — Data pipeline")
    from .data_pipeline import run_pipeline

    _raw_df, processed_df, params = run_pipeline(cfg)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2: Simulation
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("STEP 2/7 — Running simulations (primary horizon: %d days)", primary_horizon)
    from .models import simulate_bootstrap, simulate_garch, simulate_gbm, simulate_jump_diffusion

    np.random.seed(seed)  # global seed for any stochastic that bypasses rng

    all_paths: dict[str, np.ndarray] = {}
    t_sim = time.perf_counter()

    if sim_cfg["models"]["gbm"]:
        logger.info("  Simulating GBM …")
        all_paths["GBM"] = simulate_gbm(params, primary_horizon, n_paths, seed)

    if sim_cfg["models"]["bootstrap"]:
        logger.info("  Simulating Block Bootstrap …")
        all_paths["Bootstrap"] = simulate_bootstrap(
            processed_df, params, primary_horizon, n_paths, sim_cfg["block_size"], seed
        )

    if sim_cfg["models"]["jump_diffusion"]:
        logger.info("  Simulating Jump-Diffusion …")
        all_paths["Jump-Diffusion"] = simulate_jump_diffusion(
            params,
            primary_horizon,
            n_paths,
            seed,
            jump_intensity=sim_cfg["jump_intensity"],
            jump_mean=sim_cfg["jump_mean"],
            jump_vol=sim_cfg["jump_vol"],
        )

    if sim_cfg["models"]["garch"]:
        logger.info("  Simulating GARCH(1,1) …")
        all_paths["GARCH"] = simulate_garch(processed_df, params, primary_horizon, n_paths, seed)

    logger.info("  All models simulated in %.2fs", time.perf_counter() - t_sim)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3: Risk metrics
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("STEP 3/7 — Computing risk metrics")
    from .risk_metrics import build_comparison_table, compute_all_metrics

    all_metrics: dict[str, dict] = {}
    for model_name, paths in all_paths.items():
        all_metrics[model_name] = compute_all_metrics(paths, params, processed_df, cfg, model_name)

    comparison_table = build_comparison_table(all_metrics)
    logger.info("Model comparison table:\n%s", comparison_table.to_string())

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4: Walk-forward backtest
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("STEP 4/7 — Walk-forward backtest")
    from .backtest import run_walkforward

    simulators = {}
    if "GBM" in all_paths:
        simulators["GBM"] = _make_gbm_simulator(cfg)
    if "Bootstrap" in all_paths:
        simulators["Bootstrap"] = _make_bootstrap_simulator(cfg)
    if "Jump-Diffusion" in all_paths:
        simulators["Jump-Diffusion"] = _make_jump_simulator(cfg)
    if "GARCH" in all_paths:
        simulators["GARCH"] = _make_garch_simulator(cfg)

    backtest_results: dict[str, dict] = {}
    for model_name, sim_fn in simulators.items():
        logger.info("  Backtesting %s …", model_name)
        backtest_results[model_name] = run_walkforward(processed_df, cfg, sim_fn, model_name)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 5: Charts
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("STEP 5/7 — Generating charts")
    import matplotlib as mpl

    if not cfg["reporting"].get("show_plots", True):
        mpl.use("Agg")  # non-interactive backend
    else:
        try:
            mpl.use("TkAgg")
        except Exception:
            try:
                mpl.use("MacOSX")
            except Exception:
                mpl.use("Agg")

    from .plotting import plot_all

    png_paths = plot_all(processed_df, all_paths, all_metrics, params, cfg)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 6: Report
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("STEP 6/7 — Generating report")
    from .report import generate_report

    output_paths = generate_report(
        params=params,
        all_metrics=all_metrics,
        backtest_results=backtest_results,
        comparison_table=comparison_table,
        png_paths=png_paths,
        cfg=cfg,
        run_timestamp=run_ts,
    )

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 7: Console summary
    # ─────────────────────────────────────────────────────────────────────────
    logger.info("STEP 7/7 — Run summary")
    _print_summary(params, all_metrics, backtest_results, output_paths, primary_horizon, time.perf_counter() - t_start)


def _print_summary(params, all_metrics, backtest_results, output_paths, horizon, elapsed):
    """Print a clean human-readable summary to stdout."""
    S0 = params["S0"]
    sep = "─" * 62

    print(f"\n{'═' * 62}")
    print("  NIFTY BANK MONTE CARLO — RUN COMPLETE")
    print(f"{'═' * 62}")
    print(f"  S0 (Current):        {S0:>12,.2f}")
    print(f"  Annual Drift μ:      {params['mu_annual'] * 100:>11.2f}%")
    print(f"  Annual Volatility σ: {params['sigma_annual'] * 100:>11.2f}%")
    print(f"  Horizon:             {horizon:>12} trading days")
    print(f"  Data:                {params['date_start']} → {params['date_end']}")
    print(f"  History:             {params['n_historical_days']:>12} days")
    print(sep)

    for model_name, m in all_metrics.items():
        t = m["terminal"]
        vc = m["var_cvar"]
        p = m["probabilities"]
        dd = m["drawdown"]
        ss = m["sharpe_sortino"]
        print(f"\n  [{model_name}]")
        print(f"    Mean terminal price : {t['mean']:>12,.0f}")
        print(f"    Median              : {t['median']:>12,.0f}")
        print(f"    5th pct (pessim.)   : {t['pct5']:>12,.0f}")
        print(f"    95th pct (optimist) : {t['pct95']:>12,.0f}")
        print(f"    P(profit)           : {p['prob_profit'] * 100:>11.1f}%")
        print(f"    P(loss)             : {p['prob_loss'] * 100:>11.1f}%")
        print(f"    VaR 95%             : {vc.get('var_0.95', 0) * 100:>11.2f}%")
        print(f"    CVaR 95%            : {vc.get('cvar_0.95', 0) * 100:>11.2f}%")
        print(f"    Avg Max Drawdown    : {dd['avg_max_drawdown'] * 100:>11.1f}%")
        print(f"    Sharpe (mean)       : {ss['mean_sharpe']:>12.3f}")
        print(f"    Sortino             : {ss['sortino']:>12.3f}")
        if model_name in backtest_results and backtest_results[model_name].get("n_windows", 0) > 0:
            cov = backtest_results[model_name]["coverage_90"]
            print(f"    Backtest coverage   : {cov * 100:>11.1f}%  (target ~90%)")

    print(f"\n{sep}")
    print(f"  Elapsed:  {elapsed:.1f}s")
    print(f"  Report:   {output_paths.get('html', 'N/A')}")
    if "pdf" in output_paths:
        print(f"  PDF:      {output_paths['pdf']}")
    print(f"{'═' * 62}\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="python -m monte_carlo.run",
        description="Production-grade Monte Carlo simulation for Nifty Bank Index",
    )
    parser.add_argument(
        "--config",
        "-c",
        default="config/default.yaml",
        help="Path to YAML config file (default: config/default.yaml)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=None,
        help="Override primary simulation horizon in trading days (e.g. 63 for 3 months)",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Suppress matplotlib pop-up windows (still saves PNGs)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity level",
    )

    args = parser.parse_args()
    _setup_logging(args.log_level)

    try:
        run(
            config_path=args.config,
            override_horizon=args.horizon,
            no_plots=args.no_plots,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)
    except Exception as e:
        logger.exception("Fatal error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
