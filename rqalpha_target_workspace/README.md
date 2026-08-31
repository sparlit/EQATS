# RQAlpha Isolated Target Repository Workspace

Target: `ricequant/rqalpha`
Phase: 1 - Topology Mapping & Iso-Local Extraction

## Architecture Overview
- Core Architecture: Event-driven portfolio accounting and order execution engine for Python/Rust.
- Data Engine: Fast bar data indexing, tick stream parsing, and vectorized memory slices.
- Backtest State Machine: Day-by-day and minute-by-minute order processing, position tracking, cash calculation, dynamic slippage modeling.
- Execution Loop: Event orders mapped with unique Magic Number `9100001` with support for limit/market matching and portfolio rebalancing.
