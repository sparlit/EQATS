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


import io
import json
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# =====================================================================
# SYSTEM DESIGN CONFIGURATIONS & MASTER THEME SETUP
# =====================================================================
st.set_page_config(
    page_title="Neuberg Quant Signal Ledger",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.title("⚡ Neuberg Institutional Signal Ledger Engine")
st.caption("Automated Multi-Asset Performance Ranking & Alpha Deployment Core")
st.markdown("---")

# Repo location used for every remote data pull below.
REPO_USERNAME = "mechvec-debug"
REPO_NAME = "AI_driven_Algorithmic_trading"
BRANCH_NAME = "main"

# Same dark palette used in the Telegram signal card, so the chart matches
# the rest of the system instead of introducing yet another color scheme.
CHART_BG = "#0B0F19"
CHART_PANEL = "#111827"
CHART_GRID = "#232B3D"
CHART_TEXT_PRIMARY = "#E8EAF0"
CHART_TEXT_SECONDARY = "#8A93A6"
CHART_GOLD = "#C9A24B"
CHART_POSITIVE = "#3FB88F"
CHART_NEGATIVE = "#D9707A"


# =====================================================================
# SHARED FETCH HELPERS (remote GitHub raw file, falling back to local disk)
# =====================================================================
def _raw_github_url(relative_path: str) -> str:
    """Builds a correct raw.githubusercontent.com URL.
    The previous version (`https://githubusercontent.com{user}/{repo}/...`) was
    missing the 'raw.' subdomain and the '/' after the domain, so it 404'd on
    every single request and this app has actually been running on the local
    file fallback the whole time, silently."""
    return f"https://raw.githubusercontent.com/{REPO_USERNAME}/{REPO_NAME}/{BRANCH_NAME}/{relative_path}"


def _fetch_text(relative_path: str, local_fallback_path: str) -> str | None:
    """Fetches a file's raw text from GitHub, falling back to a local path
    (e.g. when running right next to main.py's own data/ output). Returns
    None if neither source is available."""
    try:
        req = urllib.request.Request(
            _raw_github_url(relative_path),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8")
    except Exception:
        if os.path.exists(local_fallback_path):
            try:
                with open(local_fallback_path) as f:
                    return f.read()
            except Exception:
                return None
        return None


def _fetch_json(relative_path: str, local_fallback_path: str) -> dict:
    raw_text = _fetch_text(relative_path, local_fallback_path)
    if not raw_text:
        return {}
    try:
        return json.loads(raw_text)
    except Exception:
        return {}


@st.cache_data(ttl=300)
def load_ticker_ohlc_history(
    file_ticker_candidates: tuple, lookback_days: int = 180
) -> pd.DataFrame:
    """Loads a single ticker's processed OHLC history (as written by main.py's
    calculate_quant_metrics -> data/processed/{ticker}_processed.csv).

    main.py names that file after the *raw* ticker (e.g. 'MARINE.NS_processed.csv'),
    but the ledger JSON displays the suffix-stripped clean name (e.g. 'MARINE'), so a
    single guess at the filename isn't reliable — this tries each candidate filename
    stem in order (raw_ticker first, then a couple of common-suffix fallbacks for
    older JSON exports that don't carry raw_ticker yet) and returns the first hit.
    """
    for candidate in file_ticker_candidates:
        if not candidate:
            continue
        relative_path = f"data/processed/{candidate}_processed.csv"
        raw_text = _fetch_text(relative_path, relative_path)
        if not raw_text:
            continue
        try:
            df = pd.read_csv(io.StringIO(raw_text), index_col=0, parse_dates=True)
            df = df.sort_index()
            df.columns = [str(c).lower() for c in df.columns]
            required_cols = {"open", "high", "low", "close"}
            if not required_cols.issubset(set(df.columns)):
                continue
            return df.tail(lookback_days)
        except Exception:
            continue
    return pd.DataFrame()


# =====================================================================
# DATA COMPILATION & CONTEXT INGESTION PIPELINE
# =====================================================================
def _build_ledger_row(signal: dict) -> dict:
    """Single row-builder used for both the remote and local-fallback paths,
    so the two can no longer silently drift out of sync with each other."""
    roi_val = signal.get("backtest_roi_pct", 0.0)
    if roi_val is None or isinstance(roi_val, str):
        roi_val = -999.0

    action_status = signal.get("action_status", "HOLD")
    peak_tracked = signal.get("highest_tracked_peak", 0.0)
    trailing_floor = signal.get("active_trailing_stop_floor", 0.0)
    target_tp1 = signal.get("take_profit_target_1", 0.0)
    target_tp2 = signal.get("take_profit_target_2", 0.0)

    return {
        "Asset Ticker": signal.get("ticker", "N/A"),
        "Industry Sector": signal.get("sector", "Other Diversified"),
        "Current Close": f"₹{signal.get('close_price', 0.0):,.2f}"
        if signal.get("close_price")
        else "N/A",
        "Ann. Volatility": f"{signal.get('ann_volatility_pct', 0.0):.2f}%",
        "Daily VaR (95%)": f"{signal.get('daily_var_95_pct', 0.0):.2f}%",
        "Qlib Alpha Score": signal.get("qlib_alpha_score", 0.0),
        "Backtest Success (ROI)": f"{roi_val:+.2f}%" if roi_val != -999.0 else "Failed Analysis",
        "Sort_Key_ROI": roi_val if roi_val != -999.0 else -9999.0,
        "Action Deployment": action_status,
        "Target Position Shares": signal.get("recommended_shares_to_buy", 0)
        if action_status == "BUY"
        else 0,
        "Capital Allocation (₹)": f"₹{signal.get('required_allocation_in_rupees', 0.0):,.2f}"
        if action_status == "BUY"
        else "₹0.00",
        "Peak Price (₹)": f"₹{peak_tracked:,.2f}"
        if action_status == "BUY" and peak_tracked > 0
        else "N/A",
        "Trailing Stop Floor (₹)": f"₹{trailing_floor:,.2f}"
        if action_status == "BUY" and trailing_floor > 0
        else "N/A",
        "Take Profit 1 (₹)": f"₹{target_tp1:,.2f}"
        if action_status == "BUY" and target_tp1 > 0
        else "N/A",
        "Take Profit 2 (₹)": f"₹{target_tp2:,.2f}"
        if action_status == "BUY" and target_tp2 > 0
        else "N/A",
        # Kept as raw numbers too, so the chart section below doesn't have to re-parse currency strings.
        "_raw_tp1": target_tp1 if action_status == "BUY" else None,
        "_raw_tp2": target_tp2 if action_status == "BUY" else None,
        "_raw_trailing_floor": trailing_floor
        if action_status == "BUY" and trailing_floor > 0
        else None,
        # The close price at the moment the signal fired — treated as the intended
        # entry price for a fresh BUY, since that's what the signal was based on.
        "_raw_entry_price": signal.get("close_price", 0.0) if action_status == "BUY" else None,
        "_raw_allocation": signal.get("required_allocation_in_rupees", 0.0)
        if action_status == "BUY"
        else 0.0,
        "_raw_shares": signal.get("recommended_shares_to_buy", 0) if action_status == "BUY" else 0,
        # The exact filename stem main.py used for data/processed/{this}_processed.csv
        # (usually includes the .NS/.BO suffix). Falls back to the clean display name
        # for older JSON exports written before this field existed.
        "_raw_ticker": signal.get("raw_ticker") or signal.get("ticker", "N/A"),
    }


@st.cache_data(ttl=60)
def compile_master_signal_ledger() -> pd.DataFrame:
    """Decodes the latest signal ledger from GitHub raw (or local disk fallback)."""
    database_payload = _fetch_json(
        "data/output/latest_market_signals.json",
        "data/output/latest_market_signals.json",
    )
    signals_list = database_payload.get("signals", [])

    master_rows = [_build_ledger_row(signal) for signal in signals_list]
    if not master_rows:
        return pd.DataFrame()

    master_df = pd.DataFrame(master_rows)
    master_df = master_df.sort_values(by="Sort_Key_ROI", ascending=False).reset_index(drop=True)
    master_df = master_df.drop(columns=["Sort_Key_ROI"])
    return master_df


# =====================================================================
# INTERACTIVE DATA PRESENTATION ENGINE LAYER
# =====================================================================
ledger_matrix = compile_master_signal_ledger()

if ledger_matrix.empty:
    st.warning(
        "⚠️ High-order analytical databases are empty. Please run your background execution loop script ('python main.py') to synchronize files."
    )
else:
    # 1. Split-View Container Filtering Module
    st.subheader("📋 Top 10 High-Performing Asset Ledger")
    st.caption(
        "Equities sorted directly by optimal backtest success metrics. Invalid rows are dynamically filtered out."
    )
    st.markdown("---")

    # =====================================================================
    # INJECTED CORE MODULE: 4-COLUMN INSTITUTIONAL SCORECARD ROW
    # =====================================================================
    top_10_ledger = ledger_matrix.head(10)

    if not top_10_ledger.empty:
        lead_row = top_10_ledger.iloc[0]

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(label="Top Asset Current Close", value=str(lead_row["Current Close"]))
        with col2:
            st.metric(
                label="LEAN Backtest Success ROI", value=str(lead_row["Backtest Success (ROI)"])
            )
        with col3:
            st.metric(label="Daily VaR (95%)", value=str(lead_row["Daily VaR (95%)"]))
        with col4:
            st.metric(label="Current Deployment Status", value=str(lead_row["Action Deployment"]))

    st.markdown("---")

    # =====================================================================
    # 2. Dynamic Structural Row-Color Formatting Styles
    # =====================================================================
    def apply_row_color_matrix(row):
        if row["Action Deployment"] == "BUY":
            return ["background-color: #1e3d2f; color: #73e6a4; font-weight: bold;"] * len(row)
        return [""] * len(row)

    display_cols = [c for c in top_10_ledger.columns if not c.startswith("_raw_")]
    styled_ledger = top_10_ledger[display_cols].style.apply(apply_row_color_matrix, axis=1)
    st.write(styled_ledger)

    # 3. Macro Dashboard Summaries Summary Containers
    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        buy_count = len(top_10_ledger[top_10_ledger["Action Deployment"] == "BUY"])
        st.metric(label="Total Active BUY Alerts (Top 10)", value=f"{buy_count} Tickers Triggered")
    with col2:
        total_tracked_valid = len(ledger_matrix)
        st.metric(
            label="Total Valid Scanned Equities Database Size",
            value=f"{total_tracked_valid} / 500+ Active",
        )

    # =====================================================================
    # 4. TRIGGERED SIGNAL PRICE CHART (candlestick built from the processed
    #    open/high/low/close history that main.py writes per ticker)
    # =====================================================================
    st.markdown("---")
    st.subheader("📈 Triggered Signal Price Chart")

    triggered_ledger = ledger_matrix[ledger_matrix["Action Deployment"] == "BUY"]

    if triggered_ledger.empty:
        st.info(
            "ℹ️ No tickers are currently flagged BUY, so there's no triggered signal to chart yet."
        )
    else:
        chart_ticker = st.selectbox(
            "Select a triggered (BUY) asset to chart",
            options=triggered_ledger["Asset Ticker"].tolist(),
            index=0,
        )

        chart_row = triggered_ledger[triggered_ledger["Asset Ticker"] == chart_ticker].iloc[0]

        # main.py names the CSV after the *raw* ticker (often with a .NS/.BO suffix,
        # e.g. "MARINE.NS_processed.csv"), while the ledger shows the suffix-stripped
        # display name (e.g. "MARINE"). Try the raw filename main.py actually wrote
        # first, then fall back to a couple of common-suffix guesses for older JSON
        # exports that predate the raw_ticker field.
        raw_ticker = chart_row.get("_raw_ticker")
        file_candidates = tuple(
            dict.fromkeys(
                [
                    raw_ticker,
                    chart_ticker,
                    f"{chart_ticker}.NS",
                    f"{chart_ticker}.BO",
                ]
            )
        )

        ohlc_df = load_ticker_ohlc_history(file_candidates)

        if ohlc_df.empty:
            st.warning(
                f"⚠️ No OHLC history found for {chart_ticker}. Checked: "
                f"{', '.join(f'{c}_processed.csv' for c in file_candidates)} — make sure one of these "
                f"exists under data/processed/ and has been committed/synced from main.py's output."
            )
        else:
            row = chart_row

            # Trend context: EMA reacts faster to recent price moves than SMA, which is
            # usually what people actually want for a short-horizon momentum chart.
            ohlc_df["ema_9"] = ohlc_df["close"].ewm(span=9, adjust=False).mean()
            ohlc_df["ema_20"] = ohlc_df["close"].ewm(span=20, adjust=False).mean()

            fig = make_subplots(
                rows=2,
                cols=1,
                shared_xaxes=True,
                row_heights=[0.75, 0.25],
                vertical_spacing=0.03,
            )

            fig.add_trace(
                go.Candlestick(
                    x=ohlc_df.index,
                    open=ohlc_df["open"],
                    high=ohlc_df["high"],
                    low=ohlc_df["low"],
                    close=ohlc_df["close"],
                    name=chart_ticker,
                    increasing_line_color=CHART_POSITIVE,
                    decreasing_line_color=CHART_NEGATIVE,
                    increasing_fillcolor=CHART_POSITIVE,
                    decreasing_fillcolor=CHART_NEGATIVE,
                    hovertemplate=(
                        "%{x|%d %b %Y}<br>"
                        "Open ₹%{open:,.2f}  High ₹%{high:,.2f}<br>"
                        "Low ₹%{low:,.2f}  Close ₹%{close:,.2f}<extra></extra>"
                    ),
                ),
                row=1,
                col=1,
            )

            fig.add_trace(
                go.Scatter(
                    x=ohlc_df.index,
                    y=ohlc_df["ema_9"],
                    mode="lines",
                    name="EMA 9",
                    line={"color": CHART_GOLD, "width": 1.3},
                    hovertemplate="EMA9 ₹%{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

            fig.add_trace(
                go.Scatter(
                    x=ohlc_df.index,
                    y=ohlc_df["ema_20"],
                    mode="lines",
                    name="EMA 20",
                    line={"color": CHART_TEXT_SECONDARY, "width": 1.3, "dash": "dot"},
                    hovertemplate="EMA20 ₹%{y:,.2f}<extra></extra>",
                ),
                row=1,
                col=1,
            )

            # Entry / TP1 / TP2 / trailing-stop levels, drawn as flat lines that sit in
            # the legend (like every other trace) instead of fig.add_hline's edge-of-chart
            # text annotations, which were getting clipped whenever the plot got resized
            # (e.g. by Streamlit's use_container_width) — there's no "outside the plot"
            # margin to clip against when the label lives in the legend instead.
            x_span = [ohlc_df.index.min(), ohlc_df.index.max()]
            for label, value, color, dash, width in [
                ("Entry", row.get("_raw_entry_price"), CHART_GOLD, "solid", 1.6),
                ("TP1", row.get("_raw_tp1"), CHART_POSITIVE, "dot", 1.4),
                ("TP2", row.get("_raw_tp2"), "#2E8B6F", "dash", 1.4),
                ("Trailing Stop", row.get("_raw_trailing_floor"), CHART_NEGATIVE, "dashdot", 1.4),
            ]:
                if value:
                    fig.add_trace(
                        go.Scatter(
                            x=x_span,
                            y=[value, value],
                            mode="lines",
                            name=f"{label}: ₹{value:,.2f}",
                            line={"color": color, "width": width, "dash": dash},
                            hoverinfo="skip",
                        ),
                        row=1,
                        col=1,
                    )

            # Entry marker: a bold gold "X" on the latest candle at the entry price, so the
            # exact spot the signal fired is obvious even when the flat Entry line runs
            # across the whole chart.
            entry_value = row.get("_raw_entry_price")
            if entry_value:
                fig.add_trace(
                    go.Scatter(
                        x=[ohlc_df.index.max()],
                        y=[entry_value],
                        mode="markers",
                        name="Entry point",
                        marker={
                            "symbol": "x",
                            "size": 15,
                            "color": CHART_GOLD,
                            "line": {"width": 3, "color": CHART_GOLD},
                        },
                        hovertemplate="Entry ₹%{y:,.2f}<extra></extra>",
                    ),
                    row=1,
                    col=1,
                )

            volume_colors = [
                CHART_POSITIVE if c >= o else CHART_NEGATIVE
                for o, c in zip(ohlc_df["open"], ohlc_df["close"], strict=False)
            ]
            fig.add_trace(
                go.Bar(
                    x=ohlc_df.index,
                    y=ohlc_df["volume"],
                    name="Volume",
                    marker_color=volume_colors,
                    marker_line_width=0,
                    opacity=0.75,
                    hovertemplate="%{x|%d %b %Y}<br>Volume %{y:,.0f}<extra></extra>",
                ),
                row=2,
                col=1,
            )

            fig.update_layout(
                title={
                    "text": f"{chart_ticker} — Price History ({len(ohlc_df)} sessions)",
                    "font": {"color": CHART_TEXT_PRIMARY, "size": 16},
                },
                template="plotly_dark",
                paper_bgcolor=CHART_BG,
                plot_bgcolor=CHART_PANEL,
                font={"color": CHART_TEXT_PRIMARY},
                showlegend=True,
                legend={
                    "orientation": "h",
                    "yanchor": "bottom",
                    "y": 1.01,
                    "xanchor": "left",
                    "x": 0,
                    "font": {"size": 11.5, "color": CHART_TEXT_PRIMARY},
                    "bgcolor": "rgba(0,0,0,0)",
                },
                hovermode="x unified",
                dragmode="zoom",  # click-drag draws a zoom box (desktop); pinch zooms on touch
                height=660,
                margin={"l": 10, "r": 10, "t": 110, "b": 10},
                xaxis_rangeslider_visible=False,
                xaxis2={
                    "rangeslider": {"visible": True, "thickness": 0.09, "bgcolor": CHART_PANEL},
                    "gridcolor": CHART_GRID,
                },
                xaxis={
                    "gridcolor": CHART_GRID,
                    "rangeselector": {
                        "buttons": [
                            {"count": 1, "label": "1M", "step": "month", "stepmode": "backward"},
                            {"count": 3, "label": "3M", "step": "month", "stepmode": "backward"},
                            {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
                            {"step": "all", "label": "All"},
                        ],
                        "bgcolor": CHART_PANEL,
                        "activecolor": CHART_GOLD,
                        "font": {"color": CHART_TEXT_PRIMARY, "size": 11},
                    },
                },
            )
            fig.update_yaxes(title_text="Price (₹)", gridcolor=CHART_GRID, row=1, col=1)
            fig.update_yaxes(title_text="Volume", gridcolor=CHART_GRID, row=2, col=1)

            # Streamlit hides Plotly's zoom/pan toolbar until you hover the chart, and
            # mouse-wheel zoom is off by default — both look like "zoom doesn't work."
            # This forces the toolbar to stay visible and turns scroll-to-zoom on.
            st.plotly_chart(
                fig,
                width="stretch",
                theme=None,  # Streamlit's default theme overrides legend/title text colors
                config={
                    "scrollZoom": True,
                    "displayModeBar": True,
                    "displaylogo": False,
                    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                },
            )
            st.caption(
                "Zoom: scroll/pinch on the chart, or click-drag to box-zoom. "
                "Double-click to reset. Drag the bar under the volume panel, or use the "
                "1M / 3M / 6M / All buttons, to change the visible date range."
            )

    # =====================================================================
    # 🟢 FIXED ACCUMULATION PORTFOLIO SUMMARY CONTAINER (RAW STREAMING)
    # =====================================================================
    st.markdown("---")
    st.subheader("⚡ Live Account Performance Tracker & Portfolio Summary")
    st.caption(
        "Tracks simulated active execution sizing parameters, liquid asset ledger holdings, and account equity growth updates."
    )

    portfolio_data = _fetch_json(
        "data/output/live_portfolio_ledger.json",
        "data/output/live_portfolio_ledger.json",
    )

    if not portfolio_data:
        st.info(
            "ℹ️ Account simulation ledger is currently empty. Run the broker agent component script ('python broker_agent.py') on your laptop or wait for the cloud workflow to complete to bring live ledger updates online."
        )
    else:
        p_telemetry = portfolio_data.get("account_telemetry", {})
        p_positions = portfolio_data.get("active_positions", {})

        # 1. Macro Summary Balance Scorecards
        m_col1, m_col2, m_col3 = st.columns(3)
        with m_col1:
            st.metric(
                label="Total Portfolio Value (Cash + Stock)",
                value=f"₹{p_telemetry.get('total_portfolio_value', 100000.0):,.2f}",
                delta=f"{p_telemetry.get('total_closed_roi_pct', 0.0):+.2f}% ROI",
            )
        with m_col2:
            st.metric(
                label="Available Cash Balance",
                value=f"₹{p_telemetry.get('available_cash', 100000.0):,.2f}",
            )
        with m_col3:
            st.metric(label="Active Open Positions Count", value=f"{len(p_positions)} Assets Live")

        # 2. Active Holdings Grid Data Table
        if p_positions:
            st.markdown("##### 📋 Current Position Holding Matrix Ledger Details")
            positions_rows = []
            for t_code, p_details in p_positions.items():
                positions_rows.append(
                    {
                        "Asset Ticker": t_code,
                        "Industry Sector": p_details.get("sector", "Other Diversified"),
                        "Shares Held (Qty)": p_details.get("qty", 0),
                        "Average Cost Price": f"₹{p_details.get('entry_avg', 0.0):,.2f}",
                        "Take Profit 1": f"₹{p_details.get('tp1', 0.0):,.2f}",
                        "Take Profit 2": f"₹{p_details.get('tp2', 0.0):,.2f}",
                        "Active Trailing Stop Floor": f"₹{p_details.get('trailing_floor', 0.0):,.2f}",
                        "Peak Price Reached": f"₹{p_details.get('peak_close', 0.0):,.2f}",
                    }
                )
            st.dataframe(pd.DataFrame(positions_rows))

            # 3. Cross-check: BUY signals in the ledger that are NOT held in the portfolio.
            # The signal ledger sizes every BUY independently (against the full account),
            # so it can't see that earlier positions already used up the cash.
            held_keys = {str(k).upper().replace(".NS", "").replace(".BO", "") for k in p_positions}
            available_cash = float(p_telemetry.get("available_cash", 0.0) or 0.0)
            unfunded = []
            for _, sig_row in triggered_ledger.iterrows():
                clean_key = str(sig_row["Asset Ticker"]).upper()
                if clean_key not in held_keys:
                    needed = float(sig_row.get("_raw_allocation", 0.0) or 0.0)
                    unfunded.append(
                        {
                            "Asset Ticker": sig_row["Asset Ticker"],
                            "Signal Status": "BUY",
                            "Capital Needed (₹)": f"₹{needed:,.2f}",
                            "Available Cash (₹)": f"₹{available_cash:,.2f}",
                            "Likely Reason": "Insufficient cash"
                            if needed > available_cash
                            else "Not yet executed by broker agent",
                        }
                    )
            if unfunded:
                st.markdown("##### ⚠️ BUY Signals Not Held in Portfolio")
                st.caption(
                    "These tickers are flagged BUY in the signal ledger but have no open position in the "
                    "simulated account."
                )
                st.dataframe(pd.DataFrame(unfunded), hide_index=True)
        else:
            st.info("💼 No active positions are currently held in the portfolio simulation ledger.")
