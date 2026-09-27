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
nse_portfolio.py — Automated Portfolio Manager (v1)
=====================================================
Runs as Step 5 in the pipeline, right after nse_output.py.

WHAT IT DOES DAILY:
  1. auto_add()     — adds stocks meeting ALL 3 criteria (streak 5+, score 6+, dist_pct <5%)
  2. update_sl()    — trails SL as T1 hit (SL → entry), T2 hit (SL → T1)
  3. check_exits()  — flags/closes positions where close < SL
  4. calc_risk()    — 8-dimension risk score per open position
  5. send_message() — daily Telegram portfolio message

ENTRY RULES (all 3 must be met):
  streak ≥ 5 days in top 25
  score ≥ 6 on technical filters
  dist_pct < 5% (not overextended)

EXIT RULE:
  SL hit only (close ≤ sl_price triggers auto-exit)
  T2 hit = trail SL to T1, stay in position

STATE FILE: portfolio.json
  {
    "positions": { SYMBOL: { ...position fields... } },
    "closed":    [ { ...closed position fields... } ],
    "last_run":  "YYYY-MM-DD"
  }

RISK LEVELS:
  🟢 HEALTHY  (0-20)   — Hold confidently
  🟡 ELEVATED (21-40)  — Watch daily, don't add
  🟠 CAUTION  (41-60)  — Tighten SL, partial exit ok
  🔴 DANGER   (61-80)  — Plan exit within 2 days
  ⚫ EXIT NOW  (81+)    — Exit today, trend broken

TIER SYSTEM:
  Conviction  — streak 10+, score 8+
  Compounder  — streak 5-9, score 6-7
  Building    — just added, streak 5, score 6
