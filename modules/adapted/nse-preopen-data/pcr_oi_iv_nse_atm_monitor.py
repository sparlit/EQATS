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


import contextlib
import os
import time
import winsound  # Windows only. On Linux/Mac swap this for a print-only alert.

import requests
import xlwings as xw

# ---------------- CONFIG ----------------
SYMBOL = "NIFTY"
EXPIRY = "11-Aug-2026"  # must match an expiry NSE actually has
POLL_SECONDS = 1  # how often to refresh the on-screen table
STORE_MINUTES = 1  # how often to write a row to the xlsm file
XLSM_PATH = "option_chain_atm_log.xlsm"
DEBUG = False  # set True to print raw CE/PE dicts for the ATM strike
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

HEADER_ROW = [
    "Time",
    "CE_OI",
    "CE_IV",
    "CE_Bid",
    "CE_Ask",
    "CE_Diff",
    "CE_TotBuyQty",
    "CE_TotSellQty",
    "CE_QtyDiff",
    "CE_Strength",
    "CE_Signal",
    "Strike",
    "Spot",
    "PCR",
    "PE_Signal",
    "PE_Strength",
    "PE_QtyDiff",
    "PE_TotBuyQty",
    "PE_TotSellQty",
    "PE_Diff",
    "PE_Ask",
    "PE_Bid",
    "PE_IV",
    "PE_OI",
]


def make_session() -> requests.Session:
    """Create a session with valid NSE cookies (required or API returns 401/garbage)."""
    s = requests.Session()
    s.headers.update(HEADERS)
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


def leg_record(leg: dict) -> dict:
    """Extract bid/ask/OI/IV/qty fields from a single CE or PE leg dict."""
    bid = get_num(leg, "buyPrice1", "bidprice", "bidPrice", "bid")
    ask = get_num(leg, "sellPrice1", "askPrice", "askprice", "ask")
    oi = get_num(leg, "openInterest")
    iv = get_num(leg, "impliedVolatility")
    mid = round((bid + ask) / 2, 2) if (bid or ask) else 0.0
    buy_qty = int(get_num(leg, "totalBuyQuantity"))
    sell_qty = int(get_num(leg, "totalSellQuantity"))
    qty_diff = buy_qty - sell_qty
    strength = "Buyer" if qty_diff > 0 else "Seller" if qty_diff < 0 else "Neutral"

    return {
        "Bid": bid,
        "Ask": ask,
        "Diff": round(ask - bid, 2),
        "OI": oi,
        "IV": iv,
        "Mid": mid,
        "TotBuyQty": buy_qty,
        "TotSellQty": sell_qty,
        "QtyDiff": qty_diff,
        "Strength": strength,
    }


def get_atm_row(rows: list, spot: float) -> dict | None:
    """Return the option-chain row (containing both CE and PE) that is the
    TRUE ATM strike, found via put-call parity: the strike where the CALL
    and PUT mid-prices are closest to each other.

    This is NOT simply "strike nearest to spot" - option premiums reflect
    the forward price (spot adjusted for time-to-expiry, interest, etc.),
    so the strike with the smallest CE/PE price gap is the market's actual
    ATM strike, and can differ from the numerically-nearest strike.
    """
    candidates = []
    for r in rows:
        strike = r.get("strikePrice")
        ce, pe = r.get("CE"), r.get("PE")
        if strike is None or not ce or not pe:
            continue
        ce_bid = get_num(ce, "buyPrice1", "bidprice", "bidPrice", "bid")
        ce_ask = get_num(ce, "sellPrice1", "askPrice", "askprice", "ask")
        pe_bid = get_num(pe, "buyPrice1", "bidprice", "bidPrice", "bid")
        pe_ask = get_num(pe, "sellPrice1", "askPrice", "askprice", "ask")
        if not (ce_bid or ce_ask) or not (pe_bid or pe_ask):
            continue  # skip strikes with no live quotes on either leg
        ce_mid = (ce_bid + ce_ask) / 2
        pe_mid = (pe_bid + pe_ask) / 2
        candidates.append((abs(ce_mid - pe_mid), r))

    if not candidates:
        return None
    # tie-break with distance to spot, in case of an exact parity tie
    candidates.sort(key=lambda t: (t[0], abs(t[1]["strikePrice"] - spot)))
    return candidates[0][1]


def compute_pcr(rows: list) -> float | None:
    """Put-Call Ratio = Total Put OI / Total Call OI, summed across
    EVERY strike in the chain (not just the ATM strike)."""
    total_ce_oi = 0.0
    total_pe_oi = 0.0
    for r in rows:
        ce, pe = r.get("CE"), r.get("PE")
        if ce:
            total_ce_oi += get_num(ce, "openInterest")
        if pe:
            total_pe_oi += get_num(pe, "openInterest")
    if total_ce_oi == 0:
        return None
    return round(total_pe_oi / total_ce_oi, 3)


