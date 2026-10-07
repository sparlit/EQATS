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


"""PDF export for a completed Backtest run: the config that produced it,
summary metrics, equity/drawdown charts, year-by-year breakdown, open
positions, and the full closed-trade list -- everything the Backtest page
itself shows, in one downloadable file since the on-screen run-configuration
form resets to defaults after a run (see dashboard.py's "Parameters used
for this run" expander, which this mirrors).

reportlab (pure-Python, no system deps) for layout/tables; matplotlib's
headless Agg backend (already a project dependency) for the two charts.
Reportlab's built-in fonts only cover WinAnsi, so currency values use
"Rs." rather than the Unicode Rupee glyph to avoid missing-glyph issues
with no embedded font.
"""


import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_GREEN = "#16a34a"
_RED = "#dc2626"
_GREY = "#6b7280"


def _chart_png(fig) -> io.BytesIO:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf


def _equity_chart(eq: pd.Series, nifty: pd.Series) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(9.5, 3.0))
    ax.plot(eq.index, eq / eq.iloc[0] * 100, color=_GREEN, linewidth=1.6, label="Strategy")
    ax.plot(
        nifty.index,
        nifty / nifty.iloc[0] * 100,
        color=_GREY,
        linewidth=1.2,
        linestyle="--",
        label="NIFTY 50",
    )
    ax.set_title("Equity curve — growth of 100", loc="left", fontsize=11)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.grid(alpha=0.25)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    return _chart_png(fig)


def _drawdown_chart(eq: pd.Series) -> io.BytesIO:
    dd = (eq / eq.cummax() - 1) * 100
    fig, ax = plt.subplots(figsize=(9.5, 2.2))
    ax.fill_between(dd.index, dd, 0, color=_RED, alpha=0.15)
    ax.plot(dd.index, dd, color=_RED, linewidth=1.2)
    ax.set_title("Drawdown from peak (%)", loc="left", fontsize=11)
    ax.grid(alpha=0.25)
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    return _chart_png(fig)


def _yearly_bar_chart(yp: pd.DataFrame) -> io.BytesIO:
    fig, ax = plt.subplots(figsize=(9.5, 2.6))
    x = range(len(yp))
    width = 0.38
    strat_colors = [_GREEN if v >= 0 else _RED for v in yp["Strategy %"]]
    ax.bar(
        [i - width / 2 for i in x], yp["Strategy %"], width, color=strat_colors, label="Strategy %"
    )
    ax.bar([i + width / 2 for i in x], yp["NIFTY %"], width, color=_GREY, label="NIFTY %")
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels([str(y) for y in yp.index], fontsize=8)
    ax.set_title("Strategy vs NIFTY by year", loc="left", fontsize=11)
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.grid(alpha=0.25, axis="y")
    ax.tick_params(labelsize=8)
    fig.tight_layout()
    return _chart_png(fig)


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("H1", parent=ss["Heading1"], fontSize=17, spaceAfter=4))
    ss.add(
        ParagraphStyle(
            "H2",
            parent=ss["Heading2"],
            fontSize=12.5,
            spaceBefore=14,
            spaceAfter=6,
            textColor=colors.HexColor("#1f2937"),
        )
    )
    ss.add(
        ParagraphStyle(
            "Meta", parent=ss["Normal"], fontSize=9, textColor=colors.HexColor("#6b7280")
        )
    )
    return ss


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    """2-column label/value grid, 2 pairs per line -- compact, matches the
    density of the UI's 4-metric-per-row expander this mirrors."""
    data = []
    for i in range(0, len(rows), 2):
        pair = rows[i : i + 2]
        line = []
        for label, value in pair:
            line += [label, value]
        if len(pair) == 1:
            line += ["", ""]
        data.append(line)
    t = Table(data, colWidths=[4.0 * cm, 4.5 * cm, 4.0 * cm, 4.5 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#374151")),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#374151")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#e5e7eb")),
            ]
        )
    )
    return t


def _data_table(df: pd.DataFrame, pnl_cols: set[str] = frozenset()) -> Table:
    header = list(df.columns)
    data = [header] + df.astype(str).values.tolist()
    t = Table(data, repeatRows=1)
    style = [
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#374151")),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#e5e7eb")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#fafafa")]),
    ]
    for col in pnl_cols:
        if col not in header:
            continue
        ci = header.index(col)
        for ri, val in enumerate(df[col], start=1):
            try:
                is_neg = float(val) < 0
            except (TypeError, ValueError):
                continue
            style.append(
                ("TEXTCOLOR", (ci, ri), (ci, ri), colors.HexColor(_RED if is_neg else _GREEN))
            )
    t.setStyle(TableStyle(style))
    return t


