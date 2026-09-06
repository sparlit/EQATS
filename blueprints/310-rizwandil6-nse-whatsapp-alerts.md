# Integration Blueprint for eqats

## Overview
The nse-whatsapp-alerts repository provides a lightweight polling mechanism to fetch NSE announcements and circulars and deliver matches via WhatsApp. This can be adapted into eqats to provide alternative market‑data ingestion and alerting channels.

## Data Engine Integration
- **RSS Announcements Ingestion**: Replace eqats’ current RSS/NSE feed connector with the public RSS polling logic (see src/main/java/.../AnnouncementPoller.java). It already handles HTTP GET, XML parsing, and in‑memory dedup.
- **Circulars JSON API**: Use the circulars fetcher (CircularPoller.java) which calls /api/circulars?dept=members. Add support for a scraping proxy via proxy.base-url and optional auth header – useful when NSE blocks direct requests.
- **Configurable Poll Interval**: Expose nse.poll-interval-ms in eqats’ configuration to control frequency.
- **Watchlist & Keyword Matching**: The matching logic (matchesWatchlist, containsKeyword) can be reused as a generic filter stage before signal generation.

## Signal & Execution Logic Integration
- **Signal Generation**: When an announcement contains a watchlist symbol or a circular contains a keyword, the app builds a message string. In eqats, treat this as a raw signal (e.g., SignalEvent{type: 'NSE_ANNOUNCEMENT', symbol: ..., details: ...}) that can be fed into strategy evaluators.
- **Execution via WhatsApp**: The Twilio wrapper (TwilioWhatsAppSender.java) shows how to send a templated message. Replace the WhatsApp sink with eqats’ execution gateway (e.g., order manager, notification service) while keeping the same credential structure (account SID, auth token, from/to).
- **Extensibility**: The current implementation logs to console; eqats can add persistence (DB) for dedup and audit, and route signals to risk checks before execution.

## Risk Engineering
The source repo does not include risk‑limit checks, position sizing, or monitoring. These would need to be added in eqats after the signal is generated (e.g., max‑alert‑rate, duplicate‑suppression, volatility‑based throttling).

## Implementation Steps
1. Clone the nse-whatsapp-alerts repo and copy the polling and matching packages into eqats’ data/ingest/nse module.
2. Create an eqats configuration block mirroring application.yml:
   ```
   nse:
     watchlist: [TCS, INFY]
     circular-keywords: [orders, contracts]
     poll-interval-ms: 600000
   twilio:
     account-sid: ...
     auth-token: ...
     whatsapp-from: +123...
     whatsapp-to:
       - +91...
   proxy:
     base-url: ...
   ```
3. Wire the pollers into eqats’ scheduler (e.g., Spring @Scheduled or eqats’ job framework).
4. Replace the WhatsApp send call with eqats’ signal publisher: publish a NseAlertSignal to the internal event bus.
5. Add a risk‑engineering subscriber that validates signal frequency, applies position‑size limits, and forwards approved signals to the execution adapter.
6. Enable in‑memory dedup initially; later swap for a Redis or DB‑based dedup store.

## Conclusion
By integrating the polling, matching, and Twilio notification components from nse-whatsapp-alerts, eqats gains a reliable, low‑maintenance source of NSE‑specific announcements and circulars, with a clear path to plug those events into its signal‑execution‑risk pipeline.