def classify_buildup(oi_change: float, mid_change: float) -> str:
    if oi_change > 0 and mid_change > 0:
        return "Long Buildup"
    if oi_change > 0 and mid_change < 0:
        return "Short Buildup"
    if oi_change < 0 and mid_change > 0:
        return "Short Covering"
    if oi_change < 0 and mid_change < 0:
        return "Long Unwinding"
    return "No Change"


def ensure_workbook():
    """Open the workbook in a live Excel instance (creating it if needed),
    make sure the ATM_Log sheet + header row exist, and return
    (workbook, sheet, next_row_to_write)."""
    if os.path.exists(XLSM_PATH):
        wb = xw.Book(XLSM_PATH)
    else:
        wb = xw.Book()
        wb.save(os.path.abspath(XLSM_PATH))

    sheet_names = [s.name for s in wb.sheets]
    sht = wb.sheets.add("ATM_Log") if "ATM_Log" not in sheet_names else wb.sheets["ATM_Log"]

    if sht.range("A1").value is None:
        sht.range("A1").value = HEADER_ROW
        next_row = 2
    else:
        # find the first empty row below the header by scanning down column A
        r = 1
        while sht.range((r + 1, 1)).value is not None:
            r += 1
        next_row = r + 1

    wb.save()
    return wb, sht, next_row


def get_last_row(sht, next_row: int) -> dict | None:
    if next_row <= 2:
        return None
    last_row_idx = next_row - 1
    values = sht.range((last_row_idx, 1), (last_row_idx, len(HEADER_ROW))).value
    return dict(zip(HEADER_ROW, values, strict=False))


def store_row(sht, row_idx: int, row: list):
    sht.range((row_idx, 1), (row_idx, len(HEADER_ROW))).value = row
    sht.book.save()


def beep():
    with contextlib.suppress(Exception):
        winsound.Beep(1000, 300)


def main():
    session = make_session()
    _wb, sht, next_row = ensure_workbook()
    last_store_time = 0.0
    print(f"Monitoring {SYMBOL} ATM strike (expiry {EXPIRY}) | storing to {XLSM_PATH} every {STORE_MINUTES} min\n")

    while True:
        data = fetch_option_chain(session)
        if data is None:
            session = make_session()
            time.sleep(POLL_SECONDS)
            continue

        spot = data["records"].get("underlyingValue", 0)
        row = get_atm_row(data["records"]["data"], spot)
        ts = time.strftime("%H:%M:%S")

        if row is None or "CE" not in row or "PE" not in row:
            print(f"[{ts}] No ATM strike with both CE and PE found, retrying...")
            time.sleep(POLL_SECONDS)
            continue

        ce = leg_record(row["CE"])
        pe = leg_record(row["PE"])
        strike = row["strikePrice"]
        pcr = compute_pcr(data["records"]["data"])

        if DEBUG:
            print(f"[DEBUG] CE {strike} raw -> {row['CE']}")
            print(f"[DEBUG] PE {strike} raw -> {row['PE']}")

        print(f"\n[{ts}] Spot={spot}  ATM Strike={strike}  PCR={pcr}")
        print(
            f"  CE  Bid={ce['Bid']:.2f} Ask={ce['Ask']:.2f} Diff={ce['Diff']:.2f} "
            f"OI={ce['OI']:.0f} IV={ce['IV']:.2f} Strength={ce['Strength']}"
        )
        print(
            f"  PE  Bid={pe['Bid']:.2f} Ask={pe['Ask']:.2f} Diff={pe['Diff']:.2f} "
            f"OI={pe['OI']:.0f} IV={pe['IV']:.2f} Strength={pe['Strength']}"
        )

        now = time.time()
        if now - last_store_time >= STORE_MINUTES * 60:
            last = get_last_row(sht, next_row)
            if last is not None and last.get("Strike") == strike:
                last_ce_mid = (float(last["CE_Bid"]) + float(last["CE_Ask"])) / 2
                last_pe_mid = (float(last["PE_Bid"]) + float(last["PE_Ask"])) / 2
                ce_signal = classify_buildup(ce["OI"] - float(last["CE_OI"]), ce["Mid"] - last_ce_mid)
                pe_signal = classify_buildup(pe["OI"] - float(last["PE_OI"]), pe["Mid"] - last_pe_mid)
            else:
                ce_signal = "No Baseline"
                pe_signal = "No Baseline"

            new_row = [
                ts,
                ce["OI"],
                ce["IV"],
                ce["Bid"],
                ce["Ask"],
                ce["Diff"],
                ce["TotBuyQty"],
                ce["TotSellQty"],
                ce["QtyDiff"],
                ce["Strength"],
                ce_signal,
                strike,
                spot,
                pcr,
                pe_signal,
                pe["Strength"],
                pe["QtyDiff"],
                pe["TotBuyQty"],
                pe["TotSellQty"],
                pe["Diff"],
                pe["Ask"],
                pe["Bid"],
                pe["IV"],
                pe["OI"],
            ]
            store_row(sht, next_row, new_row)
            next_row += 1
            last_store_time = now
            print(f"  [STORED to {XLSM_PATH}]  CE_Signal={ce_signal}  PE_Signal={pe_signal}")
            beep()

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
