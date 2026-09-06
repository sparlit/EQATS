# Integration Blueprint for nseindia_lob into eqats

## Overview
The `nseindia_lob` repository provides a high‑performance limit order book (LOB) simulator for the National Stock Exchange of India. It is written in Python with critical paths compiled via Cython, using red‑black trees and queues to maintain bid/ask levels. The simulator consumes gzipped CSV order‑flow files, processes adds, modifications, cancellations, and supports market, limit, IOC, and hidden orders. Daily statistics are accumulated and reset at date boundaries.

## Mapping to eqats Domains

### Data Engines
- **Ingestion**: Robust CSV/gzip parser that extracts fields such as timestamp, price, volume, order type, and flags. Can be reused to ingest historical NSE order‑flow or adapted for other exchanges.
- **Storage / Internal Representation**: Order book maintained as two red‑black trees (buy/sell) of price‑level queues. This provides O(log N) best‑price lookup and efficient insertion/deletion—ideal for eqats’ market‑data engine needing low‑latency book reconstruction.
- **Market Data Simulation**: Ability to replay historical order streams and generate a consistent LOB snapshot at any point, useful for back‑testing and generating synthetic market data feeds.

### Signal & Execution Logic
- **Matching Engine Core**: Implements price‑time priority with special handling for disclosed (hidden) volume and IOC orders. This logic can be wrapped as an execution simulator within eqats to test strategy order submission against a realistic LOB.
- **Order Type Support**: Market, limit, stop‑loss, and IOC orders are processed, enabling eqats to evaluate slippage, fill rates, and order‑book interaction for various algos.
- **Order Life‑Cycle Management**: Handles add, modify, and cancel messages, allowing eqats to simulate order‑management systems and test cancellation/re‑submission logic.
- **Daily Statistics**: Accumulates traded volume, VWAP, and other metrics per day; can be hooked into eqats’ signal generation to trigger intraday adjustments.

### Risk Engineering
- **Daily Stats Reset**: Automatic reset at date change provides a natural bucket for daily risk limits (e.g., max notional, max loss). eqats can attach risk‑monitoring hooks to these resets.
- **Exposure Tracking**: By monitoring cumulative volume and value of executed orders, the simulator can feed real‑time exposure metrics to eqats’ risk engine.
- **Limitations**: The repository does not contain explicit risk‑limit enforcement or position‑sizing logic; these would need to be added in eqats.

## Integration Steps
1. **Wrap the LOB Core** – Extract the Cython‑compiled order‑book module (`LOB` class) and expose a Pythonic API (e.g., `add_order`, `cancel_order`, `match`) that eqats can call from its execution engine.
2. **Adapt the CSV Parser** – Replace the hard‑coded NSE column mapping with a configurable schema so eqats can ingest order‑flow from multiple sources (e.g., Kafka, flat files).
3. **Event‑Driven Hook** – Emit events on each trade, order book update, and daily roll‑over; connect these to eqats’ event bus for signal generation and risk monitoring.
4. **Performance Tuning** – Leverage the existing Cython build (`setup.py build_ext --inplace`) to maintain low latency; consider further optimizing hot paths with Numba or additional Cython typing.
5. **Testing & Validation** – Use the provided `EXAMPLE-orders.csv` to run a baseline simulation, compare outputs with eqats’ internal back‑tester, and iteratively refine the integration.

## Expected Benefits
- **Realistic Market Impact**: Accurate LOB reconstruction improves slippage and fill‑rate estimates for strategy research.
- **Low‑Latency Back‑Testing**: Cython acceleration enables processing of millions of orders per second, suitable for high‑frequency strategy evaluation.
- **Extensible Framework**: Clear separation of ingestion, matching, and stats makes it straightforward to plug in custom risk limits, position sizing, or alternative execution algorithms.

## Caveats
- The code targets Python 2.7; migration to Python 3 may be required for eqats’ modern stack.
- Dependencies on older packages (`odict`, `rbtree`) might need replacement with maintained alternatives (e.g., `collections.OrderedDict`, `bintrees` or `sortedcontainers`).
- The simulator assumes a single futures expiration date; eqats may need to adjust this filter for multi‑product simulations.
