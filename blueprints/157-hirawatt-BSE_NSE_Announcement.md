# Integration Blueprint for BSE_NSE_Announcement into eqats

## Overview
The BSE_NSE_Announcement repository provides a Streamlit‑based scraper for BSE corporate announcements, complete with keyword filtering, CSV storage, watchlist handling, and desktop notifications. These capabilities can be repurposed within eqats to ingest regulatory news, generate event‑driven signals, and alert users.

## Data Engines
- **Ingestion**: Uses Selenium (chromedriver/geckodriver) to scrape the BSE announcements page, extracting title, date, PDF link, and company name.
- **Filtering**: Reads `keywords.txt` to keep only announcements matching user‑defined terms (e.g., "results", "dividend", "bonus").
- **Storage**: Saves each scrape run to a timestamped CSV under `data/BSE_{from-year}_{to-year}.csv`, enabling historical analysis and back‑testing.
- **Integration Point**: Replace the Streamlit UI with eqats’ data‑engine layer; expose a function `fetch_bse_announcements(start_date, end_date, keywords)` that returns a Pandas DataFrame and optionally writes to eqats’ feature store.

## Signal & Execution Logic
- **Watchlist**: Users can maintain a list of companies; the app highlights matches and triggers a desktop notification via `notification.py` (likely using `plyer`).
- **Signal Generation**: In eqats, this watchlist can map to a signal rule: when an announcement for a watched company contains a keyword (e.g., "results"), emit a `NEWS` signal with attributes `{company, announcement_type, timestamp, link}`.
- **Execution Hook**: The signal can feed into eqats’ execution engine to adjust positions (e.g., increase exposure ahead of earnings) or to trigger order‑cancel‑update logic.

## Risk Engineering
- **Current Repo**: No explicit risk limits, position sizing, or risk monitoring features.
- **Future Extension**: The announcement data could be fed into eqats’ risk engine to adjust volatility forecasts or to apply event‑risk caps (e.g., reduce exposure during result announcements).

## Implementation Steps
1. **Create a new module** `eqats/data_engines/bse_announcements.py` wrapping the Selenium scraping logic.
2. **Add a configuration** for keywords and watchlist (YAML/JSON) that eqats already uses for other data sources.
3. **Expose a function** `load_announcements()` that returns a DataFrame with columns: `timestamp`, `company`, `title`, `link`, `keywords_matched`.
4. **Register a signal parser** in `eqats/signals/news.py` that converts each row into a `NewsSignal` object.
5. **Wire the signal** into eqats’ signal bus; optionally connect to the execution module for event‑driven order adjustments.
6. **Add unit tests** using mock HTTP responses to verify filtering and storage.
7. **Document** the new data source in eqats’ README and update the requirements (`selenium`, `streamlit` optional for UI, `plyer` for notifications).

## Example Code Snippet
```python
# eqats/data_engines/bse_announcements.py
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
import time

def fetch_bse_announcements(start_date, end_date, keywords):
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    driver = webdriver.Chrome(options=options)
    driver.get('https://www.bseindia.com/corporates/ann.html')
    # ... scraping logic ...
    driver.quit()
    df = pd.DataFrame(rows, columns=['timestamp','company','title','link'])
    df['keywords_matched'] = df['title'].apply(lambda t: any(k.lower() in t.lower() for k in keywords))
    return df[df['keywords_matched']]
```
