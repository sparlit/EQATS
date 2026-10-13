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


"""Plot generation for the alpha research report.

Produces three plot files:
    results/ic_decay.png       — IC decay by signal family (one panel per family)
    results/quantile_returns.png — Decile return bar charts
    results/cumulative_ls.png  — Cumulative L/S returns (gross vs net 15bps)
"""


from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # non-interactive backend

RESULTS_DIR = Path("results")
FIGURE_DPI = 150
FIGURE_SIZE = (12, 6)


def _setup() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    plt.rcParams.update(
        {
            "figure.facecolor": "#1a1a2e",
            "axes.facecolor": "#16213e",
            "axes.edgecolor": "#4a4a8a",
            "axes.labelcolor": "#e0e0e0",
            "text.color": "#e0e0e0",
            "xtick.color": "#e0e0e0",
            "ytick.color": "#e0e0e0",
            "grid.color": "#2a2a5a",
            "grid.alpha": 0.5,
            "lines.linewidth": 1.8,
            "font.family": "DejaVu Sans",
        }
    )


def plot_ic_decay(results: list[dict[str, object]]) -> Path:
    """Plot IC vs horizon for each signal family (one subplot per family)."""
    _setup()

    # Group by family
    families: dict[str, list[dict[str, object]]] = {}
    for r in results:
        fam = str(r["family"])
        families.setdefault(fam, []).append(r)

    n_fam = len(families)
    if n_fam == 0:
        raise ValueError("No results to plot")

    fig, axes = plt.subplots(1, n_fam, figsize=(4 * n_fam, 5), squeeze=False)
    fig.patch.set_facecolor("#1a1a2e")
    colors = plt.cm.plasma(np.linspace(0.2, 0.9, 10))  # type: ignore[attr-defined]

    for ax, (fam, fam_results) in zip(axes[0], families.items(), strict=False):
        for i, r in enumerate(fam_results):
            ic_decay: pd.DataFrame = r["_ic_decay"]  # type: ignore[assignment]
            color = colors[i % len(colors)]
            ax.plot(
                ic_decay["horizon"],
                ic_decay["ic_mean"],
                marker="o",
                markersize=4,
                label=str(r["signal"]),
                color=color,
            )
        ax.axhline(0, color="#ff6b6b", linewidth=1, linestyle="--", alpha=0.7)
        ax.set_title(fam, fontsize=12, fontweight="bold")
        ax.set_xlabel("Horizon (days)")
        ax.set_ylabel("Mean IC")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc="upper right")

    fig.suptitle("IC Decay by Signal Family", fontsize=14, fontweight="bold", y=1.02)
    plt.tight_layout()
    path = RESULTS_DIR / "ic_decay.png"
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)
    return path


def plot_quantile_returns(results: list[dict[str, object]]) -> Path:
    """Plot decile return bar charts for each signal."""
    _setup()

    n = len(results)
    if n == 0:
        raise ValueError("No results to plot")

    n_cols = 3
    n_rows = (n + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows), squeeze=False)
    fig.patch.set_facecolor("#1a1a2e")

    for idx, r in enumerate(results):
        row, col = divmod(idx, n_cols)
        ax = axes[row][col]

        decile_rets: pd.DataFrame = r["_decile_rets"]  # type: ignore[assignment]
        mean_decile = decile_rets.mean()
        decile_labels = [c for c in decile_rets.columns if c in mean_decile.index]
        values = mean_decile[decile_labels].values * 252  # annualised

        bar_colors = ["#ff6b6b" if v < 0 else "#4ecdc4" for v in values]
        ax.bar(range(len(decile_labels)), values, color=bar_colors, alpha=0.85)
        ax.set_xticks(range(len(decile_labels)))
        ax.set_xticklabels(decile_labels, fontsize=7, rotation=45)
        ax.set_title(str(r["signal"]), fontsize=9, fontweight="bold")
        ax.set_ylabel("Annualised Return")
        ax.axhline(0, color="white", linewidth=0.8, alpha=0.5)
        ax.grid(True, alpha=0.2)

    # Hide empty subplots
    for idx in range(n, n_rows * n_cols):
        row, col = divmod(idx, n_cols)
        axes[row][col].set_visible(False)

    fig.suptitle("Decile Portfolio Returns (Equal-Weighted)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    path = RESULTS_DIR / "quantile_returns.png"
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)
    return path


def plot_cumulative_ls(results: list[dict[str, object]]) -> Path:
    """Plot cumulative L/S returns (gross vs net 15bps) for each signal."""
    _setup()

    n = len(results)
    if n == 0:
        raise ValueError("No results to plot")

    n_cols = 3
    n_rows = (n + n_cols - 1) // n_cols
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows), squeeze=False)
    fig.patch.set_facecolor("#1a1a2e")

    for idx, r in enumerate(results):
        row, col = divmod(idx, n_cols)
        ax = axes[row][col]

        cumulative: pd.DataFrame = r["_cumulative"]  # type: ignore[assignment]
        gross_cum = cumulative["gross"] * 100
        net_cum = cumulative["net"] * 100

        ax.plot(gross_cum.index, gross_cum.values, color="#4ecdc4", label="Gross", linewidth=1.5)
        ax.plot(
            net_cum.index,
            net_cum.values,
            color="#ff6b6b",
            label="Net 15bps",
            linewidth=1.5,
            linestyle="--",
        )
        ax.axhline(0, color="white", linewidth=0.5, alpha=0.4)
        ax.fill_between(gross_cum.index, 0, gross_cum.values, alpha=0.05, color="#4ecdc4")
        ax.set_title(str(r["signal"]), fontsize=9, fontweight="bold")
        ax.set_ylabel("Cumulative Return (%)")
        ax.legend(fontsize=7)
        ax.grid(True, alpha=0.2)
        ax.tick_params(axis="x", labelrotation=30, labelsize=6)

    for idx in range(n, n_rows * n_cols):
        row, col = divmod(idx, n_cols)
        axes[row][col].set_visible(False)

    fig.suptitle("Cumulative L/S Returns: Gross vs Net (15 bps)", fontsize=14, fontweight="bold")
    plt.tight_layout()
    path = RESULTS_DIR / "cumulative_ls.png"
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches="tight", facecolor="#1a1a2e")
    plt.close(fig)
    return path
