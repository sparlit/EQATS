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
Sub-250 Momentum Scanner - Mid/Small/Microcap Universe
Scans a universe of mid/small/microcap stocks, filters to price < Rs 250,
ranks by momentum, and maintains a rotating portfolio rebalanced every
1 month (only replacing dropped-out names, not full churn).

Run this daily. It only actually rebalances when 30+ days have passed
since the last rebalance (tracked in the log file itself).

NOTE: This currently screens the sub-Rs-250 price band only. A separate
run/config for medium-priced stocks (Rs 250-1000+) can follow the same
pattern later - just adjust MAX_PRICE/MIN_PRICE and use a different
PORTFOLIO_FILE/LOG_FILE so the two don't overwrite each other.
"""

import time
from datetime import datetime

import pandas as pd
import requests

# ---------------- CONFIG ----------------
# Universe: expanded mix of mid/small/microcap names across sectors.
# This is still a STARTING list - expand further with your own screener
# output (market cap < ~15,000 cr roughly covers mid+small+micro on NSE).
STOCK_LIST = [
    # NBFC / Finance
    "IFCI",
    "USHAFIN",
    "CSLFINANCE",
    "AKIKO",
    "TAMBOLIIN",
    "AUSOMENT",
    "IVC",
    "EDELWEISS",
    "MANAPPURAM",
    "MUTHOOTFIN",
    "SPANDANA",
    "CREDITACC",
    "UGROCAP",
    "FIVE-STAR",
    "APTUS",
    "HOMEFIRST",
    "IIFL",
    "MOTILALOFS",
    "JMFINANCIL",
    "CHOLAHLDNG",
    # PSU Banks
    "SAIL",
    "PNB",
    "BANKBARODA",
    "CANBK",
    "UNIONBANK",
    "IOB",
    "SOUTHBANK",
    "CENTRALBK",
    "MAHABANK",
    "UCOBANK",
    "PSB",
    "YESBANK",
    "IDBI",
    "J&KBANK",
    # PSU / Infra / Power
    "COALINDIA",
    "NHPC",
    "IRFC",
    "RVNL",
    "SJVN",
    "NBCC",
    "HUDCO",
    "GMRINFRA",
    "JPPOWER",
    "RPOWER",
    "JAIPRAKASH",
    "PFC",
    "RECLTD",
    "NLCINDIA",
    "NTPC",
    "PTC",
    "TORNTPOWER",
    "CESC",
    # Infra / Construction / Engineering
    "IRCON",
    "RITES",
    "MAZDOCK",
    "COCHINSHIP",
    "GRSE",
    "IRB",
    "PNCINFRA",
    "KNRCON",
    "HGINFRA",
    "ASHOKA",
    "NCC",
    "GPIL",
    "PATELENG",
    "JKIL",
    "WELSPUNIND",
    "KEC",
    "TITAGARH",
    "TEXRAIL",
    # Telecom / Media
    "IDEA",
    "TTML",
    "IFB",
    "DISHTV",
    "SUNTV",
    "ZEEL",
    "NETWORK18",
    # Metals / Mining
    "NATIONALUM",
    "HINDCOPPER",
    "MOIL",
    "NMDC",
    "GMDCLTD",
    "JINDALSTEL",
    "WELCORP",
    "RATNAMANI",
    "APLLTD",
    "JSL",
    # Textiles / Consumer
    "TRIDENT",
    "VARDHACRLC",
    "RTNINDIA",
    "GOKEX",
    "KPRMILL",
    "WELSPUNLIV",
    "SIYSIL",
    "SPENTEX",
    "NAHARSPING",
    # Chemicals / Agro
    "GNFC",
    "GSFC",
    "RCF",
    "CHAMBLFERT",
    "NFL",
    "MADRASFERT",
    "COROMANDEL",
    "SHARDACROP",
    "DHANUKA",
    "BASF",
    "INSECTICID",
    # Auto ancillary / Industrials
    "SUZLON",
    "BHEL",
    "BEML",
    "HAL",
    "BEL",
    "GRINDWELL",
    "CARBORUNIV",
    "SCHAEFFLER",
    "TIMKEN",
    "SKFINDIA",
    "GRAVITA",
    # Real Estate
    "SOBHA",
    "BRIGADE",
    "SUNTECK",
    "MAHLIFE",
    "IBREALEST",
    "PURVA",
]

MAX_PRICE = 250.0
MIN_PRICE = 5.0  # avoid true penny/illiquid junk
MAX_MARKET_CAP_CR = 15000  # rough mid+small+micro cutoff
TOP_N = 10  # portfolio size
LOOKBACK_MOMENTUM_DAYS = 20  # ~1 month momentum window
REBALANCE_DAYS = 30

PORTFOLIO_FILE = "subprice_momentum_portfolio.csv"
LOG_FILE = "subprice_momentum_log.csv"


# ---------------- DATA FETCH ----------------
def fetch_yahoo_data(symbol, range_period="3mo", interval="1d"):
    yahoo_sym = f"{symbol}.NS"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}"
    params = {"range": range_period, "interval": interval}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        result = data["chart"]["result"][0]
        ts = result["timestamp"]
        q = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(ts, unit="s").normalize(),
                "close": q["close"],
                "high": q["high"],
                "low": q["low"],
                "volume": q["volume"],
            }
        )
        df.dropna(inplace=True)
        df.set_index("date", inplace=True)
        return df
    except Exception:
        return None


def fetch_market_cap(symbol):
    """Rough market cap check via Screener.in top-ratios (reuses existing pattern)"""
    import re

    from bs4 import BeautifulSoup

    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code != 200:
            url = f"https://www.screener.in/company/{symbol}/"
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select("#top-ratios li"):
            name_tag = item.select_one(".name")
            value_tag = item.select_one(".value")
            if name_tag and value_tag and name_tag.text.strip() == "Market Cap":
                val = value_tag.text.strip().replace(",", "")
                m = re.search(r"[-+]?\d*\.?\d+", val)
                return float(m.group()) if m else None
        return None
    except Exception:
        return None


# ---------------- MOMENTUM SCORING ----------------
def compute_momentum(df):
    if df is None or len(df) < LOOKBACK_MOMENTUM_DAYS + 5:
        return None
    close = df["close"]
    roc = (close.iloc[-1] / close.iloc[-LOOKBACK_MOMENTUM_DAYS] - 1) * 100
    avg_vol_recent = df["volume"].iloc[-5:].mean()
    avg_vol_prior = df["volume"].iloc[-LOOKBACK_MOMENTUM_DAYS:-5].mean()
    vol_surge = (avg_vol_recent / avg_vol_prior) if avg_vol_prior > 0 else 1.0
    score = roc * 0.7 + (vol_surge - 1) * 100 * 0.3
    return {
        "roc_pct": round(roc, 2),
        "vol_surge": round(vol_surge, 2),
        "score": round(score, 2),
        "current_price": round(close.iloc[-1], 2),
    }


# ---------------- REBALANCE STATE ----------------
def load_portfolio():
    try:
        return pd.read_csv(PORTFOLIO_FILE)
    except FileNotFoundError:
        return pd.DataFrame(
            columns=["symbol", "entry_date", "entry_price", "score_at_entry", "status"]
        )


def save_portfolio(df):
    df.to_csv(PORTFOLIO_FILE, index=False)


def days_since_last_rebalance(portfolio_df):
    active = portfolio_df[portfolio_df["status"] == "HOLD"]
    if active.empty:
        return REBALANCE_DAYS + 1  # force rebalance if empty
    last_date = pd.to_datetime(active["entry_date"]).max()
    return (datetime.now() - last_date).days


def log_daily_snapshot(portfolio_df, universe_data):
    active = portfolio_df[portfolio_df["status"] == "HOLD"]
    if active.empty:
        return
    total_entry = 0
    total_current = 0
    for _, pos in active.iterrows():
        sym = pos["symbol"]
        if sym in universe_data and universe_data[sym] is not None:
            current_price = universe_data[sym]["close"].iloc[-1]
            total_entry += pos["entry_price"]
            total_current += current_price
    if total_entry > 0:
        pnl_pct = round((total_current - total_entry) / total_entry * 100, 2)
        log_row = pd.DataFrame(
            [
                {
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "total_entry": round(total_entry, 2),
                    "total_current": round(total_current, 2),
                    "pnl_pct": pnl_pct,
                    "stocks_held": len(active),
                }
            ]
        )
        try:
            existing_log = pd.read_csv(LOG_FILE)
            log_row = pd.concat([existing_log, log_row], ignore_index=True)
        except FileNotFoundError:
            pass
        log_row.to_csv(LOG_FILE, index=False)


# ---------------- MAIN ----------------
def run_scanner():
    print(f"Scanning {len(STOCK_LIST)} mid/small/microcap stocks...\n")
    universe_data = {}
    candidates = []

    for sym in STOCK_LIST:
        df = fetch_yahoo_data(sym)
        if df is None or len(df) < LOOKBACK_MOMENTUM_DAYS + 5:
            continue
        universe_data[sym] = df

        current_price = df["close"].iloc[-1]
        if not (MIN_PRICE <= current_price <= MAX_PRICE):
            continue

        mom = compute_momentum(df)
        if mom is None:
            continue

        mcap = fetch_market_cap(sym)
        time.sleep(1.0)
        if mcap is not None and mcap > MAX_MARKET_CAP_CR:
            continue  # too large - not mid/small/micro

        candidates.append(
            {
                "symbol": sym,
                "price": mom["current_price"],
                "roc_pct": mom["roc_pct"],
                "vol_surge": mom["vol_surge"],
                "score": mom["score"],
                "market_cap_cr": mcap,
            }
        )
        print(
            f"  {sym:15s} Price:{current_price:>7.1f} ROC:{mom['roc_pct']:>+6.1f}% "
            f"VolSurge:{mom['vol_surge']:>4.1f}x Score:{mom['score']:>+7.1f}"
        )

    candidates_df = pd.DataFrame(candidates)
    if candidates_df.empty:
        print("\nNo candidates found under Rs 250 with sufficient data.")
        return

    candidates_df = candidates_df.sort_values("score", ascending=False)
    candidates_df.to_csv("subprice_momentum_ranking.csv", index=False)
    print(f"\nSaved: subprice_momentum_ranking.csv ({len(candidates_df)} candidates)")

    # ---------------- PORTFOLIO / REBALANCE LOGIC ----------------
    portfolio_df = load_portfolio()
    days_elapsed = days_since_last_rebalance(portfolio_df)

    print(f"\nDays since last rebalance: {days_elapsed} (rebalance trigger: {REBALANCE_DAYS} days)")

    if days_elapsed >= REBALANCE_DAYS:
        print("\n" + "=" * 60)
        print("REBALANCING PORTFOLIO")
        print("=" * 60)

        # Close all current holdings
        if not portfolio_df.empty:
            portfolio_df.loc[portfolio_df["status"] == "HOLD", "status"] = "CLOSED"

        # Open new top-N positions
        top_picks = candidates_df.head(TOP_N)
        new_rows = []
        for _, row in top_picks.iterrows():
            new_rows.append(
                {
                    "symbol": row["symbol"],
                    "entry_date": datetime.now().strftime("%Y-%m-%d"),
                    "entry_price": row["price"],
                    "score_at_entry": row["score"],
                    "status": "HOLD",
                }
            )
        new_portfolio = pd.DataFrame(new_rows)
        portfolio_df = pd.concat([portfolio_df, new_portfolio], ignore_index=True)
        save_portfolio(portfolio_df)

        print(f"\nNew portfolio ({len(new_rows)} stocks):")
        for _, row in new_portfolio.iterrows():
            print(
                f"  BUY  {row['symbol']:15s} @ Rs{row['entry_price']:.2f} "
                f"(score: {row['score_at_entry']:.1f})"
            )
    else:
        print(f"\nNo rebalance yet - {REBALANCE_DAYS - days_elapsed} days remaining.")
        active = portfolio_df[portfolio_df["status"] == "HOLD"]
        if not active.empty:
            print(f"\nCurrent holdings ({len(active)}):")
            for _, row in active.iterrows():
                sym = row["symbol"]
                current_price = (
                    universe_data.get(sym, {}).get("close", pd.Series([None])).iloc[-1]
                    if sym in universe_data
                    else None
                )
                if current_price is not None:
                    chg = (current_price - row["entry_price"]) / row["entry_price"] * 100
                    print(
                        f"  {sym:15s} Entry:{row['entry_price']:>7.2f} "
                        f"Now:{current_price:>7.2f} PnL:{chg:>+6.2f}%"
                    )

        # Log daily snapshot regardless of rebalance
        log_daily_snapshot(portfolio_df, universe_data)
        print(f"\nDaily snapshot logged to {LOG_FILE}")


if __name__ == "__main__":
    run_scanner()
