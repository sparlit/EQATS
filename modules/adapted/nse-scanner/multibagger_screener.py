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
Multibagger Candidate Screener - Screener.in based
Aggressive growth screening - NOT a guarantee, higher risk than the
quality buy-and-hold screener. Looks for cheap, high-growth, small/mid-cap
names rather than established blue-chip quality.

IMPORTANT: This is a much higher-risk universe than fundamental_screener.py.
Small-caps here can be illiquid, volatile, and some may be story stocks
with weak governance. Always verify manually before investing real capital.
"""

import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ---------------- CONFIG ----------------
# Wider universe - mix of small/mid-cap growth names alongside existing list.
# Add/remove names as you discover candidates - this is a starting universe,
# not a definitive list.
STOCK_LIST = [
    # Existing quality-screen graduates (some may already be "discovered")
    "ALKYLAMINE",
    "TATAELXSI",
    "CAMS",
    "CUMMINSIND",
    "TRENT",
    "PERSISTENT",
    "APLAPOLLO",
    "POLYCAB",
    "KPITTECH",
    "RADICO",
    "SCHAEFFLER",
    "NAVINFLUOR",
    "JBCHEPHARM",
    "IPCALAB",
    "AFFLE",
    # Additional small/mid-cap growth names to screen
    "CUPID",
    "GRAVITA",
    "ANURAS",
    "SHAILY",
    "AZAD",
    "ROUTE",
    "LATENTVIEW",
    "ELECON",
    "TIMETECHNO",
    "RATNAMANI",
    "KIRLOSBROS",
    "TRIVENI",
    "JYOTHYLAB",
    "SYMPHONY",
    "VGUARD",
    "CERA",
    "KAJARIACER",
    "CENTURYPLY",
    "GREENPANEL",
    "RAJRATAN",
    "SHARDACROP",
    "PIIND",
    "CLEAN",
    "FINEORG",
    "GALAXYSURF",
    "VINATIORGA",
    "DEEPAKNTR",
    "AARTIIND",
    "GRINDWELL",
    "CARBORUNIV",
]

# Aggressive growth thresholds - looser on size/promoter, tighter on growth/valuation
MIN_ROE = 12.0  # lower bar than quality screener (young companies)
MIN_SALES_GROWTH_3Y = 20.0  # must show real acceleration
MIN_PROFIT_GROWTH_3Y = 20.0
MAX_DEBT_EQUITY = 0.75  # slightly more lenient than quality screener
MAX_PEG = 1.5  # core filter: growth must not be priced in yet
MIN_PROMOTER_HOLDING = 25.0  # slightly lower - some growth cos are professionally run

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}


# ---------------- SCRAPER ----------------
def fetch_screener_data(symbol):
    url = f"https://www.screener.in/company/{symbol}/consolidated/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            url = f"https://www.screener.in/company/{symbol}/"
            resp = requests.get(url, headers=HEADERS, timeout=15)
            if resp.status_code != 200:
                return None

        soup = BeautifulSoup(resp.text, "html.parser")
        data = {"symbol": symbol}

        # ---- Top ratios: ROE, ROCE, PE, Market Cap, Price ----
        ratio_items = soup.select("#top-ratios li")
        for item in ratio_items:
            name_tag = item.select_one(".name")
            value_tag = item.select_one(".value")
            if not name_tag or not value_tag:
                continue
            name = name_tag.text.strip()
            value = value_tag.text.strip().replace(",", "")
            num_match = re.search(r"[-+]?\d*\.?\d+", value)
            num_val = float(num_match.group()) if num_match else None

            if name == "ROE":
                data["roe"] = num_val
            elif name == "ROCE":
                data["roce"] = num_val
            elif name == "Stock P/E":
                data["pe"] = num_val
            elif name == "Market Cap":
                data["market_cap_cr"] = num_val
            elif name == "Current Price":
                data["current_price"] = num_val

        # ---- Promoter holding ----
        shp_section = soup.find(id="shareholding")
        if shp_section:
            rows = shp_section.select("table tr")
            for row in rows:
                cols = row.select("td, th")
                if not cols:
                    continue
                label = cols[0].get_text(strip=True)
                if "Promoter" in label:
                    last_val = cols[-1].get_text(strip=True).replace("%", "").replace(",", "")
                    num_match = re.search(r"[-+]?\d*\.?\d+", last_val)
                    if num_match:
                        data["promoter_holding"] = float(num_match.group())
                    break

        # ---- Debt/Equity ----
        bs_section = soup.find(id="balance-sheet")
        if bs_section:
            rows = bs_section.select("table tr")
            equity_cap = None
            reserves = None
            borrowings = None
            for row in rows:
                cols = row.select("td, th")
                if not cols:
                    continue
                label = cols[0].get_text(strip=True)
                last_val_text = cols[-1].get_text(strip=True).replace(",", "")
                num_match = re.search(r"[-+]?\d*\.?\d+", last_val_text)
                num_val = float(num_match.group()) if num_match else None
                if label == "Equity Capital":
                    equity_cap = num_val
                elif label == "Reserves":
                    reserves = num_val
                elif "Borrowing" in label:
                    borrowings = num_val
            if equity_cap is not None and reserves is not None and borrowings is not None:
                total_equity = equity_cap + reserves
                if total_equity > 0:
                    data["debt_equity"] = round(borrowings / total_equity, 2)

        # ---- Growth numbers ----
        page_text = soup.get_text()
        sales_match = re.search(r"Compounded Sales Growth[\s\S]{0,80}?3 Years:\s*(-?\d+)%", page_text)
        profit_match = re.search(r"Compounded Profit Growth[\s\S]{0,80}?3 Years:\s*(-?\d+)%", page_text)
        if sales_match:
            data["sales_growth_3y"] = float(sales_match.group(1))
        if profit_match:
            data["profit_growth_3y"] = float(profit_match.group(1))

        # ---- PEG ratio ----
        if data.get("pe") and data.get("profit_growth_3y") and data["profit_growth_3y"] > 0:
            data["peg"] = round(data["pe"] / data["profit_growth_3y"], 2)
        else:
            data["peg"] = None

        return data

    except Exception as e:
        print(f"  fetch failed {symbol}: {e}")
        return None


# ---------------- YAHOO 1Y MOMENTUM (has this already run up?) ----------------
def fetch_1y_return(symbol):
    """Check how much the stock has already moved in the last year -
    helps distinguish 'undiscovered' growth from 'already-discovered' momentum plays"""
    yahoo_sym = f"{symbol}.NS"
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_sym}"
    params = {"range": "1y", "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        result = data["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        if len(closes) < 2:
            return None
        return round((closes[-1] - closes[0]) / closes[0] * 100, 1)
    except Exception:
        return None


# ---------------- QUALITY FILTER ----------------
def passes_growth_filter(row):
    checks = {
        "ROE": row.get("roe") is not None and row["roe"] >= MIN_ROE,
        "Sales Growth": row.get("sales_growth_3y") is not None and row["sales_growth_3y"] >= MIN_SALES_GROWTH_3Y,
        "Profit Growth": row.get("profit_growth_3y") is not None and row["profit_growth_3y"] >= MIN_PROFIT_GROWTH_3Y,
        "Debt/Eq": row.get("debt_equity") is not None and row["debt_equity"] <= MAX_DEBT_EQUITY,
        "PEG": row.get("peg") is not None and 0 < row["peg"] <= MAX_PEG,
        "Promoter": row.get("promoter_holding") is not None and row["promoter_holding"] >= MIN_PROMOTER_HOLDING,
    }
    passed_count = sum(checks.values())
    return passed_count, checks


# ---------------- MAIN ----------------
def run_screener():
    print(f"Screening {len(STOCK_LIST)} stocks for multibagger candidates...")
    print("WARNING: Higher risk universe - verify manually before investing.\n")
    results = []

    for sym in STOCK_LIST:
        print(f"Fetching {sym}...")
        data = fetch_screener_data(sym)
        if data:
            passed_count, _checks = passes_growth_filter(data)
            data["checks_passed"] = passed_count
            data["growth_pass"] = passed_count >= 5  # at least 5 of 6 criteria
            time.sleep(0.5)
            data["return_1y_pct"] = fetch_1y_return(sym)
            results.append(data)
        time.sleep(1.5)

    df = pd.DataFrame(results)
    if df.empty:
        print("No data fetched. Check network/site structure.")
        return

    cols = [
        "symbol",
        "roe",
        "roce",
        "debt_equity",
        "promoter_holding",
        "sales_growth_3y",
        "profit_growth_3y",
        "pe",
        "peg",
        "market_cap_cr",
        "return_1y_pct",
        "checks_passed",
        "growth_pass",
    ]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]

    df.to_csv("multibagger_screen_all.csv", index=False)
    print("\nSaved: multibagger_screen_all.csv (all stocks, all data)")

    candidates_df = df[df["growth_pass"]].sort_values("peg", ascending=True)
    candidates_df.to_csv("multibagger_candidates.csv", index=False)

    print("\n" + "=" * 70)
    print("MULTIBAGGER CANDIDATES (sorted by PEG - cheapest growth first)")
    print("=" * 70)
    if candidates_df.empty:
        print("No stocks passed the growth filter with current thresholds.")
        print("Consider loosening MIN_SALES_GROWTH_3Y or MAX_PEG.")
    else:
        for _, row in candidates_df.iterrows():
            ret_str = f"{row.get('return_1y_pct', '-'):>+7}%" if pd.notna(row.get("return_1y_pct")) else "     -  "
            print(
                f"{row['symbol']:15s} ROE:{row.get('roe', '-'):>6} "
                f"SalesG:{row.get('sales_growth_3y', '-'):>5} ProfitG:{row.get('profit_growth_3y', '-'):>5} "
                f"PEG:{row.get('peg', '-'):>5} 1Y Return:{ret_str}"
            )
        print(f"\nTotal candidates: {len(candidates_df)} / {len(df)}")
        print("\nSaved: multibagger_candidates.csv")
        print("\nNote on '1Y Return' column:")
        print("  - Low/negative return = still under-the-radar, higher discovery potential")
        print("  - Very high return = market may have already priced in the growth story")
        symbol_list = [f'"{s}.NS"' for s in candidates_df["symbol"].tolist()]
        print("\nSymbol list for further scanning:")
        print("[" + ", ".join(symbol_list) + "]")

    print("\n" + "=" * 70)
    print("REMINDER: This is a higher-risk, speculative growth screen.")
    print("Verify governance, promoter background, and business model manually")
    print("before committing capital. Size positions smaller than your quality")
    print("buy-and-hold portfolio given the added volatility and risk.")
    print("=" * 70)


if __name__ == "__main__":
    run_screener()
