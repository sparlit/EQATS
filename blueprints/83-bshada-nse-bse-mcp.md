# Integration Blueprint for eqats: NSE-BSE MCP Server

## Overview
Provides real-time/historical NSE & BSE data via MCP over Streamable HTTP (TypeScript/Bun).

## Data Engines
- Quotes: nse_equity_quote, bse_quote
- Historical: nse_equity_historical, nse_fno_historical, nse_vix_historical, bse_index_historical, bse_all_indices_by_date
- Derivatives: nse_option_chain, nse_filtered_option_chain, nse_compile_option_chain, nse_calculate_max_pain, nse_fno_lots, nse_futures_expiry
- Corporate/IPO: nse_corporate_actions, nse_corporate_announcements, nse_board_meetings, nse_annual_reports, nse_circulars, nse_current_ipos, nse_upcoming_ipos, nse_past_ipos, nse_ipo_details, bse_corporate_actions, bse_announcements, bse_result_calendar
- Market Activity: nse_block_deals, nse_bulk_deals, nse_holidays, bse_gainers, bse_losers, bse_advance_decline, bse_near_52week
- Lists: nse_list_indices, nse_list_stocks_by_index, nse_list_etf, nse_list_sme, nse_list_sgb, nse_equity_meta_info, bse_fetch_index_names, bse_fetch_index_metadata
- Downloads: nse_download_equity_bhavcopy, nse_download_delivery_bhavcopy, nse_download_indices_bhavcopy, nse_download_fno_bhavcopy, bse_download_bhavcopy, bse_download_delivery
- Docs: download_document, read_document_pages
- Smart limiting: max_items, fields

## Signal & Execution Logic
No native signal/execution; supplies data for eqats’ own modules.

## Risk Engineering
No explicit risk limits; provides max pain, PCR/OI, VIX, corporate actions, bhavcopy for risk calculations.

## Integration Steps
1. Deploy server via Docker or Bun.
2. Configure eqats MCP client to point to http://localhost:3000/mcp.
3. Wrap tools in data‑engine adapters, use max_items/fields.
4. Build signals using quotes, historical, option analytics.
5. Compute risk using corporate actions, bhavcopy, VIX, option metrics.
6. Use download_document for IPO prospectus NLP.
7. Monitor health endpoint, enable CORS if eqats runs a web‑based dashboard.

## Benefits
Unified endpoint, scalable stateless transport, efficient smart limiting, extensible.

## Considerations
Data‑only server; eqats must add signal/execution/risk logic; respect exchange terms; watch rate limits.

## Conclusion
MCP server gives eqats ready‑to‑use Indian market data engine, letting focus on strategy and risk.