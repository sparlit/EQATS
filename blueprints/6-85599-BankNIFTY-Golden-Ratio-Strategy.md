# Integration Blueprint for BankNIFTY Golden Ratio Strategy into eqats

## Overview
The BankNIFTY Golden Ratio Strategy is a simple intraday mean‑reversion / breakout system that uses the prior day’s range and the first 10‑minute opening range to compute a ‘Golden Number’. Longs are taken when price exceeds the prior close plus this number; shorts when price falls below the prior close minus the number. A fixed 0.5 % stop‑loss and 2 % target are applied.

## Data Engines
- **Historical OHLC ingestion**: Pull previous day’s high, low, and close for BANKNIFTY futures from the eqats market‑data feed.
- **Intraday opening‑range capture**: Subscribe to live tick or 1‑minute bars and aggregate the first 10 minutes of the trading session to obtain the opening‑range high‑low.
- **Golden Number calculation**: Implement a pure‑Python function `golden_number(prev_high, prev_low, open_range) = ((prev_high - prev_low) + open_range) * 0.618`.
- **Storage**: Cache the prior‑day values and the opening‑range value for the current session; reset at each new trading day.

## Signal & Execution Logic
- **Signal generation**:
  - Long signal: `price > prev_close + golden_number`
  - Short signal: `price < prev_close - golden_number`
- **Signal validation**: Ensure the signal occurs after the opening range is complete (i.e., after 10 min) to avoid look‑ahead bias.
- **Order routing**: Use eqats’ broker‑adapter layer to send market orders to any of the supported brokers (Zerodha, Upstox, Alice Blue, SAS Online, 5paisa, IIFL, Interactive Brokers, Fyers). The adapter already exists for these APIs; the strategy only needs to emit an `OrderIntent` with `side`, `quantity`, and `order_type='MARKET'`.
- **Execution handling**: On fill, record the entry price and attach the pre‑defined stop‑loss and target levels.

## Risk Engineering
- **Static risk levels**: For a long entry at price `E`, set stop‑loss = `E * (1 - 0.005)` and target = `E * (1 + 0.02)`. For a short, invert the percentages.
- **Position sizing**: Since the original repo does not specify sizing, integrate with eqats’ risk‑engine module to compute size based on a fixed fractional equity risk (e.g., 1 % of equity per trade) using the stop‑loss distance.
- **Monitoring**: Leverage eqats’ real‑time risk monitor to automatically cancel the opposite order and exit when either stop‑loss or target is hit.
- **Logging**: Emit strategy‑specific metrics (signal frequency, win‑rate, average P&L) to eqats’ telemetry.

## Implementation Steps
1. **Create a new strategy module** `eqats/strategies/banknifty_golden_ratio.py` that inherits from `eqats.strategy.base.Strategy`.
2. **Implement `on_start`** to subscribe to previous‑day BANKNIFTY futures bar data and to a 1‑minute bar stream for the opening range.
3. **In `on_bar`** (1‑minute), after the first 10 bars, compute the opening range and store it.
4. **Each tick (or 1‑minute bar)** evaluate the long/short conditions using the cached values.
5. **When a condition fires**, call `self.submit_order(side, qty, order_type='MARKET')` via the broker adapter.
6. **Attach OCO order** (stop‑loss + target) using eqats’ order‑management system, or submit two separate stop‑limit orders.
7. **Reset** all stored values at the start of each new trading day.
8. **Unit test** the golden‑number calculation and signal logic with historical data.
9. **Run a paper‑trading simulation** in eqats’ back‑tester to validate performance before live deployment.

## Considerations
- The strategy is described as “bad but popular”; expect modest Sharpe and possible drawdowns. Use proper position sizing and max‑daily‑loss limits.
- Ensure data alignment: the prior day’s close must be from the futures contract’s settlement price, not the spot index.
- The 0.5 % stop‑loss and 2 % target are tight; slippage may affect realized results—consider using limit orders with a small tolerance.
- The strategy can be extended with volatility‑based scaling of the golden number or adaptive stop‑loss.

## Conclusion
By mapping the BankNIFTY Golden Ratio Strategy’s three core components—data ingestion, signal generation, and static risk controls—onto eqats’ Data Engines, Signal & Execution Logic, and Risk Engineering layers, the strategy can be rapidly prototyped, back‑tested, and deployed across any of the supported brokers with minimal custom code.