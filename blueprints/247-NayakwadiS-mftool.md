# Integration Blueprint: mftool → eqats

## Overview
mftool is a Python library that fetches public mutual fund data from the Association of Mutual Funds in India (AMFI). It provides real‑time NAVs, historical NAVs, scheme metadata, and performance metrics. This blueprint outlines how eqats can leverage mftool as a dedicated data engine for Indian mutual funds.

## Data Engine Integration
- **Live Quote Retrieval** – Use `mftool.get_scheme_quote(scheme_code)` to obtain the latest NAV and return it as a pandas DataFrame, JSON, or dict. eqats can wrap this call in a market‑data adapter that normalises the output to the internal `MarketTick` format.
- **Historical NAV Series** – `mftool.get_scheme_historical_nav(scheme_code, as_dataframe=True)` yields a time‑series of NAVs suitable for back‑testing, feature generation, or regime detection.
- **Universe Discovery** – `mftool.get_all_scheme_codes()` and `mftool.get_all_schemes()` provide the complete list of AMFI‑registered schemes with their codes, enabling dynamic universe construction and periodic refresh.
- **Scheme Validation** – Helper `mftool.is_valid_scheme_code(scheme_code)` can be used to guard against bad inputs before requesting data.
- **Daily Performance** – `mftool.get_scheme_daily_performance(scheme_code)` supplies day‑over‑day returns, useful for risk‑adjusted signal calculations.

### Suggested Adapter Sketch (pseudo‑code)
```python
import mftool
import pandas as pd

class MFToolAdapter:
    def fetch_latest(self, scheme_code: str) -> pd.DataFrame:
        if not mftool.is_valid_scheme_code(scheme_code):
            raise ValueError(f'Invalid scheme code: {scheme_code}')
        df = mftool.get_scheme_quote(scheme_code, as_dataframe=True)
        df = df.rename(columns={'nav': 'price', 'date': 'timestamp'})
        df['symbol'] = scheme_code
        return df[['timestamp', 'symbol', 'price']]

    def fetch_history(self, scheme_code: str, start: str, end: str) -> pd.DataFrame:
        df = mftool.get_scheme_historical_nav(scheme_code, as_dataframe=True)
        df = df[(df['date'] >= start) & (df['date'] <= end)]
        df = df.rename(columns={'nav': 'price', 'date': 'timestamp'})
        df['symbol'] = scheme_code
        return df[['timestamp', 'symbol', 'price']]
```

## Signal & Execution Logic
mftool does not generate trading signals or handle order execution. Its role is strictly data provision. Signals can be built on top of the NAV time‑series (e.g., moving‑average crossovers, momentum) using eqats’ existing signal framework.

## Risk Engineering
No direct risk‑limit or position‑sizing features are exposed by mftool. Risk metrics (volatility, drawdown, VaR) should be computed within eqats’ risk engine after ingesting the mutual‑fund data.

## Deployment Considerations
- **Rate Limits** – AMFI endpoints may impose request throttling; implement caching or a request‑queue layer.
- **Data Freshness** – NAVs are updated end‑of‑day; schedule daily ingestion jobs.
- **Dependencies** – Add `mftool>=3.3` to eqats’ `requirements.txt`; optional `pandas` and `requests` are already typical.

## Extensions
- Combine mftool data with equity data from other eqats adapters for hybrid fund‑equity strategies.
- Expose the mftool‑mcp server as a GenAI‑enabled query interface for natural‑language fund lookup within eqats’ research notebooks.

## Conclusion
By integrating mftool as a dedicated mutual‑fund data engine, eqats gains reliable, programmatic access to India’s MF universe, enabling strategy research, back‑testing, and live monitoring of fund‑based portfolios.
