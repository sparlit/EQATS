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


"""Per-symbol candlestick + real stop-line history for the Tradebook tab's
chart view.

Two sources for the stop line, preferred in this order:
1. build_real_stop_history() -- the REAL, ground-truth history from
   state_db's stop_update_log: exactly what live actually computed and
   applied each day, under whatever config was active at the time. This
   is "the same which is applied for live", not a re-simulation, and it's
   also what explains why a newly-enabled MAD trail may not visibly move
   an already-open position's stop: the ratchet only ever moves up, so a
   currently-open position's REAL applied stop stays wherever it already
   was until the MAD trail's own lower band level rises above it.
2. build_trade_overlay() -- a from-scratch simulation using the exact
   same formulas backtest.py's day-loop and live_rebalance.py's
   compute_stop_updates() use (_initial_stop's entry-day pick between the
   MAD lower band and the plain ATR stop, then the ratchet-up-only
   block), replayed under TODAY's config. Used only as a fallback for
   trades/days with no stop_update_log rows (e.g. a same-day-closed
   trade, or a position that predates the log) -- for those, this shows
   what the stop would look like under today's settings, not a strict
   historical replay.

build_symbol_figure() draws one candlestick per symbol with every trade
for that symbol overlaid (buy/sell markers + its own stop-line segment),
so a stock bought and sold multiple times shows its full history on one
chart instead of just the most recently picked trade.
"""
import pandas as pd
import plotly.graph_objects as go

import indicators


def build_trade_overlay(
    df: pd.DataFrame, cfg: dict, entry_date, entry_price: float, exit_date=None
) -> dict:
    """Simulated fallback stop-line path from entry_date through exit_date
    (or df's last available date, for an open position). df must be daily
    OHLC indexed by date, covering enough history before entry_date for
    the MAD/ATR warmup windows (precompute_mad_trail's med_len/mad_len,
    typically ~30 bars each) to be non-NaN by entry_date.

    Returns {"mode": "mad"|"atr"|"fixed", "stop": pd.Series, "median":
    pd.Series|None} -- median is the MAD trail's own diagnostic center
    line, populated only when mad_stop_enabled."""
    entry_date = pd.Timestamp(entry_date)
    end = pd.Timestamp(exit_date) if exit_date is not None else df.index[-1]
    idx = df.index[(df.index >= entry_date) & (df.index <= end)]
    if len(idx) == 0:
        return {"mode": "fixed", "stop": pd.Series(dtype=float), "median": None}

    atr_period = cfg.get("atr_period", 14)
    atr_series = indicators.atr(df, atr_period)

    mad_df = None
    if cfg.get("mad_stop_enabled", False):
        import mad_trail_strategy

        mad_cfg = mad_trail_strategy.cfg_from_strategy(cfg)
        mad_df = mad_trail_strategy.precompute_mad_trail(df, mad_cfg)

    trailing_on = cfg.get("trailing_stop_enabled", False)
    stop_vals = {}
    running_stop = None
    highest_close = entry_price
    for d in idx:
        if running_stop is None:
            atr_now = float(atr_series.loc[d]) if d in atr_series.index else float("nan")
            atr_stop = entry_price - cfg.get("atr_stop_multiple", 2.5) * atr_now
            if mad_df is not None and d in mad_df.index:
                m = mad_df.loc[d]
                if m["regime"] == 1 and not pd.isna(m["lower"]) and m["lower"] < entry_price:
                    running_stop = float(m["lower"])
                else:
                    running_stop = atr_stop
            else:
                running_stop = atr_stop
            highest_close = entry_price
        else:
            close_t = float(df.loc[d, "close"]) if d in df.index else highest_close
            if mad_df is not None:
                if d in mad_df.index and not pd.isna(mad_df.loc[d, "lower"]):
                    running_stop = max(running_stop, float(mad_df.loc[d, "lower"]))
            elif trailing_on:
                highest_close = max(highest_close, close_t)
                atr_now = float(atr_series.loc[d]) if d in atr_series.index else float("nan")
                running_stop = max(
                    running_stop, highest_close - cfg.get("trailing_atr_multiple", 3.0) * atr_now
                )
            # else: neither ratchet mechanism is on -- stop stays flat at
            # its entry-day value, matching backtest's day-loop exactly.
        stop_vals[d] = running_stop

    mode = "mad" if mad_df is not None else ("atr" if trailing_on else "fixed")
    stop = pd.Series(stop_vals)
    median = mad_df["median"].reindex(idx) if mad_df is not None else None
    return {"mode": mode, "stop": stop, "median": median}


