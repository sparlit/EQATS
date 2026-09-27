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


# ============================================================
# MOMENTUM ROTATION STRATEGY (v3 - with rebalance/check modes)
# Universe: Nifty MidSmallcap 400 + Nifty Microcap 250
# Rebalance: Monthly (21st) - exit rank>40, replace with top-ranked
# Check-only: every 2 days - just tracks P&L, no buy/sell
# ============================================================

import os
import sys
import time
from datetime import datetime
from io import StringIO

import numpy as np
import pandas as pd
import requests

os.makedirs("data", exist_ok=True)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

TOTAL_CAPITAL = 100000
TOP_N = 15
EXIT_RANK_THRESHOLD = 40
MIN_TRADING_DAYS = 200

PORTFOLIO_FILE = "data/momentum_portfolio.csv"
RANKING_FILE = "data/momentum_ranking.csv"
UNIVERSE_CACHE = "data/momentum_universe.csv"

# -------------------- UNIVERSE FETCH --------------------


def fetch_index_list(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            return []
        df = pd.read_csv(StringIO(r.text))
        symbol_col = [c for c in df.columns if "symbol" in c.lower()]
        if not symbol_col:
            return []
        return [f"{s}.NS" for s in df[symbol_col[0]].dropna().unique()]
    except Exception as e:
        print(f"  fetch failed for {url}: {e}")
        return []


def fetch_index_with_fallback(index_name, url_candidates):
    for url in url_candidates:
        symbols = fetch_index_list(url)
        if len(symbols) > 20:
            print(f"  fetched {len(symbols)} symbols from {url}")
            return symbols
        print(f"  tried {url} -> {len(symbols)} symbols, trying next...")
    print(f"  ALL URLs failed for {index_name}")
    return []


def get_universe():
    midsmallcap_urls = [
        "https://nsearchives.nseindia.com/content/indices/ind_niftymidsmallcap400list.csv",
        "https://archives.nseindia.com/content/indices/ind_niftymidsmallcap400list.csv",
    ]
    microcap_urls = [
        "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
        "https://archives.nseindia.com/content/indices/ind_niftymicrocap250list.csv",
        "https://archives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
    ]

    all_symbols = []
    all_symbols.extend(fetch_index_with_fallback("MidSmallcap400", midsmallcap_urls))
    all_symbols.extend(fetch_index_with_fallback("Microcap250", microcap_urls))

    all_symbols = sorted(set(all_symbols))

    if len(all_symbols) < 100:
        print("Fetch seems incomplete, checking cache...")
        if os.path.exists(UNIVERSE_CACHE):
            cached = pd.read_csv(UNIVERSE_CACHE)["Symbol"].tolist()
            print(f"  using cached universe: {len(cached)} symbols")
            return cached
        print("  No cache available. Fetch failed and no fallback.")
        return []

    pd.DataFrame({"Symbol": all_symbols}).to_csv(UNIVERSE_CACHE, index=False)
    return all_symbols


# -------------------- DATA FETCH --------------------


def fetch_data(symbol, retries=2):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1y", "interval": "1d"}
    for _attempt in range(retries):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            data = r.json()
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            q = result["indicators"]["quote"][0]
            df = pd.DataFrame({"Close": q["close"]}, index=pd.to_datetime(ts, unit="s"))
            return df.dropna()
        except Exception:
            time.sleep(1)
    return None


def get_current_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"range": "1d", "interval": "1m"}
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        data = r.json()
        return round(float(data["chart"]["result"][0]["meta"]["regularMarketPrice"]), 2)
    except Exception:
        return None


# -------------------- MOMENTUM SCORING --------------------


def compute_momentum(df):
    close = df["Close"]
    if len(close) < MIN_TRADING_DAYS:
        return None

    latest = float(close.iloc[-1])

    def ret_n_days(n):
        if len(close) <= n:
            return None
        past = float(close.iloc[-n - 1])
        return (latest - past) / past * 100

    ret_3m = ret_n_days(63)
    ret_6m = ret_n_days(126)
    ret_9m = ret_n_days(189)

    if None in (ret_3m, ret_6m, ret_9m):
        return None

    daily_ret = close.pct_change().tail(63)
    vol_3m = float(daily_ret.std() * 100)
    if vol_3m == 0 or np.isnan(vol_3m):
        return None

    avg_return = (ret_3m + ret_6m + ret_9m) / 3
    momentum_score = avg_return / vol_3m

    return {
        "CMP": round(latest, 2),
        "Return3M%": round(ret_3m, 2),
        "Return6M%": round(ret_6m, 2),
        "Return9M%": round(ret_9m, 2),
        "Volatility3M": round(vol_3m, 2),
        "MomentumScore": round(momentum_score, 3),
    }


# -------------------- RANK ALL STOCKS --------------------


def rank_universe():
    universe = get_universe()
    if not universe:
        print("No universe available, aborting.")
        return None

    print(f"Scanning {len(universe)} stocks...")
    results = []
    for i, sym in enumerate(universe, 1):
        if i % 25 == 0:
            print(f"  [{i}/{len(universe)}] processed...")
        df = fetch_data(sym)
        if df is None:
            continue
        m = compute_momentum(df)
        if m is None:
            continue
        results.append({"Symbol": sym.replace(".NS", ""), **m})
        time.sleep(0.3)

    dfres = pd.DataFrame(results)
    if dfres.empty:
        print("No stocks passed filters.")
        return None

    dfres = dfres.sort_values("MomentumScore", ascending=False).reset_index(drop=True)
    dfres["Rank"] = dfres.index + 1
    dfres.to_csv(RANKING_FILE, index=False)
    print(f"Ranking saved: {RANKING_FILE} ({len(dfres)} stocks)")
    return dfres


