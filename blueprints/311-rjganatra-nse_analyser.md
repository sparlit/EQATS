# Integration Blueprint for eqats

## Data Engines
- Reuse `fetchers/universe.py` to pull Nifty 500 tickers from NSE CSV.
- Adapt `fetchers/screener.py` (requests+BeautifulSoup) for price, 52‑week high/low, P/E, P/B, ROE, ROCE, D/E, dividend yield.
- Use `fetchers/fundamentals.py` (yfinance) as a fallback for income, balance sheet, cash‑flow data.
- Store outputs in a versioned `results/` folder (or data lake) and commit to Git for auditability.
- Deploy a GitHub Pages site (or internal dashboard) to visualise scores and opportunities.

## Signal & Execution Logic
- Import `analyzer/scorer.py`’s 13‑criterion weighted scoring function; expose `compute_fundamental_score(ticker)`.
- Replicate `scan_opportunities.py` logic to flag stocks near 52‑week low/high and momentum signals.
- Combine fundamental score (≥78 % = Strong) with opportunity flags to generate actionable signals.
- Automate both scans via GitHub Actions (cron: weekdays 17:00 IST, Sundays 07:30 IST) and push results to the data lake.

## Risk Engineering
- Apply the repository’s verdict bands:
  * ≥78 % → Strong (low risk)
  * 58‑78 % → Moderate (medium)
  * 40‑58 % → Weak (high)
  * <40 % → Avoid (exclude)
- Enforce low‑debt rule (D/E < 0.3) as a hard risk filter.
- Use the custom watchlist mechanism (`custom_watchlist.json`) and website star‑to‑sync for manual overrides.
- Note: current repo lacks explicit position sizing or portfolio‑level risk; these can be added in eqats by feeding scores/verdicts into a risk engine that applies VaR, max‑drawdown, or Kelly sizing.

## Implementation Steps
1. Copy the relevant modules (`fetchers/`, `analyzer/`, `scan_*.py`, `custom_watchlist.json`, workflows) into eqats under `vendor/nse_analyser`.
2. Create a thin wrapper (`eqats/integrations/nse_fundamentals.py`) that normalises outputs to eqats’ signal format.
3. Add the GitHub Actions workflow files (or translate to eqats’ scheduler) to run the scans on the desired cron.
4. Build a simple dashboard (Streamlit/FastAPI) that reads the latest results and mirrors the original site’s tabs.
5. Run an initial opportunity scan to populate the data lake, then enable the scheduled jobs.
6. Monitor verdict distribution and adjust weightings/thresholds to match eqats’ risk appetite.

## Expected Benefits
- Zero‑cost, automated data pipeline for Indian equities without paid APIs.
- Transparent, rule‑based fundamental scoring that can be back‑tested.
- Visual dashboard for quick manual inspection and watchlist management.
- Easy to extend to other indices or global markets by swapping the universe fetcher.