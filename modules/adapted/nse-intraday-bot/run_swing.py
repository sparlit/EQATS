from __future__ import annotations  # Python 3.9 compat — allows X|Y type hints

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
NSE F&O 5-Layer Smart Money Swing Scanner — Daily Runner
=========================================================
• Scans all NSE F&O stocks every market day at 15:35 IST
• 5-layer SMC scoring (out of 10), threshold 7.0
• Stores signals in swing_trades.csv (live tracker)
• Sends Telegram alert with layer breakdown

Usage:
  python run_swing.py             # auto-detect (scan + status update)
  FORCE_SWING=1 python run_swing.py   # force re-scan today
  UPDATE_ONLY=1 python run_swing.py   # status update only
"""
import os
import sys
import time
import traceback

# Force UTF-8 stdout on Windows so ₹ and other Unicode chars print without crashing
if sys.stdout.encoding and sys.stdout.encoding.upper() not in ("UTF-8", "UTF8"):
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from feeds.nse_bulk_deals import get_bulk_block_buys, has_institutional_buy
from feeds.options_feed import check_options_oi, make_nse_session
from feeds.sector_feed import check_sector_momentum, prefetch_sectors
from notifier import telegram_send
from swing_strategy import MAX_HOLD, score_swing

try:
    from config import (
        CALL_OI_INCREASE_MIN,
        PCR_MAX,
        PCR_MIN,
        SWING_MIN_SCORE,
        SWING_SCAN_STOCKS,
        SWING_TOP_N,
    )
except ImportError:
    SWING_MIN_SCORE = 7.0
    SWING_TOP_N = 5
    SWING_SCAN_STOCKS = 200
    CALL_OI_INCREASE_MIN = 0.30
    PCR_MIN = 0.8
    PCR_MAX = 1.3

# ── CSV paths ─────────────────────────────────────────────────────
TRADES_CSV = "swing_trades.csv"
_BASE_RAW = "https://raw.githubusercontent.com/lavakus/nse-intraday-bot/main"
TRADES_CSV_URL = os.environ.get("SWING_CSV_URL", f"{_BASE_RAW}/swing_trades.csv")

TRADES_COLS = [
    "id",
    "date",
    "symbol",
    "score",
    "signal_strength",
    "entry",
    "sl",
    "sl_pct",
    "t1",
    "t2",
    "rr_t1",
    "rr_t2",
    "sector",
    "layers_passed",
    "layer1",
    "layer2",
    "layer3",
    "layer4",
    "layer5",
    "bulk_buyers",
    "pcr",
    "call_oi_chg",
    "put_oi_chg",
    "status",
    "current_price",
    "exit_price",
    "pnl_pct",
    "pnl_pts",
    "exit_date",
    "exit_reason",
    "t1_hit",
    "days_held",
    "progress_pct",
    "dist_sl_pct",
    "dist_t2_pct",
    "last_updated",
    "reasons",
]

# ── Fallback F&O stock list (used when NSE API is unavailable) ────
_FNO_FALLBACK = [
    "RELIANCE",
    "TCS",
    "INFY",
    "HDFCBANK",
    "ICICIBANK",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
    "LT",
    "AXISBANK",
    "HINDUNILVR",
    "ITC",
    "SUNPHARMA",
    "BAJFINANCE",
    "MARUTI",
    "TATAMOTORS",
    "ONGC",
    "NTPC",
    "POWERGRID",
    "JSWSTEEL",
    "TATASTEEL",
    "WIPRO",
    "HCLTECH",
    "TECHM",
    "DRREDDY",
    "CIPLA",
    "DIVISLAB",
    "APOLLOHOSP",
    "BAJAJFINSV",
    "ADANIGREEN",
    "ADANIPORTS",
    "ADANIENT",
    "TATACONSUM",
    "BRITANNIA",
    "NESTLEIND",
    "DABUR",
    "MARICO",
    "COLPAL",
    "GODREJCP",
    "VEDL",
    "HINDALCO",
    "COALINDIA",
    "SAIL",
    "NMDC",
    "BPCL",
    "IOC",
    "GAIL",
    "IGL",
    "MGL",
    "DLF",
    "GODREJPROP",
    "OBEROIRLTY",
    "PRESTIGE",
    "BAJAJ-AUTO",
    "HEROMOTOCO",
    "EICHERMOT",
    "MOTHERSON",
    "ZOMATO",
    "NAUKRI",
    "IRCTC",
    "TRENT",
    "DMART",
    "MUTHOOTFIN",
    "CHOLAFIN",
    "HDFCLIFE",
    "SBILIFE",
    "ICICIGI",
    "HAL",
    "BEL",
    "BHEL",
    "RVNL",
    "ABB",
    "SIEMENS",
    "HAVELLS",
    "POLYCAB",
    "SUZLON",
    "INDUSINDBK",
    "FEDERALBNK",
    "BANDHANBNK",
    "MPHASIS",
    "PERSISTENT",
    "COFORGE",
    "LTIM",
    "OFSS",
    "AUROPHARMA",
    "TORNTPHARM",
    "IPCALAB",
    "GLENMARK",
    "BALKRISIND",
    "EXIDEIND",
    "APOLLOTYRE",
    "BHARATFORG",
    "ANGELONE",
    "CDSL",
    "BSE",
    "PNB",
    "BANKBARODA",
    "CANBK",
    "IDFCFIRSTB",
    "JINDALSTEL",
    "APLAPOLLO",
    "NATIONALUM",
    "TATAPOWER",
    "CESC",
    "TORNTPOWER",
    "HDFCAMC",
    "ABCAPITAL",
    "LICHSGFIN",
    "POONAWALLA",
    "YESBANK",
    "RBLBANK",
    "AUBANK",
    "KPITTECH",
    "TATAELXSI",
    "CYIENT",
    "MRF",
    "BOSCHLTD",
    "MINDA",
    "LALPATHLAB",
    "METROPOLIS",
    "BIOCON",
    "PHOENIXLTD",
    "SOBHA",
    "MAHLIFE",
    "PAYTM",
    "NYKAA",
    "DEVYANI",
    "JUBLFOOD",
    "ABBOTINDIA",
    "NATCOPHARM",
    "ZYDUSLIFE",
    "ALKEM",
    "GRINDWELL",
    "CUMMINSIND",
    "KEI",
    "RATNAMANI",
]


# ── Time helpers ──────────────────────────────────────────────────


def _now_ist() -> datetime:
    return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def _today_str() -> str:
    return _now_ist().strftime("%Y-%m-%d")


def _week_key(dt: datetime | None = None) -> str:
    d = (dt or _now_ist()).date()
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


# ── CSV helpers ───────────────────────────────────────────────────


def _load_trades() -> pd.DataFrame:
    # 1) Try local file
    if os.path.exists(TRADES_CSV):
        try:
            df = pd.read_csv(TRADES_CSV, dtype=str)
            for col in TRADES_COLS:
                if col not in df.columns:
                    df[col] = ""
            return df[TRADES_COLS]
        except Exception as e:
            print(f"[SWING] CSV load error: {e}")

    # 2) Fallback: fetch from GitHub (for Render / remote dashboard)
    try:
        import io

        import requests as _req

        r = _req.get(TRADES_CSV_URL, timeout=10)
        if r.status_code == 200:
            print("[SWING] Loaded swing_trades.csv from GitHub fallback")
            df = pd.read_csv(io.StringIO(r.text), dtype=str)
            for col in TRADES_COLS:
                if col not in df.columns:
                    df[col] = ""
            return df[TRADES_COLS]
    except Exception as e:
        print(f"[SWING] GitHub CSV fallback failed: {e}")

    return pd.DataFrame(columns=TRADES_COLS)


def _save_trades(df: pd.DataFrame):
    df.to_csv(TRADES_CSV, index=False)


def _next_id(df: pd.DataFrame) -> int:
    if df.empty or "id" not in df.columns:
        return 1
    ids = pd.to_numeric(df["id"], errors="coerce").dropna()
    return int(ids.max()) + 1 if len(ids) > 0 else 1


def _row_to_dict(row: pd.Series) -> dict:
    """Convert a CSV row (all-strings) to typed dict for dashboard/template use."""

    def _f(v):
        try:
            s = str(v).strip()
            if s.lower() in ("", "nan", "none", "nat", "<na>"):
                return None
            return float(s)
        except Exception:
            return None

    def _s(v):
        return str(v) if v not in ("", None, "nan", "None") else None

    def _b(v):
        return str(v).lower() in ("true", "1", "yes")

    reasons_raw = _s(row.get("reasons", "")) or ""
    reasons = [r.strip() for r in reasons_raw.split("|") if r.strip()]

    return {
        "id": _s(row.get("id")),
        "date": _s(row.get("date")),
        "scan_date": _s(row.get("date")),  # alias for template compat
        "week": _week_key() if not _s(row.get("date")) else _week_from_date(_s(row.get("date"))),
        "symbol": _s(row.get("symbol")) or "",
        "score": _f(row.get("score")) or 0,
        "score_pct": round((_f(row.get("score")) or 0) / 10 * 100, 1),
        "signal_strength": _s(row.get("signal_strength")) or "FAIR",
        "entry": _f(row.get("entry")) or 0,
        "sl": _f(row.get("sl")) or 0,
        "sl_pct": _f(row.get("sl_pct")) or 0,
        "t1": _f(row.get("t1")) or 0,
        "t2": _f(row.get("t2")) or 0,
        "rr_t1": _f(row.get("rr_t1")) or 0,
        "rr_t2": _f(row.get("rr_t2")) or 0,
        "sector": _s(row.get("sector")),
        "layers_passed": int(_f(row.get("layers_passed")) or 0),
        "layer1": _f(row.get("layer1")) or 0,
        "layer2": _f(row.get("layer2")) or 0,
        "layer3": _f(row.get("layer3")) or 0,
        "layer4": _f(row.get("layer4")) or 0,
        "layer5": _f(row.get("layer5")) or 0,
        "bulk_buyers": _s(row.get("bulk_buyers")),
        "pcr": _f(row.get("pcr")),
        "call_oi_chg": _f(row.get("call_oi_chg")),
        "put_oi_chg": _f(row.get("put_oi_chg")),
        "status": _s(row.get("status")) or "OPEN",
        "current_price": _f(row.get("current_price")),
        "exit_price": _f(row.get("exit_price")),
        "pnl_pct": _f(row.get("pnl_pct")),
        "pnl_pts": _f(row.get("pnl_pts")),
        "exit_date": _s(row.get("exit_date")),
        "exit_reason": _s(row.get("exit_reason")),
        "t1_hit": _b(row.get("t1_hit")),
        "days_held": int(_f(row.get("days_held")) or 0),
        "progress_pct": _f(row.get("progress_pct")) or 0,
        "dist_sl_pct": _f(row.get("dist_sl_pct")) or 0,
        "dist_t2_pct": _f(row.get("dist_t2_pct")) or 0,
        "last_updated": _s(row.get("last_updated")),
        "reasons": reasons,
        # Legacy compat
        "rsi": None,
        "vol_ratio": None,
        "macd_bullish": None,
        "ema21": None,
        "rank": 1,
    }


def _week_from_date(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    except Exception:
        return _week_key()


# ── NSE F&O stock list ────────────────────────────────────────────


def _fetch_fno_list() -> list:
    """
    Try NSE API for live F&O stock list.
    Falls back to built-in list on any failure.
    """
    import requests

    try:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
                "Referer": "https://www.nseindia.com/",
            }
        )
        s.get("https://www.nseindia.com/", timeout=8)
        time.sleep(0.5)
        url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
        r = s.get(url, timeout=12)
        if r.status_code == 200:
            data = r.json().get("data", [])
            syms = [row["symbol"] for row in data if row.get("symbol")]
            if len(syms) >= 50:
                print(f"[SWING] NSE F&O list: {len(syms)} stocks")
                return syms[:SWING_SCAN_STOCKS]
    except Exception as e:
        print(f"[SWING] F&O list fetch failed: {e}")
    print(f"[SWING] Using built-in F&O list ({len(_FNO_FALLBACK)} stocks)")
    return _FNO_FALLBACK[:SWING_SCAN_STOCKS]


# ── Live price + daily data ───────────────────────────────────────


def _fetch_live(symbol: str) -> float | None:
    try:
        tk = yf.Ticker(f"{symbol}.NS")
        return float(tk.fast_info["last_price"])
    except Exception:
        return None


def _fetch_daily(symbol: str) -> pd.DataFrame | None:
    try:
        tk = yf.Ticker(f"{symbol}.NS")
        df = tk.history(period="18mo", interval="1d", auto_adjust=True)
        if df.empty or len(df) < 50:
            return None
        df.columns = [c.lower() for c in df.columns]
        return df[["open", "high", "low", "close", "volume"]].dropna()
    except Exception:
        return None


# ── Progress calculator ───────────────────────────────────────────


def _calc_progress(entry: float, t2: float, sl: float, price: float) -> dict:
    total_move = t2 - entry
    done_move = price - entry
    progress = round(done_move / total_move * 100, 1) if total_move > 0 else 0
    dist_sl = round((price - sl) / price * 100, 2)
    dist_t2 = round((t2 - price) / price * 100, 2)
    return {
        "progress_pct": max(min(progress, 100), -50),
        "dist_sl_pct": dist_sl,
        "dist_t2_pct": dist_t2,
    }


# ── Status updater (runs every day on OPEN positions) ─────────────


def update_swing_statuses(silent: bool = False) -> pd.DataFrame:
    """Fetch live prices for all OPEN trades, update P&L and status."""
    df = _load_trades()
    if df.empty:
        return df

    open_mask = df["status"] == "OPEN"
    open_rows = df[open_mask]

    if open_rows.empty:
        return df

    if not silent:
        print(f"[SWING] Updating {len(open_rows)} open position(s)…")

    ist = _now_ist()
    today_str = _today_str()

    for idx, row in open_rows.iterrows():
        sym = str(row["symbol"])
        price = _fetch_live(sym)
        if price is None:
            continue

        entry = float(row["entry"]) if row["entry"] not in ("", None) else price
        t1 = float(row["t1"]) if row["t1"] not in ("", None) else price
        t2 = float(row["t2"]) if row["t2"] not in ("", None) else price
        sl = float(row["sl"]) if row["sl"] not in ("", None) else price * 0.975

        # Days held
        try:
            entry_date = datetime.strptime(str(row["date"]), "%Y-%m-%d").date()
            days_held = (date.today() - entry_date).days
        except Exception:
            days_held = 0

        pnl_pct = round((price - entry) / entry * 100, 2)
        pnl_pts = round(price - entry, 2)
        prog = _calc_progress(entry, t2, sl, price)

        # CSV loaded as dtype=str — convert all values to str before writing back
        df.at[idx, "current_price"] = str(round(price, 2))
        df.at[idx, "exit_price"] = str(round(price, 2))
        df.at[idx, "pnl_pct"] = str(pnl_pct)
        df.at[idx, "pnl_pts"] = str(pnl_pts)
        df.at[idx, "progress_pct"] = str(prog["progress_pct"])
        df.at[idx, "dist_sl_pct"] = str(prog["dist_sl_pct"])
        df.at[idx, "dist_t2_pct"] = str(prog["dist_t2_pct"])
        df.at[idx, "t1_hit"] = str(price >= t1)
        df.at[idx, "days_held"] = str(days_held)
        df.at[idx, "last_updated"] = ist.strftime("%Y-%m-%d %H:%M IST")

        # Status transitions
        if price >= t2:
            df.at[idx, "status"] = "TARGET HIT"
            df.at[idx, "exit_price"] = str(round(price, 2))
            df.at[idx, "exit_date"] = today_str
            df.at[idx, "exit_reason"] = "T2 Hit"
            if not silent:
                print(f"  TARGET HIT {sym} @ ₹{price}  (+{pnl_pct}%)")
        elif price <= sl:
            df.at[idx, "status"] = "SL HIT"
            df.at[idx, "exit_price"] = str(round(price, 2))
            df.at[idx, "exit_date"] = today_str
            df.at[idx, "exit_reason"] = "SL Hit"
            if not silent:
                print(f"  SL HIT {sym} @ ₹{price}  ({pnl_pct}%)")
        elif days_held >= MAX_HOLD:
            df.at[idx, "status"] = "EXPIRED"
            df.at[idx, "exit_price"] = str(round(price, 2))
            df.at[idx, "exit_date"] = today_str
            df.at[idx, "exit_reason"] = f"Max hold ({MAX_HOLD}d)"
            if not silent:
                print(f"  EXPIRED {sym}  {pnl_pct:+.2f}%")
        else:
            arrow = "^" if pnl_pct >= 0 else "v"
            if not silent:
                print(
                    f"  {arrow} {sym:<14} Rs{price:<10}  "
                    f"P&L {pnl_pct:+.2f}%  "
                    f"->T2 {prog['dist_t2_pct']:.1f}%  "
                    f"SL buffer {prog['dist_sl_pct']:.1f}%"
                )

        time.sleep(0.15)

    _save_trades(df)
    return df


# ── EOD Telegram update ───────────────────────────────────────────


def send_eod_update():
    df = _load_trades()
    if df.empty:
        return

    open_ = df[df["status"] == "OPEN"]
    hits = df[df["status"] == "TARGET HIT"]
    sls = df[df["status"] == "SL HIT"]

    if open_.empty and hits.empty and sls.empty:
        return

    ist = _now_ist()
    lines = [
        f"📊 SWING EOD — {ist.strftime('%A %d %b')}",
        "",
    ]

    if not open_.empty:
        lines.append("── Open Positions ──")
        for _, r in open_.iterrows():
            pnl = float(r.get("pnl_pct") or 0)
            prog = float(r.get("progress_pct") or 0)
            bar = "█" * max(0, int(prog / 10)) + "░" * max(0, 10 - int(prog / 10))
            arrow = "▲" if pnl >= 0 else "▼"
            lines.append(
                f"{arrow} {r['symbol']:<14}  ₹{r.get('current_price', '?')}  P&L {pnl:+.2f}%  [{bar}] {prog:.0f}% → T2"
            )

    if not hits.empty:
        lines += ["", "✅ Target Hit"]
        for _, r in hits.iterrows():
            pnl = float(r.get("pnl_pct") or 0)
            lines.append(f"  ✓ {r['symbol']}  +{pnl:.2f}%  @ ₹{r.get('exit_price', '?')}")

    if not sls.empty:
        lines += ["", "❌ SL Hit"]
        for _, r in sls.iterrows():
            pnl = float(r.get("pnl_pct") or 0)
            lines.append(f"  ✗ {r['symbol']}  {pnl:.2f}%  @ ₹{r.get('exit_price', '?')}")

    lines += ["", "⚠ Max hold 15 days. No overnight positions beyond MAX_HOLD."]
    telegram_send("\n".join(lines))


# ── Main scan ─────────────────────────────────────────────────────


def scan_swing() -> list:
    """
    Full daily scan: score all F&O stocks across 5 SMC layers.
    Returns list of signal dicts (score >= SWING_MIN_SCORE).
    """
    ist = _now_ist()
    _today_str()
    fno_list = _fetch_fno_list()

    print(f"[SWING] Scan start — {ist.strftime('%A %d %b %Y %H:%M IST')}")
    print(f"[SWING] Scanning {len(fno_list)} F&O stocks …")

    # ── Pre-fetch shared data (one call for all stocks) ───────────
    print("[SWING] Pre-fetching sector indices…")
    sector_cache = prefetch_sectors()

    print("[SWING] Pre-fetching bulk/block deals…")
    bulk_index = get_bulk_block_buys()

    # NSE session for options (reused across stocks)
    nse_session = None

    # Symbols already OPEN — don't double-signal
    existing_df = _load_trades()
    open_symbols = set(existing_df[existing_df["status"] == "OPEN"]["symbol"].values)

    qualified = []

    for i, sym in enumerate(fno_list, 1):
        print(f"  [{i:>3}/{len(fno_list)}] {sym:<18}", end="", flush=True)

        if sym in open_symbols:
            print("already open — skip")
            continue

        df = _fetch_daily(sym)
        if df is None:
            print("no data")
            continue

        # Fetch sector + bulk (fast, cached)
        sector = check_sector_momentum(sym, df, sector_cache)
        bulk = has_institutional_buy(sym, bulk_index)

        # Quick pre-score (layers 1-4 only — no options yet)
        pre = score_swing(sym, df, sector_result=sector, bulk_result=bulk)
        if pre is None:
            print("score<4.0 — skip")
            time.sleep(0.1)
            continue

        pre_score = pre["layer1"] + pre["layer2"] + pre["layer3"] + pre["layer4"]

        # Only call options API for stocks with promising pre-score
        options = None
        if pre_score >= 4.5:
            if nse_session is None:
                nse_session = make_nse_session()
            price = float(df["close"].iloc[-1])
            options = check_options_oi(
                sym,
                price,
                pcr_min=PCR_MIN,
                pcr_max=PCR_MAX,
                call_oi_min=CALL_OI_INCREASE_MIN,
                session=nse_session,
            )
            time.sleep(0.4)

        # Final score with all 5 layers
        sig = score_swing(
            sym,
            df,
            sector_result=sector,
            bulk_result=bulk,
            options_result=options,
        )

        if sig is None or sig["score"] < SWING_MIN_SCORE:
            score_val = sig["score"] if sig else 0
            print(f"score {score_val:.1f}/10 — below threshold")
            time.sleep(0.1)
            continue

        qualified.append(sig)
        print(
            f"✓ score={sig['score']}/10 [{sig['signal_strength']}]  "
            f"layers={sig['layers_passed']}/5  "
            f"entry=₹{sig['entry']}  T2=₹{sig['t2']}  SL=₹{sig['sl']}"
        )
        time.sleep(0.1)

    qualified.sort(key=lambda x: x["score"], reverse=True)
    top = qualified[:SWING_TOP_N]
    print(f"\n[SWING] {len(qualified)} qualify → Top {len(top)} selected")
    return top


def _add_signals_to_csv(picks: list, today: str):
    """Append new signals to swing_trades.csv."""
    df = _load_trades()
    next_id = _next_id(df)

    new_rows = []
    for i, sig in enumerate(picks):
        reasons_str = " | ".join(sig.get("reasons") or [])
        row = {
            "id": next_id + i,
            "date": today,
            "symbol": sig["symbol"],
            "score": sig["score"],
            "signal_strength": sig["signal_strength"],
            "entry": sig["entry"],
            "sl": sig["sl"],
            "sl_pct": sig["sl_pct"],
            "t1": sig["t1"],
            "t2": sig["t2"],
            "rr_t1": sig["rr_t1"],
            "rr_t2": sig["rr_t2"],
            "sector": sig.get("sector") or "",
            "layers_passed": sig["layers_passed"],
            "layer1": sig["layer1"],
            "layer2": sig["layer2"],
            "layer3": sig["layer3"],
            "layer4": sig["layer4"],
            "layer5": sig["layer5"],
            "bulk_buyers": sig.get("bulk_buyers") or "",
            "pcr": sig.get("pcr") or "",
            "call_oi_chg": sig.get("call_oi_chg") or "",
            "put_oi_chg": sig.get("put_oi_chg") or "",
            "status": "OPEN",
            "current_price": sig["entry"],
            "exit_price": "",
            "pnl_pct": 0.0,
            "pnl_pts": 0.0,
            "exit_date": "",
            "exit_reason": "",
            "t1_hit": False,
            "days_held": 0,
            "progress_pct": 0.0,
            "dist_sl_pct": "",
            "dist_t2_pct": "",
            "last_updated": _now_ist().strftime("%Y-%m-%d %H:%M IST"),
            "reasons": reasons_str,
        }
        new_rows.append(row)

    new_df = pd.DataFrame(new_rows, columns=TRADES_COLS)
    combined = pd.concat([df, new_df], ignore_index=True)
    _save_trades(combined)
    print(f"[SWING] Saved {len(new_rows)} new signals to {TRADES_CSV}")


# ── Telegram alert ────────────────────────────────────────────────


def _format_signal_alert(picks: list, today: str) -> str:
    ist = _now_ist()
    week = _week_key()
    lines = [
        f"📈 SWING SIGNALS — {ist.strftime('%d %b %Y')}  ({week})",
        f"📊 5-Layer SMC Strategy  |  Score ≥ {SWING_MIN_SCORE}/10  |  Hold max {MAX_HOLD} days",
        f"{'━' * 44}",
    ]

    for rank, p in enumerate(picks, 1):

        def bar(v):
            filled = int(v)
            half = 1 if (v - filled) >= 0.5 else 0
            return "█" * filled + ("▌" if half else "") + "░" * (2 - filled - half)

        lines += [
            "",
            f"#{rank} {p['symbol']}  [{p['signal_strength']}  {p['score']}/10]"
            + (f"  ({p.get('sector') or ''})" if p.get("sector") else ""),
            f"  Entry ₹{p['entry']}  |  SL ₹{p['sl']} (-{p['sl_pct']}%)",
            f"  T1  ₹{p['t1']} (+{round(p['t1'] / p['entry'] * 100 - 100, 1)}%)  R:R 1:{p['rr_t1']}",
            f"  T2  ₹{p['t2']} (+{round(p['t2'] / p['entry'] * 100 - 100, 1)}%)  R:R 1:{p['rr_t2']}",
            (f"  L1 Structure {bar(p['layer1'])}  L2 FVG+OB {bar(p['layer2'])}  L3 LiqGrab {bar(p['layer3'])}"),
            (f"  L4 Sector {bar(p['layer4'])}  L5 Inst+OI {bar(p['layer5'])}  ({p['layers_passed']}/5 layers)"),
        ]
        if p.get("bulk_buyers"):
            lines.append(f"  Buyers: {p['bulk_buyers']}")
        if p.get("pcr") is not None:
            coc = (p.get("call_oi_chg") or 0) * 100
            lines.append(f"  PCR {p['pcr']:.2f} | CE OI {coc:+.0f}%")
        if p.get("reasons"):
            lines.append(f"  → {' · '.join(p['reasons'][:3])}")

    lines += [
        "",
        f"{'━' * 44}",
        f"⚠ Max SL 2.5%  |  Book 50% at T1  |  Exit all at T2 or day {MAX_HOLD}",
    ]
    return "\n".join(lines)


# ── Dashboard data provider ───────────────────────────────────────


def get_swing_data() -> dict:
    """
    Load swing_trades.csv, refresh OPEN position prices, return
    dashboard-compatible dict.

    Called on every dashboard page load — keep it fast.
    On Vercel / read-only hosts: skip live yfinance calls (would time out).
    """
    _is_vercel = os.environ.get("VERCEL") or os.environ.get("VERCEL_ENV")
    if _is_vercel:
        updated_df = _load_trades()  # read-only, no live price fetch
    else:
        updated_df = update_swing_statuses(silent=True)

    if updated_df.empty:
        return {
            "week_picks": [],
            "all_picks": [],
            "summary": {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "open": 0,
                "win_rate": 0,
                "avg_score": 0,
                "week": _week_key(),
            },
        }

    # Convert all rows to typed dicts
    all_picks = [_row_to_dict(row) for _, row in updated_df.iterrows()]
    all_picks.reverse()  # newest first

    # "Week picks" = signals from the last 14 days
    cutoff = _now_ist().date() - timedelta(days=14)
    week_picks = [p for p in all_picks if p.get("date") and _safe_date(p["date"]) >= cutoff]

    # Summary stats
    wins = sum(1 for p in all_picks if p["status"] == "TARGET HIT")
    losses = sum(1 for p in all_picks if p["status"] == "SL HIT")
    opens = sum(1 for p in all_picks if p["status"] == "OPEN")
    closed = wins + losses
    total = len(all_picks)

    scores = [p["score"] for p in all_picks if p["score"]]
    avg_score = round(sum(scores) / len(scores), 2) if scores else 0

    return {
        "week_picks": week_picks[:10],
        "all_picks": all_picks[:50],
        "summary": {
            "total": total,
            "wins": wins,
            "losses": losses,
            "open": opens,
            "win_rate": round(wins / closed * 100, 1) if closed > 0 else 0,
            "avg_score": avg_score,
            "week": _week_key(),
        },
    }


def _safe_date(date_str: str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return date(2000, 1, 1)


# ── Legacy wrapper so old imports don't break ─────────────────────
# run_swing used to export scan_swing() and get_swing_data()
# Both are still exported above. SWING_WATCHLIST removed (live F&O now).


# ── Git auto-sync (PC = source of truth for the dashboard) ────────


def _git_push_csv():
    """Push swing_trades.csv to GitHub so the Render dashboard stays in
    sync with local runs. Best-effort — never crashes the bot.
    Only runs from the CLI entry point (never from the dashboard import)."""
    import subprocess

    repo = os.path.dirname(os.path.abspath(__file__))

    def _git(*args):
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=60,
        )

    try:
        status = _git("status", "--porcelain", TRADES_CSV)
        if not status.stdout.strip():
            print("[SWING] CSV unchanged — nothing to push.")
            return

        _git("add", TRADES_CSV)
        _git("commit", "-m", f"chore: sync swing_trades.csv {_today_str()} [skip ci]")
        # --autostash: local config.py (token) is always dirty; stash it
        # around the rebase automatically so the pull never fails.
        _git("pull", "--rebase", "--autostash", "origin", "main")
        push = _git("push", "origin", "main")
        if push.returncode == 0:
            print("[SWING] ✓ swing_trades.csv pushed — dashboard will update shortly.")
        else:
            print(f"[SWING] git push failed (dashboard not updated): {push.stderr.strip() or push.stdout.strip()}")
    except Exception as e:
        print(f"[SWING] git sync skipped: {e}")


# ── Entry point ───────────────────────────────────────────────────


def main():
    ist = _now_ist()
    today = _today_str()
    force_scan = os.environ.get("FORCE_SWING", "0") == "1"
    update_only = os.environ.get("UPDATE_ONLY", "0") == "1"

    print(f"[SWING] {ist.strftime('%A %d %b %Y %H:%M IST')}")

    # Always update open positions first
    updated_df = update_swing_statuses()
    open_count = int((updated_df["status"] == "OPEN").sum()) if not updated_df.empty else 0
    print(f"[SWING] {open_count} open position(s) after status update")

    if update_only:
        send_eod_update()
        return

    # Check if already scanned today
    scanned_today = (updated_df["date"] == today).any() if not updated_df.empty else False

    if scanned_today and not force_scan:
        print(f"[SWING] Already scanned today ({today}). Sending EOD update.")
        send_eod_update()
        return

    # Full scan
    picks = scan_swing()

    if not picks:
        print("[SWING] No qualifying stocks today")
        telegram_send(
            f"📊 Swing Scan {today}: No qualifying stocks (score ≥ {SWING_MIN_SCORE}/10).\n"
            f"Market may be choppy — skipping today."
        )
        return

    _add_signals_to_csv(picks, today)

    alert = _format_signal_alert(picks, today)
    ok = telegram_send(alert)
    print(f"[SWING] Alert: {'SENT' if ok else 'FAILED'}")

    print(f"\n── Today's picks ({today}) ──")
    for p in picks:
        print(f"  {p['symbol']:<14} score={p['score']}/10  entry=₹{p['entry']}  T2=₹{p['t2']}  SL=₹{p['sl']}")


if __name__ == "__main__":
    main()
    _git_push_csv()  # PC = source of truth → keep GitHub/dashboard in sync
