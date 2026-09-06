# Integration Blueprint for eqats: NSE Swing Scanner Features

## Overview
The NSE Swing Scanner provides a robust, zero‑cost pipeline for scanning the Nifty 500 universe using GitHub Actions for computation and Netlify for static frontend delivery. Its core strengths lie in:

- **Data ingestion** from multiple sources (yfinance, NSE bhavcopy, Screener.in, corporate actions) with fail‑closed gating.
- **Signal generation** via a multi‑factor scoring system (F‑Score, RSI, drawdown, liquidity, holdings, corporate actions) and a relative‑strength multiplier.
- **Risk controls** implemented as hard gates, monitoring/alerting, and on‑demand scan triggers with secure authentication.

Below are concrete ways to map each domain into the eqats project.

## Data Engines
- Replace or augment eqats’ market‑data layer with the scanner’s ingestion scripts (`backend/scanner.py`). They already pull:
  - Price/volume and fundamental data via `yfinance`.
  - NSE bhavcopy for delivery‑based liquidity checks.
  - Screener.in scraping for promoter/FII/DII holdings.
  - NSE corporate‑actions calendar to filter out upcoming events.
- Store the latest scan result as a JSON file (`frontend/public/data/latest_scan.json`) and commit it back to the repo. eqats can adopt a similar pattern: compute artifacts are version‑controlled, enabling instant rollback and auditability.
- Leverage GitHub Actions as the compute backend: no server maintenance, free minutes, and built‑in secrets handling (`GITHUB_TOKEN` for pushes). eqats could move heavy‑weight batch jobs (e.g., universe scans, factor calculations) to scheduled Actions workflows, reserving low‑latency services for real‑time needs.
- Optionally mirror the Netlify static‑hosting approach for any internal dashboards: push built assets to a branch and serve via Netlify or GitHub Pages.

## Signal & Execution Logic
- Adopt the scanner’s **hard‑gate** logic as a pre‑trade filter in eqats:
  - Piotroski F‑Score ≥ threshold.
  - Drawdown between ‑40% and ‑15% of 52‑week high.
  - RSI(14) between 25 and 40.
  - Liquidity adequacy (delivery ≥ ₹5 cr OR 20‑day ADV ≥ ₹10 cr).
  - Exclude T‑group, GSM, or suspended stocks.
  - Require promoter + FII + DII > 50% holdings.
  - Filter out stocks with excluded corporate actions in the next 30 days.
- Implement the **soft 0‑100 composite score** with the seven sub‑scores (valuation, RSI, EMA, drawdown, volume, F‑Score, holdings) and the relative‑strength‑vs‑Nifty‑50 multiplier described in `docs/methodology.md`. This yields a rank‑ordered list that can feed eqats’ signal generation module.
- Use the scanner’s **ATR(14)‑based entry zone, stop‑loss, and target calculations** as a starting point for eqats’ position‑sizing and risk‑reward engine.
- The scanner’s output JSON already contains these fields; eqats can ingest the file directly or expose a lightweight internal API that serves the same data.

## Risk Engineering
- Mirror the scanner’s **fail‑closed gating**: if any data source is unavailable, the gate is marked as failed rather than silently passing. eqats should adopt the same principle for all risk checks.
- Incorporate the scanner’s **monitoring and alerting** setup:
  - Use healthchecks.io (or equivalent) to ping after each scan job.
  - Add a watchdog that alerts on missed or delayed runs.
  - Display scan age and drift indicators on the dashboard (eqats can show “last updated” and lateness vs schedule).
- Implement the **on‑demand trigger** pattern:
  - Protect a manual scan button with a shared secret (`SCAN_TRIGGER_SECRET`) stored client‑side and verified via a server‑side function (Netlify Function or eqats’ own endpoint) that calls GitHub’s `workflow_dispatch`.
  - Require a fine‑grained GitHub PAT (`GITHUB_DISPATCH_TOKEN`) with `actions:write` scope.
  - Enforce a cooldown (e.g., 10 minutes) after each trigger to prevent abuse.
- Reuse the scanner’s **liquidity adequacy** and **drawdown limits** as concrete risk limits in eqats’ position‑sizing rules.
- Treat **T‑group / suspension / corporate‑action** filters as hard exclusions in eqats’ universe builder.

## Implementation Steps for eqats
1. **Fork the scanner’s backend** (`backend/`) into eqats’ `data_engines/` module, adapting the API to return data in eqats’ internal format.
2. **Create a GitHub Actions workflow** (similar to `.github/workflows/scan.yml`) that runs the eqats scan on a cron schedule, pushes results to a designated `data/` folder, and uses the default `GITHUB_TOKEN` for commits.
3. **Add a Netlify (or static‑site) frontend** if eqats desires a public dashboard; otherwise expose the JSON via an internal API gateway.
4. **Integrate the gating and scoring functions** into eqats’ signal generation pipeline, ensuring fail‑closed behavior.
5. **Set up monitoring** (healthchecks.io ping + alert on drift) and add UI components that show scan age and lateness.
6. **Add the secured on‑demand trigger** endpoint, store the secret in environment variables, and protect it with the same cooldown logic.
7. **Run the existing CI** (pytest + smoke scan + build) to guarantee quality; adapt eqats’ CI to include analogous tests.

By adopting these patterns, eqats gains a battle‑tested, zero‑cost data pipeline, transparent multi‑factor signals, and robust risk controls—all without managing servers or secrets.