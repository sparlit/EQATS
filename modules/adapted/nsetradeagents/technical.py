import structlog
from app.core.config import settings
from app.utils.indicators import compute_indicators
from app.utils.market_data import safe_yf_download, extract_ticker_df

logger = structlog.get_logger()


def _compute_signal(ind: dict) -> str:
    """Derive BUY, HOLD or SELL from trend and RSI.

    Price below either moving average is HOLD regardless of momentum.
    Above them, RSI over the ceiling is SELL and inside the band is BUY.
    """
    current_price = ind.get("current_price", 0)
    sma50 = ind.get("sma50") or 0
    sma200 = ind.get("sma200") or 0
    rsi = ind.get("rsi", 50)

    if sma200 and current_price < sma200:
        return "HOLD"
    if current_price < sma50:
        return "HOLD"
    if rsi > settings.rsi_max:
        return "SELL"
    if settings.rsi_min <= rsi <= settings.rsi_max:
        return "BUY"
    return "HOLD"


def _compute_strength(ind: dict) -> int:
    """Rate how cleanly a setup meets the swing criteria, 0-100.

    Weighted across RSI position in the ideal zone, MACD direction, volume
    conviction, and how extended the move already is.
    """
    rsi = ind.get("rsi", 50)
    macd_hist_trend = ind.get("macd_hist_trend", "mixed")
    volume_ratio = ind.get("volume_ratio", 0)
    momentum_5d = ind.get("momentum_5d", 0)

    score = 0

    if 62 <= rsi <= 67:
        score += 30
    elif 55 <= rsi <= 70:
        score += 20
    else:
        score += 5

    if macd_hist_trend == "expanding":
        score += 25
    elif macd_hist_trend == "mixed":
        score += 15

    if volume_ratio >= 2.0:
        score += 25
    elif volume_ratio >= 1.5:
        score += 15

    if momentum_5d <= 8:
        score += 20
    elif momentum_5d <= 10:
        score += 10

    return min(score, 100)


def _compute_summary(ind: dict, signal: str, strength: int) -> str:
    """One-line readable summary of the signal and the indicators behind it."""
    rsi = ind.get("rsi", 0)
    macd_trend = ind.get("macd_hist_trend", "mixed")
    volume_ratio = ind.get("volume_ratio", 0)
    momentum_5d = ind.get("momentum_5d", 0)
    return (
        f"{signal} (strength {strength}): RSI {rsi:.1f}, MACD {macd_trend}, "
        f"volume {volume_ratio:.1f}x, 5d momentum {momentum_5d:.1f}%"
    )


def run_technical_analysis(
    ticker: str,
    ticker_df=None,
) -> dict:
    """Compute indicators for a ticker and derive its signal, strength and summary.

    Pass `ticker_df` to reuse an already-downloaded frame. Needs at least 50
    bars; below that it returns a HOLD with empty indicators.

    Returns {signal, strength, summary, indicators}.
    """
    logger.info("technical_start", ticker=ticker)

    if ticker_df is not None:
        df = ticker_df
    else:
        df = safe_yf_download(ticker, period="12mo")

    if df is None or len(df) < 50:
        logger.warning("technical_no_data", ticker=ticker)
        return {
            "signal": "HOLD",
            "strength": 0,
            "summary": "Insufficient price data",
            "indicators": {},
        }

    extracted = extract_ticker_df(df, ticker)
    if extracted is not None:
        df = extracted
    df = df.dropna(subset=["Close", "Volume"])
    ind = compute_indicators(df)

    signal = _compute_signal(ind)
    strength = _compute_strength(ind)
    summary = _compute_summary(ind, signal, strength)

    logger.info("technical_done", ticker=ticker, signal=signal, strength=strength)
    return {
        "signal": signal,
        "strength": strength,
        "summary": summary,
        "indicators": ind,
    }
