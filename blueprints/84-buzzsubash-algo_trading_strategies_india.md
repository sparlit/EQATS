# Integration Blueprint for eqats

## Overview
The `buzzsubash/algo_trading_strategies_india` repository provides a ready‑to‑run suite of option‑selling strategies focused on Indian indices (NIFTY 50, BANK NIFTY, FIN NIFTY, MIDCAP NIFTY, SENSEX). Its core strengths lie in:
- A robust data‑engine that pulls live and historical market data via the Zerodha Kite Connect API.
- A library of short‑straddle, short‑strangle, and iron‑fly strategies with multiple exit mechanisms.
- A copy‑trading engine that scales positions across client accounts.
- Comprehensive risk‑engineering tools (fixed, percentage‑based, trailing stops; MTM‑based targets; account‑level MTM SL).

Integrating these components into the eqats platform will expand eqats’ coverage of Indian equity‑index options and add battle‑tested risk controls.

## 1. Data Engine Integration
### Features to Adopt
- **Live market data ingestion** – wrap the existing Kite Connect subscription logic into eqats’ `MarketDataFeed` abstraction.
- **Historical OHLCV retrieval** – reuse the repository’s helper functions for back‑testing and strategy warm‑up.
- **Symbol universe management** – create a static list (`NIFTY_50`, `BANK_NIFTY`, `FIN_NIFTY`, `MIDCAP_NIFTY`, `SENSEX`) and an option‑chain generator that feeds the feed.
- **Real‑time option‑chain streaming** – extend the feed to publish bid/ask, IV, and Greeks for each strike.

### Integration Steps
1. Add a new provider `ZerodhaKiteProvider` implementing eqats’ `IMarketDataProvider`.
2. Move the repository’s `get_quote`, `get_historical_data`, and `stream_ticks` functions into this provider.
3. Register the provider in eqats’ dependency‑injection container under the name `zerodha_kite`.
4. Update the universe configuration to include the five Indian indices and automatically derive the weekly expiry symbols used in the 0920 strategies.

## 2. Signal & Execution Logic Integration
### Strategies to Import
- **Short Straddle (0920 expiry)** – `finnifty_0920_short_straddle.py`, `nifty50_0920_short_straddle.py`, etc.
- **Short Strangle (0920 expiry)** – analogous files under `short-strangle/0920_short_strangle`.
- **Combined Premium variants** – `*_combined_premium_short_straddle.py` and `*_combined_premium_short_strangle.py`.
- **Iron‑Fly** – placeholder; can be added once the repo matures.
- **Copy‑Trading module** – the logic that reads a master account’s positions and replicates them with capital‑proportional sizing.

### Integration Steps
1. Create a new `strategies/indian_options` package in eqats.
2. Port each strategy file, replacing direct Zerodha API calls with eqats’ `IOrderExecutor` and `ISignalGenerator` interfaces.
   - Entry logic: sell ATM call & put (straddle) or OTM call & put (strangle) at the configured time (09:20).
   - Exit logic: delegate to the risk‑engine module (see Section 3) for stop‑loss/target evaluation.
3. Implement a `CopyTradingExecutor` that subscribes to the master account’s position stream (via Kite Connect) and issues scaled orders to child accounts.
4. Expose strategy parameters (lot size, stop‑loss type, target MTM, etc.) through eqats’ strategy configuration YAML/JSON.
5. Write unit tests using the repository’s historical data to verify P&L profiles.

## 3. Risk Engineering Integration
### Risk Features to Adopt
- **Fixed Stop‑Loss** – absolute premium loss trigger.
- **Percentage‑Based Stop‑Loss** – loss as a fraction of entry premium.
- **Trailing Percentage‑Based Stop‑Loss** – trailing stop that moves with favorable MTM.
- **Account‑Level MTM Stop‑Loss** – stops when the entire account’s MTM crosses a threshold.
- **MTM‑Based Target Execution** – exit when profit reaches a predefined MTM target.
- **Risk‑Proportional Position Sizing** – used by the copy‑trading module to scale lots according to equity.

### Integration Steps
1. Extend eqats’ `IRiskManager` with methods:
   - `check_fixed_sl(position, entry_premium)`
   - `check_pct_sl(position, entry_premium, pct)`
   - `check_trailing_sl(position, entry_premium, high_watermark, pct)`
   - `check_account_mtm_sl(account_mtm, limit)`
   - `check_mtm_target(position, target_mtm)`
2. Move the repository’s stop‑loss calculation functions into these methods.
3. In each strategy’s execution loop, after receiving a market tick, call the appropriate risk‑manager method to decide whether to emit an exit signal.
4. Configure risk parameters per strategy in eqats’ config (e.g., `stop_loss_type: fixed`, `stop_loss_value: 150`).
5. Ensure the copy‑trading executor consults the risk manager before issuing scaled orders to child accounts.

## 4. Example: Integrating the Bank Nifty 0920 Short Straddle
```yaml
# eqats/strategies/banknifty_0920_short_straddle.yaml
strategy: banknifty_0920_short_straddle
broker: zerodha_kite
symbol: BANKNIFTY24SEPFUT   # underlying future for strike selection
expiry: 0920
entry_time: "09:20"
stop_loss:
  type: trailing_percent   # or fixed, percent
  value: 15                # 15 % trailing
mtm_target:
  enabled: true
  value: 300               # exit when MTM profit reaches ₹300
lot_size: 20
```
The corresponding Python strategy class would:
1. At 09:20, fetch the ATM strike for Bank Nifty weekly options.
2. Sell one call and one put (lot_size contracts each).
3. On each tick, update MTM and query the `RiskManager` for trailing‑SL and MTM‑target.
4. On signal, submit market orders via `IOrderExecutor`.

## 5. Benefits for eqats
- **Expanded product coverage** – immediate access to Indian index options, a high‑volume, liquid segment.
- **Proven risk controls** – the repository’s stop‑loss and MTM‑target logic reduces draw‑downs in live trading.
- **Copy‑trading capability** – enables eqats to offer managed‑account services for retail clients.
- **Reusable data pipeline** – the Zerodha Kite Connect provider can serve other Indian‑market strategies.
- **Rapid back‑testing** – historical data functions allow quick strategy validation before deployment.

## 6. Next Steps
1. Sprint 1: Implement `ZerodhaKiteProvider` and configure the Indian‑universe.
2. Sprint 2: Port the short‑straddle and short‑strangle families, linking them to the new risk manager.
3. Sprint 3: Add the copy‑trading executor and configure proportional scaling.
4. Sprint 4: Integrate iron‑fly strategies once the repo releases them.
5. Sprint 5: Run paper‑trading validation on NSE/BSE data and move to live deployment.

By following this blueprint, eqats can swiftly incorporate a mature, risk‑aware option‑selling suite tailored to the Indian markets, enhancing both its strategy library and its risk‑engineering framework.
