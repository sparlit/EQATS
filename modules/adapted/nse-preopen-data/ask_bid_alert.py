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


import time
import winsound  # Windows only. On Linux/Mac swap this for a print-only alert.

import pandas as pd
import requests

# ---------------- CONFIG ----------------
SYMBOL = "NIFTY"
EXPIRY = "11-Aug-2026"  # must match an expiry NSE actually has
THRESHOLD = 0.10  # (kept, unused by the new alert logic below)
N_STRIKES = 7  # how many nearest OTM strikes to take, per side
SAME_DIFF_COUNT = 5  # alert if this many of the N_STRIKES share the same diff
POLL_SECONDS = 59  # how often to refresh
DEBUG_STRIKE = None  # set to a strike (e.g. 24650) to dump its raw fields each poll
URL = f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={SYMBOL}&expiry={EXPIRY}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/option-chain",
    "X-Requested-With": "XMLHttpRequest",
}


def make_session() -> requests.Session:
    """Create a session with valid NSE cookies (required or API returns 401/garbage)."""
    s = requests.Session()
    s.headers.update(HEADERS)
    # Hit homepage first to get cookies set
    s.get("https://www.nseindia.com", timeout=10)
    s.get("https://www.nseindia.com/option-chain", timeout=10)
    return s


def fetch_option_chain(session: requests.Session) -> dict | None:
    try:
        resp = session.get(URL, timeout=10)
        if resp.status_code != 200:
            print(f"[WARN] HTTP {resp.status_code}, retrying...")
            return None
        data = resp.json()
        if "records" not in data or "data" not in data["records"]:
            print("[WARN] Unexpected payload shape, retrying...")
            return None
        return data
    except (requests.RequestException, ValueError) as e:
        print(f"[WARN] Fetch failed ({e}), retrying...")
        return None


def get_num(d: dict, *keys):
    """Try several possible key spellings (NSE is inconsistent about casing)
    and return the first numeric value found, else 0."""
    for k in keys:
        if k in d and d[k] not in (None, ""):
            try:
                return float(d[k])
            except (TypeError, ValueError):
                pass
    return 0.0


def leg_record(leg: dict, debug_strike=None, side="", strike=None) -> dict:
    """Extract bid/ask/diff/qty fields from a single CE or PE leg dict."""
    if debug_strike is not None and strike == debug_strike:
        print(f"[DEBUG] {side} {strike} raw -> {leg}")
    bid = get_num(leg, "buyPrice1", "bidprice", "bidPrice", "bid")
    ask = get_num(leg, "sellPrice1", "askPrice", "askprice", "ask")
    buy_qty = int(get_num(leg, "totalBuyQuantity"))
    sell_qty = int(get_num(leg, "totalSellQuantity"))
    qty_diff = buy_qty - sell_qty

    if qty_diff > 0:
        strength = "Buyer"
    elif qty_diff < 0:
        strength = "Seller"
    else:
        strength = "Neutral"

    return {
        "Bid": bid,
        "Ask": ask,
        "Diff": round(ask - bid, 2),
        "TotBuyQty": buy_qty,
        "TotSellQty": sell_qty,
        "QtyDiff": qty_diff,
        "Strength": strength,
    }


def nearest_otm_legs(rows, side: str, spot: float, n: int, debug_strike=None):
    """Return the n OTM strikes closest to spot for the given side ('CE' or 'PE'),
    sorted by distance to spot (closest first)."""
    candidates = []
    for row in rows:
        strike = row.get("strikePrice")
        leg = row.get(side)
        if not leg or strike is None:
            continue
        is_otm = (strike > spot) if side == "CE" else (strike < spot)
        if not is_otm:
            continue
        rec = leg_record(leg, debug_strike, side, strike)
        if rec["Bid"] == 0 and rec["Ask"] == 0:
            continue  # no live quote
        rec["Strike"] = strike
        rec["dist"] = abs(strike - spot)
        candidates.append(rec)

    candidates.sort(key=lambda r: r["dist"])
    return candidates[:n]


def find_same_diff_alert(legs, min_count):
    """Check if `min_count` or more legs share the exact same Diff value.
    Returns (diff_value, count) or None."""
    from collections import Counter

    diffs = [leg["Diff"] for leg in legs if leg["Diff"] > 0]
    if not diffs:
        return None
    value, count = Counter(diffs).most_common(1)[0]
    if count >= min_count:
        return value, count
    return None


