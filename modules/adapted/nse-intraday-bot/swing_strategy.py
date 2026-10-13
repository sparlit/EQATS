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


"""
NSE F&O 5-Layer Smart Money Swing Strategy
==========================================
Layer 1 (2 pts): Market Structure — BoS (Break of Structure) + price above EMA200
Layer 2 (2 pts): FVG (Fair Value Gap) + bullish Order Block near price
Layer 3 (2 pts): Liquidity Grab (stop hunt) + OBV uptrend
Layer 4 (2 pts): Sector Momentum — sector above EMA20 + stock outperforming
Layer 5 (2 pts): Institutional bulk/block buys + options OI confluence

Total: 10 pts  |  Signal threshold: 7.0
"""
import numpy as np
import pandas as pd

# Trade parameters (kept as module-level for run_swing to import)
MAX_SL_PCT = 0.025  # 2.5%
T1_PCT = 0.06  # 6%
T2_PCT = 0.10  # 10%
MAX_HOLD = 15  # days


# ── helpers ──────────────────────────────────────────────────────


def _ema(series: pd.Series, n: int) -> pd.Series:
    return series.ewm(span=n, adjust=False).mean()


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff().fillna(0))
    return (direction * df["volume"]).cumsum()


def _swing_lows(low: pd.Series, n: int = 5) -> pd.Series:
    mask = pd.Series(False, index=low.index)
    for i in range(n, len(low) - n):
        if low.iloc[i] == low.iloc[i - n : i + n + 1].min():
            mask.iloc[i] = True
    return mask


# ── Layer 1: Market Structure (BOS + EMA200) ─────────────────────


def _layer1_structure(df: pd.DataFrame) -> tuple:
    score, reasons = 0.0, []
    close = df["close"]

    n_ema = min(len(df) - 1, 200)
    ema200 = _ema(close, n_ema)

    if float(close.iloc[-1]) > float(ema200.iloc[-1]):
        score += 1.0
        reasons.append("Price above EMA200 (uptrend)")

    if len(df) >= 40:
        recent_hh = float(df["high"].iloc[-20:].max())
        prev_hh = float(df["high"].iloc[-40:-20].max())
        if recent_hh > prev_hh:
            score += 1.0
            reasons.append("BoS — higher high in last 20 days")

    return score, reasons


# ── Layer 2: FVG + Order Block ───────────────────────────────────


def _layer2_fvg_ob(df: pd.DataFrame) -> tuple:
    score, reasons = 0.0, []
    close_now = float(df["close"].iloc[-1])

    # Bullish FVG: c[-i-2].high < c[-i].low, gap > 0.2% of price
    for i in range(2, min(len(df) - 2, 22)):
        c0 = df.iloc[-(i + 2)]
        c2 = df.iloc[-i]
        gap = float(c2["low"]) - float(c0["high"])
        if gap > close_now * 0.002:
            score += 1.0
            reasons.append("Bullish FVG present")
            break

    # Bullish OB: bearish candle before 2+ bullish candles, price retesting OB zone
    for i in range(3, min(len(df) - 2, 30)):
        c = df.iloc[-(i + 1)]
        n1 = df.iloc[-i]
        n2 = df.iloc[-(i - 1)]
        if (
            float(c["close"]) < float(c["open"])
            and float(n1["close"]) > float(n1["open"])
            and float(n2["close"]) > float(n2["open"])
        ):
            ob_top = max(float(c["open"]), float(c["close"]))
            ob_bot = min(float(c["open"]), float(c["close"]))
            if ob_bot <= close_now <= ob_top * 1.05:
                score += 1.0
                reasons.append("Price retesting bullish Order Block")
                break

    return score, reasons


# ── Layer 3: Liquidity Grab + OBV ────────────────────────────────


def _layer3_liq_obv(df: pd.DataFrame) -> tuple:
    score, reasons = 0.0, []

    if len(df) < 25:
        return 0.0, []

    # Swing lows in bars [-25 … -5] (exclude very recent bars)
    sl_mask = _swing_lows(df["low"].iloc[-25:-5], n=3)
    sl_prices = df["low"].iloc[-25:-5][sl_mask].values

    grab = False
    for sl_price in sl_prices:
        for j in range(-5, 0):
            bar = df.iloc[j]
            if float(bar["low"]) < sl_price * 0.9995 and float(bar["close"]) > sl_price:
                grab = True
                break
        if grab:
            break

    if grab:
        score += 1.0
        reasons.append("Liquidity grab below swing low")
    else:
        # Fallback: high-volume candle as impulse confirmation
        vol = df["volume"]
        avg_vol = float(vol.iloc[-20:-1].mean()) if len(df) >= 20 else float(vol.mean())
        if avg_vol > 0 and float(vol.iloc[-1]) > avg_vol * 1.8:
            score += 1.0
            reasons.append("Volume breakout (1.8× avg)")

    # OBV rising over last 5 bars
    obv_slope = float(_obv(df).iloc[-1]) - float(_obv(df).iloc[-5])
    if obv_slope > 0:
        score += 1.0
        reasons.append("OBV uptrend confirmed")

    return min(score, 2.0), reasons


# ── Main scorer ───────────────────────────────────────────────────


