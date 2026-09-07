# Integration Blueprint for Shoonya-php into eqats

## Overview
The Shoonya-php repository provides a PHP wrapper for Finvasia Shoonya OMS REST and WebSocket APIs. It offers functionalities for market data retrieval, order management, watchlist handling, and real-time feeds.

## Mapping to eqats Domains

### Data Engines
- **Market Data Ingestion**: getLTP, getQuotes, getTimePriceSeries, getDailyPriceSeries, getOptionChain, getScripInfo, searchScrip, getToken, getWatchListNames, getWatchList, addScripWatchList, deleteScripWatchList.
- **Real‑Time Streaming**: subscribe / unsubscribe (WebSocket touchline), subscribeOrders (order feed).
- **Account & Position Data**: getLimits, getHoldings, getPositions, getOrderbook, getTradebook, getSessionData.

These endpoints can be used by eqats’ data layer to populate tick databases, build historical candles, maintain option chains, and keep watchlists synchronized.

### Signal & Execution Logic
- **Order Placement**: placeOrder (supports various product types, price types, trigger prices, SL/TP/trailing).
- **Order Management**: modifyOrder, cancelOrder, exitOrder, getOrderStatus, singleOrderHistory.
- **Advanced Orders**: gttOrder / cancelGtt, getPendingGtt, getEnableGtt.
- **Notifications**: telegram for alerts.
- **WebSocket Order Updates**: subscribeOrders to receive live order status changes.

These functions map directly to eqats’ execution engine: signals can trigger placeOrder; risk checks can call modifyOrder/cancelOrder; GTT orders can be used for conditional entries/exits.

### Risk Engineering
- **Risk Limits**: getLimits returns margin, exposure, and turnover limits per product/segment.
- **Position & P&L Monitoring**: getHoldings, getPositions, getTradebook, getOrderbook.
- **Product Conversion**: positionProductConversion (if implemented) to switch between intraday and delivery.
- **Exposure Tracking**: Real‑time order book and trade book feeds via WebSocket.

equats can call getLimits before sending orders to enforce pre‑trade risk checks, continuously monitor getHoldings/getPositions for post‑trade risk, and use positionProductConversion for margin optimization.

## Integration Steps
1. Wrap the PHP library in a thin service layer (e.g., a Python gRPC microservice or a PHP‑to‑eqats adapter) exposing the same methods via eqats’ internal API.
2. Data Engine Adapter: schedule periodic calls to market data endpoints and subscribe to WebSocket streams to feed eqats’ historical and real‑time stores.
3. Execution Adapter: route eqats’ order objects to placeOrder/modifyOrder/cancelOrder; listen to subscribeOrders for execution reports.
4. Risk Adapter: invoke getLimits in pre‑trade risk module; use getHoldings/getPositions for risk‑engine calculations; trigger alerts via telegram.
5. Error Handling & Retry: map boolean returns to eqats’ success/failure handling; implement reconnection logic for WebSocket.
6. Testing: use the library’s demo credentials (if any) or a sandbox to validate data feeds and order flows before live deployment.

## Benefits
- Leverages an actively maintained unofficial SDK, reducing boilerplate.
- Provides both REST and WebSocket access, enabling low‑latency strategies.
- PHP compatibility allows rapid prototyping within eqats’ existing polyglot services.

## Considerations
- The library is unofficial; verify endpoint stability and authentication handling.
- Ensure proper credential storage (API key, user ID, password) per eqats’ secrets management.
- Monitor rate limits from Shoonya and implement throttling.

## Conclusion
Integrating Shoonya-php equips eqats with a ready‑made gateway to Indian equities, commodities, and derivatives markets via Finvasia Shoonya, covering data ingestion, signal‑driven execution, and risk controls.