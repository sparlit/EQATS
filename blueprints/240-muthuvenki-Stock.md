# Integration Blueprint for muthuvenki/Stock into eqats

## Overview
The repository provides a simple PHP‑CodeIgniter portfolio manager for BSE/NSE stocks. Its core strengths are:
- User management (multiple accounts)
- Easy add/update/delete of stock positions
- Automatic portfolio valuation using live prices from Quandl
- Local MySQL storage ensuring data privacy

These capabilities map closely to eqats’ Data Engines and Risk Engineering layers, while the project lacks any signal‑generation or order‑execution logic.

## Data Engines Integration
| Feature | Description | How to integrate into eqats |
|---|---|---|
| Quandl price feed | Developer key stored in report_view.php; API called to get latest BSE/NSE prices. | Replace the hard‑coded Quandl call with eqats’ market‑data abstraction layer. Use eqats’ DataIngestor interface to fetch tick‑by‑tick or daily bars for NSE/BSE symbols, caching results in eqats’ time‑series store (e.g., PostgreSQL/TimescaleDB). |
| MySQL portfolio schema | Tables for users, holdings, transactions. | Map the existing schema to eqats’ portfolio domain model (users → eqats Account, holdings → Position). Leverage eqats’ migration tooling to version‑control the schema. |
| Local‑only deployment | Designed to run on a personal machine. | eqats already supports Docker‑based local dev; the Stock app can be containerized and run as a side‑car service that feeds position data into eqats’ risk engine via a REST endpoint or message queue (e.g., RabbitMQ). |

## Signal & Execution Logic
The Stock repository does not contain any signal generation, strategy back‑testing, or order‑execution components. Consequently, there are no direct features to plug into eqats’ signal_execution layer. If desired, the portfolio holdings exported from this app could serve as input for external strategy modules, but no native integration point exists.

## Risk Engineering Integration
| Feature | Description | How to integrate into eqats |
|---|---|---|
| Current assets calculation | On‑the‑fly sum of (quantity × latest price) for each holding, displayed as portfolio value. | Replace the ad‑hoc calculation with eqats’ RiskEngine service. Expose holdings via an API; the Risk Engine computes market‑value, gross exposure, net exposure, and can apply user‑defined limits (e.g., max sector concentration). The existing view can be refactored to consume eqats’ risk‑metrics endpoint. |
| User‑level data isolation | Separate MySQL tables per user via login. | eqats already provides multi‑tenant authentication (OAuth2/JWT). Map the Stock login to eqats’ identity provider; user‑specific positions are retrieved from eqats’ secure store. |

## Implementation Steps
1. Containerize the PHP‑CodeIgniter app (Dockerfile using php:7.4-apache).
2. Expose a REST endpoint /api/positions that returns JSON of the authenticated user’s holdings.
3. Register the endpoint as a data source in eqats’ DataIngestor configuration (polling interval e.g., 5 min).
4. Map incoming positions to eqats’ Position objects (symbol, quantity, avg_price).
5. Route the positions to eqats’ RiskEngine to compute real‑time market value and risk metrics.
6. Display eqats‑generated risk metrics in the Stock UI by replacing the local calculation with an AJAX call to eqats’ /risk/metrics endpoint.
7. Optional: Add eqats’ order‑execution adapter if future work wants to turn the portfolio tracker into a live trading system.

## Conclusion
While the Stock repo offers valuable data‑engine and risk‑monitoring pieces, it lacks any signal or execution logic. Integrating its portfolio‑management front‑end with eqats’ robust data‑ingestion, storage, and risk‑engine services yields a secure, locally‑hosted portfolio tracker that can later be extended to full‑featured quantitative trading.
