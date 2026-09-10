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
FinRL Trading Dashboard
======================

Main Streamlit application for the FinRL Trading platform.
Provides interactive visualization and control of trading strategies.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

# Import project modules
try:
    from src.backtest.backtest_engine import BacktestConfig, BacktestEngine
    from src.config.settings import get_config
    from src.data.data_store import get_data_store
    from src.strategies.base_strategy import StrategyConfig, create_strategy
    from src.trading.alpaca_manager import create_alpaca_account_from_env
    from src.trading.trade_executor import ExecutionConfig, TradeExecutor
    from src.utils.logging_utils import setup_logging
except ImportError:
    # Fallback for direct module testing
    from backtest.backtest_engine import BacktestConfig, BacktestEngine
    from data.data_store import get_data_store
    from strategies.base_strategy import StrategyConfig, create_strategy
    from trading.alpaca_manager import create_alpaca_account_from_env
    from trading.trade_executor import ExecutionConfig, TradeExecutor

    from config.settings import get_config

    try:
        from utils.logging_utils import setup_logging
    except ImportError:
        setup_logging = None

# Setup logging
logger = logging.getLogger(__name__)

# Configure page
st.set_page_config(
    page_title="FinRL Trading Dashboard", page_icon="📈", layout="wide", initial_sidebar_state="expanded"
)

# Initialize session state
if "config" not in st.session_state:
    st.session_state.config = get_config()
if "data_store" not in st.session_state:
    st.session_state.data_store = get_data_store()


def main():
    """Main application function."""
    st.title("📈 FinRL Trading Dashboard")
    st.markdown("AI-powered quantitative trading platform")

    # Sidebar navigation
    with st.sidebar:
        st.header("Navigation")
        page = st.selectbox(
            "Select Page",
            ["Overview", "Data Management", "Strategy Backtesting", "Live Trading", "Portfolio Analysis", "Settings"],
        )

        st.divider()

        # Quick stats
        display_quick_stats()

    # Main content
    if page == "Overview":
        show_overview()
    elif page == "Data Management":
        show_data_management()
    elif page == "Strategy Backtesting":
        show_strategy_backtesting()
    elif page == "Live Trading":
        show_live_trading()
    elif page == "Portfolio Analysis":
        show_portfolio_analysis()
    elif page == "Settings":
        show_settings()


def display_quick_stats():
    """Display quick statistics in sidebar."""
    st.subheader("Quick Stats")

    try:
        # Get data store stats
        stats = st.session_state.data_store.get_storage_stats()

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Data Versions", stats.get("data_versions", 0))
        with col2:
            st.metric("Cache Entries", stats.get("cache_entries", 0))

        st.metric("Storage Used", ".1f")

    except Exception as e:
        st.error(f"Could not load stats: {e}")


def show_overview():
    """Show overview dashboard."""
    st.header("Trading Overview")

    # Key metrics
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Strategies", "5", "↗️ 2")
    with col2:
        st.metric("Active Positions", "12", "↗️ 3")
    with col3:
        st.metric("Portfolio Value", "$1,250,000", "+2.5%")
    with col4:
        st.metric("Today's P&L", "+$1,250", "+1.2%")

    # Recent activity
    st.subheader("Recent Activity")
    activity_data = pd.DataFrame(
        {
            "Time": pd.date_range("2024-01-01 09:00", periods=5, freq="1H"),
            "Action": ["Strategy Execution", "Portfolio Rebalance", "Data Update", "Order Filled", "Strategy Backtest"],
            "Status": ["Success", "Success", "Success", "Success", "Completed"],
            "Details": [
                "ML Strategy executed",
                "Quarterly rebalance",
                "S&P 500 data updated",
                "AAPL order filled",
                "Backtest completed",
            ],
        }
    )

    st.dataframe(activity_data, use_container_width=True)

    # Performance chart
    st.subheader("Portfolio Performance")
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    portfolio_values = 1000000 + np.cumsum(np.random.normal(1000, 5000, 30))

    fig = px.line(x=dates, y=portfolio_values, title="Portfolio Value Over Time")
    fig.update_layout(xaxis_title="Date", yaxis_title="Portfolio Value ($)")
    st.plotly_chart(fig, use_container_width=True)


