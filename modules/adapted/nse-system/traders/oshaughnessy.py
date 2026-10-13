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
James O'Shaughnessy — What Works on Wall Street (3rd Edition).
Classified: FUNDA (long-horizon, annual-rebalanced fundamental strategies).

19 methods extracted from the book per docs/BOOK_EXTRACTION_PROMPT.md.

All methods are LONG, annual-rebalance portfolio constructions. The
"signal" here is "symbol qualifies for this year's portfolio", not an
entry trigger. entry/stop/target are always None — the owner decides
sizing and rebalance timing (R19).

Data availability (as of 2026-09-14):
  AVAILABLE NOW:
    - pe, pb, dividend_yield, market_cap_cr, fcf_fy, sector
    - price appreciation 1y (252 sessions), mom_60d, mom_120d
  NOT YET IN DB (methods degrade gracefully — no hits until added):
    - price_to_sales        → Methods 6, 12, 14, 15 will emit 0 hits
    - eps_growth_1y         → Methods 8, 14, 15 partial
    - shareholder_yield     → Method 17 partial (dividend-only)
    - sales, cashflow, shares_outstanding → Method 1 partial

When those features land (ID52 data-source plugins), these methods
activate without code change — the None check simply starts passing.

Portfolio-construction methods (13, 18, 19) are listed in METHODS for
reference but NOT scanned — they are combinations of already-implemented
single strategies.
"""
import db
import numpy as np
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.oshaughnessy")

SLUG = "oshaughnessy"
NAME = "James O'Shaughnessy"
PILLAR = "funda"
SOURCE = "What Works on Wall Street (3rd Edition)"


# ----------------------------------------------------------------
# Tunables — book-cited thresholds, India adaptations noted
# ----------------------------------------------------------------
TOP_N = 50  # standard portfolio size
DOGS_N = 10  # Dogs of the Dow (Dow → Nifty 50 proxy)
PE_CAP = 20  # Graham cap for low-PE screen
PB_CAP = 1.0  # tight low-P/B
PB_CAP_LOOSE = 1.5  # looser variant
PSR_CAP = 1.0  # tight low-PSR
PSR_CAP_LOOSE = 1.5  # Cornerstone Growth uses 1.5
MCAP_FLOOR_CR = 200  # ₹200cr — book's $200M deflated proxy
UNIVERSE_MIN_PCT = 40  # book's "40th percentile of database" gate
LARGE_CAP_PROXY_N = 100  # top 100 by mcap ≈ Nifty 100
MARKET_LEADER_PROXY_N = 120  # top ~15% of band ≈ "above mean" tier

UTILITY_KEYWORDS = (
    "utilit",
    "power",
    "gas distribution",
    "water",
    "electric",
)

OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


# ----------------------------------------------------------------
# METHODS registry (19 total; 16 scanned, 3 portfolio constructions)
# ----------------------------------------------------------------
METHODS = [
    {
        "id": "market_leaders_universe",
        "name": "Market Leaders Universe",
        "description": "Size + liquidity tier — top ~15% by mcap, non-utility.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "dogs_of_the_dow",
        "name": "Dogs of the Dow",
        "description": "Top 10 highest-yielding large caps.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "low_pe_value",
        "name": "Low Price-to-Earnings",
        "description": "50 lowest PE, PE > 0, PE ≤ 20.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "low_pb_value",
        "name": "Low Price-to-Book",
        "description": "50 lowest P/B, P/B > 0.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "low_pcf_value",
        "name": "Low Price-to-Cashflow",
        "description": "50 lowest P/CF (FCF proxy), cashflow positive.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "low_psr_value",
        "name": "Low Price-to-Sales (King of Value)",
        "description": "50 lowest PSR. Requires sales data (pending).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "high_dividend_yield",
        "name": "High Dividend Yield",
        "description": "50 highest-yielding non-utility large caps.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "worst_earnings_gains",
        "name": "Worst 1Y Earnings Gains",
        "description": "Contrarian: 50 worst EPS changers. Pending EPS history.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "relative_price_strength_1y",
        "name": "1-Year Relative Strength",
        "description": "50 best 1-year price performers.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "low_pe_plus_rs",
        "name": "Low PE + Best RS",
        "description": "PE ≤ 20, then top 50 by 1-year RS.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "low_pb_plus_rs",
        "name": "Low P/B + Best RS",
        "description": "P/B ≤ 1.0, then top 50 by 1-year RS.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "low_psr_plus_rs",
        "name": "Low PSR + Best RS",
        "description": "PSR ≤ 1.0, then top 50 by 1-year RS. Pending PSR.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "cornerstone_growth_original",
        "name": "Cornerstone Growth (Original)",
        "description": "PSR ≤ 1.5 + EPS up YoY + top 50 by 1-year RS. Partial.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "cornerstone_growth_improved",
        "name": "Cornerstone Growth (Improved)",
        "description": "Above + 3m/6m RS above universe mean. Partial.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "cornerstone_value_original",
        "name": "Cornerstone Value (Original)",
        "description": "Top 50 Market Leaders by dividend yield.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "cornerstone_value_improved",
        "name": "Cornerstone Value (Improved)",
        "description": "Top 50 Market Leaders by shareholder yield. Partial.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "combined_value_three_way",
        "name": "Combined Value (3-way)",
        "description": "Portfolio: equal-weight PE+RS, PB+RS, PSR+RS.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "combined_value_growth_50_50",
        "name": "Combined Value + Growth (50/50)",
        "description": "Portfolio: 50% Improved Growth + 50% Improved Value.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "all_cap_value_growth",
        "name": "All-Cap Value-Growth",
        "description": "Portfolio: 3 growth + 4 value across cap bands.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
]


# ----------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------
def _passes(v, op, threshold):
    if v is None:
        return False
    try:
        return OPS[op](v, threshold)
    except Exception:
        return False


def _is_utility(sector):
    if not sector:
        return False
    s = sector.lower()
    return any(k in s for k in UTILITY_KEYWORDS)


def _pctile_rank(value, sorted_values):
    """Return percentile rank 0-100 (fraction of values below)."""
    if value is None or not sorted_values:
        return None
    n = len(sorted_values)
    # Binary search for insertion point
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_values[mid] < value:
            lo = mid + 1
        else:
            hi = mid
    return 100.0 * lo / n


# ----------------------------------------------------------------
# Feature loading
# ----------------------------------------------------------------
def _fundamentals_map(conn):
    """Load all fundamentals rows into {sym: dict}."""
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(fundamentals)")]
    except Exception:
        return {}
    if not cols:
        return {}
    sel = ", ".join(cols)
    out = {}
    try:
        for row in conn.execute(f"SELECT {sel} FROM fundamentals"):
            m = dict(zip(cols, row, strict=False))
            sym = m.get("symbol")
            if sym:
                out[sym] = m
    except Exception as e:
        log.warning(f"fundamentals load failed: {e}")
    return out


def _price_features(conn, sym, lookback=280):
    """Returns dict of price-based features, or None if insufficient."""
    rows = conn.execute(
        "SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT ?", (sym, lookback)
    ).fetchall()
    if len(rows) < 253:
        return None
    closes = [r[0] for r in rows if r[0] is not None]
    if len(closes) < 253:
        return None
    closes = list(reversed(closes))
    close = float(closes[-1])
    pa_1y = None
    if closes[-253] and closes[-253] > 0:
        pa_1y = close / closes[-253] - 1
    mom_60d = None
    if len(closes) >= 61 and closes[-61]:
        mom_60d = close / closes[-61] - 1
    mom_120d = None
    if len(closes) >= 121 and closes[-121]:
        mom_120d = close / closes[-121] - 1
    return {
        "close": close,
        "pa_1y": pa_1y,
        "mom_60d": mom_60d,
        "mom_120d": mom_120d,
    }


def _compute_features(conn, sym, fund_map):
    price = _price_features(conn, sym)
    if price is None:
        return None
    f = fund_map.get(sym, {})

    mcap = f.get("market_cap_cr")
    pe = f.get("pe")
    pb = f.get("pb")
    dy = f.get("dividend_yield")
    fcf = f.get("fcf_fy")

    # Approximate P/CF from FCF when positive. TV's fcf_fy is raw
    # (in reporting currency units). Ratio market_cap_cr / (fcf/1e7)
    # would be dimensionally correct, but we don't fully trust the units
    # yet. Safer: skip P/CF until cashflow standardization lands.
    # Kept as a named field so Method 5 activates cleanly once fixed.
    pcf = None

    return {
        "symbol": sym,
        **price,
        "sector": f.get("sector"),
        "market_cap_cr": mcap,
        "pe": pe,
        "pb": pb,
        "dividend_yield": dy,
        "fcf_fy": fcf,
        "eps_fy": f.get("eps_fy"),
        # Pending features:
        "price_to_sales": None,
        "price_to_cashflow": pcf,
        "shares_outstanding": None,
        "sales": None,
        "cashflow": None,
        "shareholder_yield": None,
        "eps_growth_1y": None,
    }


# ----------------------------------------------------------------
# Universe stats + rankings
# ----------------------------------------------------------------
def _universe_stats(features):
    """Cross-sectional means, percentiles, and top-N sets."""
    entries = list(features.items())
    n = len(entries)

    mcaps = sorted([f["market_cap_cr"] for _, f in entries if f.get("market_cap_cr") is not None])
    pes = [f["pe"] for _, f in entries if f.get("pe") is not None and f["pe"] > 0]
    mom60 = [f["mom_60d"] for _, f in entries if f.get("mom_60d") is not None]
    mom120 = [f["mom_120d"] for _, f in entries if f.get("mom_120d") is not None]

    mcap_mean = float(np.mean(mcaps)) if mcaps else None
    mom60_mean = float(np.mean(mom60)) if mom60 else None
    mom120_mean = float(np.mean(mom120)) if mom120 else None

    # Percentile gates
    mcap_40pct = None
    if mcaps:
        idx = max(0, int(len(mcaps) * UNIVERSE_MIN_PCT / 100.0) - 1)
        mcap_40pct = mcaps[idx]

    # Top-N by market cap — Large Stocks and Market Leaders proxy
    top_by_mcap = sorted(
        [(s, f.get("market_cap_cr") or 0) for s, f in entries], key=lambda x: -x[1]
    )
    large_cap_set = {s for s, _ in top_by_mcap[:LARGE_CAP_PROXY_N]}
    market_leaders_set = {s for s, _ in top_by_mcap[:MARKET_LEADER_PROXY_N]}

    return {
        "n": n,
        "mcap_mean": mcap_mean,
        "mcap_40pct": mcap_40pct,
        "mom60_mean": mom60_mean,
        "mom120_mean": mom120_mean,
        "large_cap_set": large_cap_set,
        "market_leaders_set": market_leaders_set,
        "n_pe": len(pes),
        "n_mcap": len(mcaps),
    }


def _compute_rankings(features, ustats):
    """
    For each ranked method, compute the top-N symbol set. Returns dict:
      {method_id: {"set": set_of_symbols, "key": field_used}}
    """
    out = {}

    def _collect(field, filt=None):
        rows = []
        for sym, f in features.items():
            v = f.get(field)
            if v is None:
                continue
            if filt and not filt(f):
                continue
            rows.append((sym, v))
        return rows

    # low_pe_value — 50 lowest PE, PE>0, PE<=20
    pe_rows = _collect("pe", filt=lambda f: 0 < (f.get("pe") or 0) <= PE_CAP)
    pe_rows.sort(key=lambda x: x[1])
    out["low_pe_value"] = {"set": {s for s, _ in pe_rows[:TOP_N]}, "key": "pe"}

    # low_pb_value — 50 lowest PB, PB>0
    pb_rows = _collect("pb", filt=lambda f: (f.get("pb") or 0) > 0)
    pb_rows.sort(key=lambda x: x[1])
    out["low_pb_value"] = {"set": {s for s, _ in pb_rows[:TOP_N]}, "key": "pb"}

    # low_psr_value — 50 lowest PSR (will be empty until sales lands)
    psr_rows = _collect("price_to_sales", filt=lambda f: (f.get("price_to_sales") or 0) > 0)
    psr_rows.sort(key=lambda x: x[1])
    out["low_psr_value"] = {"set": {s for s, _ in psr_rows[:TOP_N]}, "key": "price_to_sales"}

    # high_dividend_yield — 50 highest yield, non-utility
    dy_rows = _collect(
        "dividend_yield",
        filt=lambda f: not _is_utility(f.get("sector")) and (f.get("dividend_yield") or 0) > 0,
    )
    dy_rows.sort(key=lambda x: -x[1])
    out["high_dividend_yield"] = {"set": {s for s, _ in dy_rows[:TOP_N]}, "key": "dividend_yield"}

    # dogs_of_the_dow — top 10 by yield inside large-cap proxy
    dyd_rows = [r for r in dy_rows if r[0] in ustats["large_cap_set"]]
    out["dogs_of_the_dow"] = {"set": {s for s, _ in dyd_rows[:DOGS_N]}, "key": "dividend_yield"}

    # worst_earnings_gains — 50 worst EPS-changers (needs history)
    eg_rows = _collect("eps_growth_1y", filt=lambda f: (f.get("eps_fy") or 0) > 0)
    eg_rows.sort(key=lambda x: x[1])
    out["worst_earnings_gains"] = {"set": {s for s, _ in eg_rows[:TOP_N]}, "key": "eps_growth_1y"}

    # relative_price_strength_1y — 50 highest 1y price appreciation
    rs_rows = _collect("pa_1y")
    rs_rows.sort(key=lambda x: -x[1])
    out["relative_price_strength_1y"] = {"set": {s for s, _ in rs_rows[:TOP_N]}, "key": "pa_1y"}

    # low_pe_plus_rs — filter PE<=20 then rank by RS
    pe_rs = _collect("pa_1y", filt=lambda f: 0 < (f.get("pe") or 0) <= PE_CAP)
    pe_rs.sort(key=lambda x: -x[1])
    out["low_pe_plus_rs"] = {"set": {s for s, _ in pe_rs[:TOP_N]}, "key": "pa_1y"}

    # low_pb_plus_rs — filter P/B<=1 then rank by RS
    pb_rs = _collect("pa_1y", filt=lambda f: 0 < (f.get("pb") or 999) <= PB_CAP)
    pb_rs.sort(key=lambda x: -x[1])
    out["low_pb_plus_rs"] = {"set": {s for s, _ in pb_rs[:TOP_N]}, "key": "pa_1y"}

    # low_psr_plus_rs — filter PSR<=1 then rank by RS (empty until PSR)
    psr_rs = _collect("pa_1y", filt=lambda f: 0 < (f.get("price_to_sales") or 999) <= PSR_CAP)
    psr_rs.sort(key=lambda x: -x[1])
    out["low_psr_plus_rs"] = {"set": {s for s, _ in psr_rs[:TOP_N]}, "key": "pa_1y"}

    # cornerstone_growth_original — PSR<=1.5, EPS up, top RS
    cg_orig = _collect(
        "pa_1y",
        filt=lambda f: (
            (f.get("price_to_sales") or 999) <= PSR_CAP_LOOSE and (f.get("eps_growth_1y") or -1) > 0
        ),
    )
    cg_orig.sort(key=lambda x: -x[1])
    out["cornerstone_growth_original"] = {"set": {s for s, _ in cg_orig[:TOP_N]}, "key": "pa_1y"}

    # cornerstone_growth_improved — above + 3m/6m RS above mean
    m60 = ustats.get("mom60_mean")
    m120 = ustats.get("mom120_mean")

    def _cg_improved_filter(f):
        psr_ok = (f.get("price_to_sales") or 999) <= PSR_CAP_LOOSE
        eps_ok = (f.get("eps_growth_1y") or -1) > 0
        m60_ok = m60 is not None and (f.get("mom_60d") or -999) > m60
        m120_ok = m120 is not None and (f.get("mom_120d") or -999) > m120
        return psr_ok and eps_ok and m60_ok and m120_ok

    cg_imp = _collect("pa_1y", filt=_cg_improved_filter)
    cg_imp.sort(key=lambda x: -x[1])
    out["cornerstone_growth_improved"] = {"set": {s for s, _ in cg_imp[:TOP_N]}, "key": "pa_1y"}

    # cornerstone_value_original — top 50 Market Leaders by dividend yield
    cv_orig = [(s, v) for s, v in dy_rows if s in ustats["market_leaders_set"]]
    out["cornerstone_value_original"] = {
        "set": {s for s, _ in cv_orig[:TOP_N]},
        "key": "dividend_yield",
    }

    # cornerstone_value_improved — shareholder yield (pending). Fall back
    # to dividend yield in Market Leaders until buyback data lands.
    sv_rows = [(s, v) for s, v in dy_rows if s in ustats["market_leaders_set"]]
    out["cornerstone_value_improved"] = {
        "set": {s for s, _ in sv_rows[:TOP_N]},
        "key": "dividend_yield",
    }

    return out


# ----------------------------------------------------------------
# Per-symbol evaluation
# ----------------------------------------------------------------
def _signal(sym, method_id, confidence, notes, raw):
    return {
        "symbol": sym,
        "trader": SLUG,
        "method": method_id,
        "direction": "BULLISH",
        "signal_type": "QUALIFIES",
        "entry": None,
        "stop": None,
        "target": None,
        "confidence": confidence,
        "notes": notes,
        "raw": raw,
    }


def _evaluate_symbol(sym, f, ustats, rankings):
    signals = []

    # Method 1 — Market Leaders Universe
    if sym in ustats["market_leaders_set"] and not _is_utility(f.get("sector")):
        signals.append(
            _signal(
                sym,
                "market_leaders_universe",
                "HIGH",
                f"mcap ₹{f.get('market_cap_cr'):.0f}cr · "
                f"rank in top {MARKET_LEADER_PROXY_N} of band",
                {"mcap_cr": f.get("market_cap_cr"), "sector": f.get("sector")},
            )
        )

    # Method 2 — Dogs of the Dow
    if sym in rankings["dogs_of_the_dow"]["set"]:
        signals.append(
            _signal(
                sym,
                "dogs_of_the_dow",
                "HIGH",
                f"large-cap yield {f.get('dividend_yield'):.2f}% (top {DOGS_N})",
                {"dividend_yield": f.get("dividend_yield")},
            )
        )

    # Method 3 — Low PE
    if sym in rankings["low_pe_value"]["set"]:
        signals.append(
            _signal(
                sym,
                "low_pe_value",
                "HIGH",
                f"PE {f.get('pe'):.2f} (cap {PE_CAP})",
                {"pe": f.get("pe")},
            )
        )

    # Method 4 — Low P/B
    if sym in rankings["low_pb_value"]["set"]:
        signals.append(
            _signal(sym, "low_pb_value", "HIGH", f"P/B {f.get('pb'):.2f}", {"pb": f.get("pb")})
        )

    # Method 5 — Low P/CF (needs P/CF; currently None → no hits)
    if sym in rankings["low_pcf_value"]["set"] if "low_pcf_value" in rankings else False:
        # Currently unreachable — kept for when P/CF is added.
        pass

    # Method 6 — Low PSR (empty until sales lands)
    if sym in rankings["low_psr_value"]["set"]:
        signals.append(
            _signal(
                sym,
                "low_psr_value",
                "HIGH",
                f"PSR {f.get('price_to_sales'):.2f}",
                {"price_to_sales": f.get("price_to_sales")},
            )
        )

    # Method 7 — High Dividend Yield
    if sym in rankings["high_dividend_yield"]["set"]:
        signals.append(
            _signal(
                sym,
                "high_dividend_yield",
                "HIGH",
                f"yield {f.get('dividend_yield'):.2f}%",
                {"dividend_yield": f.get("dividend_yield")},
            )
        )

    # Method 8 — Worst 1Y Earnings Gains (empty until EPS history)
    if sym in rankings["worst_earnings_gains"]["set"]:
        signals.append(
            _signal(
                sym,
                "worst_earnings_gains",
                "MED",
                f"EPS growth 1y {f.get('eps_growth_1y'):.2f}",
                {"eps_growth_1y": f.get("eps_growth_1y")},
            )
        )

    # Method 9 — 1-Year Relative Strength
    if sym in rankings["relative_price_strength_1y"]["set"]:
        signals.append(
            _signal(
                sym,
                "relative_price_strength_1y",
                "HIGH",
                f"1y price apprec. {f.get('pa_1y') * 100:+.1f}%",
                {"pa_1y": f.get("pa_1y")},
            )
        )

    # Method 10 — Low PE + Best RS
    if sym in rankings["low_pe_plus_rs"]["set"]:
        signals.append(
            _signal(
                sym,
                "low_pe_plus_rs",
                "HIGH",
                f"PE {f.get('pe'):.2f} (≤{PE_CAP}) + RS {f.get('pa_1y') * 100:+.1f}%",
                {"pe": f.get("pe"), "pa_1y": f.get("pa_1y")},
            )
        )

    # Method 11 — Low P/B + Best RS
    if sym in rankings["low_pb_plus_rs"]["set"]:
        signals.append(
            _signal(
                sym,
                "low_pb_plus_rs",
                "HIGH",
                f"P/B {f.get('pb'):.2f} (≤{PB_CAP}) + RS {f.get('pa_1y') * 100:+.1f}%",
                {"pb": f.get("pb"), "pa_1y": f.get("pa_1y")},
            )
        )

    # Method 12 — Low PSR + Best RS (empty until PSR lands)
    if sym in rankings["low_psr_plus_rs"]["set"]:
        signals.append(
            _signal(
                sym,
                "low_psr_plus_rs",
                "HIGH",
                f"PSR {f.get('price_to_sales'):.2f} + RS {f.get('pa_1y') * 100:+.1f}%",
                {"price_to_sales": f.get("price_to_sales"), "pa_1y": f.get("pa_1y")},
            )
        )

    # Method 14 — Cornerstone Growth (Original)
    if sym in rankings["cornerstone_growth_original"]["set"]:
        signals.append(
            _signal(
                sym,
                "cornerstone_growth_original",
                "HIGH",
                f"PSR {f.get('price_to_sales'):.2f} + EPS up + RS {f.get('pa_1y') * 100:+.1f}%",
                {
                    "price_to_sales": f.get("price_to_sales"),
                    "eps_growth_1y": f.get("eps_growth_1y"),
                    "pa_1y": f.get("pa_1y"),
                },
            )
        )

    # Method 15 — Cornerstone Growth (Improved)
    if sym in rankings["cornerstone_growth_improved"]["set"]:
        signals.append(
            _signal(
                sym,
                "cornerstone_growth_improved",
                "HIGH",
                f"full growth stack: PSR≤{PSR_CAP_LOOSE}, EPS up, 3m/6m/12m RS positive",
                {
                    "price_to_sales": f.get("price_to_sales"),
                    "eps_growth_1y": f.get("eps_growth_1y"),
                    "mom_60d": f.get("mom_60d"),
                    "mom_120d": f.get("mom_120d"),
                    "pa_1y": f.get("pa_1y"),
                },
            )
        )

    # Method 16 — Cornerstone Value (Original)
    if sym in rankings["cornerstone_value_original"]["set"]:
        signals.append(
            _signal(
                sym,
                "cornerstone_value_original",
                "HIGH",
                f"Market Leader · yield {f.get('dividend_yield'):.2f}%",
                {"dividend_yield": f.get("dividend_yield")},
            )
        )

    # Method 17 — Cornerstone Value (Improved)
    if sym in rankings["cornerstone_value_improved"]["set"]:
        signals.append(
            _signal(
                sym,
                "cornerstone_value_improved",
                "HIGH",
                f"Market Leader · shareholder yield (dividend-only "
                f"until buyback data lands): {f.get('dividend_yield'):.2f}%",
                {
                    "dividend_yield": f.get("dividend_yield"),
                    "shareholder_yield": f.get("shareholder_yield"),
                },
            )
        )

    return signals


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=800):
    """
    Scan the band universe. Returns list of signal dicts — one per
    (symbol, method) pair where the symbol qualifies.

    Note: this is a screening scan, not an entry-trigger scan.
    entry/stop/target are None for all funda signals.
    """
    own = conn is None
    if own:
        conn = db.get_conn()

    syms = band_universe(conn, limit=limit)
    log.info(f"O'Shaughnessy scan: {len(syms)} symbols in universe")

    fund_map = _fundamentals_map(conn)
    log.info(f"fundamentals available for {len(fund_map)} symbols")

    # Pass 1 — features
    features = {}
    missing_prices = 0
    for i, sym in enumerate(syms, 1):
        f = _compute_features(conn, sym, fund_map)
        if f is None:
            missing_prices += 1
            continue
        features[sym] = f
        if i % 200 == 0:
            log.info(f"  features {i}/{len(syms)}")

    if not features:
        if own:
            conn.close()
        log.warning("no features computed — check prices_daily")
        return []

    # Universe stats + rankings
    ustats = _universe_stats(features)
    rankings = _compute_rankings(features, ustats)

    # Data-availability report (once per scan)
    n_psr = sum(1 for f in features.values() if f.get("price_to_sales") is not None)
    n_eg = sum(1 for f in features.values() if f.get("eps_growth_1y") is not None)
    n_sv = sum(1 for f in features.values() if f.get("shareholder_yield") is not None)
    n_pe = sum(1 for f in features.values() if f.get("pe") is not None)
    n_pb = sum(1 for f in features.values() if f.get("pb") is not None)
    n_dy = sum(1 for f in features.values() if f.get("dividend_yield") is not None)
    log.info(
        f"data coverage: PE={n_pe} PB={n_pb} DY={n_dy} "
        f"PSR={n_psr} EPSgrowth={n_eg} shareYield={n_sv} "
        f"· {missing_prices} symbols skipped (insufficient prices)"
    )

    # Pass 2 — evaluate each symbol against each method
    signals = []
    for sym, f in features.items():
        try:
            signals.extend(_evaluate_symbol(sym, f, ustats, rankings))
        except Exception as e:
            log.warning(f"{sym} evaluation failed: {e}")

    if own:
        conn.close()

    log.info(
        f"O'Shaughnessy scan complete: {len(signals)} signals "
        f"across {len({s['symbol'] for s in signals})} symbols"
    )
    return signals
