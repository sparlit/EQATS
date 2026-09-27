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
Fundamental Quality Screener - Screener.in based
Filters stocks by ROE, ROCE, Debt/Equity, Promoter Holding, Growth
"""

import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

# ---------------- CONFIG ----------------
STOCK_LIST = [
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "SBIN",
    "BHARTIARTL",
    "LT",
    "KOTAKBANK",
    "AXISBANK",
    "PERSISTENT",
    "COFORGE",
    "POLYCAB",
    "CUMMINSIND",
    "SUPREMEIND",
    "PAGEIND",
    "MFSL",
    "ASTRAL",
    "APLAPOLLO",
    "BALKRISIND",
    "TATAELXSI",
    "DEEPAKNTR",
    "PIIND",
    "SCHAEFFLER",
    "KPITTECH",
    "TRENT",
    "CROMPTON",
    "GODREJPROP",
    "OBEROIRLTY",
    "IPCALAB",
    "RADICO",
    "ROUTE",
    "CLEAN",
    "ANGELONE",
    "CDSL",
    "IEX",
    "CAMS",
    "RAILTEL",
    "TIINDIA",
    "SONACOMS",
    "AFFLE",
    "LATENTVIEW",
    "NAVINFLUOR",
    "FINEORG",
    "GRINDWELL",
    "JBCHEPHARM",
    "AARTIIND",
    "GALAXYSURF",
    "VINATIORGA",
    "ALKYLAMINE",
    "CUPID",
]

MIN_ROE = 15.0
MIN_ROCE = 15.0
MAX_DEBT_EQUITY = 0.5
MIN_PROMOTER_HOLDING = 30.0
MIN_SALES_GROWTH_3Y = 12.0
MIN_PROFIT_GROWTH_3Y = 12.0
MAX_PEG = 2.0

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

        # ---- Top ratios: ROE, ROCE, PE ----
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

        # ---- Promoter holding: last column of shareholding table ----
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

        # ---- Debt/Equity: calculate from Balance Sheet ----
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


# ---------------- QUALITY FILTER ----------------
def passes_quality_filter(row):
    checks = {
        "ROE": row.get("roe") is not None and row["roe"] >= MIN_ROE,
        "ROCE": row.get("roce") is not None and row["roce"] >= MIN_ROCE,
        "Debt/Eq": row.get("debt_equity") is not None and row["debt_equity"] <= MAX_DEBT_EQUITY,
        "Promoter": row.get("promoter_holding") is not None and row["promoter_holding"] >= MIN_PROMOTER_HOLDING,
        "Sales Growth": row.get("sales_growth_3y") is not None and row["sales_growth_3y"] >= MIN_SALES_GROWTH_3Y,
        "Profit Growth": row.get("profit_growth_3y") is not None and row["profit_growth_3y"] >= MIN_PROFIT_GROWTH_3Y,
    }
    passed_count = sum(checks.values())
    return passed_count, checks


# ---------------- MAIN ----------------
def run_screener():
    print(f"Screening {len(STOCK_LIST)} stocks for fundamental quality...\n")
    results = []

    for sym in STOCK_LIST:
        print(f"Fetching {sym}...")
        data = fetch_screener_data(sym)
        if data:
            passed_count, _checks = passes_quality_filter(data)
            data["checks_passed"] = passed_count
            data["quality_pass"] = passed_count >= 5
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
        "checks_passed",
        "quality_pass",
    ]
    cols = [c for c in cols if c in df.columns]
    df = df[cols]

    df.to_csv("fundamental_screen_all.csv", index=False)
    print("\nSaved: fundamental_screen_all.csv (all stocks, all data)")

    quality_df = df[df["quality_pass"]].sort_values("roe", ascending=False)
    quality_df.to_csv("fundamental_screen_quality_pass.csv", index=False)

    print("\n" + "=" * 60)
    print("QUALITY-FILTERED STOCK LIST")
    print("=" * 60)
    if quality_df.empty:
        print("No stocks passed the quality filter with current thresholds.")
        print("Consider loosening MIN_ROE, MIN_ROCE, or MAX_DEBT_EQUITY.")
    else:
        for _, row in quality_df.iterrows():
            print(
                f"{row['symbol']:15s} ROE:{row.get('roe', '-'):>6} "
                f"ROCE:{row.get('roce', '-'):>6} D/E:{row.get('debt_equity', '-'):>5} "
                f"Promoter:{row.get('promoter_holding', '-'):>5}%"
            )
        print(f"\nTotal passed: {len(quality_df)} / {len(df)}")
        print("\nSaved: fundamental_screen_quality_pass.csv")
        symbol_list = [f'"{s}.NS"' for s in quality_df["symbol"].tolist()]
        print("\nCopy this into your Turtle/Momentum STOCK_LIST:")
        print("[" + ", ".join(symbol_list) + "]")


if __name__ == "__main__":
    run_screener()
