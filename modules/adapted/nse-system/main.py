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
Entry point:
  python main.py scan              # live EOD scan (smallcap band)
  python main.py backtest          # 2-year backtest
  python main.py scan URL          # scan a Chartink screener
"""
import re
import sys
from datetime import datetime, timedelta

import db
import pandas as pd
import requests
from backtest import Backtester, BacktestResult
from regime import MarketRegime
from scanner import Screener
from setup import SetupDetector

FALLBACK_UNIVERSE = [
    "TATAMOTORS.NS",
    "DIXON.NS",
    "POLYCAB.NS",
    "KEI.NS",
    "ASTRAL.NS",
    "BEL.NS",
    "HAL.NS",
    "RVNL.NS",
    "IRFC.NS",
    "KPIT.NS",
]


def smallcap_universe(limit=600, min_mcap=1000, max_mcap=8000):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT symbol FROM universe_broad WHERE mcap_cr BETWEEN ? AND ? ORDER BY mcap_cr DESC LIMIT ?",
        (min_mcap, max_mcap, limit),
    ).fetchall()
    conn.close()
    return [r[0] + ".NS" for r in rows]


DEFAULT_UNIVERSE = smallcap_universe() or FALLBACK_UNIVERSE


def extract_symbols_from_chartink(url):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        return sorted(set(re.findall(r"/stocks/NSE/([A-Z0-9]+)", r.text)))
    except Exception as e:
        print("Chartink scrape failed:", e)
        return []


def live_scan(universe=None):
    print("\n🌐 MARKET REGIME CHECK")
    reg = MarketRegime.compute()
    print(
        f"   Index: {reg.index_close}  EMA10: {reg.ema10}  Stance: {'BULLISH ✅' if reg.is_bullish else 'DEFENSIVE 🛑'}"
    )
    if not reg.is_bullish:
        print("   ➤ No new entries. Manage open positions only.")
        return

    print(f"\n🔎 SCANNING {len(universe)} STOCKS...")
    end = datetime.today().strftime("%Y-%m-%d")
    start = (datetime.today() - timedelta(days=730)).strftime("%Y-%m-%d")
    setups_found = []
    for sym in universe:
        df = Backtester._load(sym, start, end)
        if df is None or len(df) < 280:
            continue
        sc = Screener.evaluate(df, sym)
        if not sc.passed:
            continue
        st = SetupDetector.detect(df, sym)
        if st.triggered:
            setups_found.append(st)
            print(
                f"   ✅ {sym}: entry ₹{st.entry_price}  "
                f"SL ₹{st.stop_loss}  TGT ₹{st.target_price}  "
                f"R:R {st.risk_reward}  PB {st.pullback_depth:.1%} "
                f"({st.pullback_days}d) near {st.ema_proximity}"
            )
    print(f"\n📊 RESULT: {len(setups_found)} setups triggered today")


def run_backtest(universe=None, years=2):
    end = datetime.today()
    start = end - timedelta(days=years * 365)
    print(f"\n🚀 BACKTESTING {len(universe)} stocks over {years} years...")
    bt = Backtester()
    result = bt.run(universe, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    print(result.summary())
    if result.trades:
        df = pd.DataFrame(
            [
                {
                    "Symbol": t.symbol,
                    "Entry": t.entry_date,
                    "Exit": t.exit_date,
                    "EntryRs": t.entry_price,
                    "ExitRs": t.exit_price,
                    "Stop": t.stop_loss,
                    "Target": t.target_price,
                    "PnLPct": round(t.pnl_pct * 100, 2),
                    "Days": t.holding_days,
                    "Reason": t.exit_reason,
                }
                for t in result.trades
            ]
        )
        df.to_csv("backtest_trades.csv", index=False)
        print(f"\n✓ Trade log saved to backtest_trades.csv ({len(result.trades)} rows)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    if mode == "backtest":
        run_backtest(DEFAULT_UNIVERSE, years=4)
    elif mode == "scan":
        if len(sys.argv) > 2 and sys.argv[2].startswith("http"):
            univ = [s + ".NS" for s in extract_symbols_from_chartink(sys.argv[2])]
            univ = univ or DEFAULT_UNIVERSE
        else:
            univ = DEFAULT_UNIVERSE
        live_scan(univ)
    else:
        print("Usage: python main.py [scan|backtest] [chartink_url]")
