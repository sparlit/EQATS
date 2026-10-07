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


#!/usr/bin/env python3
"""
Screener.in intraday list → May 2026 backtest analysis.

Fetches the top N stocks from the screener.in screen, runs a full
May 2026 walk-forward backtest on each, then reports per-stock metrics
and the overall average win rate — the key diagnostic for system health.

Usage:
    python analyze_screener.py

Optional env overrides:
    N_STOCKS=15 START=2026-05-01 END=2026-05-30 python analyze_screener.py
"""

import os
import re
import sys
import time
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

import requests
from backtest import run
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────

SCREENER_URL = "https://www.screener.in/screens/486756/intraday-stock-list/?order=asc&page=1"
N_STOCKS = int(os.getenv("N_STOCKS", 10))
START = os.getenv("START", "2026-05-01")
END = os.getenv("END", "2026-05-30")
CAPITAL = int(os.getenv("CAPITAL", 100_000))

# Stocks to try if screener.in is unreachable
_FALLBACK = [
    "HDFCBANK",
    "ICICIBANK",
    "RELIANCE",
    "INFY",
    "TCS",
    "SBIN",
    "AXISBANK",
    "KOTAKBANK",
    "BAJFINANCE",
    "BHARTIARTL",
]


# ── Screener.in scraper ───────────────────────────────────────────────────────


