"""
Committed CSV watchlist — the serverless source of truth for the intraday scanner.

On GitHub Actions the SQLite DB is ephemeral (wiped each run), so the watchlist
must live in a file that's committed to the repo. The morning briefing writes
the day's Grade A/B picks here; the intraday scanner reads it.
"""
from __future__ import annotations

import pandas as pd
from loguru import logger

from config import WATCHLIST_CSV


def load_watchlist_symbols() -> list[str]:
    """Return the symbol list from the committed watchlist CSV (empty if none)."""
    if not WATCHLIST_CSV.exists():
        return []
    try:
        df = pd.read_csv(WATCHLIST_CSV)
        if "symbol" not in df.columns or df.empty:
            return []
        return [str(s).strip() for s in df["symbol"].dropna().tolist() if str(s).strip()]
    except Exception as exc:
        logger.warning("Could not read watchlist CSV: {}", exc)
        return []


def save_watchlist_from_screener(df: pd.DataFrame, max_symbols: int = 15) -> int:
    """
    Persist Grade A/B screener picks to the committed CSV. Returns count saved.
    Keeps a small, useful set of columns for transparency.
    """
    if df is None or df.empty or "symbol" not in df.columns:
        return 0
    picks = df[df["grade"].isin(["A", "B"])] if "grade" in df.columns else df
    if picks.empty:
        return 0
    cols = [c for c in ["symbol", "grade", "score", "close", "rs_20d", "rs_60d"] if c in picks.columns]
    out = picks[cols].head(max_symbols).copy()
    WATCHLIST_CSV.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(WATCHLIST_CSV, index=False)
    logger.info("Watchlist CSV updated with {} symbols -> {}", len(out), WATCHLIST_CSV)
    return len(out)
