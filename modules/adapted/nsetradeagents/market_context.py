import yfinance as yf
import pandas as pd
import structlog
from app.utils.market_data import safe_yf_download

logger = structlog.get_logger()

# Maps yfinance sector names → NSE sector index ticker
# yfinance returns names like "Technology", "Financial Services" — not "NIFTY IT"
SECTOR_MAP = {
    "Technology": "^CNXIT",
    "Financial Services": "^NSEBANK",
    "Healthcare": "^CNXPHARMA",
    "Consumer Cyclical": "^CNXAUTO",
    "Consumer Defensive": "^CNXFMCG",
    "Basic Materials": "^CNXMETAL",
    "Real Estate": "^CNXREALTY",
    "Energy": "^CNXENERGY",
    "Industrials": "^CNXINFRA",
    "Communication Services": "^CNXMEDIA",
    "Utilities": "^CNXENERGY",  # closest proxy
}


def _day_change_pct(ticker_sym: str, df: pd.DataFrame | None = None) -> float | None:
    """Today's percentage change for a ticker.

    Uses `df` when supplied rather than downloading again. Returns None if
    there aren't two closes to compare.
    """
    try:
        if df is not None and len(df) >= 2:
            close = df["Close"].squeeze()
        else:
            data = safe_yf_download(ticker_sym, period="5d")
            if data is None or len(data) < 2:
                return None
            close = data["Close"].squeeze()
        return float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
    except Exception:
        return None


