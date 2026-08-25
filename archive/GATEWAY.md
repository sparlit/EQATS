# EAQTS v5.0 Universal Gateway Specification

## Architecture
The `UniversalBrokerGateway` class (`institutional_integrations/universal_broker_adapter.py`) decouples high-level trading brains from broker-specific protocol mechanics.

## Gateway Methods
- `connect()`: Establishes active broker session.
- `disconnect()`: Cleanly terminates connection and releases sockets.
- `is_connected()`: Performs active connection health check.
- `get_account_info()`: Normalizes balance, equity, leverage, and currency mode across brokers.
- `execute_order(symbol, order_type, lot_size, sl, tp)`: Routes orders with automatic retry backoff and timeout guards.
