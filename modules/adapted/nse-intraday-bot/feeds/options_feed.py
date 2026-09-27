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
NSE Options Chain scraper — swing trading Layer 5.
Fetches PCR and call/put OI changes for F&O stocks.
"""
import time

import requests

_EMPTY = {
    "pass": False,
    "pcr": None,
    "call_oi_chg": 0.0,
    "put_oi_chg": 0.0,
    "atm_strike": None,
    "total_ce_oi": 0,
    "total_pe_oi": 0,
}


def make_nse_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.nseindia.com/",
            "Connection": "keep-alive",
        }
    )
    try:
        s.get("https://www.nseindia.com/", timeout=10)
        time.sleep(0.5)
    except Exception:
        pass
    return s


def check_options_oi(
    symbol: str,
    current_price: float,
    pcr_min: float = 0.8,
    pcr_max: float = 1.3,
    call_oi_min: float = 0.30,
    session: requests.Session = None,
) -> dict:
    """
    Fetch NSE option chain and check Layer 5 OI confluence.
    Pass conditions (LONG swing):
      • PCR in [pcr_min, pcr_max] — neutral to slightly bullish
      • Call OI change% >= call_oi_min — smart money building calls
    """
    if session is None:
        session = make_nse_session()

    try:
        url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol.upper()}"
        r = session.get(url, timeout=15)
        if r.status_code != 200:
            print(f"[OPTIONS] {symbol} HTTP {r.status_code}")
            return _EMPTY

        data = r.json()
        records = data.get("records", {})
        chain = records.get("data", [])
        spot = float(records.get("underlyingValue", current_price) or current_price)

        if not chain:
            return _EMPTY

        strikes = [row["strikePrice"] for row in chain if "strikePrice" in row]
        if not strikes:
            return _EMPTY

        atm = min(strikes, key=lambda x: abs(x - spot))

        total_ce = total_pe = ce_chg = pe_chg = 0

        for row in chain:
            sp = row.get("strikePrice", 0)
            if abs(sp - spot) / max(spot, 1) > 0.10:  # within ±10% of spot
                continue
            ce = row.get("CE") or {}
            pe = row.get("PE") or {}
            total_ce += ce.get("openInterest", 0) or 0
            total_pe += pe.get("openInterest", 0) or 0
            ce_chg += ce.get("changeinOpenInterest", 0) or 0
            pe_chg += pe.get("changeinOpenInterest", 0) or 0

        if total_ce == 0:
            return _EMPTY

        pcr = round(total_pe / total_ce, 3)

        base_ce = max(total_ce - ce_chg, 1)
        base_pe = max(total_pe - pe_chg, 1)
        call_chg_pct = round(ce_chg / base_ce, 3)
        put_chg_pct = round(pe_chg / base_pe, 3)

        pcr_ok = pcr_min <= pcr <= pcr_max
        call_ok = call_chg_pct >= call_oi_min

        return {
            "pass": pcr_ok and call_ok,
            "pcr": pcr,
            "call_oi_chg": call_chg_pct,
            "put_oi_chg": put_chg_pct,
            "atm_strike": atm,
            "total_ce_oi": total_ce,
            "total_pe_oi": total_pe,
            "spot": spot,
        }

    except Exception as e:
        print(f"[OPTIONS] {symbol}: {e}")
        return _EMPTY