def show_data_management():
    """Show data management interface."""
    st.header("Data Management")

    tab1, tab2, tab3, tab4 = st.tabs(["Data Sources", "Data Processing", "Data Storage", "Data Quality"])

    with tab1:
        st.subheader("Data Sources")

        col1, col2 = st.columns(2)

        with col1:
            st.subheader("WRDS Data")
            if st.button("Fetch S&P 500 Components"):
                with st.spinner("Fetching data..."):
                    try:
                        from src.data.data_fetcher import fetch_sp500_tickers

                        tickers = fetch_sp500_tickers()
                        st.success(f"Successfully fetched {len(tickers)} tickers")
                        st.info(f"Sample tickers: {tickers[:10]}")
                    except Exception as e:
                        st.error(f"Failed to fetch data: {e}")

            if st.button("Fetch Fundamental Data"):
                with st.spinner("Fetching fundamental data..."):
                    try:
                        from src.data.data_fetcher import fetch_fundamental_data

                        fundamentals = fetch_fundamental_data(["AAPL", "MSFT", "GOOGL"], "2020-01-01", "2023-12-31")
                        st.success(f"Successfully fetched {len(fundamentals)} records")
                    except Exception as e:
                        st.error(f"Failed to fetch data: {e}")

        with col2:
            st.subheader("Local Data")
            uploaded_file = st.file_uploader("Upload CSV file", type=["csv"])
            if uploaded_file is not None:
                df = pd.read_csv(uploaded_file)
                st.write(f"Uploaded {len(df)} rows")
                st.dataframe(df.head())

    with tab2:
        st.subheader("Data Processing")

        if st.button("Process Raw Data"):
            with st.spinner("Processing data..."):
                try:
                    from src.data.data_processor import process_fundamentals, process_prices

                    # Process sample data
                    fundamentals = process_fundamentals("./data/fundamentals.csv")
                    prices = process_prices("./data/prices.csv")

                    st.success("Data processing completed")
                    st.write(f"Processed {len(fundamentals)} fundamental records")
                    st.write(f"Processed {len(prices)} price records")

                except Exception as e:
                    st.error(f"Data processing failed: {e}")

        if st.button("Generate ML Dataset"):
            with st.spinner("Creating ML dataset..."):
                try:
                    from src.data.data_processor import create_ml_dataset

                    X, y = create_ml_dataset("./data/fundamentals.csv", "./data/prices.csv")
                    st.success("ML dataset created")
                    st.write(f"Features shape: {X.shape}")
                    st.write(f"Target shape: {y.shape}")

                except Exception as e:
                    st.error(f"ML dataset creation failed: {e}")

    with tab3:
        st.subheader("Data Storage")

        # Display storage stats
        stats = st.session_state.data_store.get_storage_stats()
        st.json(stats)

        if st.button("Cleanup Expired Cache"):
            with st.spinner("Cleaning up cache..."):
                try:
                    st.session_state.data_store.cleanup_expired_cache()
                    st.success("Cache cleanup completed")
                except Exception as e:
                    st.error(f"Cache cleanup failed: {e}")

    with tab4:
        st.subheader("Data Quality")

        # Data quality checks
        st.subheader("Data Quality Metrics")

        # Sample quality metrics
        quality_data = pd.DataFrame(
            {
                "Metric": ["Completeness", "Accuracy", "Consistency", "Timeliness"],
                "Score": [95.2, 98.1, 92.3, 99.8],
                "Status": ["Good", "Excellent", "Good", "Excellent"],
            }
        )

        st.dataframe(quality_data, use_container_width=True)


