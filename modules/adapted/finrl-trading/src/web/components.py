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
Web Components Module
===================

Reusable UI components for the FinRL Trading dashboard.
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


def display_portfolio_summary(portfolio_data: dict[str, Any]):
    """Display portfolio summary cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Portfolio Value", ".2f", ".2f")

    with col2:
        st.metric("Today's P&L", ".2f", ".2f")

    with col3:
        st.metric("Cash", ".2f")

    with col4:
        st.metric("Buying Power", ".2f")


def create_performance_chart(
    portfolio_values: pd.Series,
    benchmark_values: dict[str, pd.Series] | None = None,
    title: str = "Portfolio Performance",
):
    """Create performance visualization chart."""
    fig = go.Figure()

    # Portfolio line
    fig.add_trace(
        go.Scatter(
            x=portfolio_values.index,
            y=portfolio_values.values,
            mode="lines",
            name="Portfolio",
            line={"color": "blue", "width": 2},
        )
    )

    # Benchmark lines
    if benchmark_values:
        colors = ["red", "green", "orange", "purple"]
        for i, (name, values) in enumerate(benchmark_values.items()):
            if len(values) > 0:
                fig.add_trace(
                    go.Scatter(
                        x=values.index,
                        y=values.values,
                        mode="lines",
                        name=name,
                        line={"color": colors[i % len(colors)], "width": 1, "dash": "dot"},
                    )
                )

    fig.update_layout(title=title, xaxis_title="Date", yaxis_title="Value ($)", hovermode="x unified", showlegend=True)

    return fig


def create_returns_distribution_chart(returns: pd.Series, title: str = "Returns Distribution"):
    """Create returns distribution histogram."""
    fig = go.Figure()

    fig.add_trace(go.Histogram(x=returns.values, nbinsx=50, name="Returns", marker_color="lightblue", opacity=0.7))

    fig.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="Break-even")

    fig.update_layout(title=title, xaxis_title="Return", yaxis_title="Frequency", bargap=0.1)

    return fig


def create_drawdown_chart(portfolio_values: pd.Series, title: str = "Portfolio Drawdown"):
    """Create drawdown visualization."""
    # Calculate drawdown
    cumulative = (1 + portfolio_values.pct_change().fillna(0)).cumprod()
    running_max = cumulative.expanding().max()
    drawdown = (cumulative - running_max) / running_max

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=drawdown.index,
            y=drawdown.values,
            fill="tozeroy",
            mode="lines",
            name="Drawdown",
            line={"color": "red"},
            fillcolor="rgba(255, 0, 0, 0.3)",
        )
    )

    fig.update_layout(title=title, xaxis_title="Date", yaxis_title="Drawdown", yaxis_tickformat=".2%", showlegend=False)

    return fig


def create_risk_metrics_table(metrics: dict[str, float]):
    """Create risk metrics table."""
    # Group metrics by category
    performance_metrics = {
        "Total Return": metrics.get("total_return", 0),
        "Annual Return": metrics.get("annual_return", 0),
        "Annual Volatility": metrics.get("annual_volatility", 0),
        "Sharpe Ratio": metrics.get("sharpe_ratio", 0),
        "Sortino Ratio": metrics.get("sortino_ratio", 0),
        "Calmar Ratio": metrics.get("calmar_ratio", 0),
    }

    risk_metrics = {
        "Maximum Drawdown": metrics.get("max_drawdown", 0),
        "Max DD Duration": metrics.get("max_dd_duration", 0),
        "VaR (95%)": metrics.get("var_95", 0),
        "CVaR (95%)": metrics.get("cvar_95", 0),
        "Skewness": metrics.get("skewness", 0),
        "Kurtosis": metrics.get("kurtosis", 0),
    }

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Performance Metrics")
        perf_df = pd.DataFrame(
            {"Metric": list(performance_metrics.keys()), "Value": [".4f" for v in performance_metrics.values()]}
        )
        st.dataframe(perf_df, use_container_width=True)

    with col2:
        st.subheader("Risk Metrics")
        risk_df = pd.DataFrame({"Metric": list(risk_metrics.keys()), "Value": [".4f" for v in risk_metrics.values()]})
        st.dataframe(risk_df, use_container_width=True)


def create_sector_allocation_chart(positions: list[dict[str, Any]], title: str = "Sector Allocation"):
    """Create sector allocation pie chart."""
    if not positions:
        return None

    # Group by sector (assuming sector info is available)
    sector_data = {}
    for position in positions:
        sector = position.get("sector", "Unknown")
        market_value = float(position.get("market_value", 0))

        if sector in sector_data:
            sector_data[sector] += market_value
        else:
            sector_data[sector] = market_value

    if not sector_data:
        return None

    fig = go.Figure(
        data=[go.Pie(labels=list(sector_data.keys()), values=list(sector_data.values()), title=title, hole=0.3)]
    )

    fig.update_layout(showlegend=True)
    return fig


def create_strategy_comparison_chart(strategies_data: dict[str, pd.Series], title: str = "Strategy Comparison"):
    """Create strategy comparison chart."""
    fig = go.Figure()

    colors = ["blue", "red", "green", "orange", "purple", "brown"]

    for i, (strategy_name, values) in enumerate(strategies_data.items()):
        fig.add_trace(
            go.Scatter(
                x=values.index,
                y=values.values,
                mode="lines",
                name=strategy_name,
                line={"color": colors[i % len(colors)], "width": 2},
            )
        )

    fig.update_layout(
        title=title, xaxis_title="Date", yaxis_title="Portfolio Value ($)", hovermode="x unified", showlegend=True
    )

    return fig


def display_orders_table(orders: list[dict[str, Any]], title: str = "Recent Orders"):
    """Display orders in a formatted table."""
    if not orders:
        st.info("No orders to display")
        return

    # Format orders for display
    display_orders = []
    for order in orders:
        display_order = {
            "Symbol": order.get("symbol", ""),
            "Side": order.get("side", "").upper(),
            "Quantity": order.get("quantity", 0),
            "Price": ".2f" if order.get("price") else "",
            "Status": order.get("status", ""),
            "Time": order.get("submitted_at", "")[:19] if order.get("submitted_at") else "",
        }
        display_orders.append(display_order)

    orders_df = pd.DataFrame(display_orders)
    st.subheader(title)
    st.dataframe(orders_df, use_container_width=True)


def create_correlation_heatmap(returns_data: dict[str, pd.Series], title: str = "Asset Correlation"):
    """Create correlation heatmap."""
    if not returns_data:
        return None

    # Create returns DataFrame
    returns_df = pd.DataFrame(returns_data)

    # Calculate correlation
    correlation = returns_df.corr()

    fig = go.Figure(
        data=go.Heatmap(
            z=correlation.values,
            x=correlation.columns,
            y=correlation.columns,
            colorscale="RdBu",
            zmid=0,
            text=np.round(correlation.values, 2),
            texttemplate="%{text}",
            textfont={"size": 10},
            hoverongaps=False,
        )
    )

    fig.update_layout(title=title, xaxis_title="Assets", yaxis_title="Assets")

    return fig


def display_alerts(alerts: list[dict[str, Any]]):
    """Display system alerts."""
    if not alerts:
        st.success("✅ No alerts")
        return

    for alert in alerts:
        alert_type = alert.get("type", "info")
        message = alert.get("message", "")

        if alert_type == "error":
            st.error(f"🚨 {message}")
        elif alert_type == "warning":
            st.warning(f"⚠️ {message}")
        elif alert_type == "success":
            st.success(f"✅ {message}")
        else:
            st.info(f"ℹ️ {message}")


def create_rolling_sharpe_chart(returns: pd.Series, window: int = 252, title: str = "Rolling Sharpe Ratio"):
    """Create rolling Sharpe ratio chart."""
    if len(returns) < window:
        st.warning("Not enough data for rolling Sharpe calculation")
        return None

    # Calculate rolling Sharpe ratio
    rolling_mean = returns.rolling(window=window).mean()
    rolling_std = returns.rolling(window=window).std()
    rolling_sharpe = rolling_mean / rolling_std * np.sqrt(252)  # Annualized

    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=rolling_sharpe.index,
            y=rolling_sharpe.values,
            mode="lines",
            name="Rolling Sharpe",
            line={"color": "green", "width": 2},
        )
    )

    fig.add_hline(y=0, line_dash="dash", line_color="red", annotation_text="Break-even")

    fig.update_layout(title=title, xaxis_title="Date", yaxis_title="Sharpe Ratio", showlegend=False)

    return fig


def display_data_quality_report(quality_metrics: dict[str, Any]):
    """Display data quality report."""
    st.subheader("Data Quality Report")

    # Overall quality score
    overall_score = quality_metrics.get("overall_score", 0)
    if overall_score >= 90:
        st.success(f"🎉 Excellent Data Quality: {overall_score:.1f}%")
    elif overall_score >= 75:
        st.info(f"👍 Good Data Quality: {overall_score:.1f}%")
    elif overall_score >= 60:
        st.warning(f"⚠️ Fair Data Quality: {overall_score:.1f}%")
    else:
        st.error(f"🚨 Poor Data Quality: {overall_score:.1f}%")

    # Detailed metrics
    metrics_cols = st.columns(3)

    with metrics_cols[0]:
        st.metric("Completeness", ".1f")
    with metrics_cols[1]:
        st.metric("Accuracy", ".1f")
    with metrics_cols[2]:
        st.metric("Timeliness", ".1f")

    # Issues and recommendations
    if quality_metrics.get("issues"):
        st.subheader("Issues Found")
        for issue in quality_metrics["issues"]:
            st.warning(f"• {issue}")

    if quality_metrics.get("recommendations"):
        st.subheader("Recommendations")
        for rec in quality_metrics["recommendations"]:
            st.info(f"• {rec}")


def create_factor_attribution_chart(attribution_data: dict[str, float], title: str = "Factor Attribution"):
    """Create factor attribution bar chart."""
    factors = list(attribution_data.keys())
    contributions = list(attribution_data.values())

    colors = ["green" if x > 0 else "red" for x in contributions]

    fig = go.Figure()

    fig.add_trace(go.Bar(x=factors, y=contributions, marker_color=colors, name="Contribution"))

    fig.update_layout(title=title, xaxis_title="Factors", yaxis_title="Contribution to Return", showlegend=False)

    return fig
