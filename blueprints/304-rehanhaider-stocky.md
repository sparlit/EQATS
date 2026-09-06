# Integration Blueprint for stocky into eqats

## Overview
stocky builds a SQLite DB mapping ISIN to symbols for BSE, NSE, Zerodha, Yahoo. It ingests bhavcopy CSV/ZIP, Zerodha instruments CSV, and Yahoo JSON cache.

## Value to eqats
- Instrument master enrichment via ISIN‑to‑symbol mapping.
- Unified symbol namespace: strategies can query by ISIN, BSE scrip, NSE symbol, Zerodha token, or Yahoo ticker.
- Automated Yahoo cache updates for reference data.
- Reusable ingestion pipeline as a template for other market data feeds.

## Integration Steps
1. Add stocky as a dependency in eqats’ pyproject.toml.
2. Place latest BSE Bhavcopy, NSE UDiFF CSV/ZIP, and Zerodha instruments CSV in eqats’ data/raw/ folder.
3. Run:
   uv run stocky rebuild --latest \
     --bse-bhavcopy data/raw/marketData/bhavCopies/<latest_bse> \
     --nse-bhavcopy data/raw/marketData/bhavCopies/<latest_nse> \
     --zerodha-instruments data/raw/zerodha/instruments.csv
   This creates data/output/stocky.db; attach it to eqats’ instrument service.
4. Wrap stocky’s lookup functions in eqats’ InstrumentService to resolve symbols.
5. Schedule `uv run stocky yahoo update --exchange NSE` and `--exchange BSE` to keep Yahoo cache fresh.
6. Include `stocky status` in observability dashboards.
7. Add tests using stocky’s sample fixtures and incorporate the DB build into CI.

## Expected Outcome
- Single source of truth for ISIN‑centric instrument data across Indian exchanges and Yahoo.
- Less custom mapping code in strategies and execution.
- Improved data quality via versioned SQLite and automated refresh.
