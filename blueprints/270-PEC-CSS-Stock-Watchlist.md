# Integration Blueprint for Stock-Watchlist into eqats

## Overview
The Stock-Watchlist repository provides a React Native/Expo mobile application with Firebase backend for user authentication and watchlist persistence. While it does not contain signal generation, execution, or risk management logic, its UI components and data storage approach can be leveraged within eqats to provide a cross-platform watchlist and asset monitoring frontend.

## Languages & Frameworks
- **Language:** JavaScript
- **Frameworks/Libraries:** React Native, Expo, Firebase (Auth & Firestore)

## Data Engines Integration
- **Firebase Authentication:** Replace eqats' current auth mechanism (if any) with Firebase Auth to enable email/password, Google, etc., leveraging the existing login screen.
- **Firestore for Watchlist Storage:** Use Firestore collections to store each user's watchlist of symbols (stocks, crypto, options, indexes). The app's existing stock screen and watchlist screen can be adapted to read/write from these collections.
- **Market Data Hook:** Although the repo does not specify a market data provider, eqats can inject its own market data service (e.g., WebSocket to exchanges) into the stock screen components to display real‑time prices.

## Signal & Execution Logic Integration
- The repository contains no signal generation or order execution features. To add these capabilities:
  - Develop new screens or modals within the React Native app that call eqats' backend strategy APIs (e.g., via REST or GraphQL) to trigger signal generation.
  - Implement order ticket components that interface with eqats' execution engine (e.g., using its order management API) to submit, modify, or cancel orders.
  - Leverage Firebase Functions as a lightweight middleware to securely invoke eqats' backend services from the mobile client.

## Risk Engineering Integration
- No risk limits, position sizing, or monitoring features are present. Integration steps:
  - Add a risk dashboard screen that reads risk metrics from eqats' risk engine (exposed via API) and displays them using existing UI components (charts, tables).
  - Implement validation hooks in the order ticket that call eqats' risk‑checking service before allowing order submission.
  - Store user‑defined risk parameters (e.g., max daily loss, position size limits) in Firestore so they persist across sessions.

## Implementation Roadmap
1. **Setup Firebase Project** – enable Auth and Firestore; configure eqats to use the same Firebase project for shared user identities.
2. **Port UI Components** – copy the login, stock screen, watchlist, about/profile, and search screens into eqats' mobile frontend repository; replace placeholder data calls with eqats' service endpoints.
3. **Add Service Layer** – create a thin abstraction layer (e.g., `eqatsService.js`) that wraps eqats' backend REST/WebSocket APIs; import this layer into the copied components.
4. **Implement Signal & Execution Screens** – build new screens for strategy activation, order ticket, and position management, calling the service layer.
5. **Integrate Risk Controls** – add risk‑check calls in the order ticket and display risk metrics in a dedicated dashboard.
6. **Testing & Deployment** – use Expo for development builds; run end‑to‑end tests with Firebase emulators; publish to Android/iOS via EAS as per the original repo's `eas build` command.

## Considerations
- The original app does not include market data fetching; ensure eqats supplies real‑time price data via WebSocket or polling to avoid stale information.
- Security: protect Firestore rules so users can only read/write their own watchlist and risk settings; use Firebase Auth tokens to authorize calls to eqats' backend.
- Performance: keep UI lightweight; leverage Expo's optimization tools and Firebase's offline persistence for watchlist data.

## Conclusion
By adopting the Stock‑Watchlist frontend and Firebase backend, eqats can rapidly acquire a polished, cross‑platform watchlist interface with persistent user settings, while adding its own signal, execution, and risk logic through well‑defined service boundaries.