def build_real_stop_history(
    log_df: pd.DataFrame, entry_date, initial_stop: float, exit_date=None
) -> pd.DataFrame | None:
    """Real, ground-truth stop history for one position, built from
    state_db.get_stop_update_log()'s rows -- exactly what live computed
    and applied each day. Returns None if log_df is empty (no daily-job
    history for this position -- caller should fall back to
    build_trade_overlay()).

    Two step columns: "applied" (the real broker-side stop over time --
    only moves on rows where applied=1, i.e. actually pushed to the GTT)
    and "recommended" (every row's raw computed candidate, applied or
    not -- lets you see e.g. a currently-enabled MAD trail's level
    sitting BELOW the already-applied stop: still correct, just not
    ratcheted up yet, since the ratchet only ever moves up)."""
    if log_df is None or log_df.empty:
        return None
    entry_date = pd.Timestamp(entry_date)
    log_df = log_df.copy()
    log_df["date"] = pd.to_datetime(log_df["date"])
    log_df = log_df.sort_values("date")
    if exit_date is not None:
        log_df = log_df[log_df["date"] <= pd.Timestamp(exit_date)]
    if log_df.empty:
        return None

    idx = [entry_date] + list(log_df["date"])
    applied_val = [initial_stop]
    rec_val = [initial_stop]
    current_applied = initial_stop
    for row in log_df.itertuples():
        if row.applied:
            current_applied = row.new_stop
        applied_val.append(current_applied)
        rec_val.append(row.new_stop)

    return pd.DataFrame(
        {"applied": applied_val, "recommended": rec_val}, index=pd.DatetimeIndex(idx)
    )


_MODE_LABEL = {
    "mad": "MAD volatility trail (simulated)",
    "atr": "ATR trailing stop (simulated)",
    "fixed": "fixed initial stop (simulated)",
}


