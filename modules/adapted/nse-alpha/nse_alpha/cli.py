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


"""NSE Alpha CLI — typer-based entry point.

Commands
--------
nse-alpha download  Download price data via yfinance and store in local cache
nse-alpha run       Download data and compute all signal metrics
nse-alpha report    Render the alpha table, plots, and REPORT.md
"""


import logging
import warnings
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table

app = typer.Typer(
    name="nse-alpha",
    help="Cross-sectional alpha research pipeline for Indian equities (NSE).",
    add_completion=False,
)
console = Console(legacy_windows=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nse_alpha.cli")


@app.command()
def download(
    universe: str = typer.Option("nifty200", help="Universe name (currently only 'nifty200')."),
    symbols: str | None = typer.Option(
        None, help="Comma-separated list of symbols (e.g. 'INFY.NS,TCS.NS')."
    ),
    start: str = typer.Option("2015-01-01", help="Start date (ISO-8601)."),
    end: str | None = typer.Option(None, help="End date (ISO-8601). Defaults to today."),
    force: bool = typer.Option(False, "--force", help="Force re-download even if already cached."),
    batch_size: int = typer.Option(10, help="Batch size for yfinance download."),
) -> None:
    """Download OHLCV data from yfinance and cache locally in Parquet format."""
    import datetime

    if end is None:
        end = datetime.date.today().isoformat()

    if symbols:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    elif universe == "nifty200":
        from nse_alpha.universe.nifty200 import get_symbols

        symbol_list = get_symbols()
    else:
        console.print(f"[red]Unknown universe '{universe}'. Only 'nifty200' is supported.[/red]")
        raise typer.Exit(code=1)

    console.rule("[bold cyan]NSE Alpha — Data Ingestion (yfinance)[/bold cyan]")
    console.print(
        f"  Symbols: [bold]{len(symbol_list)}[/bold]  |  "
        f"Start: [bold]{start}[/bold]  |  "
        f"End: [bold]{end}[/bold]  |  "
        f"Force: [bold]{force}[/bold]"
    )
    console.print()

    from nse_alpha.data.ingest import download_universe

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Downloading {len(symbol_list)} symbols via yfinance...", total=None
        )
        downloaded = download_universe(symbol_list, start, end, force=force, batch_size=batch_size)
        progress.update(
            task,
            description=f"Cached {len(downloaded)} / {len(symbol_list)} symbols.",
        )

    console.print(
        f"[green]Completed data download. {len(downloaded)} symbols ready in cache.[/green]"
    )


@app.command()
def run(
    universe: str = typer.Option("nifty200", help="Universe name (currently only 'nifty200')."),
    symbols: str | None = typer.Option(
        None, help="Comma-separated list of symbols (overrides universe)."
    ),
    start: str = typer.Option("2015-01-01", help="Start date (ISO-8601)."),
    end: str | None = typer.Option(None, help="End date (ISO-8601). Defaults to today."),
    sector_neutral: bool = typer.Option(False, help="Apply sector neutralisation."),
    size_neutral: bool = typer.Option(False, help="Apply size neutralisation."),
    force_download: bool = typer.Option(
        False, "--force-download", help="Force re-download data from yfinance."
    ),
    min_history_days: int = typer.Option(252, help="Minimum history days for liquidity filter."),
    output_dir: Path = typer.Option(Path("results"), help="Directory for output files."),
) -> None:
    """Download data via yfinance, compute signals, and evaluate all metrics.

    Produces results/alpha_table.csv and supporting data for the report command.
    """
    import datetime
    import pickle

    import numpy as np

    if end is None:
        end = datetime.date.today().isoformat()

    if symbols:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
        u_label = f"Custom ({len(symbol_list)} tickers)"
    elif universe == "nifty200":
        from nse_alpha.universe.nifty200 import get_symbols

        symbol_list = get_symbols()
        u_label = universe
    else:
        console.print(f"[red]Unknown universe '{universe}'. Only 'nifty200' is supported.[/red]")
        raise typer.Exit(code=1)

    console.rule("[bold cyan]NSE Alpha Research Pipeline[/bold cyan]")
    console.print(
        f"  Universe: [bold]{u_label}[/bold]  |  "
        f"Start: [bold]{start}[/bold]  |  "
        f"End: [bold]{end}[/bold]"
    )
    console.print()

    # Emit survivorship bias warning
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        from nse_alpha.universe import nifty200 as nifty200_mod
    console.print("[yellow]" + nifty200_mod.SURVIVORSHIP_BIAS_WARNING + "[/yellow]")

    # Step 1: Data download
    console.print(f"[cyan]Target universe: {len(symbol_list)} symbols[/cyan]")

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Fetching price data with yfinance...", total=None)
        from nse_alpha.data.ingest import download_universe

        downloaded = download_universe(symbol_list, start, end, force=force_download)
        progress.update(task, description=f"Loaded/cached {len(downloaded)} symbols.")

    # Step 2: Build panel
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Building panel...", total=None)
        from nse_alpha.data.cache import load_panel

        panel = load_panel(list(downloaded), start, end)
        n_syms = panel.index.get_level_values("symbol").nunique()
        progress.update(task, description=f"Panel: {len(panel)} rows across {n_syms} symbols.")

    if panel.empty:
        console.print("[red]Panel is empty. Check your data download or date range.[/red]")
        raise typer.Exit(code=1)

    # Step 3: Universe filters
    all_dates = panel.index.get_level_values("date").unique().sort_values()
    last_date = all_dates[-1]
    from nse_alpha.universe.nifty200 import apply_liquidity_filters, get_sector_map

    # Adjust min_history_days if total available days is shorter
    effective_min_history = min(min_history_days, len(all_dates))
    eligible = apply_liquidity_filters(panel, last_date, min_history_days=effective_min_history)
    console.print(f"[green]{len(eligible)} symbols pass liquidity filters[/green]")

    if not eligible:
        console.print(
            "[yellow]Warning: No symbols passed filters. Using all panel symbols.[/yellow]"
        )
        eligible = list(panel.index.get_level_values("symbol").unique())

    panel_filtered = panel[panel.index.get_level_values("symbol").isin(eligible)]
    sector_map = get_sector_map() if sector_neutral else None

    # Compute log-ADV for size neutralisation
    log_adv: object | None = None
    if size_neutral:
        tv = panel_filtered["turnover_value"].unstack("symbol")
        adv20 = tv.rolling(20, min_periods=5).median()
        log_adv = np.log(adv20.replace(0, float("nan"))).stack(future_stack=True)  # type: ignore[call-arg]

    # Step 4: Load signals
    from nse_alpha.signals.registry import get_all_signals, load_all_signals

    load_all_signals()
    all_sigs = get_all_signals()
    console.print(f"[cyan]{len(all_sigs)} signals registered[/cyan]")

    # Step 5: Evaluate each signal
    from nse_alpha.eval.runner import evaluate_signal

    results: list[dict[str, object]] = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Evaluating signals...", total=len(all_sigs))
        for meta, fn in all_sigs:
            try:
                raw = fn(panel_filtered)
                result = evaluate_signal(
                    name=meta.name,
                    family=meta.family,
                    raw_scores=raw,
                    panel=panel_filtered,
                    sector_map=sector_map,  # type: ignore[arg-type]
                    log_adv=log_adv,  # type: ignore[arg-type]
                )
                results.append(result)
            except Exception as exc:
                console.print(f"[red]Error evaluating {meta.name}: {exc}[/red]")
                logger.exception("Signal evaluation failed: %s", meta.name)
            finally:
                progress.advance(task)

    # Step 6: Build and save alpha table
    from nse_alpha.report.table import (
        build_alpha_table,
        count_survivors,
        save_alpha_table,
    )

    alpha_table = build_alpha_table(results)
    csv_path = save_alpha_table(alpha_table)
    survivors = count_survivors(alpha_table)

    console.print(f"\n[bold green]Alpha table saved: {csv_path}[/bold green]")
    console.print(
        f"[bold yellow]{survivors} of {len(all_sigs)} signals survived "
        f"the 15 bps cost hurdle.[/bold yellow]"
    )

    # Save results for the report command
    output_dir.mkdir(exist_ok=True)
    results_pkl = output_dir / "_results.pkl"
    with results_pkl.open("wb") as f:
        pickle.dump(results, f)

    # Display the table
    _print_alpha_table(alpha_table)


