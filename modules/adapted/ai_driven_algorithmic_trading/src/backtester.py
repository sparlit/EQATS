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


import os

import numpy as np
import pandas as pd


class LeanPortfolioStrategyEngine:
    def __init__(self, initial_capital: float = 100000.0):
        """
        Initializes the LEAN-style portfolio simulation environment.
        Sets trading constraints tailored to Indian markets.
        """
        self.initial_capital = initial_capital

        # Exact transaction fee matrices for Indian broker execution (Zerodha/Groww approximations)
        self.slippage_pct = 0.0005  # 0.05% slippage on entry/exit execution friction
        self.stt_pct = 0.001  # 0.1% Delivery Securities Transaction Tax (STT)

    def run_backtest(self, ticker: str) -> dict:
        """
        Runs a simulation iteration using data from the local data directory.
        """
        path = f"data/alpha_features/{ticker}_qlib_features.csv"
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing Qlib source data file at {path}. Run the data generator first."
            )

        df = pd.read_csv(path, index_col=0, parse_dates=True)
        print(f"-> Commencing simulated backtest run for {ticker} across {len(df)} rows...")

        # Set runtime position ledger states
        cash = self.initial_capital
        position_shares = 0.0
        portfolio_value_history = []
        trade_logs = []

        for i in range(len(df)):
            current_row = df.iloc[i]
            current_price = current_row["close"]
            alpha_signal = current_row["qlib_momentum_5d"]

            # Rebalance Engine logic (LEAN Portfolio targets)
            # Entry Signal: Strong positive momentum detected, and not holding a position
            if alpha_signal > 0.01 and position_shares == 0:
                # Calculate maximum affordable shares after reserving friction costs
                buying_power = cash / (1.0 + self.slippage_pct + self.stt_pct)
                position_shares = buying_power / current_price
                cash = 0.0
                trade_logs.append(
                    f"BUY EXECUTION | Price: ₹{current_price:,.2f} | Action: Capital Deployed"
                )

            # Exit Signal: Momentum drops below baseline, and holding a position
            elif alpha_signal < -0.01 and position_shares > 0:
                gross_proceeds = position_shares * current_price
                friction_costs = gross_proceeds * (self.slippage_pct + self.stt_pct)
                cash = gross_proceeds - friction_costs
                position_shares = 0.0
                trade_logs.append(
                    f"SELL EXECUTION | Price: ₹{current_price:,.2f} | Action: Taken Profit/Cut Loss"
                )

            # Track daily mark-to-market total liquidation value
            current_portfolio_value = cash + (position_shares * current_price)
            portfolio_value_history.append(current_portfolio_value)

        # Compile mathematical performance metrics
        df["portfolio_value"] = portfolio_value_history
        df["strategy_returns"] = df["portfolio_value"].pct_change()

        final_value = df["portfolio_value"].iloc[-1]
        total_net_return = ((final_value - self.initial_capital) / self.initial_capital) * 100

        # Calculate maximum peak-to-trough drawdown vector
        rolling_peak = df["portfolio_value"].cummax()
        drawdown_series = (df["portfolio_value"] - rolling_peak) / rolling_peak
        max_drawdown = drawdown_series.min() * 100

        # Compute Sharpe Ratio (Assuming a 6.5% standard Indian risk-free rate proxy)
        excess_returns = df["strategy_returns"] - (0.065 / 252)
        sharpe_ratio = np.sqrt(252) * (
            excess_returns.mean() / (df["strategy_returns"].std() + 1e-8)
        )

        metrics = {
            "initial_capital": self.initial_capital,
            "final_value": final_value,
            "net_return_pct": total_net_return,
            "max_drawdown_pct": max_drawdown,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": len(trade_logs),
        }

        return metrics
