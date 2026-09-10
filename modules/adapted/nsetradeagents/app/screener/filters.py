import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


from datetime import date

import pandas as pd
import structlog
from app.core.config import settings
from app.utils.indicators import compute_indicators
from app.utils.market_data import extract_ticker_df, safe_yf_download

logger = structlog.get_logger()


def evaluate_candidate(ind: dict) -> tuple[dict | None, str]:
    """Apply the screener filters to one ticker's indicators.

    Returns (candidate, "passed"), or (None, reason) where reason is one of:
    no_data, liquidity, price, trend, volatility, day_change, volume, rsi, momentum.
    """
    if ind["avg_daily_value"] < settings.min_avg_daily_value:
        return None, "liquidity"
    if ind["current_price"] < settings.min_price:
        return None, "price"
    if ind["sma200"] is None:
        return None, "no_data"
    if not (ind["current_price"] > ind["sma50"] > ind["sma200"]):
        return None, "trend"
    if ind["atr_pct"] < settings.min_atr_pct:
        return None, "volatility"
    if ind["day_change_pct"] > settings.max_day_change_pct:
        return None, "day_change"
    if ind["volume_ratio"] < settings.min_volume_ratio:
        return None, "volume"
    if ind["today_vol"] < settings.min_volume_shares:
        return None, "volume"
    if ind["day_change_pct"] <= 0.5:
        return None, "volume"
    if not (settings.rsi_min <= ind["rsi"] <= settings.rsi_max):
        return None, "rsi"
    if ind["momentum_5d"] < 2.0:
        return None, "momentum"

    vol_norm = min(ind["volume_ratio"] / 5.0, 1.0)
    momentum_norm = min(max(ind["momentum_5d"], -15), 15) / 15
    atr_norm = min(ind["atr_pct"] / 5.0, 1.0)

    return {
        "current_price": ind["current_price"],
        "volume_ratio": ind["volume_ratio"],
        "avg_daily_value": ind["avg_daily_value"],
        "day_change_pct": ind["day_change_pct"],
        "momentum_5d": ind["momentum_5d"],
        "rsi": ind["rsi"],
        "atr_pct": ind["atr_pct"],
        "sma50": ind["sma50"],
        "sma200": ind["sma200"],
        "screener_score": (vol_norm * 0.40) + (momentum_norm * 0.35) + (atr_norm * 0.25),
    }, "passed"


def breadth_pct(closes: pd.DataFrame | None) -> float | None:
    """Percentage of the universe trading above its own 50-day average.

    Only tickers with usable data are counted — a missing series compares as
    False and would otherwise be counted as a downtrend, dragging breadth down
    early in a run. Returns None when it cannot be computed, so callers can
    fail open.
    """
    if closes is None or closes.empty or len(closes) < settings.regime_sma_period:
        return None
    try:
        last = closes.iloc[-1]
        sma = closes.tail(settings.regime_sma_period).mean()
        valid = last.notna() & sma.notna()
        if not valid.any():
            return None
        return float((last[valid] > sma[valid]).mean() * 100)
    except Exception:
        return None


def regime_open_at(breadth: float | None) -> bool:
    """Whether new entries are allowed at a given breadth reading.

    Takes the reading rather than the frame so the caller can record it — a
    decision that stores only the pass/fail freezes the current floor forever.
    Fails open on an unknown reading: a silently halted bot looks exactly like
    a quiet market.
    """
    return breadth is None or breadth >= settings.breadth_floor_pct


def screen(tickers: list[str]) -> tuple[list[dict], bool, float | None]:
    """Run the full universe through the screener filters.

    Downloads every ticker in one batch, then applies `evaluate_candidate` to
    each. Returns (candidates sorted best-first, regime_open, breadth_pct).

    The raw breadth reading comes back alongside the verdict so decisions can
    record it — storing only the pass/fail would freeze the current floor.

    Candidates come back regardless of the regime — the gate stops execution,
    not observation. Recording decisions on blocked days is what lets the veto
    experiment accumulate through a downtrend, and what makes the gate itself
    measurable after the fact.
    """
    logger.info("screener_start", total=len(tickers))

    if not tickers:
        logger.warning("screener_empty_universe")
        return [], True, None

    # Download all tickers in one batch
    raw = safe_yf_download(tickers, period="12mo", group_by="ticker")

    # The regime gate runs after the download because breadth is measured on
    # the universe itself, which this batch already contains. Defaults to open
    # so a failure here never silently halts trading.
    regime_open, breadth = True, None
    try:
        try:
            closes = raw.xs("Close", axis=1, level=1)
        except Exception:
            closes = None
        breadth = breadth_pct(closes)
        regime_open = regime_open_at(breadth)
        if not regime_open:
            logger.info(
                "screener_regime_blocked",
                reason="under half the universe above its 50d SMA",
            )
    except Exception as e:
        logger.warning("regime_check_failed", error=str(e))

    candidates = []
    counts = {
        "no_data": 0,
        "liquidity": 0,
        "price": 0,
        "trend": 0,
        "volatility": 0,
        "day_change": 0,
        "volume": 0,
        "rsi": 0,
        "passed": 0,
        "momentum": 0,
        "stale": 0,
    }

    for ticker in tickers:
        try:
            df = extract_ticker_df(raw, ticker)
            if df is None:
                counts["no_data"] += 1
                continue

            df = df.dropna(subset=["Close", "Volume"])

            if len(df) < 25:
                counts["no_data"] += 1
                continue

            # The scan runs late in the session and screens today's partial
            # bar deliberately. If the feed has not published it yet, the last
            # bar is yesterday's — we would screen yesterday's completed data
            # while buying at today's price, silently reverting to the old
            # entry model with no error.
            if df.index[-1].date() != date.today():
                counts["stale"] += 1
                continue

            ind = compute_indicators(df)

            candidate, reason = evaluate_candidate(ind)
            counts[reason] += 1

            if candidate is None:
                continue

            candidates.append({"ticker": ticker, "score": candidate["screener_score"], **candidate})

        except Exception as e:
            logger.warning("ticker_screen_failed", ticker=ticker, error=str(e))
            counts["no_data"] += 1

    candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info("screener_done", **counts)

    # One stale ticker is a quiet listing; most of the universe stale means the
    # feed has not published today yet and this scan saw almost nothing.
    if tickers and counts["stale"] > len(tickers) / 2:
        logger.error(
            "screener_feed_stale",
            stale=counts["stale"],
            total=len(tickers),
            reason="today's bar missing for most of the universe",
        )

    return candidates, regime_open, breadth