@app.command()
def report(
    survivorship_note: bool = typer.Option(
        False, "--survivorship-note", help="Stamp survivorship bias caveat on the output."
    ),
    results_dir: Path = typer.Option(Path("results"), help="Directory with run results."),
) -> None:
    """Render the alpha table, plots, and REPORT.md from a previous 'run'."""
    import pickle

    results_pkl = results_dir / "_results.pkl"
    if not results_pkl.exists():
        console.print("[red]No run results found. Run 'nse-alpha run' first.[/red]")
        raise typer.Exit(code=1)

    with results_pkl.open("rb") as f:
        results = pickle.load(f)

    from nse_alpha.report.markdown import render_report
    from nse_alpha.report.plots import (
        plot_cumulative_ls,
        plot_ic_decay,
        plot_quantile_returns,
    )
    from nse_alpha.report.table import build_alpha_table, count_survivors

    alpha_table = build_alpha_table(results)
    survivors = count_survivors(alpha_table)

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        t1 = progress.add_task("Plotting IC decay...", total=None)
        plot_ic_decay(results)
        progress.update(t1, description="IC decay plot saved.")

        t2 = progress.add_task("Plotting quantile returns...", total=None)
        plot_quantile_returns(results)
        progress.update(t2, description="Quantile returns plot saved.")

        t3 = progress.add_task("Plotting cumulative L/S...", total=None)
        plot_cumulative_ls(results)
        progress.update(t3, description="Cumulative L/S plot saved.")

        t4 = progress.add_task("Rendering REPORT.md...", total=None)
        report_path = render_report(
            alpha_table,
            survivor_count=survivors,
            n_total=len(results),
            survivorship_note=survivorship_note,
        )
        progress.update(t4, description=f"Report saved: {report_path}")

    console.print(f"\n[bold green]Report generated: {report_path}[/bold green]")
    console.print(
        f"[bold yellow]{survivors} of {len(results)} signals survived "
        f"the 15 bps cost hurdle.[/bold yellow]"
    )
    _print_alpha_table(alpha_table)


def _print_alpha_table(df: object) -> None:
    """Pretty-print the alpha table to the console."""
    import pandas as pd

    assert isinstance(df, pd.DataFrame)

    table = Table(title="Alpha Table", show_header=True, header_style="bold cyan")
    for col in df.columns:
        table.add_column(str(col), justify="right" if col not in ("signal", "family") else "left")

    for _, row in df.iterrows():
        style = "green" if row.get("survives") else "white"
        table.add_row(*[str(v) for v in row.values], style=style)

    console.print(table)


if __name__ == "__main__":
    app()