def show_strategy_backtesting():
    """Show strategy backtesting interface."""
    st.header("Strategy Backtesting")

    col1, col2 = st.columns([1, 2])

    with col1:
        st.subheader("Backtest Configuration")

        # Strategy selection
        strategy_type = st.selectbox("Strategy Type", ["equal_weight", "market_cap_weight", "ml_strategy"])

        # Backtest parameters
        start_date = st.date_input("Start Date", datetime(2020, 1, 1))
        end_date = st.date_input("End Date", datetime(2023, 12, 31))
        initial_capital = st.number_input("Initial Capital", value=1000000, step=100000)

        # ML strategy parameters
        if strategy_type == "ml_strategy":
            top_quantile = st.slider("Top Quantile", 0.5, 1.0, 0.75, 0.05)

        if st.button("Run Backtest"):
            with st.spinner("Running backtest..."):
                try:
                    run_backtest(
                        strategy_type=strategy_type,
                        start_date=start_date,
                        end_date=end_date,
                        initial_capital=initial_capital,
                        top_quantile=top_quantile if strategy_type == "ml_strategy" else 0.75,
                    )
                except Exception as e:
                    st.error(f"Backtest failed: {e}")

    with col2:
        st.subheader("Backtest Results")

        # Display results if available
        if "backtest_result" in st.session_state:
            result = st.session_state.backtest_result

            # Key metrics
            metrics_cols = st.columns(4)
            with metrics_cols[0]:
                st.metric("Final Value", ".2f")
            with metrics_cols[1]:
                st.metric("Total Return", ".2%")
            with metrics_cols[2]:
                st.metric("Annual Return", ".2%")
            with metrics_cols[3]:
                st.metric("Sharpe Ratio", ".2f")

            # Performance chart
            if hasattr(result, "portfolio_values"):
                fig = px.line(
                    x=result.portfolio_values.index, y=result.portfolio_values.values, title="Portfolio Value"
                )
                st.plotly_chart(fig, use_container_width=True)

            # Detailed metrics
            st.subheader("Detailed Metrics")
            metrics_df = pd.DataFrame(
                {"Metric": list(result.metrics.keys()), "Value": [".4f" for v in result.metrics.values()]}
            )
            st.dataframe(metrics_df)


def run_backtest(strategy_type, start_date, end_date, initial_capital, top_quantile):
    """Run backtest with given parameters."""
    # Create strategy
    config = StrategyConfig(name=f"{strategy_type} Backtest")
    strategy = create_strategy(strategy_type, config)

    # Create backtest configuration
    backtest_config = BacktestConfig(
        start_date=start_date.strftime("%Y-%m-%d"),
        end_date=end_date.strftime("%Y-%m-%d"),
        initial_capital=initial_capital,
    )

    # Load sample data (in practice, load real data)
    dates = pd.date_range(start_date, end_date, freq="D")
    price_data = pd.DataFrame({"datadate": dates, "adj_close": 100 + np.cumsum(np.random.normal(0, 0.02, len(dates)))})

    # Sample weight signals
    weight_signals = pd.DataFrame(
        {"date": pd.date_range(start_date, end_date, freq="Q"), "AAPL": 0.5, "MSFT": 0.3, "GOOGL": 0.2}
    )

    # Run backtest
    engine = BacktestEngine(backtest_config)
    result = engine.run_backtest(strategy, price_data, weight_signals)

    # Store result
    st.session_state.backtest_result = result

    st.success("Backtest completed successfully!")