"""

import json
import logging
import os
from datetime import date, datetime
from pathlib import Path

import requests

try:
    import config
except ImportError:
    print("ERROR: config.py not found.")

# ── Paths ─────────────────────────────────────────────────────
_HERE = Path(__file__).parent
PORTFOLIO_FILE = _HERE / "portfolio.json"
LOG_DIR = getattr(config, "LOG_DIR", "logs")

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[logging.FileHandler(os.path.join(LOG_DIR, "portfolio.log")), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# ── Entry criteria ────────────────────────────────────────────
ENTRY_MIN_STREAK = 5  # consecutive days in top 25
ENTRY_MIN_SCORE = 7  # technical score
ENTRY_MAX_DIST_PCT = 5.0  # % above HMA55 — not overextended

# ── Risk thresholds ───────────────────────────────────────────
RISK_HEALTHY = 20
RISK_ELEVATED = 40
RISK_CAUTION = 60
RISK_DANGER = 80

# ── Tier thresholds ───────────────────────────────────────────
TIER_CONVICTION_STREAK = 10
TIER_CONVICTION_SCORE = 8
TIER_COMPOUNDER_STREAK = 5
TIER_COMPOUNDER_SCORE = 6


# ═══════════════════════════════════════════════════════════════
# PORTFOLIO FILE I/O
# ═══════════════════════════════════════════════════════════════


def _load_portfolio() -> dict:
    if not PORTFOLIO_FILE.exists():
        return {"positions": {}, "closed": [], "last_run": ""}
    try:
        with open(PORTFOLIO_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.exception(f"Failed to load portfolio.json: {e}")
        return {"positions": {}, "closed": [], "last_run": ""}


def _save_portfolio(data: dict):
    data["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    log.info(f"portfolio.json saved — {len(data['positions'])} open, {len(data['closed'])} closed")


# ═══════════════════════════════════════════════════════════════
# TIER ASSIGNMENT
# ═══════════════════════════════════════════════════════════════


def _assign_tier(streak: int, score: float) -> str:
    if streak >= TIER_CONVICTION_STREAK and score >= TIER_CONVICTION_SCORE:
        return "Conviction"
    if streak >= TIER_COMPOUNDER_STREAK and score >= TIER_COMPOUNDER_SCORE:
        return "Compounder"
    return "Building"


# ═══════════════════════════════════════════════════════════════
# 8-DIMENSION RISK ENGINE
# ═══════════════════════════════════════════════════════════════


def calc_risk_score(position: dict, scanner_stock: dict, news: dict | None = None) -> dict:
    """
    Calculate 8-dimension risk score for one open position.

    Args:
        position     : dict from portfolio.json positions
        scanner_stock: dict from telegram_last_scan.json stocks list
        news         : dict from nse_news_collector (optional)

    Returns:
        {
          "total": int,
          "level": str,          # HEALTHY / ELEVATED / CAUTION / DANGER / EXIT
          "icon": str,
          "dimensions": { dim_name: score }
          "flags": [str]         # human-readable reasons
        }
    """
    dims = {}
    flags = []

    # ── D1: Trend Health (HMA) ────────────────────────────────
    daily_hull = str(scanner_stock.get("daily_hull_status", "NOT_ALIGNED"))
    weekly_hull = str(scanner_stock.get("weekly_hull_status", "NOT_ALIGNED"))
    kama_rising = bool(scanner_stock.get("kama_rising", False))

    if daily_hull == "BULLISH" and weekly_hull == "BULLISH" and kama_rising:
        d1 = 0
    elif daily_hull == "BULLISH" and weekly_hull != "NOT_ALIGNED":
        d1 = 5
        flags.append("Weekly Hybrid Hull confirmation is weakening")
    elif daily_hull != "BULLISH":
        d1 = 15
        flags.append("Daily Hybrid Hull trend is no longer aligned")
    else:
        d1 = 10
        flags.append("Hybrid Hull momentum is weakening")
    dims["trend_health"] = d1

    # ── D2: Momentum Quality (RSI + MACD) ────────────────────
    rsi = float(scanner_stock.get("rsi", 55))
    pts_macd = int(scanner_stock.get("pts_macd", 0))

    if 55 <= rsi <= 75 and pts_macd == 1:
        d2 = 0
    elif 55 <= rsi <= 75 and pts_macd == 0:
        d2 = 5
        flags.append("MACD histogram falling")
    elif rsi > 75:
        d2 = 8
        flags.append(f"RSI overbought ({rsi:.0f})")
    elif rsi < 50 and pts_macd == 0:
        d2 = 12
        flags.append(f"RSI + MACD both weak ({rsi:.0f})")
    elif rsi < 40:
        d2 = 15
        flags.append(f"RSI bearish ({rsi:.0f})")
    else:
        d2 = 3
    dims["momentum_quality"] = d2

    # ── D3: Extension Risk (dist_pct / ATR) ──────────────────
    close = float(scanner_stock.get("close", 1))
    sl = float(scanner_stock.get("sl", close * 0.93))
    hull_distance_atr = abs(float(scanner_stock.get("hull_distance_atr", 0)))

    if hull_distance_atr < 1:
        d3 = 0
    elif hull_distance_atr < 1.5:
        d3 = 3
    elif hull_distance_atr < 1.8:
        d3 = 8
        flags.append(f"Stretched {hull_distance_atr:.1f} ATR above Hybrid Hull")
    elif hull_distance_atr < 2.5:
        d3 = 12
        flags.append(f"Overextended {hull_distance_atr:.1f} ATR above Hybrid Hull")
    else:
        d3 = 15
        flags.append(f"Extreme stretch {hull_distance_atr:.1f} ATR — don't add")
    dims["extension_risk"] = d3

    # ── D4: Volume Conviction ─────────────────────────────────
    acc_days = int(scanner_stock.get("acc_days", 0))
    dist_days = int(scanner_stock.get("dist_days", 0))
    obv_dir = str(scanner_stock.get("obv_dir", "flat"))
    del_trend = str(scanner_stock.get("del_trend", "flat"))

    if acc_days >= 3 and obv_dir == "rising" and del_trend == "rising":
        d4 = 0
    elif acc_days >= 2 and obv_dir != "falling":
        d4 = 3
    elif obv_dir == "rising" and del_trend == "falling":
        d4 = 10
        flags.append("Volume rising but delivery falling — speculative")
    elif dist_days >= 3 and obv_dir == "falling":
        d4 = 12
        flags.append("Distribution pattern — institutional exit")
    elif dist_days >= 4:
        d4 = 15
        flags.append("Heavy distribution — exit pressure")
    else:
        d4 = 3
    dims["volume_conviction"] = d4

    # ── D5: Return Sustainability ─────────────────────────────
    r1m = float(scanner_stock.get("return_1m_pct", 0))
    r3m = float(scanner_stock.get("return_3m_pct", 0))

    if r1m > 0 and r3m > 0:
        ratio = r1m / r3m if r3m > 0 else 0
        if 0.2 <= ratio <= 0.5:
            d5 = 0  # steady, sustainable
        elif ratio > 0.7:
            d5 = 8
            flags.append(f"Most gains recent — spike risk (1M={r1m:.1f}%, 3M={r3m:.1f}%)")
        else:
            d5 = 3
    elif r1m < 0 and r3m > 0:
        d5 = 10
        flags.append(f"1M negative ({r1m:.1f}%) — trend reversing")
    elif r1m < 0 and r3m < 0:
        d5 = 15
        flags.append("Both 1M and 3M negative — downtrend")
    else:
        d5 = 3
    dims["return_sustainability"] = d5

    # ── D6: Position Safety (SL cushion) ─────────────────────
    entry_price = float(position.get("entry_price", close))
    current_sl = float(position.get("current_sl", sl))
    current_price = float(scanner_stock.get("close", entry_price))

    if current_sl > 0 and current_price > 0:
        sl_cushion_pct = (current_price - current_sl) / current_price * 100
    else:
        sl_cushion_pct = 10.0  # assume ok if no data

    if sl_cushion_pct > 10:
        d6 = 0
    elif sl_cushion_pct > 7:
        d6 = 3
    elif sl_cushion_pct > 4:
        d6 = 8
        flags.append(f"SL tightening — {sl_cushion_pct:.1f}% cushion")
    elif sl_cushion_pct > 2:
        d6 = 12
        flags.append(f"SL very close — {sl_cushion_pct:.1f}% — one bad day away")
    else:
        d6 = 15
        flags.append(f"SL almost hit — {sl_cushion_pct:.1f}% cushion only")
    dims["position_safety"] = d6

    # ── D7: List Persistence (streak) ─────────────────────────
    streak = int(scanner_stock.get("streak", 0))
    # Also check historical appearance count from position record
    days_in_list = int(position.get("days_in_list", streak))

    if streak >= 15 or days_in_list >= 15:
        d7 = 0
    elif streak >= 10:
        d7 = 3
    elif streak >= 5 or streak >= 1:
        d7 = 8
    else:
        d7 = 15
        flags.append("Stock left top 25 — scanner rejecting it")
    dims["list_persistence"] = d7

    # ── D8: Event Risk (news) ─────────────────────────────────
    d8 = 0
    if news:
        news_tone = str(news.get("news_tone", "NEUTRAL"))
        news_flags = news.get("flags", [])
        ann_count = int(news.get("ann_count", 0))

        if any("RISK:REGULATORY" in f for f in news_flags):
            d8 = 15
            flags.append("⚠️ SEBI/Regulatory issue flagged")
        elif any("DEAL:PROMOTER_SELL" in f for f in news_flags):
            d8 = 12
            flags.append("⚠️ Promoter selling — insider exit")
        elif any("DEAL:INSTITUTION_BUY" in f for f in news_flags):
            d8 = 0  # institutional buy = confirmation
        elif ann_count > 0 and any(
            "RESULTS" in f or "MEETING" in f for f in [n.get("type", "") for n in news.get("announcements", [])]
        ):
            d8 = 5
            flags.append("Board meeting / results upcoming — gap risk")
        elif news_tone == "NEGATIVE":
            d8 = 8
            flags.append("News sentiment negative")
    dims["event_risk"] = d8

    # ── Total + Level ─────────────────────────────────────────
    total = sum(dims.values())

    if total <= RISK_HEALTHY:
        level, icon = "HEALTHY", "🟢"
    elif total <= RISK_ELEVATED:
        level, icon = "ELEVATED", "🟡"
    elif total <= RISK_CAUTION:
        level, icon = "CAUTION", "🟠"
    elif total <= RISK_DANGER:
        level, icon = "DANGER", "🔴"
    else:
        level, icon = "EXIT NOW", "⚫"
        flags.append("Risk score critical — exit today")

    return {
        "total": total,
        "level": level,
        "icon": icon,
        "dimensions": dims,
        "flags": flags,
    }


# ═══════════════════════════════════════════════════════════════
# AUTO ADD
# ═══════════════════════════════════════════════════════════════


def auto_add(portfolio: dict, scanner_stocks: list, scan_date: str, news_data: dict | None = None) -> list:
    """
    Check scanner stocks against entry criteria. Add qualifying stocks.

    Entry criteria (ALL required): BUY_TRIGGER, fixed Hybrid Hull alignment,
    KAMA30 rising, no stretch/chop, streak >= 5, score >= 7, and no
    material negative news. This is a scanner model position, not a broker fill.

    Returns list of newly added symbols.
    """
    positions = portfolio.get("positions", {})
    added = []

    for stock in scanner_stocks:
        sym = stock.get("symbol", "")
        streak = int(stock.get("streak", 0))
        score = float(stock.get("score", 0))
        dist_pct = float(stock.get("dist_pct", 999))
        action = str(stock.get("action", "WATCH"))
        daily_hull = str(stock.get("daily_hull_status", "NOT_ALIGNED"))
        weekly_hull = str(stock.get("weekly_hull_status", "NOT_ALIGNED"))
        kama_rising = bool(stock.get("kama_rising", False))
        hull_stretched = bool(stock.get("hull_stretched", False))
        hull_chop = bool(stock.get("hull_chop", False))
        news = (news_data or {}).get(sym, {})
        flags = news.get("flags", []) if isinstance(news, dict) else []
        negative_news = str(news.get("news_tone", "NEUTRAL")) == "NEGATIVE" if isinstance(news, dict) else False
        material_news_risk = negative_news or any(
            "RISK:REGULATORY" in str(flag) or "DEAL:PROMOTER_SELL" in str(flag) for flag in flags
        )

        # Skip if already in portfolio
        if sym in positions:
            continue

        # A model entry must be an actual scanner entry, not merely a good stock.
        if action != "BUY_TRIGGER":
            continue
        if not (daily_hull == "BULLISH" and weekly_hull == "BULLISH" and kama_rising):
            continue
        if hull_stretched or hull_chop or material_news_risk:
            continue
        if streak < ENTRY_MIN_STREAK:
            continue
        if score < ENTRY_MIN_SCORE:
            continue
        if dist_pct >= ENTRY_MAX_DIST_PCT:
            continue

        # All criteria met — add position
        close = float(stock.get("close", 0))
        sl = float(stock.get("sl", round(close * 0.93, 2)))
        t1 = float(stock.get("target1", round(close + (close - sl), 2)))
        t2 = float(stock.get("target2", round(close + 2 * (close - sl), 2)))
        tier = _assign_tier(streak, score)

        positions[sym] = {
            "symbol": sym,
            "entry_price": close,
            "entry_date": scan_date,
            "entry_score": score,
            "entry_streak": streak,
            "current_sl": sl,
            "original_sl": sl,
            "t1_price": t1,
            "t2_price": t2,
            "current_price": close,
            "tier": tier,
            "sl_stage": "original",  # original → entry → t1
            "t1_hit": False,
            "t2_hit": False,
            "t1_hit_date": None,
            "t2_hit_date": None,
            "highest_price": close,
            "days_in_list": streak,
            "added_date": scan_date,
            "last_updated": scan_date,
            "milestones": [
                {
                    "event": "added",
                    "date": scan_date,
                    "price": close,
                    "reason": (f"BUY_TRIGGER | Hull aligned | streak={streak} score={score} dist={dist_pct:.1f}%"),
                }
            ],
        }
        added.append(sym)
        log.info(f"AUTO-ADD: {sym} | streak={streak} score={score:.1f} dist={dist_pct:.1f}% | tier={tier}")

    portfolio["positions"] = positions
    return added


# ═══════════════════════════════════════════════════════════════
# UPDATE SL (TRAIL)
# ═══════════════════════════════════════════════════════════════


def update_sl(portfolio: dict, scanner_stocks: list, scan_date: str) -> list:
    """
    Trail SL as price milestones are hit.

    Rules:
      T1 hit → SL moves to entry price (breakeven)
      T2 hit → SL moves to T1 price (lock profit)

    Returns list of symbols where SL was updated.
    """
    positions = portfolio.get("positions", {})
    updated = []

    stock_map = {s["symbol"]: s for s in scanner_stocks}

    for sym, pos in positions.items():
        stock = stock_map.get(sym)
        if not stock:
            continue

        current_price = float(stock.get("close", pos.get("current_price", 0)))
        pos["current_price"] = current_price

        if current_price > pos.get("highest_price", 0):
            pos["highest_price"] = current_price

        t1 = float(pos.get("t1_price", 0))
        t2 = float(pos.get("t2_price", 0))
        entry = float(pos.get("entry_price", 0))

        # T2 hit → trail SL to T1
        if not pos.get("t2_hit") and t2 > 0 and pos.get("highest_price", 0) >= t2:
            pos["t2_hit"] = True
            pos["t2_hit_date"] = scan_date
            old_sl = pos["current_sl"]
            pos["current_sl"] = t1
            pos["sl_stage"] = "t1"
            pos["milestones"].append(
                {
                    "event": "t2_hit",
                    "date": scan_date,
                    "price": current_price,
                    "sl_moved_from": old_sl,
                    "sl_moved_to": t1,
                }
            )
            updated.append(sym)
            log.info(f"T2 HIT: {sym} @ {current_price} | SL trailed to T1={t1}")

        # T1 hit → trail SL to entry (only if T2 not hit yet)
        elif not pos.get("t1_hit") and t1 > 0 and pos.get("highest_price", 0) >= t1:
            pos["t1_hit"] = True
            pos["t1_hit_date"] = scan_date
            old_sl = pos["current_sl"]
            pos["current_sl"] = entry
            pos["sl_stage"] = "entry"
            pos["milestones"].append(
                {
                    "event": "t1_hit",
                    "date": scan_date,
                    "price": current_price,
                    "sl_moved_from": old_sl,
                    "sl_moved_to": entry,
                }
            )
            updated.append(sym)
            log.info(f"T1 HIT: {sym} @ {current_price} | SL trailed to entry={entry}")

        pos["last_updated"] = scan_date
        # Keep tier updated
        streak = int(stock.get("streak", pos.get("entry_streak", 5)))
        score = float(stock.get("score", pos.get("entry_score", 6)))
        pos["tier"] = _assign_tier(streak, score)
        pos["days_in_list"] = streak

    return updated


# ═══════════════════════════════════════════════════════════════
# CHECK EXITS (SL hit)
# ═══════════════════════════════════════════════════════════════


def check_exits(portfolio: dict, scanner_stocks: list, scan_date: str) -> list:
    """
    Auto-exit positions where today's close is at or below current SL.

    Returns list of exited symbols.
    """
    positions = portfolio.get("positions", {})
    closed = portfolio.get("closed", [])
    exited = []

    stock_map = {s["symbol"]: s for s in scanner_stocks}

    for sym in list(positions.keys()):
        pos = positions[sym]
        stock = stock_map.get(sym)

        current_price = float(stock.get("close", pos.get("current_price", 0)) if stock else pos.get("current_price", 0))
        current_sl = float(pos.get("current_sl", 0))

        if current_sl > 0 and current_price <= current_sl:
            # SL hit — close position
            entry = float(pos.get("entry_price", 1))
            pl_abs = round(current_price - entry, 2)
            pl_pct = round((current_price - entry) / entry * 100, 1) if entry > 0 else 0
            t1_hit = pos.get("t1_hit", False)

            pos["exit_price"] = current_price
            pos["exit_date"] = scan_date
            pos["exit_reason"] = "SL_HIT"
            pos["final_pl"] = pl_abs
            pos["final_pl_pct"] = pl_pct
            pos["milestones"].append(
                {
                    "event": "sl_exit",
                    "date": scan_date,
                    "price": current_price,
                    "sl_was": current_sl,
                    "pl_pct": pl_pct,
                }
            )

            closed.append(dict(pos))
            del positions[sym]
            exited.append(sym)

            result_tag = "PROFIT" if pl_pct > 0 else "LOSS"
            t1_tag = " [T1 was hit ✅]" if t1_hit else ""
            log.info(f"SL EXIT: {sym} @ {current_price} | {result_tag} {pl_pct:+.1f}%{t1_tag}")

    # Keep only last 200 closed trades
    if len(closed) > 200:
        closed = closed[-200:]

    portfolio["positions"] = positions
    portfolio["closed"] = closed
    return exited


# ═══════════════════════════════════════════════════════════════
# TELEGRAM MESSAGE BUILDER
# ═══════════════════════════════════════════════════════════════


def _h(v):
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _b(v):
    return f"<b>{_h(v)}</b>"


def _i(v):
    return f"<i>{_h(v)}</i>"


def _code(v):
    return f"<code>{_h(v)}</code>"


SEP = "━" * 20


def build_portfolio_message(
    portfolio: dict,
    scanner_stocks: list,
    added: list,
    sl_updated: list,
    exited: list,
    risk_scores: dict,
    scan_date: str,
) -> list:
    """
    Build daily Telegram portfolio messages.
    Returns list of strings (split for 4096 char limit).

    Structure:
      Header — date, counts
      EXITS today (if any)
      NEW ADDITIONS today (if any)
      OPEN POSITIONS — sorted by risk level
      SUMMARY footer
    """
    positions = portfolio.get("positions", {})
    closed = portfolio.get("closed", [])
    stock_map = {s["symbol"]: s for s in scanner_stocks}

    try:
        ds = datetime.strptime(scan_date[:10], "%Y-%m-%d").strftime("%d-%b-%Y")
    except Exception:
        ds = scan_date

    messages = []

    # ── Header ────────────────────────────────────────────────
    total_open = len(positions)
    healthy = sum(1 for r in risk_scores.values() if r["level"] == "HEALTHY")
    caution = sum(1 for r in risk_scores.values() if r["level"] in ("CAUTION", "DANGER", "EXIT NOW"))

    header = f"💼 {_b('Portfolio — ' + ds)}\n"
    header += f"{_i(str(total_open) + ' open · ' + str(healthy) + ' healthy · ' + str(caution) + ' need attention')}\n"
    header += f"{SEP}\n"

    if exited:
        header += f"\n📉 {_b('Exits Today (' + str(len(exited)) + ')')}\n"
        today_closed = [c for c in closed if c.get("exit_date", "")[:10] == scan_date[:10]]
        for c in today_closed:
            sym = c["symbol"]
            pl_pct = float(c.get("final_pl_pct", 0))
            sign = "+" if pl_pct >= 0 else ""
            t1_tag = " ✅T1" if c.get("t1_hit") else ""
            header += f"  {_code(sym)} SL hit · {sign}{pl_pct:.1f}%{t1_tag}\n"

    if added:
        header += f"\n✅ {_b('New Additions (' + str(len(added)) + ')')}\n"
        for sym in added:
            pos = positions.get(sym, {})
            header += f"  {_code(sym)} ₹{int(pos.get('entry_price', 0)):,} tier={pos.get('tier', 'Building')}\n"

    if sl_updated:
        header += f"\n🔼 {_b('SL Trailed')}: "
        header += ", ".join(_code(s) for s in sl_updated) + "\n"

    messages.append(header)

    # ── Open Positions ────────────────────────────────────────
    if not positions:
        messages.append(_i("No open positions.\nStocks will auto-add when streak≥5, score≥6, dist<5%."))
        return messages

    # Sort: EXIT NOW → DANGER → CAUTION → ELEVATED → HEALTHY
    risk_order = {"EXIT NOW": 0, "DANGER": 1, "CAUTION": 2, "ELEVATED": 3, "HEALTHY": 4}
    sorted_syms = sorted(
        positions.keys(),
        key=lambda s: (
            risk_order.get(risk_scores.get(s, {}).get("level", "HEALTHY"), 4),
            -float(positions[s].get("entry_price", 0)),
        ),
    )

    block = f"\n{_b('Open Positions (' + str(len(positions)) + ')')}\n{SEP}\n"

    for sym in sorted_syms:
        pos = positions[sym]
        stock = stock_map.get(sym, {})
        risk = risk_scores.get(sym, {"icon": "🟢", "level": "HEALTHY", "total": 0, "flags": []})

        entry = float(pos.get("entry_price", 0))
        current = float(pos.get("current_price", entry))
        sl_cur = float(pos.get("current_sl", 0))
        t1 = float(pos.get("t1_price", 0))
        t2 = float(pos.get("t2_price", 0))
        tier = pos.get("tier", "Building")
        streak = int(stock.get("streak", pos.get("days_in_list", 0)))
        score = float(stock.get("score", pos.get("entry_score", 0)))

        # P/L
        pl_abs = current - entry
        pl_pct = (pl_abs / entry * 100) if entry > 0 else 0
        pl_sign = "+" if pl_pct >= 0 else ""

        # Milestone tags
        t1_tag = " ✅T1" if pos.get("t1_hit") else ""
        t2_tag = " 🎯T2" if pos.get("t2_hit") else ""

        # SL stage label
        sl_stage = pos.get("sl_stage", "original")
        sl_labels = {
            "original": "orig SL",
            "entry": "BE SL ✅",
            "t1": "T1 SL 🎯",
        }
        sl_label = sl_labels.get(sl_stage, sl_stage)

        card = f"\n{risk['icon']} {_b(sym)} [{tier}]{t1_tag}{t2_tag}\n"
        card += f"   Entry ₹{int(entry):,} → Now ₹{int(current):,} ({pl_sign}{pl_pct:.1f}%)\n"
        card += f"   SL ₹{int(sl_cur):,} ({sl_label}) | T1 ₹{int(t1):,} | T2 ₹{int(t2):,}\n"
        card += f"   Score {score:.0f}/10 | Streak {streak}d | Risk {risk['total']} {risk['level']}\n"

        # Show top 2 risk flags if caution or worse
        if risk["flags"] and risk["level"] not in ("HEALTHY", "ELEVATED"):
            for flag in risk["flags"][:2]:
                card += f"   ⚠️ {_i(flag)}\n"

        # Split message if needed
        if len(block) + len(card) > 3800:
            messages.append(block)
            block = f"{_b('Positions (contd.)')}\n{SEP}\n"

        block += card

    messages.append(block)

    # ── Summary footer ────────────────────────────────────────
    footer = f"\n{SEP}\n"

    # Portfolio P/L snapshot
    total_pl = 0
    winners = 0
    losers = 0
    for pos in positions.values():
        entry = float(pos.get("entry_price", 0))
        current = float(pos.get("current_price", entry))
        if entry > 0:
            pl = (current - entry) / entry * 100
            total_pl += pl
            if pl >= 0:
                winners += 1
            else:
                losers += 1

    avg_pl = total_pl / len(positions) if positions else 0
    pl_sign = "+" if avg_pl >= 0 else ""

    # Closed trade stats
    recent_closed = [c for c in closed[-30:] if c.get("final_pl_pct") is not None]
    if recent_closed:
        won = sum(1 for c in recent_closed if float(c.get("final_pl_pct", 0)) > 0)
        win_rate = round(won / len(recent_closed) * 100)
        avg_win = sum(float(c.get("final_pl_pct", 0)) for c in recent_closed if float(c.get("final_pl_pct", 0)) > 0)
        avg_loss = sum(float(c.get("final_pl_pct", 0)) for c in recent_closed if float(c.get("final_pl_pct", 0)) <= 0)
        n_win = sum(1 for c in recent_closed if float(c.get("final_pl_pct", 0)) > 0)
        n_loss = len(recent_closed) - n_win
        avg_w = avg_win / n_win if n_win > 0 else 0
        avg_l = avg_loss / n_loss if n_loss > 0 else 0

        footer += f"Last {len(recent_closed)} exits: {win_rate}% win rate\n"
        footer += f"Avg win {avg_w:+.1f}% | Avg loss {avg_l:.1f}%\n"

    footer += f"Open P/L avg: {pl_sign}{avg_pl:.1f}% ({winners}W {losers}L)\n"
    footer += _i("Tap /portfolio for live positions · /exits for history")

    messages[-1] += footer

    return messages


# ═══════════════════════════════════════════════════════════════
# TELEGRAM SEND
# ═══════════════════════════════════════════════════════════════


def send_portfolio_message(messages: list, chat_id: str | None = None):
    """Send portfolio message(s) to Telegram."""
    token = getattr(config, "TELEGRAM_TOKEN", None)
    target = chat_id or getattr(config, "TELEGRAM_CHATID", None)

    if not token or not target:
        log.warning("Telegram not configured — skipping portfolio message")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    success = True

    for i, msg in enumerate(messages):
        try:
            r = requests.post(
                url,
                data={
                    "chat_id": str(target),
                    "text": msg,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            if r.status_code != 200:
                log.error(f"Portfolio msg {i + 1} failed: {r.status_code} {r.text[:200]}")
                success = False
        except Exception as e:
            log.exception(f"Portfolio send error: {e}")
            success = False

    if success:
        log.info(f"Portfolio message sent ({len(messages)} parts)")
    return success


# ═══════════════════════════════════════════════════════════════
# MAIN ENTRY — called from pipeline
# ═══════════════════════════════════════════════════════════════


def run_portfolio_step(
    scanner_stocks: list, scan_date: str | None = None, news_data: dict | None = None, chat_id: str | None = None
):
    """
    Full portfolio step. Call this from main_pipeline.py after nse_output.

    Args:
        scanner_stocks : list of stock dicts from telegram_last_scan.json
        scan_date      : 'YYYY-MM-DD' string (default: today)
        news_data      : dict from nse_news_collector (optional)
        chat_id        : override Telegram chat ID (optional)

    Returns:
        dict with summary stats
    """
    if scan_date is None:
        scan_date = date.today().strftime("%Y-%m-%d")

    log.info(f"Portfolio step start — {scan_date} — {len(scanner_stocks)} scanner stocks")

    # Load state
    portfolio = _load_portfolio()

    # Step A: Check exits first (before adding new)
    exited = check_exits(portfolio, scanner_stocks, scan_date)

    # Step B: Trail SL for existing positions
    sl_updated = update_sl(portfolio, scanner_stocks, scan_date)

    # Step C: Auto-add qualifying new stocks
    added = auto_add(portfolio, scanner_stocks, scan_date, news_data=news_data)

    # Step D: Calculate risk for all open positions
    risk_scores = {}
    for sym, pos in portfolio["positions"].items():
        stock = next((s for s in scanner_stocks if s["symbol"] == sym), None)
        if stock:
            news = news_data.get(sym, {}) if news_data else {}
            risk = calc_risk_score(pos, stock, news)
            risk_scores[sym] = risk
        else:
            # Stock not in today's scan — risk elevated
            risk_scores[sym] = {
                "total": 50,
                "level": "CAUTION",
                "icon": "🟠",
                "dimensions": {},
                "flags": ["Not in today's top 25"],
            }

    # Save updated state
    _save_portfolio(portfolio)

    # Step E: Build and send message
    messages = build_portfolio_message(
        portfolio=portfolio,
        scanner_stocks=scanner_stocks,
        added=added,
        sl_updated=sl_updated,
        exited=exited,
        risk_scores=risk_scores,
        scan_date=scan_date,
    )

    send_portfolio_message(messages, chat_id=chat_id)

    summary = {
        "open": len(portfolio["positions"]),
        "added": len(added),
        "exited": len(exited),
        "sl_updated": len(sl_updated),
        "closed_total": len(portfolio["closed"]),
    }

    log.info(
        f"Portfolio done — open={summary['open']} added={summary['added']} "
        f"exited={summary['exited']} sl_trailed={summary['sl_updated']}"
    )

    return summary


# ═══════════════════════════════════════════════════════════════
# BOT QUERY HELPERS (for nse_telegram_handler.py to call)
# ═══════════════════════════════════════════════════════════════


def get_open_positions() -> dict:
    return _load_portfolio().get("positions", {})


def get_closed_positions() -> list:
    return _load_portfolio().get("closed", [])


def get_portfolio_summary() -> dict:
    portfolio = _load_portfolio()
    positions = portfolio.get("positions", {})
    closed = portfolio.get("closed", [])

    recent = [c for c in closed[-50:] if c.get("final_pl_pct") is not None]
    wins = [c for c in recent if float(c.get("final_pl_pct", 0)) > 0]

    return {
        "open_count": len(positions),
        "closed_count": len(closed),
        "win_rate": round(len(wins) / len(recent) * 100) if recent else 0,
        "tiers": {
            t: sum(1 for p in positions.values() if p.get("tier") == t)
            for t in ("Conviction", "Compounder", "Building")
        },
        "last_run": portfolio.get("last_run", ""),
    }


def format_portfolio_for_bot() -> str:
    """Format open positions for /portfolio bot command."""
    portfolio = _load_portfolio()
    positions = portfolio.get("positions", {})

    if not positions:
        return _i("No open positions. Stocks auto-add when streak≥5, score≥6, dist<5%.")

    msg = f"{_b('Open Portfolio (' + str(len(positions)) + ')')}\n{SEP}\n"

    for sym, pos in sorted(positions.items()):
        entry = float(pos.get("entry_price", 0))
        current = float(pos.get("current_price", entry))
        sl = float(pos.get("current_sl", 0))
        t1 = float(pos.get("t1_price", 0))
        t2 = float(pos.get("t2_price", 0))
        tier = pos.get("tier", "Building")
        pl_pct = (current - entry) / entry * 100 if entry > 0 else 0
        pl_sign = "+" if pl_pct >= 0 else ""
        t1_tag = " ✅" if pos.get("t1_hit") else ""
        t2_tag = " 🎯" if pos.get("t2_hit") else ""

        msg += f"\n{_code(sym)} [{tier}]{t1_tag}{t2_tag}\n"
        msg += f"   ₹{int(entry):,} → ₹{int(current):,} ({pl_sign}{pl_pct:.1f}%)\n"
        msg += f"   SL ₹{int(sl):,} | T1 ₹{int(t1):,} | T2 ₹{int(t2):,}\n"

    return msg


def format_exits_for_bot(last_n: int = 10) -> str:
    """Format closed positions for /exits bot command."""
    closed = _load_portfolio().get("closed", [])
    if not closed:
        return _i("No closed positions yet.")

    recent = closed[-last_n:][::-1]  # most recent first
    msg = f"{_b('Recent Exits (' + str(len(recent)) + ')')}\n{SEP}\n"

    for c in recent:
        sym = c.get("symbol", "?")
        entry = float(c.get("entry_price", 0))
        exit_p = float(c.get("exit_price", 0))
        pl_pct = float(c.get("final_pl_pct", 0))
        days = c.get("days_in_list", 0)
        t1_tag = " T1✅" if c.get("t1_hit") else ""
        pl_sign = "+" if pl_pct >= 0 else ""
        icon = "✅" if pl_pct > 0 else "❌"

        msg += f"{icon} {_code(sym)}{t1_tag} ₹{int(entry):,}→₹{int(exit_p):,} {pl_sign}{pl_pct:.1f}% ({days}d)\n"

    return msg


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    import json
    import re

    parser = argparse.ArgumentParser(description="NSE Portfolio Manager v1")
    parser.add_argument("--status", action="store_true", help="Show open positions")
    parser.add_argument("--exits", action="store_true", help="Show recent exits")
    parser.add_argument("--summary", action="store_true", help="Portfolio summary stats")
    parser.add_argument("--run", action="store_true", help="Run full portfolio step from last_scan.json")
    args = parser.parse_args()

    if args.status:
        print(re.sub(r"<[^>]+>", "", format_portfolio_for_bot()))

    elif args.exits:
        print(re.sub(r"<[^>]+>", "", format_exits_for_bot()))

    elif args.summary:
        s = get_portfolio_summary()
        print(f"Open       : {s['open_count']}")
        print(f"Closed     : {s['closed_count']}")
        print(f"Win rate   : {s['win_rate']}%")
        print(f"Tiers      : {s['tiers']}")
        print(f"Last run   : {s['last_run']}")

    elif args.run:
        # Load from telegram_last_scan.json
        scan_file = Path("telegram_last_scan.json")
        if not scan_file.exists():
            print("ERROR: telegram_last_scan.json not found. Run pipeline first.")
        else:
            data = json.loads(scan_file.read_text(encoding="utf-8"))
            stocks = data.get("stocks", [])
            s_date = data.get("scan_date", date.today().strftime("%Y-%m-%d"))
            summary = run_portfolio_step(stocks, s_date)
            print(
                f"Done — open={summary['open']} added={summary['added']} "
                f"exited={summary['exited']} sl_trailed={summary['sl_updated']}"
            )
    else:
        parser.print_help()
