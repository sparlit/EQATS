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
John Crane — Advanced Swing Trading.
Classified: SWING.

Methods (see METHODS list below):
  reaction_swing      — detect completed reaction swing
  time_forecast       — Reverse Count → Forward Count → reversal date
  action_reaction     — geometric projection lines
  retracement_window  — 60% / 30% retracement zones
  two_day_rule        — 2 consecutive same-colour days
  peg_leg             — 20d extreme + 3d separation
  gap_and_go          — bullish/bearish gap continuation
  gap_reversal        — gap against trend that reverses
  trail_day           — confirmation bar after reversal date
  continuation_gap    — breakaway gap on reversal/trail day
  major_reversal      — 10d extreme + 3 consecutive same-colour closes
  ssto_divergence     — 20-period stochastic price/osc divergence
  master_engine       — Time × Price × Pattern triple convergence

Signal shape (from traders/__init__ docstring).
"""
import db
import pandas as pd
from log_utils import get_logger
from traders import base as B
from universe_helper import band_universe

log = get_logger("trader.john_crane")

SLUG = "john_crane"
NAME = "John Crane"
PILLAR = "swing"
SOURCE = "Advanced Swing Trading (2002)"

METHODS = [
    {
        "id": "reaction_swing",
        "name": "Reaction Swing",
        "description": "Detect completed counter-trend reaction swing (B→C).",
        "direction": "both",
    },
    {
        "id": "time_forecast",
        "name": "Reverse → Forward Count",
        "description": "Project next reversal date from prior swing length.",
        "direction": "both",
    },
    {
        "id": "action_reaction",
        "name": "Action / Reaction Lines",
        "description": "Andrews/Babson parallel line projection.",
        "direction": "both",
    },
    {
        "id": "retracement_window",
        "name": "Retracement Window",
        "description": "60% (standard) or 30% (strong trend) zone.",
        "direction": "both",
    },
    {
        "id": "two_day_rule",
        "name": "Two-Day Rule",
        "description": "2 consecutive same-colour days → 50% trigger.",
        "direction": "both",
    },
    {
        "id": "peg_leg",
        "name": "Peg-Leg",
        "description": "20d extreme ≥3 days after prior pivot; fade 3-5 ticks.",
        "direction": "both",
    },
    {
        "id": "gap_and_go",
        "name": "Gap and Go",
        "description": "Gap on day 2 in same direction, unfilled.",
        "direction": "both",
    },
    {
        "id": "gap_reversal",
        "name": "Gap Reversal",
        "description": "Gap against prior bar's trend, close reverses.",
        "direction": "both",
    },
    {
        "id": "trail_day",
        "name": "Trail Day Confirmation",
        "description": "Bar after reversal date confirms via close vs open.",
        "direction": "both",
    },
    {
        "id": "continuation_gap",
        "name": "Continuation Gapping",
        "description": "Breakaway gap on reversal/trail day → 2-3d hold.",
        "direction": "both",
    },
    {
        "id": "major_reversal",
        "name": "Major Reversal",
        "description": "10d extreme + ≥3 consecutive same-colour closes.",
        "direction": "both",
    },
    {
        "id": "ssto_divergence",
        "name": "SSTO 20 Divergence",
        "description": "Price vs 20-period smoothed stochastic divergence.",
        "direction": "both",
    },
    {
        "id": "master_engine",
        "name": "Master Decision Engine",
        "description": "Time × Price × Pattern convergence.",
        "direction": "both",
    },
]


# ============================================================
# Detection helpers (operate on the same bars list)
# ============================================================
def _reaction_swing(bars, trend_direction):
    """Return (B, C, is_confirmed) or (None, None, False)."""
    if len(bars) < 10:
        return None, None, False
    closes = [b["Close"] for b in bars]
    if trend_direction == "DOWN":
        lows = B.find_pivot_lows(closes, k=3)
        if not lows:
            return None, None, False
        cand_B = lows[-1]
        seg = closes[cand_B["index"] :]
        if not seg:
            return None, None, False
        rel_max = max(range(len(seg)), key=lambda i: seg[i])
        cand_C = {"index": cand_B["index"] + rel_max, "value": float(seg[rel_max])}
        if cand_C["index"] - cand_B["index"] + 1 < 3:
            return None, None, False
        b_idx, c_idx = cand_B["index"], cand_C["index"]
        if c_idx + 2 >= len(bars):
            return cand_B, cand_C, False
        rule_a = bars[c_idx + 1]["Close"] < cand_C["value"] and bars[c_idx + 2]["Close"] < bars[c_idx + 1]["Close"]
        lows_arr = [b["Low"] for b in bars]
        highs_arr = [b["High"] for b in bars]
        rule_b = B.check_trendline_break_lows(highs_arr, lows_arr, closes, b_idx, c_idx)
        rule_c = any(b["Close"] < cand_B["value"] for b in bars[c_idx + 1 :])
        return cand_B, cand_C, (rule_a or rule_b or rule_c)
    # UP
    highs = B.find_pivot_highs(closes, k=3)
    if not highs:
        return None, None, False
    cand_B = highs[-1]
    seg = closes[cand_B["index"] :]
    if not seg:
        return None, None, False
    rel_min = min(range(len(seg)), key=lambda i: seg[i])
    cand_C = {"index": cand_B["index"] + rel_min, "value": float(seg[rel_min])}
    if cand_C["index"] - cand_B["index"] + 1 < 3:
        return None, None, False
    b_idx, c_idx = cand_B["index"], cand_C["index"]
    if c_idx + 2 >= len(bars):
        return cand_B, cand_C, False
    rule_a = bars[c_idx + 1]["Close"] > cand_C["value"] and bars[c_idx + 2]["Close"] > bars[c_idx + 1]["Close"]
    lows_arr = [b["Low"] for b in bars]
    highs_arr = [b["High"] for b in bars]
    rule_b = B.check_trendline_break_highs(highs_arr, lows_arr, closes, b_idx, c_idx)
    rule_c = any(b["Close"] > cand_B["value"] for b in bars[c_idx + 1 :])
    return cand_B, cand_C, (rule_a or rule_b or rule_c)


def _project_reversal_date(bars, a_idx, b_idx, c_idx):
    """
    Reverse count from B back to A (B→A is prior swing)
    Forward count from C forward.
    Holidays (weekday gaps) counted as full days.
    Returns (projected_index_or_None, reverse_count).
    """
    if a_idx is None or b_idx is None or c_idx is None:
        return None, 0
    if a_idx >= b_idx:
        return None, 0
    reverse = 0
    cur = b_idx - 1
    while cur >= a_idx:
        reverse += 1
        # Holiday in gap
        reverse += B.count_weekday_holidays(bars[cur]["date"], bars[cur + 1]["date"])
        cur -= 1
    if reverse == 0:
        return None, 0
    # Forward count
    target = 0
    j = c_idx + 1
    while j < len(bars):
        target += 1
        # Approximate forward holidays using same bar gaps
        target += B.count_weekday_holidays(bars[j - 1]["date"], bars[j]["date"])
        if target >= reverse:
            return j, reverse
        j += 1
    return None, reverse


def _action_reaction(bars, a_idx, b_idx, c_idx):
    """Return dict of line params or None."""
    if a_idx is None or b_idx is None or c_idx is None:
        return None
    if a_idx >= b_idx or b_idx >= c_idx:
        return None
    A_c = bars[a_idx]["Close"]
    B_c = bars[b_idx]["Close"]
    C_c = bars[c_idx]["Close"]
    m_action = ((C_c - B_c) / (c_idx - b_idx)) if c_idx != b_idx else 0.0
    mid_price = (B_c + C_c) / 2.0
    mid_idx = (b_idx + c_idx) / 2.0
    if mid_idx == a_idx:
        return None
    m_center = (mid_price - A_c) / (mid_idx - a_idx)
    b_center = A_c - m_center * a_idx
    reverse_bars = abs(b_idx - a_idx)
    forward_x = c_idx + reverse_bars
    target_center_y = m_center * forward_x + b_center
    b_reaction = target_center_y - m_action * forward_x
    return {
        "m_action": m_action,
        "m_center": m_center,
        "b_center": b_center,
        "forward_x": forward_x,
        "target_center_y": target_center_y,
        "b_reaction": b_reaction,
    }


def _retracement_window(high, low, mode="STANDARD"):
    rng = high - low
    if mode == "STRONG_TREND":
        return low + rng * 0.30, high - rng * 0.30, "30pct"
    return low + rng * 0.60, high - rng * 0.60, "60pct"


def _two_day_rule(bars, trend_direction):
    if len(bars) < 4:
        return None
    b1, b2 = bars[-2], bars[-1]
    if trend_direction == "UP":
        if B.is_bearish(b1) and B.is_bearish(b2):
            high_pivot = max(bars[-3]["High"], b1["High"])
            low_ext = min(b1["Low"], b2["Low"])
            trig = high_pivot - (high_pivot - low_ext) / 2.0
            return {"entry": trig, "stop": low_ext, "order": "BUY_STOP", "notes": "2 down closes → 50% trigger"}
    elif B.is_bullish(b1) and B.is_bullish(b2):
        low_pivot = min(bars[-3]["Low"], b1["Low"])
        high_ext = max(b1["High"], b2["High"])
        trig = low_pivot + (high_ext - low_pivot) / 2.0
        return {"entry": trig, "stop": high_ext, "order": "SELL_STOP", "notes": "2 up closes → 50% trigger"}
    return None


def _peg_leg(bars, trend_direction):
    if len(bars) < 25:
        return None
    cur = bars[-1]
    if trend_direction == "UP":
        window = bars[-20:]
        if cur["High"] != max(b["High"] for b in window):
            return None
        # Prior high pivot index (excluding current)
        prior_highs = B.find_pivot_highs([b["High"] for b in bars[:-1]], k=3)
        if not prior_highs:
            return None
        prev = prior_highs[-1]["index"]
        if (len(bars) - 1 - prev) < 3:
            return None
        tick4 = B.ticks(4, cur["Close"])
        return {
            "entry": cur["Low"] - tick4,
            "stop": cur["High"] + tick4,
            "order": "SELL_STOP",
            "notes": "Peg-Leg (up): 20d high ≥3d after prior pivot",
            "ttl": 2,
        }
    window = bars[-20:]
    if cur["Low"] != min(b["Low"] for b in window):
        return None
    prior_lows = B.find_pivot_lows([b["Low"] for b in bars[:-1]], k=3)
    if not prior_lows:
        return None
    prev = prior_lows[-1]["index"]
    if (len(bars) - 1 - prev) < 3:
        return None
    tick4 = B.ticks(4, cur["Close"])
    return {
        "entry": cur["High"] + tick4,
        "stop": cur["Low"] - tick4,
        "order": "BUY_STOP",
        "notes": "Peg-Leg (down): 20d low ≥3d after prior pivot",
        "ttl": 2,
    }


def _gap_and_go(bars):
    if len(bars) < 3:
        return None
    d1, d2 = bars[-2], bars[-1]
    prior = bars[-3]
    # Bullish
    if (d1["Low"] < prior["Low"]) and B.is_bearish(d1):
        if (d2["Open"] > d1["Close"]) and (d2["Low"] > d1["Close"]) and (d2["Close"] > d1["High"]):
            tick1 = B.ticks(1, d2["Close"])
            tick2 = B.ticks(2, d2["Close"])
            return {
                "entry": d2["High"] + tick1,
                "stop": d2["Low"] - tick2,
                "order": "BUY_STOP",
                "notes": "Bullish Gap and Go",
            }
    # Bearish
    if (d1["High"] > prior["High"]) and B.is_bullish(d1):
        if (d2["Open"] < d1["Close"]) and (d2["High"] < d1["Close"]) and (d2["Close"] < d1["Low"]):
            tick1 = B.ticks(1, d2["Close"])
            tick2 = B.ticks(2, d2["Close"])
            return {
                "entry": d2["Low"] - tick1,
                "stop": d2["High"] + tick2,
                "order": "SELL_STOP",
                "notes": "Bearish Gap and Go",
            }
    return None


def _gap_reversal(bars):
    if len(bars) < 3:
        return None
    d1, d2 = bars[-2], bars[-1]
    prior = bars[-3]
    tick1 = B.ticks(1, d1["Close"])
    tick3 = B.ticks(3, d1["Close"])
    # Bullish
    if d1["Low"] < prior["Low"]:
        if d2["Open"] < d1["Low"] and B.is_bullish(d2) and abs(d2["Open"] - d2["Low"]) <= B.ticks(2, d2["Close"]):
            return {
                "entry": d1["High"] + tick1,
                "stop": d2["Low"] - tick3,
                "order": "BUY_STOP",
                "notes": "Bullish Gap Reversal",
            }
    # Bearish
    if d1["High"] > prior["High"]:
        if d2["Open"] > d1["High"] and B.is_bearish(d2) and abs(d2["Open"] - d2["High"]) <= B.ticks(2, d2["Close"]):
            return {
                "entry": d1["Low"] - tick1,
                "stop": d2["High"] + tick3,
                "order": "SELL_STOP",
                "notes": "Bearish Gap Reversal",
            }
    return None


def _continuation_gap(bars, is_rev_or_trail):
    if not is_rev_or_trail or len(bars) < 2:
        return None
    cur, prior = bars[-1], bars[-2]
    # Up: gap above prior high, close > open
    if cur["Low"] > prior["High"] and B.is_bullish(cur):
        return {"hold_bars": 3, "notes": "Continuation gap up — expect 2-3 day persistence"}
    if cur["High"] < prior["Low"] and B.is_bearish(cur):
        return {"hold_bars": 3, "notes": "Continuation gap down — expect 2-3 day persistence"}
    return None


def _major_reversal(bars, trend_direction):
    if len(bars) < 12:
        return None
    cur = bars[-1]
    if trend_direction == "DOWN":
        window = bars[-10:]
        if cur["Low"] != min(b["Low"] for b in window):
            return None
        n_down = 0
        for b in reversed(bars):
            if B.is_bearish(b):
                n_down += 1
            else:
                break
        if n_down < 3:
            return None
        tick1 = B.ticks(1, cur["Close"])
        tick3 = B.ticks(3, cur["Close"])
        stop = min(b["Low"] for b in bars[-n_down:]) - tick3
        return {
            "entry": cur["High"] + tick1,
            "stop": stop,
            "order": "BUY_STOP",
            "ttl": 2,
            "notes": f"Major Reversal: 10d low + {n_down} down closes",
        }
    window = bars[-10:]
    if cur["High"] != max(b["High"] for b in window):
        return None
    n_up = 0
    for b in reversed(bars):
        if B.is_bullish(b):
            n_up += 1
        else:
            break
    if n_up < 3:
        return None
    tick1 = B.ticks(1, cur["Close"])
    tick3 = B.ticks(3, cur["Close"])
    stop = max(b["High"] for b in bars[-n_up:]) + tick3
    return {
        "entry": cur["Low"] - tick1,
        "stop": stop,
        "order": "SELL_STOP",
        "ttl": 2,
        "notes": f"Major Reversal: 10d high + {n_up} up closes",
    }


def _ssto_divergence(bars, trend_direction):
    if len(bars) < 40:
        return None
    closes = [b["Close"] for b in bars]
    highs = [b["High"] for b in bars]
    lows = [b["Low"] for b in bars]
    k = B.ssto_k(closes, highs, lows, period=20, smooth=3)
    if trend_direction == "UP":
        peaks = B.find_pivot_highs(closes, k=4)[-3:]
        if len(peaks) < 3:
            return None
        p_vals = [p["value"] for p in peaks]
        k_vals = [k[p["index"]] for p in peaks]
        if any(v is None for v in k_vals):
            return None
        if p_vals[2] > p_vals[1] > p_vals[0] and k_vals[2] < k_vals[1] < k_vals[0]:
            return {"order": "SELL_STOP", "notes": "SSTO bearish divergence (3 peaks)"}
    else:
        troughs = B.find_pivot_lows(closes, k=4)[-3:]
        if len(troughs) < 3:
            return None
        t_vals = [t["value"] for t in troughs]
        k_vals = [k[t["index"]] for t in troughs]
        if any(v is None for v in k_vals):
            return None
        if t_vals[2] < t_vals[1] < t_vals[0] and k_vals[2] > k_vals[1] > k_vals[0]:
            return {"order": "BUY_STOP", "notes": "SSTO bullish divergence (3 troughs)"}
    return None


# ============================================================
# Per-symbol scan
# ============================================================
def _scan_symbol(symbol, df):
    """Return list of signals for one symbol. df has Open/High/Low/Close."""
    if df is None or len(df) < 60:
        return []
    bars = B.bars_to_dicts(df)
    signals = []
    bars[-1]

    # Primary trend guess: close vs 50-bar SMA
    closes = [b["Close"] for b in bars]
    ma50 = sum(closes[-50:]) / 50
    ma200 = sum(closes[-200:]) / 200 if len(closes) >= 200 else ma50
    trend = "UP" if closes[-1] > ma50 else "DOWN"
    if ma50 > ma200 * 1.01:
        trend = "UP"
    elif ma50 < ma200 * 0.99:
        trend = "DOWN"

    # 1. Reaction Swing
    B_pt, C_pt, confirmed = _reaction_swing(bars, trend)
    if B_pt is not None:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "reaction_swing",
                "direction": "BULLISH" if trend == "UP" else "BEARISH",
                "signal_type": "WATCH" if not confirmed else "CONFIRMED",
                "entry": None,
                "stop": None,
                "target": None,
                "confidence": "MED" if confirmed else "LOW",
                "notes": f"Reaction swing B→C over "
                f"{C_pt['index'] - B_pt['index'] + 1} bars; "
                f"{'confirmed' if confirmed else 'forming'}",
                "raw": {"B_idx": B_pt["index"], "C_idx": C_pt["index"], "trend": trend},
            }
        )

    # 2. Time forecast — need prior A pivot
    if B_pt is not None and C_pt is not None:
        if trend == "UP":
            prior_lows = B.find_pivot_lows(closes[: B_pt["index"]], k=3)
            a_idx = prior_lows[-1]["index"] if prior_lows else None
        else:
            prior_highs = B.find_pivot_highs(closes[: B_pt["index"]], k=3)
            a_idx = prior_highs[-1]["index"] if prior_highs else None
        proj_idx, rev_count = _project_reversal_date(bars, a_idx, B_pt["index"], C_pt["index"])
        if proj_idx is not None and proj_idx < len(bars):
            signals.append(
                {
                    "symbol": symbol,
                    "trader": SLUG,
                    "method": "time_forecast",
                    "direction": "BULLISH" if trend == "UP" else "BEARISH",
                    "signal_type": "DATE_PROJECTED",
                    "entry": None,
                    "stop": None,
                    "target": None,
                    "confidence": "MED",
                    "notes": f"Reversal projected at bar {proj_idx} "
                    f"({bars[proj_idx]['date']}); reverse count "
                    f"{rev_count}",
                    "raw": {
                        "reverse_count": rev_count,
                        "projected_idx": proj_idx,
                        "projected_date": bars[proj_idx]["date"],
                    },
                }
            )

        # 3. Action / Reaction lines
        ar = _action_reaction(bars, a_idx, B_pt["index"], C_pt["index"])
        if ar:
            signals.append(
                {
                    "symbol": symbol,
                    "trader": SLUG,
                    "method": "action_reaction",
                    "direction": "BULLISH" if trend == "UP" else "BEARISH",
                    "signal_type": "LINE_PROJECTED",
                    "entry": None,
                    "stop": None,
                    "target": None,
                    "confidence": "LOW",
                    "notes": f"Action slope {ar['m_action']:.4f}, "
                    f"center slope {ar['m_center']:.4f}; "
                    f"reaction line b={ar['b_reaction']:.2f}",
                    "raw": ar,
                }
            )

    # 4. Retracement window — current swing
    if len(bars) >= 25:
        seg = bars[-25:]
        hh = max(b["High"] for b in seg)
        ll = min(b["Low"] for b in seg)
        sell_th, buy_th, mode = _retracement_window(hh, ll, "STANDARD")
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "retracement_window",
                "direction": "both",
                "signal_type": "WINDOW",
                "entry": None,
                "stop": None,
                "target": None,
                "confidence": "LOW",
                "notes": f"{mode}: buy zone ≤ ₹{buy_th:.2f}, sell zone ≥ ₹{sell_th:.2f}",
                "raw": {"buy_threshold": buy_th, "sell_threshold": sell_th, "mode": mode},
            }
        )

    # 5. Two-Day Rule
    tdr = _two_day_rule(bars, trend)
    if tdr:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "two_day_rule",
                "direction": "BULLISH" if tdr["order"] == "BUY_STOP" else "BEARISH",
                "signal_type": tdr["order"],
                "entry": tdr["entry"],
                "stop": tdr["stop"],
                "target": None,
                "confidence": "MED",
                "notes": tdr["notes"],
                "raw": {},
            }
        )

    # 6. Peg-Leg
    pl = _peg_leg(bars, trend)
    if pl:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "peg_leg",
                "direction": "BULLISH" if pl["order"] == "BUY_STOP" else "BEARISH",
                "signal_type": pl["order"],
                "entry": pl["entry"],
                "stop": pl["stop"],
                "target": None,
                "confidence": "MED",
                "notes": pl["notes"],
                "raw": {"ttl_days": pl.get("ttl")},
            }
        )

    # 7. Gap and Go
    gg = _gap_and_go(bars)
    if gg:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "gap_and_go",
                "direction": "BULLISH" if gg["order"] == "BUY_STOP" else "BEARISH",
                "signal_type": gg["order"],
                "entry": gg["entry"],
                "stop": gg["stop"],
                "target": None,
                "confidence": "HIGH",
                "notes": gg["notes"],
                "raw": {},
            }
        )

    # 8. Gap Reversal
    gr = _gap_reversal(bars)
    if gr:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "gap_reversal",
                "direction": "BULLISH" if gr["order"] == "BUY_STOP" else "BEARISH",
                "signal_type": gr["order"],
                "entry": gr["entry"],
                "stop": gr["stop"],
                "target": None,
                "confidence": "HIGH",
                "notes": gr["notes"],
                "raw": {},
            }
        )

    # 9. Continuation Gap
    cg = _continuation_gap(bars, is_rev_or_trail=True)
    if cg:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "continuation_gap",
                "direction": "BULLISH" if closes[-1] > closes[-2] else "BEARISH",
                "signal_type": "CONTINUATION",
                "entry": None,
                "stop": None,
                "target": None,
                "confidence": "MED",
                "notes": cg["notes"],
                "raw": {"hold_bars": cg["hold_bars"]},
            }
        )

    # 10. Major Reversal
    mr = _major_reversal(bars, trend)
    if mr:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "major_reversal",
                "direction": "BULLISH" if mr["order"] == "BUY_STOP" else "BEARISH",
                "signal_type": mr["order"],
                "entry": mr["entry"],
                "stop": mr["stop"],
                "target": None,
                "confidence": "HIGH",
                "notes": mr["notes"],
                "raw": {"ttl_days": mr.get("ttl")},
            }
        )

    # 11. SSTO Divergence
    sst = _ssto_divergence(bars, trend)
    if sst:
        signals.append(
            {
                "symbol": symbol,
                "trader": SLUG,
                "method": "ssto_divergence",
                "direction": "BULLISH" if sst["order"] == "BUY_STOP" else "BEARISH",
                "signal_type": sst["order"],
                "entry": None,
                "stop": None,
                "target": None,
                "confidence": "MED",
                "notes": sst["notes"],
                "raw": {},
            }
        )

    return signals


# ============================================================
# Universe scan
# ============================================================
def scan(conn=None, limit=800):
    """Scan the band universe. Returns list of signals."""
    own = conn is None
    if own:
        conn = db.get_conn()
    syms = band_universe(conn, limit=limit)

    signals = []
    for i, sym in enumerate(syms, 1):
        rows = conn.execute(
            "SELECT date, open, high, low, close, volume FROM prices_daily WHERE symbol=? ORDER BY date", (sym,)
        ).fetchall()
        if len(rows) < 260:
            continue
        df = pd.DataFrame(list(rows), columns=["date", "Open", "High", "Low", "Close", "Volume"]).set_index("date")
        df.index = pd.to_datetime(df.index)
        try:
            sigs = _scan_symbol(sym, df)
            signals.extend(sigs)
        except Exception as e:
            log.warning(f"{sym} scan failed: {e}")
        if i % 100 == 0:
            log.info(f"progress {i}/{len(syms)}, {len(signals)} signals")

    if own:
        conn.close()
    return signals