def show_live_trading():
    """Show live trading interface."""
    st.header("Live Trading")

    # Check if trading is configured
    try:
        account = create_alpaca_account_from_env()
        st.success(f"Connected to Alpaca account (Paper: {account.is_paper})")

        tab1, tab2, tab3 = st.tabs(["Portfolio", "Order Management", "Strategy Execution"])

        with tab1:
            st.subheader("Current Portfolio")

            if st.button("Refresh Portfolio"):
                with st.spinner("Loading portfolio..."):
                    try:
                        from src.trading.alpaca_manager import AlpacaManager

                        manager = AlpacaManager([account])

                        # Get account info
                        manager.get_account_info()
                        positions = manager.get_positions()

                        col1, col2, col3 = st.columns(3)
                        with col1:
                            st.metric("Portfolio Value", ".2f")
                        with col2:
                            st.metric("Cash", ".2f")
                        with col3:
                            st.metric("Buying Power", ".2f")

                        # Positions table
                        if positions:
                            positions_df = pd.DataFrame(positions)
                            st.dataframe(
                                positions_df[["symbol", "qty", "avg_entry_price", "market_value", "unrealized_pl"]],
                                use_container_width=True,
                            )
                        else:
                            st.info("No open positions")

                    except Exception as e:
                        st.error(f"Failed to load portfolio: {e}")

        with tab2:
            st.subheader("Order Management")

            # Place order form
            with st.form("place_order"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    symbol = st.text_input("Symbol", "AAPL").upper()
                with col2:
                    quantity = st.number_input("Quantity", min_value=1, value=10)
                with col3:
                    side = st.selectbox("Side", ["buy", "sell"])

                order_type = st.selectbox("Order Type", ["market", "limit"])
                limit_price = (
                    st.number_input("Limit Price", min_value=0.01, step=0.01) if order_type == "limit" else None
                )

                submitted = st.form_submit_button("Place Order")
                if submitted:
                    try:
                        from src.trading.alpaca_manager import AlpacaManager, OrderRequest

                        manager = AlpacaManager([account])

                        order = OrderRequest(
                            symbol=symbol, quantity=quantity, side=side, order_type=order_type, limit_price=limit_price
                        )

                        response = manager.place_order(order)
                        st.success(f"Order placed: {response.order_id}")

                    except Exception as e:
                        st.error(f"Failed to place order: {e}")

        with tab3:
            st.subheader("Strategy Execution")

            # Strategy execution
            if st.button("Execute Sample Strategy"):
                with st.spinner("Executing strategy..."):
                    try:
                        from src.strategies.base_strategy import EqualWeightStrategy, StrategyConfig
                        from src.trading.trade_executor import TradeExecutor

                        manager = AlpacaManager([account])
                        executor = TradeExecutor(manager)

                        # Create sample strategy
                        config = StrategyConfig(name="Sample Equal Weight")
                        strategy = EqualWeightStrategy(config)

                        # Sample data
                        sample_data = {
                            "fundamentals": pd.DataFrame(
                                {"gvkey": ["AAPL", "MSFT", "GOOGL"], "datadate": ["2024-01-01"] * 3}
                            )
                        }

                        result = executor.execute_strategy(strategy, sample_data)
                        st.success(f"Strategy executed: {len(result.orders_placed)} orders placed")

                    except Exception as e:
                        st.error(f"Strategy execution failed: {e}")

    except Exception as e:
        st.error(f"Trading not configured: {e}")
        st.info("Please set up Alpaca API credentials in environment variables")


def show_portfolio_analysis():
    """Show portfolio analysis interface."""
    st.header("Portfolio Analysis")

    # Sample portfolio data
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    portfolio_values = 1000000 + np.cumsum(np.random.normal(2000, 8000, 100))

    tab1, tab2, tab3, tab4 = st.tabs(["Performance", "Risk Analysis", "Attribution", "Benchmarking"])

    with tab1:
        st.subheader("Performance Analysis")

        # Performance chart
        fig = px.line(x=dates, y=portfolio_values, title="Portfolio Performance")
        st.plotly_chart(fig, use_container_width=True)

        # Performance metrics
        returns = pd.Series(portfolio_values).pct_change().dropna()
        (portfolio_values[-1] / portfolio_values[0]) - 1
        annual_return = returns.mean() * 252
        volatility = returns.std() * np.sqrt(252)
        annual_return / volatility if volatility > 0 else 0

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total Return", ".2%")
        with col2:
            st.metric("Annual Return", ".2%")
        with col3:
            st.metric("Volatility", ".2%")
        with col4:
            st.metric("Sharpe Ratio", ".2f")

    with tab2:
        st.subheader("Risk Analysis")

        # Drawdown analysis
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max

        fig = px.line(x=dates[1:], y=drawdown, title="Portfolio Drawdown")
        fig.update_layout(yaxis_title="Drawdown", yaxis_tickformat=".2%")
        st.plotly_chart(fig, use_container_width=True)

        # Risk metrics
        drawdown.min()
        var_95 = np.percentile(returns, 5)
        returns[returns <= var_95].mean()

        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Max Drawdown", ".2%")
        with col2:
            st.metric("VaR (95%)", ".2%")
        with col3:
            st.metric("CVaR (95%)", ".2%")

    with tab3:
        st.subheader("Attribution Analysis")

        # Sample attribution data
        attribution_data = pd.DataFrame(
            {
                "Asset": ["AAPL", "MSFT", "GOOGL", "Bonds", "Cash"],
                "Weight": [0.3, 0.25, 0.2, 0.15, 0.1],
                "Return": [0.15, 0.12, 0.18, 0.03, 0.02],
                "Contribution": [0.045, 0.03, 0.036, 0.0045, 0.002],
            }
        )

        fig = px.bar(attribution_data, x="Asset", y="Contribution", title="Return Attribution by Asset")
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(attribution_data, use_container_width=True)

    with tab4:
        st.subheader("Benchmarking")

        # Sample benchmark comparison
        benchmark_data = pd.DataFrame(
            {
                "Date": dates,
                "Portfolio": portfolio_values,
                "SPY": 1000000 + np.cumsum(np.random.normal(1500, 6000, 100)),
                "QQQ": 1000000 + np.cumsum(np.random.normal(1800, 7000, 100)),
            }
        )

        fig = px.line(benchmark_data, x="Date", y=["Portfolio", "SPY", "QQQ"], title="Portfolio vs Benchmarks")
        st.plotly_chart(fig, use_container_width=True)


def show_settings():
    """Show settings interface."""
    st.header("Settings")

    tab1, tab2, tab3 = st.tabs(["General", "Trading", "Data"])

    with tab1:
        st.subheader("General Settings")

        # Logging level
        log_level = st.selectbox("Logging Level", ["DEBUG", "INFO", "WARNING", "ERROR"])
        if st.button("Apply Logging Level"):
            logging.getLogger().setLevel(getattr(logging, log_level))
            st.success(f"Logging level set to {log_level}")

        # Theme
        theme = st.selectbox("Theme", ["Light", "Dark"])
        if st.button("Apply Theme"):
            st.success(f"Theme set to {theme}")

    with tab2:
        st.subheader("Trading Settings")

        # Risk limits
        st.number_input("Max Order Value ($)", value=100000, step=10000)
        st.slider("Max Portfolio Turnover (%)", 0.0, 1.0, 0.5, 0.05)

        if st.button("Save Trading Settings"):
            st.success("Trading settings saved")

        # API Configuration
        st.subheader("API Configuration")
        st.text_input("Alpaca API Key", type="password")
        st.text_input("Alpaca API Secret", type="password")
        st.checkbox("Use Paper Trading", value=True)

        if st.button("Save API Settings"):
            st.success("API settings saved")

    with tab3:
        st.subheader("Data Settings")

        # Data paths
        st.text_input("Data Directory", value="./data")
        st.text_input("Cache Directory", value="./data/cache")

        if st.button("Save Data Settings"):
            st.success("Data settings saved")

        # Data sources
        st.subheader("Data Sources")
        st.checkbox("Enable WRDS", value=True)
        st.checkbox("Enable Alpha Vantage", value=False)

        if st.button("Save Data Source Settings"):
            st.success("Data source settings saved")


if __name__ == "__main__":
    main()
