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


import sys
from pathlib import Path

from defs.config import config
from renderer import cli
from renderer.annotations import DrawingManager, DrawingTool
from renderer.breadth_render import BreadthRenderer
from renderer.candle_render import CandlestickRenderer
from renderer.coordinator import PlotCoordinator
from renderer.dtypes import TF_MAP, AppPaths, RenderContext
from renderer.indicators import IndicatorPipeline
from renderer.loader import EODFileLoader
from renderer.navigation import NavigationList
from renderer.persistence import SessionStore


def main(argv: list[str] | None = None) -> int:
    paths = AppPaths.from_root(Path(__file__).parent)

    try:
        action = cli.parse_cli(argv, config_path=paths.config_path)

        return run_action(action, paths)
    except cli.CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


def run_action(action: cli.CliAction, paths: AppPaths) -> int:
    match action.kind:
        case "list":
            cli.print_available()
            return 0
        case "preset_remove":
            if not action.name:
                msg = "Missing preset name"
                raise cli.CliError(msg)

            cli.remove_preset(paths.config_path, action.name)
            return 0
        case "watch_add":
            if not action.name or action.path is None:
                msg = "Missing watchlist name or path"
                raise cli.CliError(msg)

            cli.add_watch(action.name, action.path, paths.config_path)
            return 0
        case "watch_remove":
            if not action.name:
                msg = "Missing watchlist name"
                raise cli.CliError(msg)

            cli.remove_watch(action.name, paths.config_path)
            return 0
        case "run":
            return run_chart(action.command, paths)

    msg = f"Unsupported CLI action: {action.kind}"
    raise cli.CliError(msg)


def run_chart(cmd, paths: AppPaths) -> int:
    if cmd.timeframe in {"w", "m", "q"} and cmd.delivery:
        print("WARN: Delivery data not available on weekly timeframe or higher")
        return 0

    cli.validate_file(paths.breadth_file)
    sym_list = cli.resolve_symbols(cmd)

    if not sym_list:
        print("WARN: Watch file is empty. No symbols to display")
        return 1

    context = build_stock_context(cmd, paths) if cmd.source.mode == "stock" else build_breadth_context(cmd, paths)

    if cmd.save:
        save_all(cmd, paths, sym_list, context)
        return 0

    run_interactive(cmd, sym_list, context)
    return 0


def build_stock_context(cmd, paths: AppPaths) -> RenderContext:

    from renderer.panels import allocate_indicator_panels

    indicator_pipeline = IndicatorPipeline(cmd)

    panel_layout = allocate_indicator_panels(cmd)

    plot_args = {
        "type": config.PLOT_CHART_TYPE,
        "style": config.PLOT_CHART_STYLE,
        "volume": cmd.volume,
        "xrotation": 0,
        "datetime_format": "%d %b %y",
        "scale_padding": {"left": 0.28, "right": 0.65, "top": 0.3, "bottom": 0.38},
    }

    if cmd.volume:
        plot_args["volume_panel"] = 1

    loader = EODFileLoader(
        timeframe=cmd.timeframe,
        data_path=paths.data_path,
        breadth_filepath=paths.breadth_file,
        period=cli.compute_max_period(cmd),
        index_name="nifty 500",
        end_date=cmd.date,
    )

    if cmd.rs or cmd.mansfield_rs:
        cli.validate_file(paths.rs_index_file)

        idx_df = loader.load(config.PLOT_RS_INDEX)

        if idx_df is None:
            print(f"WARN: Could not load index data for {config.PLOT_RS_INDEX}")
            sys.exit(1)

        indicator_pipeline.set_index_close(idx_df.Close)

    plugin_runner = None

    if cmd.plugins:
        from renderer.plugins.runner import PluginRunner

        plugin_runner = PluginRunner(
            cmd.plugins,
            panel_layout=panel_layout,
        )

    drawing_manager = DrawingManager(timeframe=cmd.timeframe)

    session_store = SessionStore(
        paths.config_path,
        paths.drawings,
        paths.selections,
        timeframe=cmd.timeframe,
    )

    return RenderContext(
        loader=loader,
        renderer=CandlestickRenderer(panel_layout),
        indicator_pipeline=indicator_pipeline,
        drawing_manager=drawing_manager,
        plot_args=plot_args,
        session_store=session_store,
        plugin_runner=plugin_runner,
        panel_layout=panel_layout,
    )


def build_breadth_context(cmd, paths: AppPaths) -> RenderContext:
    if cmd.source.breadth is None:
        msg = "Breadth command missing breadth source details"
        raise cli.CliError(msg)

    breadth = cmd.source.breadth

    return RenderContext(
        loader=EODFileLoader(
            timeframe=cmd.timeframe,
            data_path=paths.data_path,
            breadth_filepath=paths.breadth_file,
            period=cmd.period,
            index_name=breadth.index,
            end_date=cmd.date,
        ),
        renderer=BreadthRenderer(index_name=breadth.index, timeframe=TF_MAP[cmd.timeframe]),
        indicator_pipeline=None,
        drawing_manager=None,
        plot_args={
            "figsize": (12, 6) if config.PLOT_SIZE is None else config.PLOT_SIZE,
            "constrained_layout": True,
        },
        session_store=None,
    )


def save_all(cmd, paths: AppPaths, sym_list, context: RenderContext) -> None:
    from renderer.batch import BatchRender

    if context.drawing_manager is not None and paths.drawings.is_file():
        drawings = cli.load_json(paths.drawings)

        context.drawing_manager.from_dict(drawings[cmd.timeframe])

    batch = BatchRender(
        cmd=cmd,
        context=context,
        save_dir=paths.save_dir,
        sym_list=sym_list,
    )

    batch.save_all()


def run_interactive(cmd, sym_list, context: RenderContext) -> None:
    nav = NavigationList(
        items=sym_list,
        length=len(sym_list),
        current_index=resume_index(cmd, len(sym_list)),
    )

    drawing_tool = None

    if context.drawing_manager is not None:
        drawing_tool = DrawingTool(
            magnet_mode=config.MAGNET_MODE if cmd.source.mode == "stock" else False,
            drawing_manager=context.drawing_manager,
        )

    coordinator = PlotCoordinator(
        cmd=cmd,
        nav=nav,
        context=context,
        drawing_tool=drawing_tool,
    )

    coordinator.run()


def resume_index(cmd, symbol_count: int) -> int:
    if cmd.source.mode != "stock":
        return 0

    if not cmd.source.watch or not cmd.source.watch.resume:
        return 0

    idx = cmd.source.watch.resume.idx

    return idx if idx < symbol_count else 0


if __name__ == "__main__":
    sys.exit(main())
