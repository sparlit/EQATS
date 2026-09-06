# Nseproxy Integration Blueprint for eqats

## Overview
Integrate the nseproxy HTTP proxy as a data acquisition layer within eqats to fetch live National Stock Exchange (India) market data.

## Components
- **nseproxy_client.rs**: Rust module providing a synchronous client (fetch) that queries the locally running nseproxy on http://127.0.0.1:3000.
- **Configuration**: Environment variable NSEPROXY_ADDR (default http://127.0.0.1:3000) to override proxy endpoint.
- **Error Handling**: Returns Result<String, reqwest::Error>; callers can transform to domain‑specific types.
- **Testing**: Unit test validates URL construction; integration test can be added against a running proxy.

## Data Flow
1. eqats strategy calls nseproxy_client::fetch(endpoint).
2. Module builds full URL by appending endpoint to base proxy address.
3. HTTP GET request is sent to the proxy.
4. Proxy forwards request to https://www.nseindia.com/<endpoint> and returns the raw JSON/text response.
5. Response is returned to eqats for further processing (signal generation, risk checks, storage).

## Safety & Performance
- Built on reqwest with Tokio async runtime; client reuses connection pool.
- Timeout configurable via reqwest::ClientBuilder::timeout.
- No blocking of async runtime; designed to be called from async contexts via .await.

## Future Extensions
- Add caching layer (e.g., using tokio::sync::OnceCell or async-cache).
- Expose PyO3 bindings for Python consumption.
- Metrics integration (Prometheus) for request latency and error rates.