def fetch_market_context(
    ticker: str,
    ticker_df: pd.DataFrame | None = None,
    ticker_info: dict | None = None,
    nifty_df: pd.DataFrame | None = None,
    sector_dfs: dict[str, pd.DataFrame] | None = None,
    vix_df: pd.DataFrame | None = None,
) -> dict:
    """
    Collect market-wide and stock-level context

    Returns:
        nifty_day_pct      float   Nifty 50 day change %
        nifty_5d_pct       float   Nifty 50 5-day change %
        market_label       str     "bullish" / "bearish" / "neutral"
        sector             str     Sector name from stock info (or "Unknown")
        sector_day_pct     float   Sector index day change % (or None)
        pct_from_52w_high  float   How far stock is below its 52-week high
        pct_from_52w_low   float   How far stock is above its 52-week low
        divergence_note    str     e.g. "Stock up while sector down"
    """
    logger.info("market_context_start", ticker=ticker)

    # --- 1. Nifty 50 — use pre-fetched df if available --------------------------------
    try:
        nifty_raw = (
            nifty_df
            if nifty_df is not None
            else safe_yf_download("^NSEI", period="60d")
        )
        nifty_close = nifty_raw["Close"].squeeze()
        nifty_day_pct = float(
            (nifty_close.iloc[-1] - nifty_close.iloc[-2]) / nifty_close.iloc[-2] * 100
        )
        nifty_5d_pct = (
            float(
                (nifty_close.iloc[-1] - nifty_close.iloc[-6])
                / nifty_close.iloc[-6]
                * 100
            )
            if len(nifty_close) >= 6
            else 0.0
        )
        nifty_10d_pct = (
            float(
                (nifty_close.values[-1] - nifty_close.values[-11])
                / nifty_close.values[-11]
                * 100
            )
            if len(nifty_close) >= 11
            else 0.0
        )

        nifty_20d_pct = (
            float(
                (nifty_close.values[-1] - nifty_close.values[-21])
                / nifty_close.values[-21]
                * 100
            )
            if len(nifty_close) >= 21
            else 0.0
        )

    except Exception as e:
        logger.warning("nifty_fetch_failed", error=str(e))
        nifty_day_pct = 0.0
        nifty_5d_pct = 0.0
        nifty_10d_pct = 0.0
        nifty_20d_pct = 0.0

    if nifty_day_pct > 0.5:
        market_label = "bullish"
    elif nifty_day_pct < -0.5:
        market_label = "bearish"
    else:
        market_label = "neutral"

    # --- 2. Sector — use pre-fetched info if available --------------------------------
    sector = "Unknown"
    sector_day_pct = None
    try:
        info = ticker_info if ticker_info is not None else yf.Ticker(ticker).info
        sector = info.get("sector") or info.get("industry") or "Unknown"

        # Direct lookup — keys match yfinance sector names exactly
        matched_index = SECTOR_MAP.get(sector)
        if matched_index:
            injected = sector_dfs.get(matched_index) if sector_dfs else None
            sector_day_pct = _day_change_pct(matched_index, df=injected)
    except Exception as e:
        logger.warning("sector_fetch_failed", ticker=ticker, error=str(e))

    # --- 3. 52-week position — use pre-fetched ticker_df (12mo covers 52wk) ----------
    pct_from_52w_high = None
    pct_from_52w_low = None
    try:
        hist = (
            ticker_df
            if ticker_df is not None
            else safe_yf_download(ticker, period="52wk")
        )

        if hist is not None and len(hist) > 0:
            current = float(hist["Close"].squeeze().iloc[-1])
            high_52w = float(hist["High"].squeeze().max())
            low_52w = float(hist["Low"].squeeze().min())
            pct_from_52w_high = round((current - high_52w) / high_52w * 100, 2)
            pct_from_52w_low = round((current - low_52w) / low_52w * 100, 2)
    except Exception as e:
        logger.warning("52w_fetch_failed", ticker=ticker, error=str(e))

    # --- 4. Divergence note — compute from pre-fetched ticker_df if available --------
    stock_day_pct = _day_change_pct(ticker, df=ticker_df)
    divergence_note = ""
    if stock_day_pct is not None and sector_day_pct is not None:
        if stock_day_pct > 1.0 and sector_day_pct < -0.5:
            divergence_note = "Stock rising while sector falling - relative strength"
        elif stock_day_pct < -1.0 and sector_day_pct > 0.5:
            divergence_note = "Stock falling while sector rising - relative weakness"
        else:
            divergence_note = "Stock moving in line with sector"

    # --- 5. SMA20 trend position - early correction signal --------------------------
    trend_label = "unknown"
    try:
        if len(nifty_close) >= 20:
            nifty_current = float(nifty_close.iloc[-1])
            above_sma20 = nifty_current > float(nifty_close.tail(20).mean())
            if len(nifty_close) >= 50:
                above_sma50 = nifty_current > float(nifty_close.tail(50).mean())
                if above_sma50 and above_sma20:
                    trend_label = "above both SMA20 and SMA50 - healthy uptrend"
                elif above_sma50 and not above_sma20:
                    trend_label = (
                        "above SMA50 but below SMA20 - early correction developing"
                    )
                else:
                    trend_label = "below SMA50 - sustained downtrend"  # Should be blocked by regime gate, but good to note
            else:
                trend_label = (
                    "above SMA20"
                    if above_sma20
                    else "below SMA20 - short-term weakness"
                )
    except Exception as e:
        logger.warning("sma20_compute_failed", error=str(e))

    # --- 6. India VIX - marktet fear indicator -----------------------------------------
    india_vix = None
    try:
        if vix_df is not None and not vix_df.empty:
            vix_close = vix_df["Close"].squeeze()
            india_vix = round(float(vix_close.values[-1]), 2)
    except Exception as e:
        logger.warning("vix_parse_failed", error=str(e))

    context = {
        "nifty_day_pct": round(nifty_day_pct, 2),
        "nifty_5d_pct": round(nifty_5d_pct, 2),
        "nifty_10d_pct": round(nifty_10d_pct, 2),
        "nifty_20d_pct": round(nifty_20d_pct, 2),
        "india_vix": india_vix,
        "market_label": market_label,
        "sector": sector,
        "sector_day_pct": (
            round(sector_day_pct, 2) if sector_day_pct is not None else None
        ),
        "pct_from_52w_high": pct_from_52w_high,
        "pct_from_52w_low": pct_from_52w_low,
        "divergence_note": divergence_note,
        "trend_label": trend_label,
    }
    logger.info(
        "market_context_done",
        ticker=ticker,
        market=market_label,
        nifty_day=nifty_day_pct,
    )
    return context