def build_pdf(res: dict, bench: pd.DataFrame, cfg: dict, run_meta: dict, run_time) -> bytes:
    """res: bt.run_backtest()'s return dict (equity_curve/trades/
    open_positions/final_capital/metrics). cfg: the exact run_cfg used.
    run_meta: {range_mode, years, start_date, end_date, bt_capital,
    rebalance_cadence, use_fundamentals} as saved alongside the result."""
    eq = res["equity_curve"]
    nifty = bench["close"].reindex(eq.index).ffill()
    yp = None
    try:
        import backtest as bt

        yp = bt.yearly_performance(eq, bench, res["trades"])
    except Exception:
        yp = pd.DataFrame()

    ss = _styles()
    story = []

    story.append(Paragraph("Backtest Report", ss["H1"]))
    story.append(Paragraph(f"Run: {run_time:%d %b %Y %H:%M}", ss["Meta"]))
    story.append(Spacer(1, 10))

    # ---- Run configuration ----
    story.append(Paragraph("Run configuration", ss["H2"]))
    if run_meta.get("range_mode") == "Custom dates":
        range_txt = f"{run_meta.get('start_date')} to {run_meta.get('end_date')}"
    else:
        range_txt = f"{run_meta.get('years')} years trailing"
    story.append(
        _kv_table(
            [
                ("Date range", range_txt),
                ("Starting capital", f"Rs. {run_meta.get('bt_capital', 0):,.0f}"),
                ("Max positions", str(cfg.get("max_positions"))),
                ("Rebalance cadence", str(cfg.get("rebalance_cadence"))),
            ]
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("Trade management", ss["Meta"]))
    trail = "ON" if cfg.get("trailing_stop_enabled") else "OFF"
    mad_on = "ON" if cfg.get("mad_stop_enabled") else "OFF"
    story.append(
        _kv_table(
            [
                ("Initial stop (x ATR)", str(cfg.get("atr_stop_multiple"))),
                ("Trailing stop", f"{trail} ({cfg.get('trailing_atr_multiple')}x)"),
                (
                    "MAD trail stop",
                    f"{mad_on} (med={cfg.get('mad_stop_med_len')}, "
                    f"mad={cfg.get('mad_stop_mad_len')}, dev={cfg.get('mad_stop_dev_factor')}, "
                    f"floor x={cfg.get('mad_stop_atr_floor_mult')})",
                ),
                ("Risk per trade (%)", str(cfg.get("risk_per_trade_pct"))),
                ("History fetched (days)", str(cfg.get("history_days"))),
                ("Entry confirmation (days)", str(cfg.get("entry_confirm_days", 0))),
            ]
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("Technical indicator", ss["Meta"]))
    rsi_exit = "ON" if cfg.get("rsi_exit_gate_enabled") else "OFF"
    wm_rsi = "ON" if cfg.get("weekly_monthly_gate_enabled") else "OFF"
    story.append(
        _kv_table(
            [
                ("RSI range", f"{cfg.get('rsi_min')}-{cfg.get('rsi_max')}"),
                ("EMA fast/slow", f"{cfg.get('ema_fast')}/{cfg.get('ema_slow')}"),
                (
                    "Momentum lookback",
                    f"{cfg.get('mom_lookback_days_short')}/{cfg.get('mom_lookback_days_long')}d",
                ),
                ("Skip most recent (days)", str(cfg.get("skip_recent_days"))),
                ("Exit RSI ceiling", f"{rsi_exit} ({cfg.get('rsi_exit_max')})"),
                ("Weekly/monthly EMA trend gate", f"{wm_rsi} (price>200EMA on both)"),
            ]
        )
    )
    story.append(Spacer(1, 6))
    story.append(Paragraph("Scanner param", ss["Meta"]))
    ew = "ON" if cfg.get("advanced_equal_weight_sizing") else "OFF"
    fg = "ON" if cfg.get("fundamental_gate_enabled") else "OFF"
    sd = "ON" if cfg.get("sector_diversification_enabled") else "OFF"
    sc = "composite" if cfg.get("sector_composite_score_enabled") else "RS-only"
    rg = "ON" if cfg.get("regime_filter_enabled") else "OFF"
    story.append(
        _kv_table(
            [
                ("Equal-weight allocator", f"{ew} (tol {cfg.get('equal_weight_tolerance_pct')})"),
                ("Fundamental gate", fg),
                ("Fundamental bonus weight", str(cfg.get("fundamental_bonus_weight"))),
                ("Min fundamental score", str(cfg.get("min_fundamental_score"))),
                ("52w-high proximity (%)", f"{cfg.get('near_high_threshold', 0) * 100:.0f}"),
                ("Sector bonus weight", str(cfg.get("sector_bonus_weight"))),
                (
                    "Sector diversification",
                    f"{sd} (top {cfg.get('top_n_sectors')}, "
                    f"max {cfg.get('max_positions_per_sector')}/sector, {sc})",
                ),
                ("Resistance zone weight", str(cfg.get("resistance_zone_weight", 0.0))),
                (
                    "Market regime filter",
                    f"{rg} (x{cfg.get('regime_position_multiplier', 0.5)} positions "
                    f"when NIFTY < {cfg.get('regime_ema_period', 200)}EMA)",
                ),
            ]
        )
    )

    # ---- Summary metrics ----
    story.append(Paragraph("Summary metrics", ss["H2"]))
    m = res["metrics"]
    total_ret = (res["final_capital"] / eq.iloc[0] - 1) * 100
    story.append(
        _kv_table(
            [
                ("Final capital", f"Rs. {res['final_capital']:,.0f}"),
                ("Total return", f"{total_ret:+.1f}%"),
                ("CAGR", f"{m.get('CAGR %', '-')}%"),
                ("NIFTY CAGR", f"{m.get('NIFTY CAGR %', '-')}%"),
                ("Alpha (CAGR)", f"{m.get('Alpha (CAGR) %', '-')}%"),
                ("Sharpe", str(m.get("Sharpe", "-"))),
                ("Max drawdown", f"{m.get('Max drawdown %', '-')}%"),
                ("Win rate", f"{m.get('Win rate %', '-')}%"),
                ("Trades", str(m.get("Trades", "-"))),
                ("Profit factor", str(m.get("Profit factor", "-"))),
                ("Avg hold (days)", str(m.get("Avg hold (days)", "-"))),
                ("Open positions at end", str(len(res["open_positions"]))),
            ]
        )
    )

    # ---- Charts ----
    story.append(Paragraph("Equity curve", ss["H2"]))
    story.append(Image(_equity_chart(eq, nifty), width=17 * cm, height=5.4 * cm))
    story.append(Paragraph("Drawdown", ss["H2"]))
    story.append(Image(_drawdown_chart(eq), width=17 * cm, height=4.0 * cm))

    # ---- Year by year ----
    if yp is not None and not yp.empty:
        story.append(Paragraph("Year-by-year performance", ss["H2"]))
        story.append(Image(_yearly_bar_chart(yp), width=17 * cm, height=4.6 * cm))
        story.append(Spacer(1, 8))
        ypd = yp.reset_index()
        story.append(_data_table(ypd, pnl_cols={"Strategy %", "NIFTY %", "Alpha %"}))

    # ---- Open positions ----
    op = res["open_positions"]
    if not op.empty:
        story.append(Paragraph(f"Open positions at period end ({len(op)})", ss["H2"]))
        opd = op.copy()
        opd["entry_date"] = pd.to_datetime(opd["entry_date"]).dt.date.astype(str)
        opd = opd.sort_values("unrealized_pnl", ascending=False)
        for c in opd.columns:
            if opd[c].dtype.kind == "f":
                opd[c] = opd[c].round(2)
        story.append(_data_table(opd, pnl_cols={"unrealized_pnl", "unrealized_ret_pct"}))

    # ---- Closed trades ----
    tr = res["trades"]
    if not tr.empty:
        story.append(PageBreak())
        story.append(Paragraph(f"All closed trades ({len(tr)})", ss["H2"]))
        trd = tr.copy()
        trd["entry_date"] = pd.to_datetime(trd["entry_date"]).dt.date.astype(str)
        trd["exit_date"] = pd.to_datetime(trd["exit_date"]).dt.date.astype(str)
        trd = trd.sort_values("entry_date", ascending=False)
        for c in trd.columns:
            if trd[c].dtype.kind == "f":
                trd[c] = trd[c].round(2)
        story.append(_data_table(trd, pnl_cols={"pnl", "ret_pct"}))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=1.4 * cm,
        rightMargin=1.4 * cm,
        topMargin=1.4 * cm,
        bottomMargin=1.4 * cm,
        title="Backtest Report",
    )
    doc.build(story)
    buf.seek(0)
    return buf.getvalue()
