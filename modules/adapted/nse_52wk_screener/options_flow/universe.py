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
Scoped options universe for the live flow scanner.

Indices + ~40 liquid F&O stocks, nearest expiry, ATM ± N strikes → the option
tokens to poll, plus the nearest FUTURE token per underlying (its LTP is the
forward F used for Black-76 IV/Greeks).

Rebuilt once per trading day (expiries roll, ATM drifts). ATM is centered on a
rough spot from yfinance prev-close (good enough to center ±N strikes); the live
forward for IV comes from the future at poll time.
"""
import json
import os
import time
from datetime import datetime

import requests

SCRIP_MASTER = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
CACHE = "/tmp/angel_scrip_master.json"

INDICES = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "FINNIFTY": None, "MIDCPNIFTY": None}
LIQUID_STOCKS = [
    "RELIANCE",
    "HDFCBANK",
    "ICICIBANK",
    "INFY",
    "TCS",
    "SBIN",
    "AXISBANK",
    "KOTAKBANK",
    "BAJFINANCE",
    "BHARTIARTL",
    "ITC",
    "LT",
    "HINDUNILVR",
    "MARUTI",
    "TATAPOWER",
    "TATASTEEL",
    "SUNPHARMA",
    "WIPRO",
    "HCLTECH",
    "ADANIENT",
    "ADANIPORTS",
    "TITAN",
    "ULTRACEMCO",
    "ASIANPAINT",
    "BAJAJFINSV",
    "POWERGRID",
    "NTPC",
    "ONGC",
    "COALINDIA",
    "JSWSTEEL",
    "HINDALCO",
    "GRASIM",
    "TECHM",
    "INDUSINDBK",
    "DRREDDY",
    "CIPLA",
    "EICHERMOT",
    "BAJAJ-AUTO",
    "HEROMOTOCO",
    "DLF",
]


def _load_master():
    if os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < 6 * 3600:
        with open(CACHE) as f:
            return json.load(f)
    d = requests.get(SCRIP_MASTER, timeout=120).json()
    with open(CACHE, "w") as f:
        json.dump(d, f)
    return d


def _spots(names_yf):
    import yfinance as yf

    tickers = {n: t for n, t in names_yf.items() if t}
    out = {}
    if not tickers:
        return out
    data = yf.download(
        list(tickers.values()), period="5d", auto_adjust=False, progress=False, threads=True
    )
    close = data.get("Close", data)
    for name, tk in tickers.items():
        try:
            s = close[tk].dropna()
            if len(s):
                out[name] = float(s.iloc[-1])
        except Exception:
            pass
    return out


def build(strikes_each_side=15, cache_path=None):
    """Return {options:[...], futures:{underlying:{token,expiry}}, tokens:[...],
    meta:{...}}. Also writes to cache_path if given."""
    master = _load_master()
    today = datetime.now().date().isoformat()
    underlyings = list(INDICES) + LIQUID_STOCKS
    uset = set(underlyings)

    opts, futs = {}, {}
    for r in master:
        if r.get("exch_seg") != "NFO":
            continue
        name = r.get("name")
        if name not in uset:
            continue
        it = r.get("instrumenttype")
        sym = str(r.get("symbol", ""))
        try:
            exp = datetime.strptime(r.get("expiry"), "%d%b%Y").date().isoformat()
        except (TypeError, ValueError):
            continue
        if exp < today:
            continue
        if it in ("OPTIDX", "OPTSTK"):
            cp = "CE" if sym.endswith("CE") else ("PE" if sym.endswith("PE") else None)
            if cp is None:
                continue
            try:
                strike = float(r.get("strike", 0)) / 100.0
            except (TypeError, ValueError):
                continue
            opts.setdefault(name, []).append(
                {
                    "token": str(r.get("token")),
                    "symbol": sym,
                    "underlying": name,
                    "type": cp,
                    "strike": strike,
                    "expiry": exp,
                    "lotsize": int(float(r.get("lotsize", 0) or 0)),
                }
            )
        elif it in ("FUTIDX", "FUTSTK"):
            futs.setdefault(name, []).append({"token": str(r.get("token")), "expiry": exp})

    yf_map = dict(INDICES)
    for s in LIQUID_STOCKS:
        yf_map[s] = f"{s}.NS"
    spots = _spots(yf_map)

    options, futures, missing = [], {}, []
    for name in underlyings:
        legs = opts.get(name)
        if not legs:
            missing.append(name)
            continue
        near_exp = min(l["expiry"] for l in legs)
        leg = [l for l in legs if l["expiry"] == near_exp]
        strikes = sorted({l["strike"] for l in leg})
        spot = spots.get(name)
        atm = min(strikes, key=lambda k: abs(k - spot)) if spot else strikes[len(strikes) // 2]
        i = strikes.index(atm)
        keep = set(strikes[max(0, i - strikes_each_side) : i + strikes_each_side + 1])
        for l in leg:
            if l["strike"] in keep:
                l["dte"] = (datetime.fromisoformat(l["expiry"]).date() - datetime.now().date()).days
                options.append(l)
        # nearest future for this underlying (forward source)
        fl = futs.get(name)
        if fl:
            nf = min(fl, key=lambda x: x["expiry"])
            futures[name] = {"token": nf["token"], "expiry": nf["expiry"]}

    fut_tokens = [f["token"] for f in futures.values()]
    tokens = [o["token"] for o in options] + fut_tokens
    result = {
        "options": options,
        "futures": futures,
        "tokens": tokens,
        "meta": {
            "built": datetime.now().isoformat(),
            "n_options": len(options),
            "n_futures": len(futures),
            "spot_priced": len(spots),
            "missing": missing,
        },
    }
    if cache_path:
        with open(cache_path, "w") as f:
            json.dump(result, f)
    return result


if __name__ == "__main__":
    u = build()
    m = u["meta"]
    print(
        f"options={m['n_options']} futures={m['n_futures']} "
        f"tokens={len(u['tokens'])} spot_priced={m['spot_priced']}"
    )
    if m["missing"]:
        print("missing:", m["missing"])
