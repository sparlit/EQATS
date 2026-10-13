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
Bitcoin (BTCUSDT) Strategy — SMC + ICT + Price Action
======================================================
Timeframes : Weekly (macro) → 4H (structure) → 1H (OB) → 15min (entry)
Scoring    : 150-point scale, minimum 65 to trade

Required to trade:
  Phase 1: BOS/CHOCH on 4H  +  Order Block  +  Liquidity Sweep (all 3)
  Phase 2: Inside Crypto Kill Zone (KZ-A / KZ-L / KZ-NY)

Hard rules:
  SL max 1.5 % of price
  Min RR  1:3.0 (T1)  and  1:5.0 (T2)
  Max 3 trades per 24-hour period
  Funding rate check mandatory for every long entry
  No trade when Fear & Greed < 15 or > 85 (unless score >= 85)
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from shared.smc_engine import (
    add_rsi,
    add_vol_ma,
    add_vwap,
    detect_bos_choch,
    detect_fvg,
    detect_liquidity_sweep,
    detect_order_block,
    detect_ote,
    detect_rejection_candle,
    detect_volume_signature,
    get_kill_zone,
    signal_strength_label,
)

# ── Asset constants ─────────────────────────────────────────────
ASSET = "BTC"
MIN_SCORE = 60
MAX_SL_PCT = 0.015  # 1.5 % (crypto is more volatile)
MIN_RR_T1 = 3.0
MIN_RR_T2 = 5.0

_ROUND_LEVELS = [
    10_000,
    15_000,
    20_000,
    25_000,
    30_000,
    35_000,
    40_000,
    45_000,
    50_000,
    55_000,
    60_000,
    65_000,
    70_000,
    75_000,
    80_000,
    85_000,
    90_000,
    95_000,
    100_000,
    110_000,
    120_000,
]


# ── Weekly candle direction ─────────────────────────────────────


def _weekly_bullish(df_weekly: pd.DataFrame) -> bool:
    if df_weekly.empty or len(df_weekly) < 3:
        return False
    last = df_weekly.iloc[-1]
    return float(last["close"]) > float(last["open"])


# ── CME gap check ───────────────────────────────────────────────


def _cme_gap_below_is_magnet(cme_gap: dict, entry: float) -> bool:
    """
    If there is an unfilled CME gap directly below our entry,
    it acts as a price magnet — avoid bullish entries.
    """
    below = cme_gap.get("nearest_gap_below")
    if below and entry is not None:
        gap_pct = (entry - below) / entry
        return gap_pct < 0.03  # within 3% below is dangerous
    return False


# ── Main scoring function ────────────────────────────────────────


