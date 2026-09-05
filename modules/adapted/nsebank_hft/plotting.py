"""
plotting.py — All Matplotlib Charts (pop-up + PNG export)
==========================================================

Produces 8 publication-quality charts:
  1. Historical price chart with returns overlay
  2. Simulated path fan chart (200 paths + percentile bands)
  3. Terminal price distribution histogram + VaR/CVaR markers
  4. Return distribution vs. normal + Q-Q plot
  5. Rolling volatility (30/60/90-day)
  6. Drawdown distribution histogram
  7. Model comparison — terminal distributions of all models
  8. Heatmap — P(price range) at different time horizons

Each chart is:
  - Shown as a Matplotlib pop-up window (if cfg.reporting.show_plots = True)
  - Saved as a PNG to reports/ (if cfg.reporting.save_plots = True)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

# ─── Style ────────────────────────────────────────────────────────────────────
PALETTE = {
    "bg": "#0f1117",
    "panel": "#1a1d2e",
    "text": "#e8eaf6",
    "accent1": "#7c83fd",
    "accent2": "#fd7c7c",
    "accent3": "#7cfdbc",
    "accent4": "#fdd97c",
    "accent5": "#fd7ce8",
    "band_fill": "#7c83fd",
    "grid": "#2a2d3e",
    "gbm": "#7c83fd",
    "bootstrap": "#7cfdbc",
    "jump": "#fd7c7c",
    "garch": "#fdd97c",
}

MODEL_COLORS = {
    "GBM": PALETTE["gbm"],
    "Bootstrap": PALETTE["bootstrap"],
    "Jump-Diffusion": PALETTE["jump"],
    "GARCH": PALETTE["garch"],
}


def _apply_dark_style() -> None:
    """Apply a premium dark theme to all matplotlib figures."""
    plt.rcParams.update({
        "figure.facecolor": PALETTE["bg"],
        "axes.facecolor": PALETTE["panel"],
        "axes.edgecolor": PALETTE["grid"],
        "axes.labelcolor": PALETTE["text"],
        "axes.titlecolor": PALETTE["text"],
        "axes.titlesize": 13,
        "axes.labelsize": 10,
        "axes.grid": True,
        "grid.color": PALETTE["grid"],
        "grid.linewidth": 0.5,
        "grid.alpha": 0.6,
        "xtick.color": PALETTE["text"],
        "ytick.color": PALETTE["text"],
        "text.color": PALETTE["text"],
        "legend.facecolor": PALETTE["panel"],
        "legend.edgecolor": PALETTE["grid"],
        "legend.labelcolor": PALETTE["text"],
        "figure.titlesize": 15,
        "font.family": "DejaVu Sans",
        "lines.linewidth": 1.5,
        "savefig.facecolor": PALETTE["bg"],
        "savefig.dpi": 150,
    })


def _save_and_show(fig: plt.Figure, name: str, report_dir: Path, cfg: dict) -> str:
    """Save figure to PNG and optionally display it."""
    rep_cfg = cfg["reporting"]
    png_path = report_dir / f"{name}.png"

    if rep_cfg.get("save_plots", True):
        report_dir.mkdir(parents=True, exist_ok=True)
        fig.savefig(png_path, bbox_inches="tight", dpi=150)
        logger.info("Chart saved → %s", png_path)

    if rep_cfg.get("show_plots", True):
        plt.show(block=False)
        plt.pause(0.1)

    return str(png_path)


def plot_all(
    processed_df: pd.DataFrame,
    all_paths: Dict[str, np.ndarray],
    all_metrics: Dict[str, Dict],
    params: Dict,
    cfg: dict,
) -> List[str]:
    """
    Generate all 8 charts and return list of saved PNG paths.

    Parameters
    ----------
    processed_df : pd.DataFrame
        Processed historical data.
    all_paths : dict
        model_name → np.ndarray of shape (n_paths, n_steps+1).
    all_metrics : dict
        model_name → metrics dict from risk_metrics.
    params : dict
        GBM parameters.
    cfg : dict
        Full configuration.

    Returns
    -------
    list of str
        Absolute paths to saved PNG files.
    """
    _apply_dark_style()
    report_dir = Path(cfg["reporting"]["report_dir"])
    saved_paths: List[str] = []

    # Primary model paths (GBM as baseline)
    primary_model = list(all_paths.keys())[0]
    primary_paths = all_paths[primary_model]
    primary_metrics = all_metrics[primary_model]

    logger.info("Generating charts …")

    saved_paths.append(_chart1_historical(processed_df, params, report_dir, cfg))
    saved_paths.append(_chart2_fan(primary_paths, primary_metrics, params, cfg, report_dir))
    saved_paths.append(_chart3_terminal_dist(primary_paths, primary_metrics, params, cfg, report_dir))
    saved_paths.append(_chart4_return_dist(processed_df, primary_paths, report_dir, cfg))
    saved_paths.append(_chart5_rolling_vol(processed_df, report_dir, cfg))
    saved_paths.append(_chart6_drawdown_dist(primary_metrics, report_dir, cfg))
    saved_paths.append(_chart7_model_comparison(all_paths, all_metrics, params, report_dir, cfg))
    saved_paths.append(_chart8_heatmap(all_paths, params, cfg, report_dir))

    logger.info("All 8 charts generated.")
    return saved_paths


# ─── Chart 1 ─────────────────────────────────────────────────────────────────

def _chart1_historical(
    df: pd.DataFrame, params: Dict, report_dir: Path, cfg: dict
) -> str:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True,
                                    gridspec_kw={"height_ratios": [3, 1]})
    fig.suptitle("Nifty Bank Index — Historical Price & Daily Returns", y=0.98)

    # Price
    ax1.plot(df.index, df["Close"], color=PALETTE["accent1"], linewidth=1.2, label="Close Price")
    ax1.fill_between(df.index, df["Close"], alpha=0.15, color=PALETTE["accent1"])
    ax1.set_ylabel("Index Level")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax1.legend(loc="upper left")
    ax1.set_title("Closing Price (Adjusted)")

    # Annotate S0
    ax1.axhline(params["S0"], color=PALETTE["accent4"], linestyle="--", linewidth=1,
                label=f"Current S0 = {params['S0']:,.0f}")
    ax1.legend(loc="upper left")

    # Returns
    ret = df["log_return"]
    colors = [PALETTE["accent3"] if r >= 0 else PALETTE["accent2"] for r in ret]
    ax2.bar(df.index, ret * 100, color=colors, width=1.5, alpha=0.8)
    ax2.set_ylabel("Log Return (%)")
    ax2.set_xlabel("Date")
    ax2.axhline(0, color=PALETTE["text"], linewidth=0.5)

    plt.tight_layout()
    return _save_and_show(fig, "chart1_historical", report_dir, cfg)


# ─── Chart 2 ─────────────────────────────────────────────────────────────────

def _chart2_fan(
    paths: np.ndarray, metrics: Dict, params: Dict, cfg: dict, report_dir: Path
) -> str:
    n_sample = cfg["reporting"]["n_sample_paths"]
    n_steps = paths.shape[1] - 1
    x = np.arange(n_steps + 1)

    fig, ax = plt.subplots(figsize=(14, 7))
    fig.suptitle(f"Monte Carlo Simulated Price Paths — {n_steps} Trading Days ({n_steps//21} months)")

    # Sample paths
    rng = np.random.default_rng(999)
    sample_idx = rng.choice(paths.shape[0], size=min(n_sample, paths.shape[0]), replace=False)
    for idx in sample_idx:
        ax.plot(x, paths[idx], alpha=0.05, linewidth=0.6, color=PALETTE["accent1"])

    # Confidence bands
    bands = metrics["confidence_bands"]
    ax.fill_between(x, bands["p5"], bands["p95"], alpha=0.25, color=PALETTE["accent1"],
                    label="5%–95% band")
    ax.fill_between(x, bands["p25"], bands["p75"], alpha=0.35, color=PALETTE["accent1"],
                    label="25%–75% band")
    ax.plot(x, bands["p50"], color=PALETTE["accent4"], linewidth=2, label="Median path")
    ax.plot(x, bands["p5"], color=PALETTE["accent2"], linewidth=1.2, linestyle="--", label="5th pct")
    ax.plot(x, bands["p95"], color=PALETTE["accent3"], linewidth=1.2, linestyle="--", label="95th pct")

    ax.axhline(params["S0"], color=PALETTE["text"], linewidth=1, linestyle=":", alpha=0.7,
               label=f"S0 = {params['S0']:,.0f}")
    ax.set_xlabel("Trading Days")
    ax.set_ylabel("Index Level")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(loc="upper left", fontsize=9)

    plt.tight_layout()
    return _save_and_show(fig, "chart2_fan", report_dir, cfg)


# ─── Chart 3 ─────────────────────────────────────────────────────────────────

def _chart3_terminal_dist(
    paths: np.ndarray, metrics: Dict, params: Dict, cfg: dict, report_dir: Path
) -> str:
    terminal = paths[:, -1]
    S0 = params["S0"]
    vc = metrics["var_cvar"]
    t = metrics["terminal"]

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.suptitle("Terminal Price Distribution — VaR & CVaR")

    n, bins, patches = ax.hist(terminal, bins=120, color=PALETTE["accent1"],
                                alpha=0.7, density=True, label="Simulated Distribution")

    # Colour bars below VaR 95% in red
    var95_price = S0 * (1 - vc.get("var_0.95", 0))
    for patch, left in zip(patches, bins[:-1]):
        if left < var95_price:
            patch.set_facecolor(PALETTE["accent2"])
            patch.set_alpha(0.85)

    # VaR lines
    ax.axvline(S0, color=PALETTE["accent4"], linewidth=2, linestyle="--", label=f"S0 = {S0:,.0f}")
    ax.axvline(t["pct5"], color=PALETTE["accent2"], linewidth=1.5, linestyle=":",
               label=f"5th pct = {t['pct5']:,.0f}")
    ax.axvline(t["pct95"], color=PALETTE["accent3"], linewidth=1.5, linestyle=":",
               label=f"95th pct = {t['pct95']:,.0f}")
    ax.axvline(t["mean"], color=PALETTE["accent5"], linewidth=1.5,
               label=f"Mean = {t['mean']:,.0f}")

    # KDE overlay
    from scipy.stats import gaussian_kde
    kde = gaussian_kde(terminal)
    x_range = np.linspace(terminal.min(), terminal.max(), 500)
    ax.plot(x_range, kde(x_range), color="white", linewidth=1.5, alpha=0.8, label="KDE")

    ax.set_xlabel("Terminal Price")
    ax.set_ylabel("Density")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend(fontsize=8)

    # Annotation box
    var95 = vc.get("var_0.95", 0)
    cvar95 = vc.get("cvar_0.95", 0)
    textstr = f"VaR 95% = {var95:.2%}\nCVaR 95% = {cvar95:.2%}"
    ax.text(0.02, 0.97, textstr, transform=ax.transAxes, fontsize=9,
            verticalalignment="top", bbox=dict(boxstyle="round,pad=0.4",
            facecolor=PALETTE["panel"], alpha=0.9, edgecolor=PALETTE["grid"]))

    plt.tight_layout()
    return _save_and_show(fig, "chart3_terminal_dist", report_dir, cfg)


# ─── Chart 4 ─────────────────────────────────────────────────────────────────

def _chart4_return_dist(
    processed_df: pd.DataFrame, paths: np.ndarray, report_dir: Path, cfg: dict
) -> str:
    hist_ret = processed_df["log_return"].dropna().values
    sim_ret = np.log(paths[:, 1:] / paths[:, :-1]).flatten()

    fig = plt.figure(figsize=(14, 6))
    gs = gridspec.GridSpec(1, 2, figure=fig)
    fig.suptitle("Return Distribution: Historical vs. Normal vs. Simulated")

    # ── Left: distribution overlay ──────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    # Historical returns histogram
    ax1.hist(hist_ret * 100, bins=100, density=True, alpha=0.6, color=PALETTE["accent1"],
             label="Historical log returns", zorder=2)

    # Sample of simulated daily returns
    n_sim_sample = min(len(hist_ret) * 5, len(sim_ret))
    rng = np.random.default_rng(42)
    sim_sample = rng.choice(sim_ret, size=n_sim_sample, replace=False) * 100
    ax1.hist(sim_sample, bins=100, density=True, alpha=0.4, color=PALETTE["accent4"],
             label="Simulated log returns", zorder=2)

    # Normal fit over historical
    mu_fit, std_fit = stats.norm.fit(hist_ret * 100)
    xmin = np.percentile(hist_ret * 100, 0.5)
    xmax = np.percentile(hist_ret * 100, 99.5)
    x_range = np.linspace(xmin, xmax, 500)
    ax1.plot(x_range, stats.norm.pdf(x_range, mu_fit, std_fit),
             color=PALETTE["accent2"], linewidth=2, label="Normal fit")

    ax1.set_xlabel("Daily Log Return (%)")
    ax1.set_ylabel("Density")
    ax1.legend(fontsize=8)
    ax1.set_title("Distribution Overlay")

    # ── Right: Q-Q plot ─────────────────────────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    (osm, osr), (slope, intercept, r) = stats.probplot(hist_ret, dist="norm")
    ax2.scatter(osm, osr, color=PALETTE["accent1"], s=8, alpha=0.5, label="Historical returns", zorder=2)
    ax2.plot([osm[0], osm[-1]], [osm[0] * slope + intercept, osm[-1] * slope + intercept],
             color=PALETTE["accent2"], linewidth=2, label="Normal reference line")
    ax2.set_xlabel("Theoretical Quantiles")
    ax2.set_ylabel("Sample Quantiles")
    ax2.set_title("Q-Q Plot (Fat Tails Diagnostic)")
    ax2.legend(fontsize=8)

    plt.tight_layout()
    return _save_and_show(fig, "chart4_return_dist", report_dir, cfg)


# ─── Chart 5 ─────────────────────────────────────────────────────────────────

def _chart5_rolling_vol(df: pd.DataFrame, report_dir: Path, cfg: dict) -> str:
    fig, ax = plt.subplots(figsize=(14, 6))
    fig.suptitle("Volatility Clustering — Rolling Annualised Volatility")

    ax.plot(df.index, df["rolling_vol_30"] * 100, color=PALETTE["accent2"],
            linewidth=1.2, alpha=0.85, label="30-day rolling vol")
    ax.plot(df.index, df["rolling_vol_60"] * 100, color=PALETTE["accent4"],
            linewidth=1.2, alpha=0.85, label="60-day rolling vol")
    ax.plot(df.index, df["rolling_vol_90"] * 100, color=PALETTE["accent3"],
            linewidth=1.2, alpha=0.85, label="90-day rolling vol")

    ax.fill_between(df.index, df["rolling_vol_30"] * 100, alpha=0.1, color=PALETTE["accent2"])
    ax.set_xlabel("Date")
    ax.set_ylabel("Annualised Volatility (%)")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
    ax.legend()

    plt.tight_layout()
    return _save_and_show(fig, "chart5_rolling_vol", report_dir, cfg)


# ─── Chart 6 ─────────────────────────────────────────────────────────────────

def _chart6_drawdown_dist(metrics: Dict, report_dir: Path, cfg: dict) -> str:
    dd_array = metrics["drawdown"]["max_drawdown_per_path"] * 100  # in %
    avg_dd = metrics["drawdown"]["avg_max_drawdown"] * 100
    worst_dd = metrics["drawdown"]["worst_drawdown"] * 100

    fig, ax = plt.subplots(figsize=(12, 6))
    fig.suptitle("Maximum Drawdown Distribution Across Simulated Paths")

    ax.hist(dd_array, bins=100, color=PALETTE["accent2"], alpha=0.75, density=True,
            label="Max drawdown per path")
    ax.axvline(avg_dd, color=PALETTE["accent4"], linewidth=2,
               label=f"Average = {avg_dd:.1f}%")
    ax.axvline(worst_dd, color=PALETTE["accent5"], linewidth=2, linestyle="--",
               label=f"Worst = {worst_dd:.1f}%")

    for thresh in cfg["risk"]["drawdown_thresholds"]:
        pct_exceeded = float(np.mean(dd_array / 100 > thresh) * 100)
        ax.axvline(thresh * 100, color="white", linewidth=1, linestyle=":",
                   alpha=0.6, label=f"P(DD>{thresh:.0%}) = {pct_exceeded:.1f}%")

    ax.set_xlabel("Maximum Drawdown (%)")
    ax.set_ylabel("Density")
    ax.legend(fontsize=8)

    plt.tight_layout()
    return _save_and_show(fig, "chart6_drawdown_dist", report_dir, cfg)


# ─── Chart 7 ─────────────────────────────────────────────────────────────────

def _chart7_model_comparison(
    all_paths: Dict[str, np.ndarray],
    all_metrics: Dict[str, Dict],
    params: Dict,
    report_dir: Path,
    cfg: dict,
) -> str:
    S0 = params["S0"]
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.suptitle("Model Comparison — Terminal Price Distributions")

    from scipy.stats import gaussian_kde

    for model_name, paths in all_paths.items():
        terminal = paths[:, -1]
        color = MODEL_COLORS.get(model_name, PALETTE["accent1"])
        kde = gaussian_kde(terminal)
        x_range = np.linspace(np.percentile(terminal, 0.5), np.percentile(terminal, 99.5), 500)
        ax.plot(x_range, kde(x_range), color=color, linewidth=2, label=model_name)
        ax.fill_between(x_range, kde(x_range), alpha=0.08, color=color)

    ax.axvline(S0, color="white", linewidth=1.5, linestyle="--", label=f"S0 = {S0:,.0f}")
    ax.set_xlabel("Terminal Price")
    ax.set_ylabel("Density (KDE)")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f}"))
    ax.legend()

    plt.tight_layout()
    return _save_and_show(fig, "chart7_model_comparison", report_dir, cfg)


# ─── Chart 8 ─────────────────────────────────────────────────────────────────

def _chart8_heatmap(
    all_paths: Dict[str, np.ndarray], params: Dict, cfg: dict, report_dir: Path
) -> str:
    """Heatmap: P(price in range) at different time horizons."""
    S0 = params["S0"]
    primary_paths = list(all_paths.values())[0]

    # Define price ranges as % of S0
    pct_ranges = [-30, -20, -10, -5, 0, 5, 10, 20, 30, 50]
    horizons = [21, 42, 63, 126, 189, 252]  # trading days

    n_total = primary_paths.shape[1] - 1
    horizons_valid = [h for h in horizons if h <= n_total]

    # Build probability matrix
    prob_matrix = np.zeros((len(pct_ranges) - 1, len(horizons_valid)))
    y_labels = []

    for j, h in enumerate(horizons_valid):
        terminal = primary_paths[:, h]
        for i in range(len(pct_ranges) - 1):
            lower = S0 * (1 + pct_ranges[i] / 100)
            upper = S0 * (1 + pct_ranges[i + 1] / 100)
            prob_matrix[i, j] = np.mean((terminal >= lower) & (terminal < upper))

    for i in range(len(pct_ranges) - 1):
        y_labels.append(f"{pct_ranges[i]:+d}% to {pct_ranges[i+1]:+d}%")

    x_labels = [f"{h}d\n({h//21}m)" for h in horizons_valid]

    fig, ax = plt.subplots(figsize=(12, 7))
    fig.suptitle("Probability of Price Range at Different Horizons")

    import matplotlib.colors as mcolors
    cmap = matplotlib.colormaps.get_cmap("RdYlGn")
    im = ax.imshow(prob_matrix, cmap=cmap, aspect="auto", vmin=0, vmax=0.4)

    # Labels on cells
    for i in range(prob_matrix.shape[0]):
        for j in range(prob_matrix.shape[1]):
            val = prob_matrix[i, j]
            ax.text(j, i, f"{val:.1%}", ha="center", va="center",
                    fontsize=8, color="black" if val > 0.2 else "white", fontweight="bold")

    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels)
    ax.set_yticks(range(len(y_labels)))
    ax.set_yticklabels(y_labels, fontsize=8)
    ax.set_xlabel("Forecast Horizon")
    ax.set_ylabel("Price Range (% of S0)")

    cbar = plt.colorbar(im, ax=ax, fraction=0.03, pad=0.04)
    cbar.set_label("Probability", color=PALETTE["text"])
    cbar.ax.yaxis.set_tick_params(color=PALETTE["text"])
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color=PALETTE["text"])
    cbar.ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))

    plt.tight_layout()
    return _save_and_show(fig, "chart8_heatmap", report_dir, cfg)
