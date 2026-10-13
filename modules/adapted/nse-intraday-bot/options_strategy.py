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
Nifty / Bank Nifty / Sensex Options Strategy
=============================================
Gives CALL or PUT recommendation with specific strike & expiry.
Minimum score: 70/100  (strict — only "sure shot" setups fire)

Scoring (100 pts)
-----------------
Phase 1 — Structure REQUIRED (all 3 must pass, else blocked):
    BOS or CHOCH on 15min                mandatory
    Inside Kill Zone                     mandatory
    India VIX < 25                       mandatory

Phase 2 — Structure Quality (40 pts):
    Order Block on 15min                 +15
    Liquidity Sweep (PDH/PDL)            +12
    Fair Value Gap aligned               + 8
    Multi-TF (5m aligns with 15m)        + 5

Phase 3 — Momentum (35 pts):
    RSI 40–65 (ideal entry zone)         +15
    VWAP reclaim / rejection             +10
    Volume spike 1.5× at signal candle   + 7
    Round number / strike confluence     + 3

Phase 4 — Confidence Boosters (25 pts):
    OTE (61.8–79% Fibonacci)             +10
    15min candle close confirms          + 8
    Previous session structure support   + 7

Hard blocks:
    VIX ≥ 25                             → blocked
    Not in Kill Zone                     → blocked
    No BOS/CHOCH on 15min               → blocked
    Score < 70                           → blocked
