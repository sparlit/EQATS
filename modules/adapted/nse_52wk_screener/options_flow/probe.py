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
PHASE-0 FEASIBILITY PROBE for the live options-flow scanner (throwaway).

Goal: prove Angel One can feed the scoped options universe (indices + ~40 liquid
stocks, near-ATM, near-expiry) at a ~60s cadence, and that we can compute
IV/Greeks ourselves — BEFORE building the real collector.

Two modes:

  build  (offline, no Angel creds; needs internet for yfinance + scrip master)
      Constructs the scoped contract universe and writes it to
      options_flow/probe_universe.json, printing the contract count per
      underlying and the grand total (the key feasibility number).

  rest   (market hours; needs ANGEL_* env)
      Loads that universe, logs into Angel, pulls getMarketData FULL in 50-token
      batches over ALL scoped tokens, and reports: wall-clock to cover the whole
      set, whether it fits in 60s, rate-limit behaviour, OI/volume presence, and
      a computed IV/Greeks sanity sample.

    python options_flow/probe.py build  [--strikes 15] [--expiries 1]
    python options_flow/probe.py rest
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime

SCRIP_MASTER = (
    "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
)
CACHE = "/tmp/angel_scrip_master.json"
UNIVERSE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_universe.json")
RISK_FREE = 0.065  # ~6.5% for IV/Greeks sanity check
FULL_BATCH = 50

# Index underlyings + a yfinance spot ticker (fallback to median strike if None/fails)
INDICES = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
    "FINNIFTY": None,  # flaky yf ticker -> median-strike ATM proxy
    "MIDCPNIFTY": None,
}
# ~40 liquid F&O stocks (Angel scrip-master 'name' spelling). Refine later.
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
YF_INDEX = INDICES  # alias


# ----------------------------------------------------------------------------
# scrip master
# ----------------------------------------------------------------------------
def load_master():
    import requests

    if os.path.exists(CACHE) and time.time() - os.path.getmtime(CACHE) < 6 * 3600:
        with open(CACHE) as f:
            return json.load(f)
    print("downloading Angel scrip master (~40 MB)…", flush=True)
    d = requests.get(SCRIP_MASTER, timeout=120).json()
    with open(CACHE, "w") as f:
        json.dump(d, f)
    return d


def opt_rows(master):
    """NSE F&O option rows only, normalized."""
    out = []
    for r in master:
        if r.get("exch_seg") != "NFO":
            continue
        it = r.get("instrumenttype")
        if it not in ("OPTIDX", "OPTSTK"):
            continue
        sym = str(r.get("symbol", ""))
        cp = "CE" if sym.endswith("CE") else ("PE" if sym.endswith("PE") else None)
        if cp is None:
            continue
        try:
            strike = float(r.get("strike", 0)) / 100.0
            exp = datetime.strptime(r.get("expiry"), "%d%b%Y").date()
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "token": str(r.get("token")),
                "symbol": sym,
                "name": r.get("name"),
                "type": cp,
                "strike": strike,
                "expiry": exp.isoformat(),
                "lotsize": int(float(r.get("lotsize", 0) or 0)),
                "exch_seg": "NFO",
                "kind": it,
            }
        )
    return out


# ----------------------------------------------------------------------------
# spot (for ATM) — yfinance prev close; stocks via .NS
# ----------------------------------------------------------------------------
def spot_prices(names_yf: dict[str, str | None]):
    import yfinance as yf

    tickers = {n: t for n, t in names_yf.items() if t}
    out: dict[str, float] = {}
    if tickers:
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