def score_swing(
    symbol: str,
    df: pd.DataFrame,
    sector_result: dict = None,
    bulk_result: dict = None,
    options_result: dict = None,
) -> dict | None:
    """
    Score one stock across all 5 SMC layers.
    Returns signal dict (score /10) or None if pre-filter fails.
    Caller applies the MIN_SCORE threshold (7.0).

    Layer 4 & 5 data must be fetched externally and passed in.
    """
    if len(df) < 50:
        return None

    close = float(df["close"].iloc[-1])
    if not (100 <= close <= 5000):
        return None

    layer_scores: dict[str, float] = {}
    all_reasons: list[str] = []

    # Layer 1
    l1, r1 = _layer1_structure(df)
    layer_scores["layer1"] = l1
    all_reasons.extend(r1)

    # Layer 2
    l2, r2 = _layer2_fvg_ob(df)
    layer_scores["layer2"] = l2
    all_reasons.extend(r2)

    # Layer 3
    l3, r3 = _layer3_liq_obv(df)
    layer_scores["layer3"] = l3
    all_reasons.extend(r3)

    # Layer 4: Sector Momentum
    l4, r4 = 0.0, []
    if sector_result:
        if sector_result.get("sector_above_ema"):
            l4 += 1.0
            r4.append(f"{sector_result.get('sector_name', 'Sector')} above EMA20")
        if sector_result.get("outperforming"):
            s5d = sector_result.get("stock_5d_pct", 0)
            x5d = sector_result.get("sector_5d_pct", 0)
            l4 += 1.0
            r4.append(f"Outperforms sector ({s5d:+.1f}% vs {x5d:+.1f}%)")
    layer_scores["layer4"] = l4
    all_reasons.extend(r4)

    # Layer 5: Bulk/Block Deals + Options OI
    l5, r5 = 0.0, []
    if bulk_result and bulk_result.get("pass"):
        l5 += 1.0
        buyers = ", ".join((bulk_result.get("buyers") or [])[:2])
        r5.append(f"Institutional buy: {buyers}" if buyers else "Institutional buy")

    if options_result:
        if options_result.get("pass"):
            l5 += 1.0
            pcr = options_result.get("pcr", 0)
            coc = (options_result.get("call_oi_chg") or 0) * 100
            r5.append(f"Options bullish — PCR {pcr:.2f} | CE OI +{coc:.0f}%")
        elif options_result.get("pcr") is not None:
            pcr = options_result.get("pcr", 0)
            if 0.8 <= pcr <= 1.3:
                l5 += 0.5
                r5.append(f"PCR neutral ({pcr:.2f})")

    layer_scores["layer5"] = min(l5, 2.0)
    all_reasons.extend(r5)

    total = round(sum(layer_scores.values()), 2)
    layers_passed = sum(1 for v in layer_scores.values() if v >= 1.0)

    if total < 4.0:
        return None

    # ── Trade parameters ─────────────────────────────────────────
    entry = round(close, 2)
    rec_low = float(df["low"].iloc[-10:].min())
    sl_raw = max(rec_low * 0.998, entry * (1 - MAX_SL_PCT))
    sl = round(sl_raw, 2)
    sl_pct = round((entry - sl) / entry * 100, 2)

    if sl_pct > MAX_SL_PCT * 100:
        sl = round(entry * (1 - MAX_SL_PCT), 2)
        sl_pct = round(MAX_SL_PCT * 100, 2)

    t1 = round(entry * (1 + T1_PCT), 2)
    t2 = round(entry * (1 + T2_PCT), 2)
    risk = entry - sl
    rr_t1 = round((t1 - entry) / risk, 2) if risk > 0 else 0
    rr_t2 = round((t2 - entry) / risk, 2) if risk > 0 else 0

    strength = "STRONG" if total >= 9.0 else "GOOD" if total >= 7.0 else "FAIR"

    ema21 = round(float(_ema(df["close"], 21).iloc[-1]), 2)

    return {
        "symbol": symbol,
        "score": total,
        "score_pct": round(total / 10 * 100, 1),
        "signal_strength": strength,
        "entry": entry,
        "sl": sl,
        "sl_pct": sl_pct,
        "t1": t1,
        "t2": t2,
        "rr_t1": rr_t1,
        "rr_t2": rr_t2,
        "layers_passed": layers_passed,
        "layer1": layer_scores["layer1"],
        "layer2": layer_scores["layer2"],
        "layer3": layer_scores["layer3"],
        "layer4": layer_scores["layer4"],
        "layer5": layer_scores["layer5"],
        "sector": (sector_result or {}).get("sector_name"),
        "bulk_buyers": ", ".join((bulk_result or {}).get("buyers", [])[:2]),
        "pcr": (options_result or {}).get("pcr"),
        "call_oi_chg": (options_result or {}).get("call_oi_chg"),
        "put_oi_chg": (options_result or {}).get("put_oi_chg"),
        "reasons": all_reasons[:6],
        "ema21": ema21,
        # Legacy compat fields
        "rsi": None,
        "vol_ratio": None,
        "macd_bullish": None,
        "week": None,  # filled by run_swing
        "scan_date": None,  # filled by run_swing
    }