def build_symbol_figure(
    symbol: str, df: pd.DataFrame, trades: list[dict], chart_start=None, chart_end=None
) -> go.Figure:
    """One candlestick for `symbol` with EVERY trade in `trades` overlaid
    -- each trade's own stop-line segment (real_history preferred, else
    overlay) plus its buy/sell markers -- so a symbol bought and sold
    multiple times shows its complete history on one chart, starting from
    its first-ever occurrence, not just the most recently picked trade.

    trades: chronologically-ordered list of dicts with keys entry_date,
    entry_price, exit_date (None if still open), exit_price (None if
    open), overlay (from build_trade_overlay), real_history (from
    build_real_stop_history, or None).
    `df` is the full fetched OHLC window; chart_start/chart_end trim the
    visible candlestick x-range without affecting any trade's own stop
    computation."""
    plot_df = df
    if chart_start is not None:
        plot_df = plot_df[plot_df.index >= pd.Timestamp(chart_start)]
    if chart_end is not None:
        plot_df = plot_df[plot_df.index <= pd.Timestamp(chart_end)]

    fig = go.Figure()
    fig.add_trace(
        go.Candlestick(
            x=plot_df.index,
            open=plot_df["open"],
            high=plot_df["high"],
            low=plot_df["low"],
            close=plot_df["close"],
            name=symbol,
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            showlegend=False,
        )
    )

    multi = len(trades) > 1
    for i, tr in enumerate(trades):
        entry_date = pd.Timestamp(tr["entry_date"])
        exit_date = pd.Timestamp(tr["exit_date"]) if tr.get("exit_date") is not None else None
        overlay = tr["overlay"]
        real_history = tr.get("real_history")
        first = i == 0

        if real_history is not None and not real_history.empty:
            fig.add_trace(
                go.Scatter(
                    x=real_history.index,
                    y=real_history["applied"],
                    mode="lines",
                    name="Applied stop (live)",
                    legendgroup="applied",
                    showlegend=first,
                    line={"color": "#f9a825", "width": 2.5, "shape": "hv"},
                )
            )
            # "recommended" column is left out by the caller for an open
            # position (the applied line above already IS what's live) --
            # only drawn when explicitly present.
            if "recommended" in real_history.columns:
                # Markers, not a connected line: the recommended level is a
                # raw daily reading and can legitimately go up AND down day
                # to day (unlike the ratchet-only-up applied line) --
                # connecting it with a step line draws a confusing
                # zigzag/box wherever it dips. Individual dots read cleanly
                # instead.
                fig.add_trace(
                    go.Scatter(
                        x=real_history.index,
                        y=real_history["recommended"],
                        mode="markers",
                        name="Recommended (MAD/ATR, may not be applied yet)",
                        legendgroup="recommended",
                        showlegend=first,
                        marker={
                            "symbol": "diamond",
                            "size": 6,
                            "color": "#2e7d32",
                            "opacity": 0.85,
                        },
                    )
                )
        else:
            stop = overlay["stop"]
            if not stop.empty:
                fig.add_trace(
                    go.Scatter(
                        x=stop.index,
                        y=stop.values,
                        mode="lines",
                        name=_MODE_LABEL[overlay["mode"]],
                        legendgroup="stop",
                        showlegend=first,
                        line={"color": "#f9a825", "width": 2.5, "shape": "hv"},
                    )
                )

        if overlay.get("median") is not None:
            med = overlay["median"].dropna()
            if not med.empty:
                fig.add_trace(
                    go.Scatter(
                        x=med.index,
                        y=med.values,
                        mode="lines",
                        name="MAD median",
                        legendgroup="median",
                        showlegend=first,
                        line={"color": "#9e9e9e", "width": 1, "dash": "dot"},
                    )
                )

        suffix = f" #{i + 1}" if multi else ""
        fig.add_trace(
            go.Scatter(
                x=[entry_date],
                y=[tr["entry_price"]],
                mode="markers+text",
                name="Buy",
                legendgroup="buy",
                showlegend=first,
                marker={
                    "symbol": "triangle-up",
                    "size": 14,
                    "color": "#26a69a",
                    "line": {"width": 1, "color": "#0d3b36"},
                },
                text=[f"BUY{suffix}"],
                textposition="bottom center",
            )
        )

        if exit_date is not None and tr.get("exit_price") is not None:
            fig.add_trace(
                go.Scatter(
                    x=[exit_date],
                    y=[tr["exit_price"]],
                    mode="markers+text",
                    name="Sell",
                    legendgroup="sell",
                    showlegend=first,
                    marker={
                        "symbol": "triangle-down",
                        "size": 14,
                        "color": "#ef5350",
                        "line": {"width": 1, "color": "#4a0e0e"},
                    },
                    text=[f"SELL{suffix}"],
                    textposition="top center",
                )
            )

    # Plotly's default date x-axis is a continuous calendar timeline, so it
    # reserves visual space for weekends (and NSE holidays) even though no
    # candle exists there -- shows up as a gap between Friday's and
    # Monday's candles. rangebreaks tells it to skip those spans entirely
    # instead of leaving a blank gap.
    if not plot_df.empty:
        import nse_holidays

        _lo, _hi = plot_df.index.min().date().isoformat(), plot_df.index.max().date().isoformat()
        _holidays = sorted(d for d in nse_holidays.get_holidays(verbose=False) if _lo <= d <= _hi)
        fig.update_xaxes(
            rangebreaks=[
                {"bounds": ["sat", "mon"]},
                {"values": _holidays},
            ]
        )

    # No Plotly-native title here -- the caller (dashboard.py) renders the
    # symbol/date-range heading as a separate Streamlit element above the
    # chart, so it never fights the horizontal legend for the same
    # top-of-plot space (the two used to overlap into unreadable text).
    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=560,
        margin={"l": 10, "r": 10, "t": 60, "b": 10},
        hovermode="x unified",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0},
    )
    return fig