# ----------------------------------------------------------------------------
# build the scoped universe
# ----------------------------------------------------------------------------
def build(strikes_each_side: int, n_expiries: int):
    master = load_master()
    rows = opt_rows(master)
    today = datetime.now().date().isoformat()

    underlyings = list(INDICES.keys()) + LIQUID_STOCKS
    by_name: dict[str, list] = {}
    for r in rows:
        if r["name"] in underlyings:
            by_name.setdefault(r["name"], []).append(r)

    # spot: indices via their yf ticker, stocks via SYMBOL.NS
    yf_map = dict(INDICES)
    for s in LIQUID_STOCKS:
        yf_map[s] = f"{s}.NS"
    spots = spot_prices(yf_map)

    universe, per_under, missing = [], {}, []
    for name in underlyings:
        rs = by_name.get(name)
        if not rs:
            missing.append(name)
            continue
        expiries = sorted({r["expiry"] for r in rs if r["expiry"] >= today})[:n_expiries]
        picked = 0
        for exp in expiries:
            leg = [r for r in rs if r["expiry"] == exp]
            strikes = sorted({r["strike"] for r in leg})
            if not strikes:
                continue
            spot = spots.get(name)
            atm = (
                min(strikes, key=lambda k: abs(k - spot)) if spot else strikes[len(strikes) // 2]
            )  # median fallback
            i = strikes.index(atm)
            keep = set(strikes[max(0, i - strikes_each_side) : i + strikes_each_side + 1])
            for r in leg:
                if r["strike"] in keep:
                    universe.append(r)
                    picked += 1
        per_under[name] = picked
    with open(UNIVERSE, "w") as f:
        json.dump(universe, f)

    idx_ct = sum(v for k, v in per_under.items() if k in INDICES)
    stk_ct = sum(v for k, v in per_under.items() if k not in INDICES)
    print(
        f"\nspot source: {len(spots)}/{len(yf_map)} underlyings priced (rest use median-strike ATM)"
    )
    if missing:
        print(f"⚠ no contracts for (name mismatch?): {', '.join(missing)}")
    print("\nper-underlying contract counts:")
    for name in underlyings:
        if name in per_under:
            tag = "IDX" if name in INDICES else "stk"
            print(f"  {tag} {name:12} {per_under[name]:4}  (spot {spots.get(name, '—')})")
    print(f"\nTOTAL scoped contracts: {len(universe)}  (indices {idx_ct}, stocks {stk_ct})")
    print(
        f"REST cost @ {FULL_BATCH}/call: {math.ceil(len(universe) / FULL_BATCH)} "
        f"getMarketData calls per 60s cycle"
    )
    print(f"universe written -> {UNIVERSE}")


# ----------------------------------------------------------------------------
# IV / Greeks (Black-Scholes, spot-based, q=0) — pure python sanity check
# ----------------------------------------------------------------------------
def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_price(cp, S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return max(0.0, (S - K) if cp == "CE" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if cp == "CE":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def implied_vol(cp, price, S, K, T, r):
    if price <= 0 or T <= 0:
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if bs_price(cp, S, K, T, r, mid) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def greeks(cp, S, K, T, r, sigma):
    if T <= 0 or sigma <= 0:
        return {}
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d1 - sigma * math.sqrt(T)
    delta = _norm_cdf(d1) if cp == "CE" else _norm_cdf(d1) - 1
    gamma = _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * _norm_pdf(d1) * math.sqrt(T) / 100.0
    return {"delta": round(delta, 3), "gamma": round(gamma, 5), "vega": round(vega, 3)}


# ----------------------------------------------------------------------------
# rest probe (market hours)
# ----------------------------------------------------------------------------
def _angel_login():
    import pyotp
    from SmartApi import SmartConnect

    for v in ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PIN", "ANGEL_TOTP_SECRET"):
        if not os.getenv(v):
            print(f"ERROR: missing env {v}", file=sys.stderr)
            sys.exit(2)
    obj = SmartConnect(api_key=os.getenv("ANGEL_API_KEY"))
    totp = pyotp.TOTP(os.getenv("ANGEL_TOTP_SECRET")).now()
    sess = obj.generateSession(os.getenv("ANGEL_CLIENT_CODE"), os.getenv("ANGEL_PIN"), totp)
    if not sess or not sess.get("status"):
        print(f"ERROR: Angel login failed: {sess}", file=sys.stderr)
        sys.exit(3)
    return obj


def rest():
    if not os.path.exists(UNIVERSE):
        print("ERROR: run `build` first.", file=sys.stderr)
        sys.exit(1)
    with open(UNIVERSE) as f:
        universe = json.load(f)
    by_token = {c["token"]: c for c in universe}
    tokens = list(by_token)
    print(
        f"probing {len(tokens)} contracts via getMarketData FULL ({FULL_BATCH}/call)…", flush=True
    )

    obj = _angel_login()
    fetched, rate_errs, t0 = {}, 0, time.time()
    for i in range(0, len(tokens), FULL_BATCH):
        chunk = tokens[i : i + FULL_BATCH]
        try:
            resp = obj.getMarketData(mode="FULL", exchangeTokens={"NFO": chunk})
            for row in (resp or {}).get("data", {}).get("fetched", []) or []:
                fetched[str(row.get("symbolToken"))] = row
        except Exception as e:
            rate_errs += 1
            if rate_errs <= 3:
                print(f"  batch {i}: {e}", file=sys.stderr)
        time.sleep(1.0)  # 1 req/s — Angel getMarketData limit
    elapsed = time.time() - t0

    have_oi = sum(1 for r in fetched.values() if r.get("opnInterest") not in (None, ""))
    have_vol = sum(1 for r in fetched.values() if r.get("tradeVolume") not in (None, ""))
    print("\n--- RESULT ---")
    print(
        f"fetched {len(fetched)}/{len(tokens)} contracts in {elapsed:.1f}s "
        f"(batch errors: {rate_errs})"
    )
    print(
        f"fits in 60s? {'YES' if elapsed <= 60 else 'NO — needs WebSocket or a narrower universe'}"
    )
    print(f"OI present: {have_oi}/{len(fetched)} | volume present: {have_vol}/{len(fetched)}")

    # IV/Greeks sanity on up to 5 liquid contracts
    print("\nIV/Greeks sanity (spot-based BS, r=6.5%):")
    shown = 0
    for tok, row in fetched.items():
        c = by_token.get(tok)
        if not c:
            continue
        try:
            ltp = float(row.get("ltp"))
        except (TypeError, ValueError):
            continue
        T = max(
            1e-6, (datetime.fromisoformat(c["expiry"]).date() - datetime.now().date()).days / 365.0
        )
        S = c["strike"]  # probe proxy: ATM ~ strike (real collector uses spot/future)
        iv = implied_vol(c["type"], ltp, S, c["strike"], T, RISK_FREE)
        g = greeks(c["type"], S, c["strike"], T, RISK_FREE, iv) if iv else {}
        print(
            f"  {c['symbol']:24} ltp={ltp:8} OI={row.get('opnInterest')} "
            f"vol={row.get('tradeVolume')} IV~{iv and round(iv * 100, 1)}% {g}"
        )
        shown += 1
        if shown >= 5:
            break


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    b = sub.add_parser("build")
    b.add_argument("--strikes", type=int, default=15, help="ATM ± this many strikes")
    b.add_argument("--expiries", type=int, default=1, help="nearest N expiries")
    sub.add_parser("rest")
    a = ap.parse_args()
    if a.mode == "build":
        build(a.strikes, a.expiries)
    else:
        rest()


if __name__ == "__main__":
    main()