def score_btc(
    df_weekly: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_1h: pd.DataFrame,
    df_15m: pd.DataFrame,
    pdh=None,
    pdl=None,
    funding: dict = None,
    fear_greed: dict = None,
    cme_gap: dict = None,
    ist_time: datetime = None,
) -> dict:
    """
    Score Bitcoin for LONG or SHORT.
    Returns full signal dict or {} if blocked.
    """
    if funding is None:
        funding = {}
    if fear_greed is None:
        fear_greed = {}
    if cme_gap is None:
        cme_gap = {}

    if len(df_4h) < 12 or len(df_15m) < 10:
        return {}

    if ist_time is None:
        ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    # ── Kill zone — bonus points only (NOT a hard block) ─────────
    # KZ active  → +15 pts added in Phase 2
    # KZ inactive → 0 pts, still fires if 4H BOS + OB + other signals align
    kill_zone, kz_pts = get_kill_zone(ASSET, ist_time.hour, ist_time.minute)

    # ── Prepare indicators on 15min ────────────────────────────
    df15 = add_rsi(add_vol_ma(add_vwap(df_15m.copy())))
    close = float(df15["close"].iloc[-1])
    if close <= 0:
        return {}

    # ── Fear & Greed extreme block ──────────────────────────────
    fg_val = fear_greed.get("value", 50)
    fg_extreme = fg_val < 15 or fg_val > 85

    # ════════════════════════════════════════
    # PHASE 1 — SMC Structure on 4H (REQUIRED)
    # ════════════════════════════════════════

    # Try 4H BOS/CHOCH first — gives full 25 pts
    struct = detect_bos_choch(df_4h, left=3, right=3)
    if not struct["bos"] and not struct["choch"]:
        # Fallback: 1H BOS/CHOCH — gives 18 pts (less conviction than 4H)
        struct = detect_bos_choch(df_1h, left=2, right=2)
        if not struct["bos"] and not struct["choch"]:
            return {}
        direction = struct["direction"]
        if not direction:
            return {}
        phase1 = 18
        reasons = [f"{'BOS' if struct['bos'] else 'CHOCH'} confirmed 1H ({direction}) — 4H pending"]
    else:
        direction = struct["direction"]
        if not direction:
            return {}
        phase1 = 25
        reasons = [f"{'BOS' if struct['bos'] else 'CHOCH'} confirmed 4H ({direction})"]

    # Order Block — 4H first, then 1H fallback
    ob = detect_order_block(df_4h, direction)
    if not ob["valid"]:
        ob = detect_order_block(df_1h, direction)
    if not ob["valid"]:
        return {}
    phase1 += 20
    reasons.append(f"Unmitigated OB {ob['body_bot']:.2f}–{ob['body_top']:.2f}")

    # Liquidity Sweep — bonus points (not a hard block)
    swept, sweep_lvl = detect_liquidity_sweep(df_4h, direction, pdh, pdl)
    if not swept:
        swept, sweep_lvl = detect_liquidity_sweep(df_1h, direction, pdh, pdl)
    if not swept:
        swept, sweep_lvl = detect_liquidity_sweep(df_15m, direction, pdh, pdl)
    if swept:
        phase1 += 15
        reasons.append(f"Liquidity sweep at {sweep_lvl:.2f}")
    else:
        reasons.append("No liquidity sweep — structure + OB entry")

    # ════════════════════════════════════════
    # PHASE 2 — ICT + Crypto-specific filters
    # ════════════════════════════════════════

    phase2 = kz_pts
    reasons.append(f"Kill Zone {kill_zone} active (+{kz_pts}pts)")

    # Funding rate (+12 pts)
    rate_pct = funding.get("rate_pct", 0)
    if direction == "LONG":
        if funding.get("danger_for_longs", False):
            # Funding too positive — do NOT block, but don't award points
            reasons.append(f"WARNING: Funding {rate_pct:.3f}% — expensive for longs")
        elif funding.get("squeeze_potential", False) or rate_pct <= 0:
            phase2 += 12
            reasons.append(f"Funding {rate_pct:.3f}% — favourable for longs")
        else:
            phase2 += 6  # neutral funding = half pts
            reasons.append(f"Funding {rate_pct:.3f}% — neutral")
    else:  # SHORT — positive funding helps (shorts receive)
        if rate_pct > 0.02:
            phase2 += 12
            reasons.append(f"Funding {rate_pct:.3f}% — favourable for shorts")
        else:
            phase2 += 4

    # OTE on 1H (+10 pts)
    ote = detect_ote(df_1h, direction)
    if ote["in_zone"]:
        phase2 += 10
        reasons.append(f"OTE zone 61.8–79% fib (1H, {ote['fib_level']}%)")

    # FVG on 1H or 15min (+8 pts)
    fvg = detect_fvg(df_1h, direction)
    if not fvg["valid"]:
        fvg = detect_fvg(df_15m, direction)
    if fvg["valid"]:
        phase2 += 8
        reasons.append(f"FVG {fvg['bot']:.2f}–{fvg['top']:.2f}")

    # Fear & Greed 25–60 (+7 pts)
    if fear_greed.get("in_ideal_range", True) and not fg_extreme:
        phase2 += 7
        reasons.append(f"Fear & Greed {fg_val} — ideal zone (25–60)")
    elif fg_extreme:
        reasons.append(f"Fear & Greed {fg_val} — EXTREME (caution)")

    # ════════════════════════════════════════
    # PHASE 3 — Price Action + Boosters
    # ════════════════════════════════════════

    phase3 = 0

    # Rejection candle at 4H OB on 1H TF (+10 pts)
    if detect_rejection_candle(df_1h, direction, ob):
        phase3 += 10
        reasons.append("Strong rejection at 4H OB (1H candle)")
    elif detect_rejection_candle(df_15m, direction, ob):
        phase3 += 6
        reasons.append("Rejection candle at OB (15min)")

    # 15min → 1H → 4H structure alignment (+7 pts)
    r5 = df_15m.iloc[-5:]
    if direction == "LONG" and (
        r5["high"].iloc[-1] > r5["high"].iloc[-3] and r5["low"].iloc[-1] > r5["low"].iloc[-3]
    ):
        phase3 += 7
        reasons.append("15min HH+HL aligns with 4H bullish bias")
    elif direction == "SHORT" and (
        r5["high"].iloc[-1] < r5["high"].iloc[-3] and r5["low"].iloc[-1] < r5["low"].iloc[-3]
    ):
        phase3 += 7
        reasons.append("15min LH+LL aligns with 4H bearish bias")

    # CME gap awareness: unfilled gap above = T2 target (+5 pts)
    gap_above = cme_gap.get("nearest_gap_above")
    gap_below = cme_gap.get("nearest_gap_below")
    if direction == "LONG" and gap_above:
        phase3 += 5
        reasons.append(f"CME gap target above at ${gap_above:,.0f}")
    elif direction == "SHORT" and gap_below:
        phase3 += 5
        reasons.append(f"CME gap target below at ${gap_below:,.0f}")

    # Volume spike (+5 pts)
    vol_sig, vol_ratio = detect_volume_signature(df15)
    if vol_sig:
        phase3 += 5
        reasons.append(f"Volume {vol_ratio}x spike at reaction zone")

    # Round number confluence (+5 pts)
    for lvl in _ROUND_LEVELS:
        if abs(close - lvl) / close < 0.003:
            phase3 += 5
            reasons.append(f"Round number ${lvl:,}")
            break

    # Weekly candle structure (+3 pts)
    if direction == "LONG" and _weekly_bullish(df_weekly):
        phase3 += 3
        reasons.append("Weekly candle structure is bullish")
    elif direction == "SHORT" and not _weekly_bullish(df_weekly):
        phase3 += 3
        reasons.append("Weekly candle structure is bearish")

    # RSI 40–65 (+3 pts)
    rsi_v = float(df15["rsi"].iloc[-1]) if "rsi" in df15.columns else 50.0
    if not np.isnan(rsi_v) and 40 <= rsi_v <= 65:
        phase3 += 3
        reasons.append(f"RSI {rsi_v:.0f} — ideal zone")

    # ── Extreme Fear/Greed override ────────────────────────────
    if fg_extreme:
        # Only allow trade if score is very high AND 4H OB is present
        total_prelim = phase1 + phase2 + phase3
        if total_prelim < 85:
            return {}  # BLOCKED: extreme sentiment without conviction

    # ── Total & threshold ──────────────────────────────────────
    total = phase1 + phase2 + phase3
    if total < MIN_SCORE:
        return {}

    # ── Trade parameters ───────────────────────────────────────
    entry = round(close, 2)
    risk = 0.0

    if direction == "LONG":
        # Block if CME gap is directly below (price magnet risk)
        if _cme_gap_below_is_magnet(cme_gap, entry):
            reasons.append("CAUTION: Unfilled CME gap below entry")
        sl = round(max(ob["low"] * 0.999, entry * (1 - MAX_SL_PCT)), 2)
        sl_pct = round((entry - sl) / entry * 100, 3)
        if sl_pct > MAX_SL_PCT * 100 or sl >= entry:
            return {}
        risk = entry - sl
        t1 = round(entry + risk * MIN_RR_T1, 2)
        t2 = round(entry + risk * MIN_RR_T2, 2)
        # Use CME gap above as T2 if closer
        if gap_above and entry < gap_above < t2:
            t2 = round(gap_above, 2)
    else:
        sl = round(min(ob["high"] * 1.001, entry * (1 + MAX_SL_PCT)), 2)
        sl_pct = round((sl - entry) / entry * 100, 3)
        if sl_pct > MAX_SL_PCT * 100 or sl <= entry:
            return {}
        risk = sl - entry
        t1 = round(entry - risk * MIN_RR_T1, 2)
        t2 = round(entry - risk * MIN_RR_T2, 2)
        if gap_below and entry > gap_below > t2:
            t2 = round(gap_below, 2)

    if risk <= 0:
        return {}
    rr_t1 = round(abs(t1 - entry) / risk, 2)
    rr_t2 = round(abs(t2 - entry) / risk, 2)
    if rr_t1 < MIN_RR_T1 or rr_t2 < MIN_RR_T2:
        return {}

    pct = round(total / 150 * 100, 1)
    strength = signal_strength_label(total)
    vwap_v = round(float(df15["vwap"].iloc[-1]), 2) if "vwap" in df15.columns else None

    return {
        "asset": ASSET,
        "symbol": "BTCUSDT",
        "direction": direction,
        "signal": "BUY" if direction == "LONG" else "SELL",
        "score": total,
        "score_pct": pct,
        "signal_strength": strength,
        "blocked_reason": None,
        "kill_zone": kill_zone,
        "funding_rate": funding.get("rate_pct", 0),
        "fear_greed_index": fg_val,
        "phase_scores": {
            "smc_structure": phase1,
            "ict_crypto_filters": phase2,
            "pa_boosters": phase3,
        },
        "must_have_checklist": {
            "bos_or_choch_4h": struct["bos"] or struct["choch"],
            "order_block_valid": ob["valid"],
            "liquidity_sweep": swept,
            "inside_kill_zone": kz_pts > 0,
        },
        "trade_params": {
            "entry": entry,
            "sl": sl,
            "sl_pct": sl_pct,
            "t1": t1,
            "t2": t2,
            "rr_t1": rr_t1,
            "rr_t2": rr_t2,
        },
        "cme_gap": cme_gap,
        # backward compat
        "entry": entry,
        "target": t2,
        "t1": t1,
        "sl": sl,
        "rr": rr_t2,
        "reasons": reasons,
        "rsi": round(rsi_v, 1),
        "vwap": vwap_v,
        "vol_ratio": vol_ratio,
        "confidence": strength,
        "timestamp": ist_time.isoformat(),
    }
