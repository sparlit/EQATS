# Integration Blueprint: portfolio-monte-carlo → eqats

## Overview
The `portfolio-monte-carlo` repository provides a Monte Carlo‑based efficient frontier calculator for a basket of NSE stocks. Its core value lies in the risk‑return simulation engine and the extraction of optimal portfolios (max Sharpe, min risk). These capabilities can be plugged into the **Risk Engineering** domain of eqats to enhance portfolio construction and risk analytics.

## Data Engines
- **Historical price ingestion** – The script fetches daily OHLCV data for a list of NSE tickers (e.g., using `yfinance`). This can replace or supplement eqats’ existing market‑data adapters.
- **Data storage & preprocessing** – Prices are stored in pandas DataFrames, log‑returns are computed, and the annualized covariance matrix is derived. eqats can reuse this preprocessing pipeline to feed its risk models.
- **Cache mechanism** – Although not explicit, adding a local CSV/Parquet cache would align with eqats’ data‑engine best practices.

## Signal & Execution Logic
- **No relevant features** – The repository does not generate trading signals, position‑sizing rules, or order‑execution logic. Integration would therefore focus solely on risk‑analytics; any signal generation would need to be added separately in eqats’ `signal_execution` layer.

## Risk Engineering
- **Monte Carlo simulation** – Generates N random weight vectors, computes portfolio expected return and volatility, and stores results for analysis. eqats can adopt this simulation as a flexible scenario‑analysis tool alongside its existing optimizers.
- **Efficient frontier extraction** – By identifying the upper‑left envelope of the simulated cloud, the code provides a non‑parametric frontier that can be visualized or used for constraint‑based optimization.
- **Sharpe‑ratio based selection** – The max‑Sharpe portfolio is highlighted; eqats can use this as a default risk‑adjusted objective when no user‑specified utility function is provided.
- **Minimum‑risk portfolio** – The lowest‑volatility point on the frontier offers a conservative baseline for risk‑limits or capital‑allocation rules.
- **Output artifacts** – The script returns weights, expected return, volatility, and Sharpe ratio for both optimal portfolios, which map directly onto eqats’ risk‑engineering output schema (e.g., `PortfolioMetrics`).

## Integration Steps
1. **Wrap the simulation** – Create a new eqats service `MonteCarloEfficientFrontier` that accepts:
   - List of tickers (NSE)
   - Look‑back period
   - Number of simulations (default 100k)
   - Risk‑free rate (for Sharpe)
2. **Reuse data‑engine** – Call eqats’ existing market‑data adapter to pull price data; feed it into the wrapper’s preprocessing logic (returns, covariance).
3. **Run simulation** – Generate random weights (Dirichlet distribution), compute portfolio metrics, track max Sharpe and min volatility.
4. **Return results** – Output a JSON object containing:
   - `max_sharpe`: {weights, expected_return, volatility, sharpe}
   - `min_risk`: {weights, expected_return, volatility}
   - `simulation_summary`: (e.g., number of portfolios, frontier points)
5. **Hook into eqats** – Register the service as a risk‑engineering plugin; allow strategies to request an optimal portfolio for rebalancing or to use the frontier as a constraint in higher‑order optimizers.
6. **Visualization** – Optionally expose the frontier plot via eqats’ dashboard (matplotlib → base64 or saved image) for monitoring.

## Benefits
- Adds a lightweight, simulation‑based alternative to quadratic‑programming optimizers.
- Provides model‑free efficient frontier that captures non‑linearities and fat‑tails inherent in empirical returns.
- Enhances eqats’ risk‑engineering toolkit with clear, interpretable outputs (max Sharpe, min risk) that can drive alerts, position‑sizing, or capital‑allocation policies.

## Considerations
- Ensure the random‑weight generation respects any user‑defined constraints (sector caps, long‑only, etc.) – can be added by rejecting or reshaping samples.
- Performance: 100k simulations is trivial; increase for higher resolution or decrease for real‑time use.
- Extend to include transaction costs or factor models if needed.