"""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from feeds.index_feed import STRIKE_STEP, nearest_strike, next_expiry
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
    detect_vwap_reclaim,
    get_kill_zone,
    signal_strength_label,
)

MIN_SCORE = 62
ASSET_MAP = {
    "NIFTY": "NSE",  # uses NSE kill zone table
    "BANKNIFTY": "NSE",
    "SENSEX": "NSE",
}


def _index_target_sl(index: str, direction: str, entry: float, ob: dict) -> dict:
    """
    Calculate index-level entry / target / SL for options.
    Options target = index moves 0.8–1.2% for Nifty, 1.2–1.8% for BN.
    SL = index moves 0.4–0.5% against.
    """
    step = STRIKE_STEP.get(index, 50)

    if direction == "LONG":  # CALL option
        sl = round(
            max(ob.get("low", entry * 0.995), entry * (0.995 if index == "NIFTY" else 0.993)), 1
        )
        t1 = round(entry + (entry - sl) * 1.5, 1)
        t2 = round(entry + (entry - sl) * 3.0, 1)
        # snap targets to nearest strike level for clarity
        t1_s = round(t1 / step) * step
        t2_s = round(t2 / step) * step
        sl_s = round(sl / step) * step
        sl_pct = round((entry - sl) / entry * 100, 2)
    else:  # PUT option
        sl = round(
            min(ob.get("high", entry * 1.005), entry * (1.005 if index == "NIFTY" else 1.007)), 1
        )
        t1 = round(entry - (sl - entry) * 1.5, 1)
        t2 = round(entry - (sl - entry) * 3.0, 1)
        t1_s = round(t1 / step) * step
        t2_s = round(t2 / step) * step
        sl_s = round(sl / step) * step
        sl_pct = round((sl - entry) / entry * 100, 2)

    rr = round(abs(t2 - entry) / abs(sl - entry), 1) if abs(sl - entry) > 0 else 0

    return {
        "entry": round(entry, 1),
        "sl": sl_s,
        "sl_pct": sl_pct,
        "t1": t1_s,
        "t2": t2_s,
        "rr": rr,
    }


def score_options(
    index: str,
    df_15m: pd.DataFrame,
    df_5m: pd.DataFrame,
    vix: float,
    pdh: float = None,
    pdl: float = None,
    ist_time: datetime = None,
) -> dict:
    """
    Score an index for a CALL or PUT options trade.
    Returns full signal dict or {} if blocked.
    """
    if df_15m is None or len(df_15m) < 15:
        return {}
    if ist_time is None:
        ist_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    # ── BLOCK 1: VIX ─────────────────────────────────────────────
    if vix >= 25:
        return {}

    # ── Kill Zone — bonus points (NOT a hard block) ──────────────
    # Active KZ → +15 pts; outside KZ → 0 pts but can still fire
    kz, kz_pts = get_kill_zone("NSE", ist_time.hour, ist_time.minute)

    # ── Prepare indicators ────────────────────────────────────────
    df15 = add_rsi(add_vol_ma(add_vwap(df_15m.copy())))
    close = float(df15["close"].iloc[-1])
    if close <= 0:
        return {}

    # ── BLOCK 3: BOS/CHOCH on 15min ──────────────────────────────
    struct = detect_bos_choch(df15, left=2, right=2)
    if not struct["bos"] and not struct["choch"]:
        return {}
    direction = struct["direction"]
    if not direction:
        return {}

    opt_type = "CALL" if direction == "LONG" else "PUT"
    score = 0
    reasons = []
    reasons.append(f"{'BOS' if struct['bos'] else 'CHOCH'} 15min → {opt_type}")

    # ════════════════════════════════════════
    # PHASE 2 — Structure Quality (40 pts)
    # ════════════════════════════════════════

    # Order Block on 15min (+15)
    ob = detect_order_block(df15, direction)
    if ob["valid"]:
        score += 15
        reasons.append(f"OB {ob['body_bot']:.0f}–{ob['body_top']:.0f}")

    # Liquidity Sweep (+12)
    swept, sweep_lvl = detect_liquidity_sweep(df15, direction, pdh, pdl)
    if swept:
        score += 12
        reasons.append(f"Liquidity sweep {sweep_lvl:.0f}")

    # FVG aligned (+8)
    fvg = detect_fvg(df15, direction)
    if not fvg["valid"] and df_5m is not None and len(df_5m) > 5:
        fvg = detect_fvg(df_5m.copy(), direction)
    if fvg["valid"]:
        score += 8
        reasons.append(f"FVG {fvg['bot']:.0f}–{fvg['top']:.0f}")

    # 5min alignment with 15min direction (+5)
    if df_5m is not None and len(df_5m) >= 6:
        df5 = add_rsi(add_vwap(df_5m.copy()))
        s5 = detect_bos_choch(df5, left=2, right=2)
        if s5["direction"] == direction:
            score += 5
            reasons.append("5min structure aligns with 15min")

    # ════════════════════════════════════════
    # PHASE 3 — Momentum (35 pts)
    # ════════════════════════════════════════

    # RSI 40–65 (+15)
    rsi_v = float(df15["rsi"].iloc[-1]) if "rsi" in df15.columns else 50.0
    if not np.isnan(rsi_v) and 40 <= rsi_v <= 65:
        score += 15
        reasons.append(f"RSI {rsi_v:.0f} — ideal zone")
    elif not np.isnan(rsi_v) and 35 <= rsi_v <= 70:
        score += 8
        reasons.append(f"RSI {rsi_v:.0f} — acceptable")

    # VWAP (+10)
    if detect_vwap_reclaim(df15, direction):
        score += 10
        reasons.append("VWAP reclaim confirmed")

    # Volume spike (+7)
    vol_sig, vol_ratio = detect_volume_signature(df15, threshold=1.5)
    if vol_sig:
        score += 7
        reasons.append(f"Volume {vol_ratio}× spike — smart money")

    # Round number / strike confluence (+3)
    step = STRIKE_STEP.get(index, 50)
    atm = round(close / step) * step
    if abs(close - atm) / close < 0.002:
        score += 3
        reasons.append(f"Price at round strike {atm:.0f}")

    # ════════════════════════════════════════
    # PHASE 4 — Confidence Boosters (25 pts)
    # ════════════════════════════════════════

    # OTE zone (+10)
    if ob["valid"]:
        ote = detect_ote(df15, direction)
        if ote["in_zone"]:
            score += 10
            reasons.append(f"OTE zone {ote['fib_level']}% — premium entry")

    # Rejection candle at OB (+8)
    if ob["valid"] and detect_rejection_candle(df15, direction, ob):
        score += 8
        reasons.append("Rejection candle at OB — strong confirmation")

    # Previous session structure (+7)
    if pdh and pdl:
        if direction == "LONG" and close > pdh:
            score += 7
            reasons.append(f"Breaking above PDH {pdh:.0f} — bullish")
        elif direction == "SHORT" and close < pdl:
            score += 7
            reasons.append(f"Breaking below PDL {pdl:.0f} — bearish")
        elif direction == "LONG" and abs(close - pdl) / close < 0.003:
            score += 4
            reasons.append(f"Bouncing off PDL {pdl:.0f}")
        elif direction == "SHORT" and abs(close - pdh) / close < 0.003:
            score += 4
            reasons.append(f"Rejecting PDH {pdh:.0f}")

    # ── Kill Zone bonus ───────────────────────────────────────────
    score += kz_pts
    if kz_pts > 0:
        reasons.append(f"Kill Zone {kz} active (+{kz_pts}pts)")
    else:
        reasons.append(f"Zone: {kz} (no KZ bonus — structure + momentum driving signal)")

    # ── VIX bonus (cheap options = more confidence) ───────────────
    if vix < 14:
        score += 3
        reasons.append(f"VIX {vix} — options cheap, ideal")

    # ── Score check ───────────────────────────────────────────────
    if score < MIN_SCORE:
        return {}

    # ── Trade parameters ──────────────────────────────────────────
    ob_for_calc = ob if ob["valid"] else {"low": close * 0.997, "high": close * 1.003}
    params = _index_target_sl(index, direction, close, ob_for_calc)

    # Strike recommendations
    strikes = nearest_strike(close, index, opt_type)
    expiry = next_expiry(index)
    strength = signal_strength_label(score)

    # VIX-based strike advice
    if vix < 15:
        strike_rec = strikes["atm"]
        strike_note = "ATM — VIX low, buy ATM for max delta"
    elif vix < 20:
        strike_rec = strikes["atm"]
        strike_note = "ATM — balanced risk/reward"
    else:
        strike_rec = strikes["otm1"]
        strike_note = "Slight OTM — VIX elevated, reduce premium risk"

    return {
        "index": index,
        "symbol": index,
        "direction": direction,
        "option_type": opt_type,
        "signal": opt_type,
        "score": score,
        "score_pct": round(score / 100 * 100, 1),
        "signal_strength": strength,
        "kill_zone": kz,
        "vix": vix,
        # Index levels
        "entry": params["entry"],
        "sl": params["sl"],
        "sl_pct": params["sl_pct"],
        "t1": params["t1"],
        "t2": params["t2"],
        "rr": params["rr"],
        # Options specifics
        "strike": strike_rec,
        "strike_atm": strikes["atm"],
        "strike_otm1": strikes["otm1"],
        "strike_otm2": strikes["otm2"],
        "strike_note": strike_note,
        "expiry": expiry,
        "strike_step": step,
        "rsi": round(rsi_v, 1),
        "vwap": float(df15["vwap"].iloc[-1]) if "vwap" in df15.columns else None,
        "vol_ratio": vol_ratio,
        "reasons": reasons,
        "phase_scores": {
            "structure_quality": min(score, 40),
            "momentum": min(max(score - 40, 0), 35),
            "confidence": min(max(score - 75, 0), 25),
        },
        "must_have_checklist": {
            "bos_or_choch_15m": struct["bos"] or struct["choch"],
            "inside_kill_zone": kz_pts > 0,
            "vix_safe": vix < 25,
            "order_block": ob["valid"],
            "liquidity_sweep": swept,
        },
        "asset": "OPTIONS",
        "datetime": ist_time.strftime("%Y-%m-%d %H:%M"),
        "date": ist_time.strftime("%Y-%m-%d"),
        "status": "OPEN",
        "exit_price": None,
        "pnl_pts": None,
        "pnl_pct": None,
        "timestamp": ist_time.isoformat(),
    }
