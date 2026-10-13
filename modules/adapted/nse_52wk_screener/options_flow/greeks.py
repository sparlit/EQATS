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
Black-76 implied volatility + Greeks for options priced off the FUTURE (forward).

Indian index/stock options are European and cleanest to price off the underlying
future F (Black-76) rather than spot — that's what fixes the probe's nonsense IVs
(which used strike as spot). Pure stdlib, fast enough for a few thousand contracts
per 2-min cycle.
"""
import math

R_DEFAULT = 0.065  # ~6.5% risk-free


def _N(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _n(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def price(cp, F, K, T, r, sigma):
    """Black-76 option price. cp in {'CE','PE'}."""
    if F <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        intr = (F - K) if cp == "CE" else (K - F)
        return max(0.0, intr) * math.exp(-r * max(T, 0.0))
    st = sigma * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / st
    d2 = d1 - st
    df = math.exp(-r * T)
    if cp == "CE":
        return df * (F * _N(d1) - K * _N(d2))
    return df * (K * _N(-d2) - F * _N(-d1))


IV_MAX = 1.5  # ceiling; above this the quote is stale/illiquid → None


def implied_vol(cp, mkt_price, F, K, T, r=R_DEFAULT, iv_max=IV_MAX):
    """Solve IV by bisection. Returns None when it can't be trusted: no time value
    to invert (deep ITM at intrinsic), non-positive inputs, or a price so rich it
    implies IV above `iv_max` — which for our large-cap/index universe means a
    stale last-traded print on an illiquid deep-ITM/OTM strike, not a real vol."""
    if mkt_price is None or mkt_price <= 0 or F <= 0 or K <= 0 or T <= 0:
        return None
    df = math.exp(-r * T)
    intrinsic = df * max(0.0, (F - K) if cp == "CE" else (K - F))
    if mkt_price <= intrinsic + 1e-6:
        return None
    lo, hi = 1e-4, iv_max
    if price(cp, F, K, T, r, hi) < mkt_price:  # richer than the ceiling → junk
        return None
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if price(cp, F, K, T, r, mid) > mkt_price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def greeks(cp, F, K, T, r, sigma):
    """delta/gamma/vega (Black-76). vega per 1 vol-point (÷100)."""
    if F <= 0 or K <= 0 or T <= 0 or sigma is None or sigma <= 0:
        return {"delta": None, "gamma": None, "vega": None}
    st = sigma * math.sqrt(T)
    df = math.exp(-r * T)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / st
    delta = df * _N(d1) if cp == "CE" else -df * _N(-d1)
    gamma = df * _n(d1) / (F * st)
    vega = F * df * _n(d1) * math.sqrt(T) / 100.0
    return {"delta": round(delta, 4), "gamma": round(gamma, 6), "vega": round(vega, 4)}


def iv_and_greeks(cp, mkt_price, F, K, T, r=R_DEFAULT):
    iv = implied_vol(cp, mkt_price, F, K, T, r)
    g = greeks(cp, F, K, T, r, iv) if iv else {"delta": None, "gamma": None, "vega": None}
    return iv, g
