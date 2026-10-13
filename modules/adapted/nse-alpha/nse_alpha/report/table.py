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


"""Alpha table construction — sorts, annotates, and exports the signal results table."""


from pathlib import Path

import pandas as pd

RESULTS_DIR = Path("results")

SURVIVOR_IC_TSTAT_THRESHOLD: float = 2.0
SURVIVOR_NET_SHARPE_THRESHOLD: float = 0.5

TABLE_COLUMNS = [
    "signal",
    "family",
    "IC",
    "IC_tstat",
    "IR",
    "turnover",
    "gross_sharpe",
    "net_sharpe_5bps",
    "net_sharpe_15bps",
    "net_sharpe_30bps",
    "capacity_cr",
    "half_life_days",
    "survives",
]


def build_alpha_table(results: list[dict[str, object]]) -> pd.DataFrame:
    """Build the formatted alpha table from a list of signal evaluation results.

    Columns
    -------
    signal, family, IC, IC_tstat, IR, turnover,
    gross_sharpe, net_sharpe_5bps, net_sharpe_15bps, net_sharpe_30bps,
    capacity_cr, half_life_days, survives

    Parameters
    ----------
    results:
        List of dicts from ``eval.runner.evaluate_signal``.

    Returns
    -------
    pd.DataFrame
        Sorted by ``net_sharpe_15bps`` descending.
    """
    if not results:
        return pd.DataFrame(columns=TABLE_COLUMNS)

    rows: list[dict[str, object]] = []
    for r in results:
        net_sharpe_15 = float(r.get("net_sharpe_15bps", float("nan")))  # type: ignore[arg-type]
        ic_tstat = float(r.get("ic_tstat", float("nan")))  # type: ignore[arg-type]
        survives = (
            net_sharpe_15 > SURVIVOR_NET_SHARPE_THRESHOLD
            and abs(ic_tstat) > SURVIVOR_IC_TSTAT_THRESHOLD
        )
        rows.append(
            {
                "signal": r.get("signal", "unknown"),
                "family": r.get("family", "unknown"),
                "IC": round(float(r.get("ic_mean", float("nan"))), 4),  # type: ignore[arg-type]
                "IC_tstat": round(ic_tstat, 2),
                "IR": round(float(r.get("ir", float("nan"))), 2),  # type: ignore[arg-type]
                "turnover": round(float(r.get("turnover", float("nan"))), 4),  # type: ignore[arg-type]
                "gross_sharpe": round(float(r.get("gross_sharpe", float("nan"))), 2),  # type: ignore[arg-type]
                "net_sharpe_5bps": round(float(r.get("net_sharpe_5bps", float("nan"))), 2),  # type: ignore[arg-type]
                "net_sharpe_15bps": round(net_sharpe_15, 2),
                "net_sharpe_30bps": round(float(r.get("net_sharpe_30bps", float("nan"))), 2),  # type: ignore[arg-type]
                "capacity_cr": round(float(r.get("capacity_cr", float("nan"))), 1),  # type: ignore[arg-type]
                "half_life_days": round(float(r.get("half_life_days", float("nan"))), 1),  # type: ignore[arg-type]
                "survives": survives,
            }
        )

    df = pd.DataFrame(rows)
    if "net_sharpe_15bps" in df.columns:
        df = df.sort_values("net_sharpe_15bps", ascending=False).reset_index(drop=True)
    return df


def save_alpha_table(df: pd.DataFrame) -> Path:
    """Save the alpha table to CSV and return the path."""
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / "alpha_table.csv"
    df.to_csv(path, index=False)
    return path


def count_survivors(df: pd.DataFrame) -> int:
    """Count signals that survive the net Sharpe and IC t-stat hurdles."""
    if df.empty or "survives" not in df.columns:
        return 0
    return int(df["survives"].sum())


def table_to_markdown(df: pd.DataFrame, survivorship_note: bool = False) -> str:
    """Render the alpha table as a GitHub-flavoured Markdown table."""
    lines: list[str] = []

    if survivorship_note:
        lines.append(
            "> [!] **SURVIVORSHIP BIAS**: Universe is today's Nifty 200. "
            "Results are overstated. See Limitations.\n"
        )

    if df.empty:
        return "\n".join(lines) + "\n*No signal results available.*"

    # Header
    cols = list(df.columns)
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")

    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(v) for v in row.values) + " |")

    return "\n".join(lines)
