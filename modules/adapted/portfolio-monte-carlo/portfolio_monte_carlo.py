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
Markowitz Efficient Frontier via Monte Carlo Simulation

"""
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import yfinance as yf

sns.set_style("whitegrid")

# --- Constants ---
NUM_TRADING_DAYS = 252
NUM_SIMULATIONS = 100_000
RISK_FREE_RATE_SIMPLE = 0.07  # stated as a simple annual rate
RISK_FREE_RATE_LOG = np.log(1 + RISK_FREE_RATE_SIMPLE)  # converted to log-return terms
SEED = 42

STOCKS = ["DRREDDY.NS", "BHARTIARTL.NS", "BAJFINANCE.NS", "ULTRACEMCO.NS", "NTPC.NS"]
START_DATE = "2010-01-01"
END_DATE = "2026-01-01"

rng = np.random.default_rng(SEED)

# --- 1. Data Fetching ---
stock_prices = yf.download(STOCKS, start=START_DATE, end=END_DATE, auto_adjust=True)["Close"]

# Reorder columns to match STOCKS order
stock_prices = stock_prices[STOCKS]

# Log returns, with NaNs (first row + any gaps) dropped
log_returns = np.log(stock_prices / stock_prices.shift(1)).dropna()

if log_returns.empty:
    msg = "No valid return data after dropna() - check tickers/date range."
    raise ValueError(msg)

# --- 2. Portfolio statistics ---
num_stocks = len(STOCKS)
mean_returns = log_returns.mean().values * NUM_TRADING_DAYS  # (k,)
cov_matrix = (log_returns.cov() * NUM_TRADING_DAYS).values  # (k, k)

# --- 3. Fully vectorized Monte Carlo simulation ---
# Dirichlet gives weights that sum to 1 and are uniformly distributed
# over the simplex (long-only, no-leverage assumption).
portfolio_weights = rng.dirichlet(np.ones(num_stocks), size=NUM_SIMULATIONS)  # (N, k)

portfolio_returns = portfolio_weights @ mean_returns  # (N,)

# w^T Σ w for every simulated portfolio at once
portfolio_variances = np.einsum("ij,jk,ik->i", portfolio_weights, cov_matrix, portfolio_weights)
portfolio_risks = np.sqrt(portfolio_variances)  # (N,)

# Guard against divide-by-zero (won't trigger with correlated equities,
# but cheap insurance if this is ever extended to include a riskless asset)
safe_risks = np.where(portfolio_risks == 0, np.nan, portfolio_risks)
sharpe_ratios = (portfolio_returns - RISK_FREE_RATE_LOG) / safe_risks

# --- 4. Identify key portfolios ---
max_sharpe_idx = np.nanargmax(sharpe_ratios)
min_risk_idx = np.argmin(portfolio_risks)

print(f"Maximum Sharpe Ratio = {sharpe_ratios[max_sharpe_idx]:.4f}")
print("Weights (Max Sharpe Portfolio):")
for i, stock in enumerate(STOCKS):
    print(f"  {stock:15s}: {portfolio_weights[max_sharpe_idx][i]:.4f}")

print(f"\nMinimum Risk = {portfolio_risks[min_risk_idx]:.4f}")
print(f"Corresponding Return = {portfolio_returns[min_risk_idx]:.4f}")
print("Weights (Min Risk Portfolio):")
for i, stock in enumerate(STOCKS):
    print(f"  {stock:15s}: {portfolio_weights[min_risk_idx][i]:.4f}")

# --- 5. Plotting ---
plt.figure(figsize=(12, 8))
plt.scatter(portfolio_risks, portfolio_returns, c=sharpe_ratios, cmap="viridis", marker="o", s=10, alpha=0.3)
plt.colorbar(label="Sharpe Ratio")
plt.xlabel("Expected Risk")
plt.ylabel("Expected Return")

plt.plot(portfolio_risks[max_sharpe_idx], portfolio_returns[max_sharpe_idx], "r*", markersize=15.0, label="Max Sharpe")
plt.plot(portfolio_risks[min_risk_idx], portfolio_returns[min_risk_idx], "g*", markersize=15.0, label="Min Risk")
plt.title("Efficient Frontier - Monte Carlo Simulation")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()