def fetch_symbols(url: str, n: int) -> list[str]:
    """Return first n NSE symbols from a screener.in screen page."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [WARN] screener.in fetch failed: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    found, seen = [], set()
    for a in soup.select("a[href^='/company/']"):
        m = re.match(r"^/company/([A-Z0-9&]+)/", a["href"])
        if m:
            sym = m.group(1)
            if sym not in seen:
                seen.add(sym)
                found.append(sym)
        if len(found) >= n:
            break
    return found


def to_yf_ticker(symbol: str) -> str:
    """Convert a bare NSE symbol to the yfinance format (add .NS)."""
    if symbol.endswith(".NS") or symbol.endswith(".BO"):
        return symbol
    return f"{symbol}.NS"


# ── Per-stock backtest ────────────────────────────────────────────────────────


def backtest_stock(symbol: str, ticker: str) -> dict:
    try:
        r = run(symbols=[ticker], start_date=START, end_date=END, capital=CAPITAL, save_to_db=False)
        s = r["summary"]
        rs = r["regime_stats"]

        regime_mix = {k: v["days"] for k, v in rs.items() if v["days"] > 0}

        # Per-regime win rates
        regime_wr = {
            k: round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0 for k, v in rs.items()
        }

        return {
            "symbol": symbol,
            "ticker": ticker,
            "trades": s["total_trades"],
            "wins": s["wins"],
            "wr": s["win_rate"],
            "pnl": s["pnl"],
            "expectancy": s["expectancy"],
            "pf": s["profit_factor"],
            "avg_win": s["avg_win"],
            "avg_loss": s["avg_loss"],
            "max_dd": s["max_drawdown"],
            "sharpe": s["sharpe"],
            "regime_mix": regime_mix,
            "regime_wr": regime_wr,
            "ok": True,
        }
    except Exception as e:
        return {"symbol": symbol, "ticker": ticker, "ok": False, "error": str(e)}


# ── Printing helpers ──────────────────────────────────────────────────────────


def _pnl_str(v: float) -> str:
    return f"+₹{v:,.0f}" if v >= 0 else f"-₹{abs(v):,.0f}"


def _regime_summary(mix: dict) -> str:
    labels = {"trending": "T", "sideways": "S", "high_vol": "V"}
    return "  ".join(f"{labels[k]}:{v}d" for k, v in mix.items())


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    print(f"\n{'=' * 62}")
    print(f"  Screener → Backtest  |  {START} – {END}  |  capital ₹{CAPITAL:,}")
    print(f"{'=' * 62}\n")

    # Step 1: Fetch stock list
    print("[1/3] Fetching stock list from screener.in...")
    symbols = fetch_symbols(SCREENER_URL, N_STOCKS)
    if not symbols:
        print("      Screener unavailable — using fallback list.")
        symbols = _FALLBACK[:N_STOCKS]
    else:
        print(f"      Got {len(symbols)} stocks: {', '.join(symbols[:N_STOCKS])}")
    symbols = symbols[:N_STOCKS]

    yf_tickers = [to_yf_ticker(s) for s in symbols]

    # Step 2: Run backtests
    print(f"\n[2/3] Running backtests ({len(symbols)} stocks)...\n")
    results = []
    for i, (sym, ticker) in enumerate(zip(symbols, yf_tickers, strict=False), 1):
        print(f"  [{i:02d}/{len(symbols)}] {sym:<14}", end="", flush=True)
        t0 = time.time()
        row = backtest_stock(sym, ticker)
        elapsed = time.time() - t0
        if row["ok"]:
            print(
                f"  {row['trades']:>3} trades  WR={row['wr']:>5.1f}%  "
                f"PnL={_pnl_str(row['pnl']):>14}  ({elapsed:.1f}s)"
            )
        else:
            print(f"  FAILED: {row.get('error', '?')}")
        results.append(row)

    valid = [r for r in results if r.get("ok") and r["trades"] > 0]
    failed = [r for r in results if not r.get("ok")]

    # Step 3: Print summary table
    print("\n[3/3] Results\n")
    _W = 62
    print(
        f"  {'Symbol':<12}  {'Trades':>6}  {'WR%':>6}  {'PnL':>12}  "
        f"{'Expect':>8}  {'PF':>5}  Regime (days)"
    )
    print("  " + "-" * (_W - 2))

    for r in sorted(results, key=lambda x: -x.get("wr", -999)):
        if not r.get("ok") or r["trades"] == 0:
            print(f"  {r['symbol']:<12}  {'—':>6}  {'—':>6}  {'no data':>12}")
            continue
        print(
            f"  {r['symbol']:<12}  {r['trades']:>6}  {r['wr']:>5.1f}%  "
            f"{_pnl_str(r['pnl']):>12}  {r['expectancy']:>+8.0f}  "
            f"{r['pf']:>5.2f}  {_regime_summary(r['regime_mix'])}"
        )

    if not valid:
        print("\n  No valid results. Check tickers / date range.\n")
        return

    print("  " + "-" * (_W - 2))

    avg_wr = sum(r["wr"] for r in valid) / len(valid)
    avg_pnl = sum(r["pnl"] for r in valid) / len(valid)
    avg_exp = sum(r["expectancy"] for r in valid) / len(valid)
    avg_pf = sum(r["pf"] for r in valid) / len(valid)
    total_trades = sum(r["trades"] for r in valid)

    print(
        f"  {'AVERAGE':<12}  {total_trades:>6}  {avg_wr:>5.1f}%  "
        f"{_pnl_str(avg_pnl):>12}  {avg_exp:>+8.0f}  {avg_pf:>5.2f}"
    )

    # Best / worst
    best = max(valid, key=lambda x: x["wr"])
    worst = min(valid, key=lambda x: x["wr"])

    print(f"\n  Best  : {best['symbol']:<14} WR={best['wr']:.1f}%  PnL={_pnl_str(best['pnl'])}")
    print(f"  Worst : {worst['symbol']:<14} WR={worst['wr']:.1f}%  PnL={_pnl_str(worst['pnl'])}")

    # Regime mix aggregated
    t_days = s_days = v_days = 0
    for r in valid:
        t_days += r["regime_mix"].get("trending", 0)
        s_days += r["regime_mix"].get("sideways", 0)
        v_days += r["regime_mix"].get("high_vol", 0)
    total_days = t_days + s_days + v_days or 1
    print("\n  Regime distribution (across all stocks):")
    print(f"    Trending  {t_days:>4}d  ({t_days / total_days * 100:.0f}%)")
    print(f"    Sideways  {s_days:>4}d  ({s_days / total_days * 100:.0f}%)")
    print(f"    High-vol  {v_days:>4}d  ({v_days / total_days * 100:.0f}%)")

    # Diagnosis
    print(f"\n{'=' * 62}")
    print(f"  Average Win Rate : {avg_wr:.1f}%   (breakeven at R:R 2.5x = 28.6%)")
    margin = avg_wr - 28.6
    if margin >= 5:
        verdict = "EDGE CONFIRMED — focus on position sizing & diversification."
    elif margin >= 0:
        verdict = "MARGINAL EDGE — small sample noise can flip this. Gather more days."
    else:
        verdict = "NO EDGE YET — entry quality needs work (regime filter / signal filter)."
    print(f"  Margin over b/e  : {margin:+.1f}pp")
    print(f"  Verdict          : {verdict}")

    if failed:
        print(f"\n  Failed stocks ({len(failed)}): {', '.join(r['symbol'] for r in failed)}")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