# -------------------- PORTFOLIO MANAGEMENT --------------------


def load_portfolio():
    if os.path.exists(PORTFOLIO_FILE):
        return pd.read_csv(PORTFOLIO_FILE)
    return pd.DataFrame(columns=["Symbol", "EntryDate", "EntryPrice", "Quantity", "AllocatedAmount"])


def save_portfolio(df):
    df.to_csv(PORTFOLIO_FILE, index=False)


def rebalance(ranking_df):
    portfolio = load_portfolio()
    today = datetime.now().strftime("%Y-%m-%d")

    rank_lookup = dict(zip(ranking_df["Symbol"], ranking_df["Rank"], strict=False))

    if portfolio.empty:
        print("\nNo existing portfolio. Initial allocation...")
        top15 = ranking_df.head(TOP_N)
        per_stock = TOTAL_CAPITAL / TOP_N
        rows = []
        for _, r in top15.iterrows():
            qty = int(per_stock // r["CMP"])
            if qty < 1:
                continue
            rows.append(
                {
                    "Symbol": r["Symbol"],
                    "EntryDate": today,
                    "EntryPrice": r["CMP"],
                    "Quantity": qty,
                    "AllocatedAmount": round(qty * r["CMP"], 2),
                }
            )
        portfolio = pd.DataFrame(rows)
        save_portfolio(portfolio)
        print(f"Initial portfolio created: {len(portfolio)} stocks")
        return portfolio

    print("\nExisting portfolio found. Checking exit conditions...")
    exits = []
    keeps = []
    for _, row in portfolio.iterrows():
        rank = rank_lookup.get(row["Symbol"], 9999)
        if rank > EXIT_RANK_THRESHOLD:
            exits.append(row)
        else:
            keeps.append(row)

    print(f"  Exiting {len(exits)} stocks (rank > {EXIT_RANK_THRESHOLD})")
    for e in exits:
        cur_price = get_current_price(e["Symbol"] + ".NS")
        if cur_price:
            pnl_pct = round((cur_price - e["EntryPrice"]) / e["EntryPrice"] * 100, 2)
            print(f"    EXIT {e['Symbol']}: Entry {e['EntryPrice']} -> Now {cur_price} ({pnl_pct}%)")

    held_symbols = {k["Symbol"] for k in keeps}
    replacements_needed = len(exits)
    candidates = ranking_df[~ranking_df["Symbol"].isin(held_symbols)].head(replacements_needed)

    freed_capital = sum(e["AllocatedAmount"] for e in exits) if exits else 0
    per_new_stock = freed_capital / max(len(candidates), 1) if len(candidates) > 0 else 0

    new_rows = []
    for _, r in candidates.iterrows():
        qty = int(per_new_stock // r["CMP"]) if per_new_stock > 0 else 0
        if qty < 1:
            continue
        new_rows.append(
            {
                "Symbol": r["Symbol"],
                "EntryDate": today,
                "EntryPrice": r["CMP"],
                "Quantity": qty,
                "AllocatedAmount": round(qty * r["CMP"], 2),
            }
        )
        print(f"    ENTER {r['Symbol']} @ {r['CMP']} (rank {r['Rank']})")

    final_portfolio = pd.DataFrame(keeps + new_rows)
    save_portfolio(final_portfolio)
    print(f"\nPortfolio rebalanced: {len(final_portfolio)} stocks held")
    return final_portfolio


# -------------------- PORTFOLIO SUMMARY --------------------


def portfolio_summary():
    portfolio = load_portfolio()
    if portfolio.empty:
        print("No portfolio found yet. Run in 'rebalance' mode first.")
        return
    rows = []
    for _, r in portfolio.iterrows():
        cur_price = get_current_price(r["Symbol"] + ".NS")
        if cur_price is None:
            continue
        cur_value = round(cur_price * r["Quantity"], 2)
        pnl_pct = round((cur_price - r["EntryPrice"]) / r["EntryPrice"] * 100, 2)
        rows.append(
            {
                "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "Symbol": r["Symbol"],
                "EntryPrice": r["EntryPrice"],
                "CurrentPrice": cur_price,
                "Quantity": r["Quantity"],
                "Invested": r["AllocatedAmount"],
                "CurrentValue": cur_value,
                "PnL%": pnl_pct,
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return
    total_invested = df["Invested"].sum()
    total_current = df["CurrentValue"].sum()
    overall_pnl = round((total_current - total_invested) / total_invested * 100, 2)

    print("\n=== PORTFOLIO SUMMARY ===")
    print(df.to_string(index=False))
    print(f"\nTotal Invested: {total_invested:.2f} | Current Value: {total_current:.2f} | Overall P&L: {overall_pnl}%")

    log_file = "data/momentum_portfolio_log.csv"
    summary_row = pd.DataFrame(
        [
            {
                "Date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "TotalInvested": total_invested,
                "CurrentValue": total_current,
                "OverallPnL%": overall_pnl,
            }
        ]
    )
    if os.path.exists(log_file):
        summary_row.to_csv(log_file, mode="a", header=False, index=False)
    else:
        summary_row.to_csv(log_file, index=False)


# -------------------- RUN --------------------

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"

    if mode == "rebalance":
        print("=== MOMENTUM ROTATION STRATEGY (REBALANCE MODE) ===")
        ranking = rank_universe()
        if ranking is not None:
            rebalance(ranking)
            portfolio_summary()
    else:
        print("=== MOMENTUM ROTATION STRATEGY (CHECK-ONLY MODE) ===")
        portfolio_summary()
