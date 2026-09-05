import datetime
from models import Asset, DailyPrice, Suggestion, get_session

def calculate_rsi(prices: list, period: int = 14) -> float:
    """Calculate RSI from a list of closing prices (oldest to newest)."""
    if len(prices) < period + 1:
        return 50.0  # Neutral if not enough data
    deltas = [prices[i+1] - prices[i] for i in range(len(prices)-1)]
    gains = [d for d in deltas[-period:] if d > 0]
    losses = [-d for d in deltas[-period:] if d < 0]
    avg_gain = sum(gains) / period if gains else 0
    avg_loss = sum(losses) / period if losses else 0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_score(price: DailyPrice) -> float:
    """
    Enhanced scoring using:
    - Price momentum
    - Volume surge
    - RSI signal
    - Distance from 20-day MA (trend)
    - Close strength (close vs high/low range)
    - Gap up signal
    """
    session = get_session()
    twenty_days_ago = price.date - datetime.timedelta(days=20)

    recent_prices = (
        session.query(DailyPrice)
        .filter(
            DailyPrice.asset_id == price.asset_id,
            DailyPrice.date >= twenty_days_ago,
            DailyPrice.date < price.date,
            DailyPrice.is_holiday == False
        )
        .order_by(DailyPrice.date.asc())
        .all()
    )
    session.close()

    # --- 1. Momentum: (close - open) / open ---
    # Fall back to previous close if open is missing (partial data)
    eff_open = price.open if price.open is not None else (recent_prices[-1].close if recent_prices else price.close)
    momentum = (price.close - eff_open) / eff_open if eff_open else 0
    momentum = max(min(momentum, 0.1), -0.1)  # Cap at ±10%

    # --- 2. Volume surge vs 20-day avg ---
    volumes = [p.volume for p in recent_prices if p.volume]
    avg_volume = sum(volumes) / len(volumes) if volumes else price.volume
    volume_factor = min(price.volume / avg_volume, 3.0) if avg_volume else 1.0  # Cap at 3x

    # --- 3. RSI signal (favour 40–60 range, penalise overbought >70) ---
    closes = [p.close for p in recent_prices if p.close is not None] + [price.close]
    rsi = calculate_rsi(closes)
    if rsi < 30:
        rsi_score = 0.8   # Oversold — potential bounce
    elif rsi < 50:
        rsi_score = 1.0   # Healthy momentum building
    elif rsi < 65:
        rsi_score = 0.9   # Strong but not overextended
    else:
        rsi_score = 0.5   # Overbought — risky entry

    # --- 4. Price vs 20-day MA (trend confirmation) ---
    ma20_closes = [p.close for p in recent_prices if p.close is not None]
    ma20 = sum(ma20_closes) / len(ma20_closes) if ma20_closes else price.close
    ma_factor = price.close / ma20 if ma20 else 1.0
    ma_score = min(ma_factor, 1.1)  # Reward being above MA, cap the bonus

    # --- 5. Close strength: where did it close in the day's range? ---
    # Use available high/low; if missing, assume a neutral 0.5 close strength
    hi = price.high if price.high is not None else price.close
    lo = price.low if price.low is not None else price.close
    day_range = hi - lo
    close_strength = (price.close - lo) / day_range if day_range else 0.5
    # 1.0 = closed at high (bullish), 0.0 = closed at low (bearish)

    # --- 6. Gap up signal ---
    prev_close = recent_prices[-1].close if recent_prices else eff_open
    gap = (eff_open - prev_close) / prev_close if prev_close else 0
    gap_score = 1.0 + min(gap, 0.05)  # Reward gap up, cap bonus at 5%

    # --- Composite Score (tunable weights) ---
    score = (
        momentum      * 0.25 +
        (volume_factor - 1) * 0.15 +  # Normalise so 1x volume = 0 contribution
        rsi_score     * 0.20 +
        ma_score      * 0.20 +
        close_strength * 0.10 +
        gap_score     * 0.10
    )

    return score

def generate_suggestions(target_date: datetime.date = None, top_n: int = 50):
    session = get_session()
    if target_date is None:
        target_date = datetime.date.today() - datetime.timedelta(days=1)

    # Exclude mutual funds; they are scored separately via mutual_funds.db
    # Also exclude holiday placeholder rows
    prices = (
        session.query(DailyPrice)
        .join(Asset, DailyPrice.asset_id == Asset.id)
        .filter(
            DailyPrice.date == target_date,
            Asset.type != 'mutual_fund',
            DailyPrice.is_holiday == False  # <-- Filter out holidays
        )
        .all()
    )
    suggestions = []
    for price in prices:
        # Skip prices with no close (cannot score without a price)
        if price.close is None:
            continue
        score = calculate_score(price)
        eff_open = price.open if price.open is not None else price.close
        momentum_pct = (price.close - eff_open) / eff_open if eff_open else 0
        hi = price.high if price.high is not None else price.close
        lo = price.low if price.low is not None else price.close
        day_range = hi - lo
        close_strength = (price.close - lo) / day_range if day_range else 0.5
        reasoning = (
            f"Momentum: {momentum_pct:.2%} | "
            f"Volume: {price.volume:,} | "
            f"Close strength: {close_strength:.2%}"
        )
        suggestions.append((price.asset.symbol, score, reasoning))

    suggestions.sort(key=lambda x: x[1], reverse=True)
    top = suggestions[:top_n]

    for symbol, score, reasoning in top:
        asset = session.query(Asset).filter_by(symbol=symbol).first()
        if asset:
            existing = (
                session.query(Suggestion)
                .filter_by(date=target_date, asset_id=asset.id)
                .first()
            )
            if not existing:
                sug = Suggestion(date=target_date, asset_id=asset.id, score=score, reasoning=reasoning)
                session.add(sug)
    session.commit()
    session.close()
    return top



