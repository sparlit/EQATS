# nselib Integration Blueprint for eqats

## Overview
nselib is a Python library that provides programmatic access to publicly available data from the National Stock Exchange of India (NSE). It offers a wide range of market data endpoints covering capital markets, derivatives, indices, debt, corporate filings, market activity, and utilities.

## Data Engine Integration
- **Market Data Ingestion**: Use functions such as `price_volume_data`, `price_volume_and_deliverable_position_data`, `deliverable_position_data`, `bulk_deal_data`, `block_deals_data`, `short_selling_data`, various bhav copy functions, and equity list helpers to pull historical and intraday OHLCV, delivery, and trade‑by‑trade information.
- **Reference Data**: Retrieve constituent lists for Nifty 50, Nifty Next 50, Nifty Midcap 150, Nifty Smallcap 250, F&O equity and index lists via `nifty50_equity_list`, `fno_equity_list`, etc.
- **Index & Volatility Data**: Pull index OHLC history with `index_data` and real‑time snapshots via `market_watch_all_indices`. Obtain India VIX historical series through `india_vix_data`.
- **Corporate Filings & Activity**: Access financial results, corporate actions, event calendars, FII/DII trading activity, and market‑wide gainers/losers to enrich fundamental datasets.
- **Utilities**: Leverage the trading holiday calendar for schedule alignment.

All functions return pandas DataFrames, making them directly consumable by eqats’ data pipelines (e.g., feeding into a feature store or a time‑series database).

## Signal & Execution Logic
nselib does not generate trading signals or execute orders. Its role is strictly to supply clean, timely market data. eqats can combine the fetched data with internal signal‑generation modules (e.g., momentum, mean‑reversion, arbitrage) and then route signals to its execution engine.

## Risk Engineering Integration
- **Value‑at‑Risk (VaR)**: Use the suite of VaR functions (`var_begin_day`, `var_1st_intra_day`, `var_2nd_intra_day`, `var_3rd_intra_day`, `var_4th_intra_day`, `var_end_of_day`) to obtain NSE‑provided VaR estimates for equities and indices, which can be incorporated into eqats’ risk limits and position‑sizing logic.
- **Volatility Metrics**: Retrieve daily volatility reports via `daily_volatility` and the India VIX index via `india_vix_data` to monitor market‑wide risk and adjust exposure dynamically.
- **Margin & Delivery Data**: Deliverable position and bhav‑copy‑with‑delivery files give insight into settlement risk and can be used to flag high‑delivery‑percentage stocks.

## Example Usage (Python)
```python
import pandas as pd
from nselib import capital_market, indices

# 1. Pull price‑volume data for a stock
df_price = capital_market.price_volume_data(symbol='RELIANCE', period='3M')

# 2. Get latest Nifty 50 constituents for universe construction
nifty50 = capital_market.nifty50_equity_list()

# 3. Fetch VaR for risk monitoring
var_df = capital_market.var_end_of_day(trade_date='25-09-2025')

# 4. Obtain India VIX for volatility scaling
vix = capital_market.india_vix_data(period='1M')
```

## Deployment Considerations
- **Rate Limits**: nselib relies on public NSE endpoints; implement caching or a request‑throttling layer to avoid being blocked.
- **Data Freshness**: For intraday strategies, pair nselib’s end‑of‑day bhav copies with real‑time websockets or exchange‑provided feeds.
- **Dependency Management**: Add `nselib` and `pandas` to eqats’ `requirements.txt` or `environment.yml`.
- **Testing**: Mock the library’s responses in unit tests to isolate signal and risk modules.

By treating nselib as the dedicated Indian‑market data engine, eqats can rapidly expand its coverage to NSE securities while keeping signal generation and risk management layers independent and interchangeable.
