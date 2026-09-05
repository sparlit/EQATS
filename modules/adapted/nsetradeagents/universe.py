import requests
import pandas as pd
import io
import structlog

logger = structlog.get_logger()

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com",
}

NSE_SOURCES = [
    (
        "Nifty Smallcap 250",
        "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    ),
    (
        "Nifty Midcap 150",
        "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    ),
]


def fetch_universe() -> list[str]:
    """Fetch the smallcap and midcap universe from NSE's published CSV lists.

    Returns tickers in yfinance format, e.g. ['TITAN.NS'].
    """
    tickers: list[str] = []

    for name, url in NSE_SOURCES:
        try:
            logger.info("fetching_universe", source=name)
            resp = requests.get(url, headers=NSE_HEADERS, timeout=15)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")

            df = pd.read_csv(io.StringIO(resp.text))
            symbol_col = next((c for c in df.columns if "symbol" in c.lower()), None)

            if not symbol_col:
                logger.warning("no_symbol_column", source=name)
                continue

            symbols = (
                df[symbol_col].dropna().astype(str).str.strip().str.upper().tolist()
            )
            valid = [s for s in symbols if 2 <= len(s) <= 20]
            tickers += [f"{s}.NS" for s in valid]
            logger.info("universe_fetched", source=name, count=len(valid))

        except Exception as e:
            logger.error("universe_fetch_failed", source=name, error=str(e))

    # Deduplicate
    seen = set()
    unique = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    logger.info("universe_ready", total=len(unique))
    return unique
