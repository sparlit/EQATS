# EQATS v5.0 Supported Protocols Reference

## Supported Connectivity Protocols
EQATS v5.0 provides native protocol abstraction across 7 broker integration drivers:

1. **MetaTrader 5 (MT5)**: IPC bindings via native `MetaTrader5` Python library.
2. **FIX 4.4 / 5.0**: Institutional FIX Engine with logon, heartbeats, and NewOrderSingle tags.
3. **REST / WebSockets**: Direct JSON endpoint routing for institutional LP APIs.
4. **Interactive Brokers (IBKR)**: TWS and Gateway API connections.
5. **cTrader**: Open API 2.0 OAuth / protobuf messaging.
6. **CCXT**: Unified cryptocurrency exchange integration (Binance, Bybit, OKX, Kraken, Coinbase).
7. **Paper Simulator**: High-fidelity local order matching engine with slippage and spread simulation.
