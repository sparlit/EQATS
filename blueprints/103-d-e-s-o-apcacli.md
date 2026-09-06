# Integration Blueprint for apcacli into eqats

## Overview
apcacli is a Rust‑based command‑line interface for the Alpaca API that provides direct access to account data, market data, order management, and event streaming. These capabilities can be wrapped as reusable services within the eqats quantitative trading platform.

## Data Engines
- **Account & Activity Queries** – `apcacli account`, `apcacli activity` map to eqats’ data‑engine layer for ingesting cash balances, buying power, and historical fills.
- **Market Clock & Asset Info** – `apcacli clock` and `apcacli asset` supply timing and symbol metadata needed for market‑data synchronization.
- **Position & P&L Listing** – `apcacli position list` provides real‑time exposure and profit‑loss figures, suitable for feeding a risk‑monitoring store.
- **Streaming** – The tool’s streaming mode can be adapted to push live account and trade events into eqats’ event bus (e.g., via a WebSocket adapter).

## Signal & Execution Logic
- **Order Submission** – Commands like `apcacli order submit buy SYMBOL --value 1000 --limit-price 200` map directly to eqats’ order‑execution interface, supporting market, limit, stop, and trailing‑stop types.
- **Order Management** – `apcacli order get`, `apcacli order list`, `apcacli order update`, and `apcacli order cancel` enable eqats to monitor, amend, or cancel live orders.
- **Shell Completion** – While not a core trading feature, the completion mechanism illustrates how eqats could expose CLI‑style helpers for strategy developers.

## Risk Engineering
- **Exposure Reporting** – The position table with average entry, today P/L, and total P/L gives eqats a ready‑made risk snapshot for limit checks.
- **Account Configuration** – Commands to view/modify account settings (e.g., `apcacli account`) can be used to enforce or verify risk‑related parameters such as margin limits or pattern‑day‑trader flags.
- **Note** – apcacli does not embed automated position‑sizing or max‑loss rules; eqats would need to add those logic layers on top of the data provided.

## Example Integration Sketch
1. **Data Engine Adapter** – A Rust service shells out to `apcacli account --format json` (or uses the underlying `apca` crate) to populate eqats’ account store every few seconds.
2. **Execution Adapter** – When eqats’ signal generator emits an order intent, it calls the same `apca` crate functions that apcacli uses, passing the appropriate parameters (side, quantity, type, price, time‑in‑force).
3. **Risk Monitor** – A periodic job runs `apcacli position list` and parses the output to compute gross/net exposure, then compares against eqats’ risk limits, issuing alerts or auto‑reducing positions if needed.
4. **Event Streaming** – By invoking apcacli’s streaming mode and forwarding received WebSocket messages to eqats’ internal event bus, strategies can react to fills, cancellations, or margin changes in near‑real time.

## Considerations
- **Authentication** – Both apcacli and eqats must share the same `APCA_API_KEY_ID`/`APCA_API_SECRET_KEY` environment variables; consider a shared secrets manager.
- **Paper vs Live** – The default points to Alpaca paper; switching to live requires setting `APCA_API_BASE_URL`, a flag that eqats should propagate uniformly.
- **Error Handling** – Map Alpaca HTTP error codes to eqats’ retry/backoff policies.
- **Performance** – For high‑frequency use, bypass the CLI and call the `apca` crate directly to avoid process‑overhead.
