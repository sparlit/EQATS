# Integration Blueprint: nse-oi-analysis → eqats

## Overview
The `nse-oi-analysis` repository provides a lightweight Python pipeline that:
1. Pulls real‑time option chain data from NSE’s public API.
2. Computes the sum of open‑interest (OI) change for near‑ATM call and put strikes.
3. Derives a directional bias (bullish/bearish) based on which side shows larger OI change.
4. Writes the results to a Google Sheet (or CSV).

This core logic maps cleanly onto the **Data Engines** and **Signal & Execution Logic** domains of eqats, while the **Risk Engineering** domain would need to be supplemented.

---

## 1. Data Engine Integration

### Feature Mapping
| nse-oi-analysis Feature | eqats Data Engine Role |
|-------------------------|------------------------|
| `fetch_option_chain()` – HTTP GET to NSE endpoint | Market data ingestion (real‑time option chain) |
| JSON parsing & strike filtering | Normalisation & symbol mapping (NSE → eqats internal IDs) |
| OI change aggregation per call/put bucket | Feature engineering: compute `call_oi_delta_sum`, `put_oi_delta_sum` |
| Write to Google Sheets / CSV | Persistent storage layer (optional) – can be replaced by eqats timeseries DB (e.g., InfluxDB, Timescale) |

### Integration Steps
1. **Wrap the fetch logic** in an eqats-compatible data‑plugin (e.g., `nse_oi_feed.py`) that implements the `MarketDataFeed` interface.
2. **Return a structured payload** such as:
   ```json
   {
     "timestamp": "2025-08-27T10:15:00Z",
     "symbol": "NIFTY",
     "call_oi_delta_sum": 125000,
     "put_oi_delta_sum":  98000,
     "oi_delta_diff": 27000
   }
   ```
3. **Store the payload** in eqats’ timeseries store (via the existing `DataWriter` abstraction) instead of, or in addition to, Google Sheets.
4. **Schedule** the feed to run at the desired frequency (e.g., every 30 seconds during market hours) using eqats’ execution scheduler.

---

## 2. Signal & Execution Logic Integration

### Feature Mapping
| nse-oi-analysis Logic | eqats Signal Role |
|-----------------------|-------------------|
| Compare `call_oi_delta_sum` vs `put_oi_delta_sum` | Generate a directional signal (bullish/bearish) |
| Apply a threshold to avoid noise | Configurable signal‑strength filter |
| Output bias (e.g., "Bullish" / "Bearish") | Emit a signal object consumable by strategy modules |

### Integration Steps
1. **Create a signal generator** (`nse_oi_signal.py`) that subscribes to the OI feed.
2. **Implement the signal rule**:
   ```python
   def generate_signal(oi_data):
       diff = oi_data['call_oi_delta_sum'] - oi_data['put_oi_delta_sum']
       if diff > THRESHOLD_BULL:   # put > call -> bullish
           return {"signal": "BULLISH", "strength": abs(diff)}
       elif diff < -THRESHOLD_BEAR: # call > put -> bearish
           return {"signal": "BEARISH", "strength": abs(diff)}
       else:
           return {"signal": "NEUTRAL", "strength": 0}
   ```
3. **Publish the signal** to eqats’ signal bus (e.g., via Redis Pub/Sub or internal event queue) under a topic like `nse.oi.signal.NIFTY`.
4. **Strategy consumption**: Existing eqats strategies can subscribe to this topic and combine the OI signal with other inputs (price action, volatility, etc.) to produce final trade ideas.
5. **Backtesting**: Re‑use the historical OI CSV dumps (if available) to replay the signal generation within eqats’ backtesting harness.

---

## 3. Risk Engineering Considerations

The source repo does **not** contain any risk‑management logic (position sizing, stop‑loss, exposure limits, margin checks). To integrate safely into eqats:

- **Position Sizing**: Use eqats’ `RiskManager` to convert the OI signal strength into a target notional based on account equity and volatility.
- **Stop‑Loss / Targets**: Define ATR‑ or volatility‑based exits; the OI signal alone does not provide price levels.
- **Exposure Limits**: Enforce max gross/net exposure per underlying (NIFTY, BANKNIFTY) and per sector.
- **Monitoring**: Feed the OI signal and resulting positions into eqats’ real‑time risk dashboard for anomaly detection (e.g., sudden OI spikes).
- **Validation**: Add pre‑trade checks that ensure the signal is not stale (timestamp validation) and that the underlying is liquid enough for the intended trade size.

These components would be added as a thin wrapper around the signal generator, adhering to eqats’ risk‑engineering interfaces.

---

## 4. End‑to‑End Example Flow

1. **Market Data Feed** (`nse_oi_feed`) pulls option chain every 20 s.
2. **Feature Engine** computes call/put OI deltas and writes to timeseries DB.
3. **Signal Generator** reads the latest OI delta, applies threshold, emits `BULLISH`/`BEARISH`/`NEUTRAL`.
4. **Risk Manager** receives signal, calculates target position size, checks limits, and emits an order intent.
5. **Execution Adapter** sends orders to the broker via eqats’ execution gateway.
6. **Monitoring** logs OI values, signal, and order outcomes for post‑trade analysis.

---

## 5. Implementation Checklist

- [ ] Create `nse_oi_feed.py` implementing `MarketDataFeed`.
- [ ] Create `nse_oi_signal.py` implementing `SignalGenerator`.
- [ ] Wire feed → signal → risk manager in eqats’ `strategy_runner.yaml`.
- [ ] Define configurable parameters: OI threshold, feed frequency, symbols (NIFTY, BANKNIFTY).
- [ ] Add unit tests using historical JSON snapshots.
- [ ] Document the new plugin in eqats’ `plugins/` directory.
- [ ] Deploy to staging, validate signal latency (< 1 s) and data integrity.

---

## Conclusion
By extracting the data‑ingestion and OI‑based signal generation components from `nse-oi-analysis` and plugging them into eqats’ modular architecture, we gain a real‑time, alternative‑data signal that captures institutional positioning via open‑interest flows. The only missing piece—risk controls—can be supplied by eqats’ existing risk‑engineering framework, resulting in a robust, production‑ready integration.
