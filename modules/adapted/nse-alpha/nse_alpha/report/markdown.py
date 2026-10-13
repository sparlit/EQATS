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


"""Markdown report generator — produces REPORT.md with table, plots, and Limitations."""


from pathlib import Path

import pandas as pd

RESULTS_DIR = Path("results")


def render_report(
    table: pd.DataFrame,
    survivor_count: int,
    n_total: int,
    survivorship_note: bool = False,
) -> Path:
    """Render the full REPORT.md.

    Parameters
    ----------
    table:
        Alpha table from ``report.table.build_alpha_table``.
    survivor_count:
        Number of signals that survived the cost hurdle.
    n_total:
        Total number of signals evaluated.
    survivorship_note:
        If True, stamp survivorship bias caveat prominently.

    Returns
    -------
    Path
        Path to the rendered REPORT.md.
    """
    from nse_alpha.report.table import table_to_markdown

    RESULTS_DIR.mkdir(exist_ok=True)

    lines: list[str] = []
    lines.append("# NSE Alpha Research Report\n")
    _date_str = _today_str()
    lines.append(f"*Generated: {_date_str}*\n")

    if survivorship_note:
        lines.append(
            "> ⚠️ **SURVIVORSHIP BIAS NOTE**: This report uses a static Nifty 200 "
            "constituent list (today's composition). Backtest results are "
            "survivorship-biased and likely overstated. See Limitations section.\n"
        )

    lines.append("## Alpha Table\n")
    lines.append(table_to_markdown(table, survivorship_note=False))
    lines.append("")
    lines.append(
        f"\n**{survivor_count} of {n_total} signals survived a 15 bps cost hurdle** "
        f"(net Sharpe > 0.5 AND |IC t-stat| > 2.0).\n"
    )

    lines.append("\n## IC Decay by Signal Family\n")
    lines.append("![IC Decay](ic_decay.png)\n")

    lines.append("\n## Decile Portfolio Returns\n")
    lines.append("![Quantile Returns](quantile_returns.png)\n")

    lines.append("\n## Cumulative Long-Short Returns\n")
    lines.append("![Cumulative L/S](cumulative_ls.png)\n")

    lines.append("\n---\n")
    lines.append("## Limitations\n")
    lines.append(
        "1. **Survivorship bias**: The universe is derived from today's Nifty 200 "
        "constituents. Stocks delisted, merged, or dropped from the index since "
        "2015 are excluded from history. All performance numbers are likely overstated."
    )
    lines.append(
        "\n2. **Daily bars only**: Signals use end-of-day prices. No intraday data, "
        "tick data, or microstructure information is used. Intraday alpha, "
        "execution timing effects, and bid-ask spread dynamics are not captured."
    )
    lines.append(
        "\n3. **Linear cost model**: Transaction costs are modelled as "
        "turnover × round-trip bps. Nonlinear market impact (which grows with "
        "order size) is not modelled. Real costs at significant AUM will be higher."
    )
    lines.append(
        "\n4. **No borrow costs or short-sale constraints**: The short leg of the "
        "L/S portfolio is treated as freely shortable at zero cost. In practice, "
        "borrow availability and costs vary significantly across NSE stocks."
    )
    lines.append(
        "\n5. **Corporate action coverage**: adj_close from yfinance handles splits "
        "and dividends but may not correctly handle rights issues, demergers, "
        "scheme of arrangements, or other complex corporate actions."
    )
    lines.append(
        "\n6. **No portfolio optimisation**: Portfolios are equal-weighted within "
        "deciles. Mean-variance or factor-risk optimisation would change results."
    )
    lines.append(
        "\n7. **Walk-forward validation only**: Only expanding-window walk-forward CV "
        "is implemented. Purged K-fold and combinatorial purged CV are not yet "
        "available, which may lead to slight overestimation of OOS metrics."
    )

    lines.append("\n## Future Work\n")
    lines.append(
        "- **Point-in-time universe**: Replace static Nifty 200 with historical "
        "index composition data (requires NSE Data API or Refinitiv feed). "
        "See `universe/point_in_time.py` for the protocol interface.\n"
        "- **Purged K-Fold CV**: Implement `PurgedKFold` and `CombinatorialPurgedCV` "
        "in `eval/validation.py`.\n"
        "- **Nonlinear cost model**: Incorporate Almgren-Chriss impact model.\n"
        "- **Borrow cost integration**: Add short rebate / borrow cost curves.\n"
        "- **Factor risk model**: Neutralise to Barra-style factor exposures.\n"
        "- **Signal combination**: Explore composite signal construction.\n"
    )

    content = "\n".join(lines)
    path = RESULTS_DIR / "REPORT.md"
    path.write_text(content, encoding="utf-8")
    return path


def _today_str() -> str:
    import datetime

    return datetime.date.today().isoformat()