def build_near_the_money_dataframe(data: dict, debug_strike=None):
    spot = data["records"].get("underlyingValue", 0)
    rows = data["records"]["data"]

    ce_legs = nearest_otm_legs(rows, "CE", spot, N_STRIKES, debug_strike)
    pe_legs = nearest_otm_legs(rows, "PE", spot, N_STRIKES, debug_strike)

    ce_alert = find_same_diff_alert(ce_legs, SAME_DIFF_COUNT)
    pe_alert = find_same_diff_alert(pe_legs, SAME_DIFF_COUNT)

    n_rows = max(len(ce_legs), len(pe_legs))
    records = []
    for i in range(n_rows):
        rec = {}
        if i < len(ce_legs):
            c = ce_legs[i]
            rec.update(
                {
                    "CE_Strike": c["Strike"],
                    "CE_Bid": c["Bid"],
                    "CE_Ask": c["Ask"],
                    "CE_Diff": c["Diff"],
                    "CE_TotBuyQty": c["TotBuyQty"],
                    "CE_TotSellQty": c["TotSellQty"],
                    "CE_QtyDiff": c["QtyDiff"],
                    "CE_Strength": c["Strength"],
                }
            )
        if i < len(pe_legs):
            p = pe_legs[i]
            rec.update(
                {
                    "PE_Strike": p["Strike"],
                    "PE_Bid": p["Bid"],
                    "PE_Ask": p["Ask"],
                    "PE_Diff": p["Diff"],
                    "PE_TotBuyQty": p["TotBuyQty"],
                    "PE_TotSellQty": p["TotSellQty"],
                    "PE_QtyDiff": p["QtyDiff"],
                    "PE_Strength": p["Strength"],
                }
            )
        records.append(rec)

    df = pd.DataFrame(records)
    ##    cols = ["CE_TotBuyQty", "CE_TotSellQty", "CE_QtyDiff", "CE_Strength",
    ##            "CE_Bid", "CE_Ask", "CE_Diff", "CE_Strike",
    ##            "PE_Strike", "PE_Bid", "PE_Ask", "PE_Diff",
    ##            "PE_QtyDiff", "PE_Strength", "PE_TotBuyQty", "PE_TotSellQty"]
    cols = [
        "CE_QtyDiff",
        "CE_Strength",
        "CE_Bid",
        "CE_Ask",
        "CE_Diff",
        "CE_Strike",
        "PE_Strike",
        "PE_Bid",
        "PE_Ask",
        "PE_Diff",
        "PE_QtyDiff",
        "PE_Strength",
    ]
    for c in cols:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[cols]
    return df, ce_alert, pe_alert


def beep():
    try:
        winsound.Beep(1000, 300)  # 1000 Hz, 300 ms
    except Exception:
        pass  # non-Windows fallback: just skip the sound


def main():
    pd.set_option("display.width", 160)
    pd.set_option("display.max_rows", None)
    session = make_session()
    print(
        f"Monitoring {SYMBOL} nearest {N_STRIKES} OTM CE (left) / PE (right) strikes "
        f"(expiry {EXPIRY}) | alert if >= {SAME_DIFF_COUNT} of {N_STRIKES} share the same diff\n"
    )

    while True:
        data = fetch_option_chain(session)
        if data is None:
            # Cookies may have expired / been rejected - refresh session and retry
            session = make_session()
            time.sleep(POLL_SECONDS)
            continue

        df, ce_alert, pe_alert = build_near_the_money_dataframe(data, debug_strike=DEBUG_STRIKE)
        ts = time.strftime("%H:%M:%S")
        spot = data["records"].get("underlyingValue", "?")

        print(f"\n[{ts}] Spot={spot}")
        if df.empty:
            print("No near-the-money strikes with live quotes right now.")
        else:
            print(df.to_string(index=False))

        fired = False
        if ce_alert:
            value, count = ce_alert
            print(f"ALERT: CE side - {count}/{N_STRIKES} strikes have the same diff = {value}")
            fired = True
        if pe_alert:
            value, count = pe_alert
            print(f"ALERT: PE side - {count}/{N_STRIKES} strikes have the same diff = {value}")
            fired = True
        if fired:
            beep()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
