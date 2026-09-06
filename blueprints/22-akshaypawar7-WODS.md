# Integration Blueprint for WODS Features into eqats

## Overview
The WODS repository provides a Flutter‑based stock‑market UI backed by Firebase services and local Hive storage. While it lacks explicit trading logic, its data‑engine components can be repurposed to feed market data, cache features, and visualize eqats signals.

## Data Engines
- **Firebase Realtime Database & Firestore** – Use as a scalable ingestion pipeline for real‑time tick data, order‑book snapshots, or alternative data streams. Write a Firebase Cloud Function that subscribes to external market data APIs and pushes updates into Realtime/Firestore; eqats can listen via the Firebase SDK to obtain low‑latency feeds.
- **Firebase Storage** – Store model artifacts, backtest results, or log files. eqats can upload/download these objects directly from storage, enabling version‑controlled model distribution across nodes.
- **Hive & Hive Flutter** – Replace eqats’ current local cache with Hive boxes for ultra‑fast read/write of tick bars, feature vectors, or position state. Hive’s encryption can protect sensitive data on disk.
- **HTTP client** – Leverage the existing `http` package to pull data from REST endpoints (e.g., fundamental data, news) and feed it into eqats’ feature‑engine pipeline.

## Signal & Execution Logic
The WODS codebase does not contain signal generation, strategy backtesting, or order‑execution modules. Consequently, there are no direct components to map into eqats’ Signal & Execution domain. If desired, the UI layers (Provider, Syncfusion charts) could be reused to build a custom dashboard for visualizing eqats‑generated signals, but the core logic would need to be developed separately.

## Risk Engineering
No risk‑limit, position‑sizing, or monitoring features are present in WODS. Hence, nothing can be directly integrated into eqats’ Risk Engineering domain. Risk controls would need to be implemented within eqats using its own libraries or third‑party risk packages.

## Recommended Integration Steps
1. **Set up Firebase project** and enable Realtime Database, Firestore, and Storage.
2. **Create a data‑ingestion Cloud Function** that pulls market data from your preferred provider and writes to Realtime/Firestore.
3. **In eqats**, add the Firebase Dart SDK and initialize it with the same config; subscribe to the relevant collections/topics to receive real‑time updates.
4. **Add Hive dependencies** and define boxes for cached bars, features, and account state; replace any existing file‑based caches.
5. **Optionally**, reuse the Syncfusion Flutter Charts widget to plot eqats‑generated equity curves or signal overlays within a Flutter‑based monitoring dashboard.
6. **Remove or ignore** the social‑feature modules (feed, posts, authentication) unless a community‑layer is desired; they are not required for the core quantitative pipeline.

## Conclusion
By adopting WODS’s Firebase‑centric storage and local‑caching mechanisms, eqats can achieve a resilient, low‑latency data layer while leveraging familiar Flutter UI tools for visualization. The missing signal/execution and risk components must be sourced elsewhere or built in‑house.