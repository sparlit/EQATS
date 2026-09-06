# Integration Blueprint for eqats

## Overview
The alice‑blue‑options‑buying repo provides a ready‑to‑run options buying algorithm for Nifty and BankNifty using the SuperTrend indicator, optional RSI filters, and bracket‑order execution via the Alice Blue API. Its core strengths lie in a configurable realtime data engine, a clear signal‑execution flow, and explicit risk controls that can be mapped onto the eqats architecture.

## Data Engines Integration
- **Realtime tick loop**: Replace the existing `while True` tick processing with eqats’ `MarketDataEngine` subscription model. The configurable `tick_processing_sleep_secs` can be exposed as a strategy‑level polling interval.
- **OHLC candles**: Implement a candle builder that aggregates ticks into user‑defined periods (default 3 min) and feeds the SuperTrend calculation. This mirrors eqats’ `FeatureStore` for rolling windows.
- **CSV export**: Hook the `export_data` flag into eqats’ `DataLogger` to persist raw ticks or derived features for offline analysis.
- **Data toggles**: Map `enable_nfo_data` / `enable_bank_data` to eqats’ asset‑specific subscription switches, allowing selective market‑data feeds.
- **Symbol files**: Use `file_nifty` and `file_bank` as plain‑text lists of option symbols; eqats can load these at startup and feed them to the symbol resolver.
- **Configuration**: Migrate the `.ini` sections into eqats’ YAML/JSON config schema, preserving credential groups (`[tokens]`) and runtime‑adjustable sections (`[realtime]`).

## Signal & Execution Logic Integration
- **SuperTrend signal**: Plug the SuperTrend calculation (already present) into eqats’ `SignalGenerator` interface. The signal can be combined with eqats’ existing signal‑fusion framework.
- **RSI filters**: Expose `use_rsi`, `use_rsi_roc`, `rsi_period`, `rsi_buy_param`, `rsi_sell_param` as strategy parameters; eqats can apply them as pre‑trade gating logic.
- **Bracket orders**: Translate the three‑leg BO logic into eqats’ `OrderExecutor` using the `BracketOrder` wrapper. Quantities (`nifty_bo1_qty`, etc.) map to lot‑size‑scaled order quantities.
- **Price & strike offsets**: The limit price offsets (`nifty_limit_price_offset`, `bank_limit_price_offset`) and strike offsets (`*_strike_ce_offset`, `*_strike_pe_offset`) become parameters that adjust the entry price and option selection logic.
- **Profit targets & trailing SL**: Map `nifty_tgt1‑3`, `bank_tgt1‑3`, `nifty_tsl`, `bank_tsl` to eqats’ profit‑target and trailing‑stop modules, enabling multi‑target exit strategies.
- **Time‑based controls**: Use `nifty_trade_start_time`, `nifty_trade_end_time`, `nifty_no_trade_zones` to drive eqats’ `TradingSession` filter; similar for BankNifty.
- **Order type**: The `ord_type` flag (BO/MIS) selects between eqats’ bracket‑order and intraday‑margin order types.

## Risk Engineering Integration
- **Stop‑loss points**: The fixed SL values (`nifty_sl`, `bank_sl`) become per‑symbol risk parameters feeding eqats’ `StopLoss` module.
- **MTM limits**: `mtm_sl` (max daily loss) and `mtm_target` (daily profit goal) map to eqats’ `DailyPnLGuard` that can halt trading when breached.
- **Trade count limit**: `no_of_trades_limit` implements a max‑trade‑per‑day rule in eqats’ `TradeCounter`.
- **Order timeout**: `sl_wait_time` and `pending_ord_limit_mins` translate to eqats’ `OrderTimeout` and `PendingOrderMonitor` to cancel stale limit orders.
- **Lot size enforcement**: Use `nifty_lot_size` and `bank_lot_size` to round order quantities to the nearest lot, matching eqats’ lot‑size validator.
- **Background process**: The `enable_bg_process` flag can be mirrored by eqats’ runtime‑config service, allowing parameters to be updated via a control channel (e.g., Telegram or REST) without restarting the strategy.

## Implementation Steps
1. **Create a new strategy module** `eqats/strategies/alice_blue_options.py` that inherits from `eqats.strategy.BaseStrategy`.
2. **Define configuration schema** replicating the `.ini` groups; load via eqats’ config manager.
3. **Initialize market data subscriptions** for NIFTY and BANKNIFTY futures/options, using the tick‑loop sleep as the polling interval.
4. **Build OHLC candles** (3 min) and compute SuperTrend; optionally compute RSI and ROC.
5. **Generate entry signal** when SuperTrend crosses and RSI conditions are satisfied.
6. **Select ATM strike** using the configured offsets, then place a bracket order with up to three legs, respecting lot sizes and quantities.
7. **Attach profit targets and trailing stop** as per the targets/TSL values.
8. **Activate risk guards**: daily MTM limits, max trades, order timeouts, and lot‑size checks.
9. **Wire optional CSV export** and Telegram logging via eqats’ notification adapters.
10. **Run the strategy** within eqats’ live‑trading container, ensuring the background‑process flag enables dynamic re‑load of parameters.

By following this blueprint, eqats can quickly incorporate a proven, configurable options‑buying algorithm while benefiting from its unified data, execution, and risk layers.