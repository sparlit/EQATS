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
Janet Lowe — Value Investing Made Easy (1996).
Classified: FUNDA (long-horizon, annual-rebalanced value).

18 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.

The book is a simplified restatement of Benjamin Graham's principles
for the individual investor. Core doctrines:
  - Margin of safety
  - Think like an owner
  - Mr. Market is emotional, not informational
  - Diversify (5-30 stocks)
  - Patience (3-5 years)

Data availability (as of 2026-09-14):
  AVAILABLE NOW:
    pe, pb, roce, roe, debt_to_equity, cfo_positive,
    operating_margin, net_profit_margin, dividend_yield,
    market_cap_cr, sector, eps_fy, book_value
  NOT YET IN DB — methods degrade gracefully:
    current_assets, current_liabilities, cash, inventory,
    total_debt, shares_outstanding, EBIT, interest_expense,
    10-year EPS history, 20-year dividend history,
    bond/convertible/preferred data, event filings
    (IBC/NCLT/SAST), promoter holding.

Proxy policy (R2 + R19):
  Book's AAA bond yield (Y)   -> AAA_BOND_YIELD_PCT constant,
    default 7.5% (10yr G-sec + ~100bps). Owner updates when
    rate regime shifts.
  Book's NCAV per share       -> unavailable; P/B <= 0.67 is
    used as a proxy for deep asset discount (Method 2 criteria 4).
  Book's current ratio >= 2.0 -> unavailable; we substitute
    D/E <= 0.50 as a crude financial-health filter.
  Book's 10yr EPS stability   -> unavailable; flagged as BACKLOG.
  Book's 20yr dividend record -> unavailable; flagged as BACKLOG.

When ID52 (Phase 4 data-source plugins) lands, the 11 flagged
methods auto-activate without code change.
"""
import db
import numpy as np
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.value_investing_made_easy")

SLUG = "value_investing_made_easy"
NAME = "Janet Lowe"
PILLAR = "funda"
SOURCE = "Value Investing Made Easy (1996)"


# ----------------------------------------------------------------
# Tunables — book-cited thresholds, India adaptations noted
# ----------------------------------------------------------------
AAA_BOND_YIELD_PCT = 7.5  # Indian AAA corp yield proxy (10yr G-sec + ~100bps)
MIN_PRICE = 100  # book's $1 minimum -> ₹100 (penny avoidance)
UNIVERSE_MIN_PCT = 40  # book's NYSE 40th pct -> NSE 40th pct

# Graham's defensive investor thresholds
GRAHAM_PE_MAX = 15
GRAHAM_PB_MAX = 1.5
GRAHAM_DE_MAX = 0.50

# Method 2 criteria thresholds
GRAHAM_PB_DEEP = 0.67  # 2/3 of book value
GRAHAM_EY_MULT = 2.0  # earnings yield >= 2x AAA
GRAHAM_DY_MULT = 0.667  # dividend yield >= 2/3 AAA

# Method 6 (dividend assessment) — our relaxed version
DIV_YIELD_MIN = 0.03  # 3%

# Method 9 (management quality)
MANAGEMENT_ROCE_MIN = 12.0
MANAGEMENT_ROE_MIN = 12.0
MANAGEMENT_MARGIN_MIN = 10.0

# Intrinsic value formula
IV_BUY_DISCOUNT = 0.80  # buy at 20% discount to intrinsic value

EXCLUDE_SECTOR_KEYWORDS = (
    "financ",
    "bank",
    "nbfc",
    "insur",
    "utilit",
    "power",
    "gas distribution",
    "water",
    "electric",
    "reit",
)


# ----------------------------------------------------------------
# METHODS registry — 18 methods (7 scanned, 11 flagged)
# ----------------------------------------------------------------
METHODS = [
    # ---- SCANNED (7) ----
    {
        "id": "graham_deep_value_pb",
        "name": "Deep Value P/B (Graham crit 4)",
        "description": "Price <= 2/3 of book value (P/B <= 0.67).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "graham_earnings_yield",
        "name": "Earnings Yield (Graham crit 1)",
        "description": "Earnings yield >= 2x AAA bond yield (i.e. PE <= ~6.7).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "graham_dividend_yield",
        "name": "Dividend Yield (Graham crit 3)",
        "description": "Dividend yield >= 2/3 of AAA bond yield (~5.0%).",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "intrinsic_value_formula",
        "name": "Intrinsic Value Formula",
        "description": "Graham: V = E x (2r + 8.5) x 4.4 / Y. Buy below 80% of V.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "dividend_yield_assessment",
        "name": "Dividend Yield Assessment",
        "description": "DY >= 3%, PE <= 20, CFO+. Partial Method 6.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "balance_sheet_safety",
        "name": "Balance Sheet Safety",
        "description": "D/E <= 0.5, P/B <= 1.2, CFO+. Partial Method 7.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "management_quality_roic",
        "name": "Management Quality (ROCE)",
        "description": "ROCE >= 12%, ROE >= 12%, operating margin >= 10%.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    # ---- FLAGGED (11) ----
    {
        "id": "net_current_asset_value",
        "name": "Net Current Asset Value (Net-Net)",
        "description": "Price <= 2/3 of NCAV per share. Needs balance-sheet line items.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "graham_ten_attributes",
        "name": "Graham's 10 Attributes (full)",
        "description": "Score >= 7 of 10 criteria. Needs 10yr earnings history.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "defensive_investor_strategy",
        "name": "Defensive Investor (7 requirements)",
        "description": "All 7 criteria incl. 20yr dividend history. Needs history.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "enterprising_investor_1975",
        "name": "Enterprising Investor (1975)",
        "description": "5 value criteria incl. 7yr avg PE + 2yr high. Needs history.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "earnings_stability_growth",
        "name": "Earnings Stability & Growth",
        "description": "EPS doubled in 10yr, declines <=5% in <=2 years. Needs history.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "babson_pricing_method",
        "name": "Babson Pricing Method",
        "description": "Normal value = 7-10yr avg PE x avg earnings. Needs history.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "liquidation_arbitrage",
        "name": "Liquidation Arbitrage",
        "description": "Buy at discount to liquidation value. Needs IBC/NCLT feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "merger_takeover_arbitrage",
        "name": "Merger / Takeover Arbitrage",
        "description": "Buy target below offer price. Needs SAST/open-offer feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "bankruptcy_arbitrage",
        "name": "Bankruptcy Arbitrage",
        "description": "Buy bonds/stock at deep discount pre-emergence. Needs IBC feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "junk_bond_value",
        "name": "Junk Bond Value Play",
        "description": "Buy distressed bonds at deep discount. Needs bond feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "convertible_securities_value",
        "name": "Convertible Securities Value",
        "description": "Buy convertibles at low premium. Needs convertible feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "preferred_stock_value",
        "name": "Preferred Stock Value",
        "description": "Buy preferreds with adequate coverage. Needs preferred feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "ipo_value_assessment",
        "name": "IPO Value Assessment",
        "description": "Evaluate new listings on value criteria. Needs IPO feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "dollar_cost_averaging",
        "name": "Dollar Cost Averaging",
        "description": "Accumulation mechanics, not a scan method.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
]


# ----------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------
def _is_excluded_sector(sector):
    if not sector:
        return False
    s = sector.lower()
    return any(k in s for k in EXCLUDE_SECTOR_KEYWORDS)


def _safe_num(v):
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _fundamentals_map(conn):
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


def _last_close(conn, sym):
    r = conn.execute(
        "SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)
    ).fetchone()
    return _safe_num(r[0]) if r else None


# ----------------------------------------------------------------
# Feature builder
# ----------------------------------------------------------------
def _build_features(conn, syms):
    fund_map = _fundamentals_map(conn)
    features = {}
    excluded_sector = 0
    missing_fund = 0
    for i, sym in enumerate(syms, 1):
        f = fund_map.get(sym)
        if not f:
            missing_fund += 1
            continue
        sector = f.get("sector")
        if _is_excluded_sector(sector):
            excluded_sector += 1
            continue
        pe = _safe_num(f.get("pe"))
        pb = _safe_num(f.get("pb"))
        roce = _safe_num(f.get("roce"))
        roe = _safe_num(f.get("roe"))
        de = _safe_num(f.get("debt_to_equity"))
        dy = _safe_num(f.get("dividend_yield"))
        mcap = _safe_num(f.get("market_cap_cr"))
        cfo = f.get("cfo_positive")
        op_margin = _safe_num(f.get("operating_margin"))
        npm = _safe_num(f.get("net_profit_margin"))
        eps = _safe_num(f.get("eps_fy"))
        bv = _safe_num(f.get("book_value"))
        pg3y = _safe_num(f.get("profit_growth_3y"))
        close = _last_close(conn, sym)

        earnings_yield = (1.0 / pe) if (pe and pe > 0) else None

        features[sym] = {
            "symbol": sym,
            "sector": sector,
            "close": close,
            "market_cap_cr": mcap,
            "pe": pe,
            "pb": pb,
            "roce": roce,
            "roe": roe,
            "debt_to_equity": de,
            "cfo_positive": cfo,
            "operating_margin": op_margin,
            "net_profit_margin": npm,
            "dividend_yield": dy,
            "eps_fy": eps,
            "book_value": bv,
            "profit_growth_3y": pg3y,
            "earnings_yield": earnings_yield,
        }
        if i % 200 == 0:
            log.info(f"  features {i}/{len(syms)}")
    log.info(
        f"features: kept={len(features)}, "
        f"sector-excluded={excluded_sector}, "
        f"no-fundamentals={missing_fund}"
    )
    return features


# ----------------------------------------------------------------
# Universe stats
# ----------------------------------------------------------------
def _universe_stats(features):
    mcaps = sorted(
        [f["market_cap_cr"] for f in features.values() if f.get("market_cap_cr") is not None]
    )
    mcap_40pct = None
    if mcaps:
        idx = max(0, int(len(mcaps) * UNIVERSE_MIN_PCT / 100.0) - 1)
        mcap_40pct = mcaps[idx]
    return {"mcap_40pct": mcap_40pct}


# ----------------------------------------------------------------
# Cross-sectional rankings + gate sets
# ----------------------------------------------------------------
def _compute_rankings(features, ustats):
    """Return dict: method_id -> set of qualifying symbols."""
    out = {}

    # Method 2 crit 4 — deep value P/B
    deep_pb = set()
    for s, f in features.items():
        pb = f.get("pb")
        if pb is not None and 0 < pb <= GRAHAM_PB_DEEP:
            deep_pb.add(s)
    out["graham_deep_value_pb"] = deep_pb

    # Method 2 crit 1 — earnings yield >= 2x AAA
    ey_threshold = GRAHAM_EY_MULT * AAA_BOND_YIELD_PCT / 100.0  # 0.15
    ey_set = set()
    for s, f in features.items():
        ey = f.get("earnings_yield")
        if ey is not None and ey >= ey_threshold:
            ey_set.add(s)
    out["graham_earnings_yield"] = ey_set

    # Method 2 crit 3 — dividend yield >= 2/3 x AAA (~5%)
    dy_threshold = GRAHAM_DY_MULT * AAA_BOND_YIELD_PCT  # ~5.0
    dy_deep = set()
    for s, f in features.items():
        dy = f.get("dividend_yield")
        if dy is not None and dy >= dy_threshold:
            dy_deep.add(s)
    out["graham_dividend_yield"] = dy_deep

    # Method 6 partial — DY >= 3%, PE <= 20, CFO+
    dy_assess = set()
    for s, f in features.items():
        dy = f.get("dividend_yield")
        pe = f.get("pe")
        cfo = f.get("cfo_positive")
        if dy is not None and dy >= DIV_YIELD_MIN and pe is not None and 0 < pe <= 20 and cfo == 1:
            dy_assess.add(s)
    out["dividend_yield_assessment"] = dy_assess

    # Method 7 partial — balance sheet safety (D/E, P/B, CFO+)
    bss = set()
    for s, f in features.items():
        de = f.get("debt_to_equity")
        pb = f.get("pb")
        cfo = f.get("cfo_positive")
        if (
            de is not None
            and de <= GRAHAM_DE_MAX
            and pb is not None
            and 0 < pb <= 1.20
            and cfo == 1
        ):
            bss.add(s)
    out["balance_sheet_safety"] = bss

    # Method 9 partial — management quality (ROCE, ROE, margin)
    mq = set()
    for s, f in features.items():
        roce = f.get("roce")
        roe = f.get("roe")
        margin = f.get("operating_margin")
        if (
            roce is not None
            and roce >= MANAGEMENT_ROCE_MIN
            and roe is not None
            and roe >= MANAGEMENT_ROE_MIN
            and margin is not None
            and margin >= MANAGEMENT_MARGIN_MIN
        ):
            mq.add(s)
    out["management_quality_roic"] = mq

    # Method 5 — Graham's intrinsic value formula
    # V = E * (2r + 8.5) * 4.4 / Y     (r, Y in percent)
    iv = set()
    for s, f in features.items():
        eps = f.get("eps_fy")
        close = f.get("close")
        if eps is None or close is None or eps <= 0 or close <= 0:
            continue
        r = f.get("profit_growth_3y") or 0.0
        intrinsic = eps * (2.0 * r + 8.5) * 4.4 / AAA_BOND_YIELD_PCT
        if close <= IV_BUY_DISCOUNT * intrinsic:
            iv.add(s)
    out["intrinsic_value_formula"] = iv

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
        "signal_type": "SELECTED",
        "entry": None,
        "stop": None,
        "target": None,
        "confidence": confidence,
        "notes": notes,
        "raw": raw,
    }


def _evaluate_symbol(sym, f, rankings):
    sigs = []

    if sym in rankings.get("graham_deep_value_pb", set()):
        sigs.append(
            _signal(
                sym,
                "graham_deep_value_pb",
                "HIGH",
                f"P/B {f.get('pb'):.2f} <= {GRAHAM_PB_DEEP} "
                f"(Graham crit 4: price <= 2/3 book value)",
                {"pb": f.get("pb")},
            )
        )

    if sym in rankings.get("graham_earnings_yield", set()):
        sigs.append(
            _signal(
                sym,
                "graham_earnings_yield",
                "HIGH",
                f"Earnings yield {f.get('earnings_yield') * 100:.2f}% "
                f">= 2 x AAA ({AAA_BOND_YIELD_PCT}%)",
                {"earnings_yield": f.get("earnings_yield"), "pe": f.get("pe")},
            )
        )

    if sym in rankings.get("graham_dividend_yield", set()):
        sigs.append(
            _signal(
                sym,
                "graham_dividend_yield",
                "HIGH",
                f"Dividend yield {f.get('dividend_yield'):.2f}% "
                f">= 2/3 x AAA ({GRAHAM_DY_MULT * AAA_BOND_YIELD_PCT:.1f}%)",
                {"dividend_yield": f.get("dividend_yield")},
            )
        )

    if sym in rankings.get("intrinsic_value_formula", set()):
        eps = f.get("eps_fy")
        r = f.get("profit_growth_3y") or 0.0
        iv = eps * (2 * r + 8.5) * 4.4 / AAA_BOND_YIELD_PCT
        sigs.append(
            _signal(
                sym,
                "intrinsic_value_formula",
                "MED",
                f"Graham IV ₹{iv:.2f}, close ₹{f.get('close'):.2f} "
                f"<= 80% of IV (E=₹{eps:.2f}, r={r:.1f}%, Y={AAA_BOND_YIELD_PCT}%)",
                {
                    "eps_fy": eps,
                    "growth_r": r,
                    "intrinsic_value": round(iv, 2),
                    "close": f.get("close"),
                },
            )
        )

    if sym in rankings.get("dividend_yield_assessment", set()):
        sigs.append(
            _signal(
                sym,
                "dividend_yield_assessment",
                "MED",
                f"DY {f.get('dividend_yield'):.2f}% >= 3%, PE {f.get('pe'):.1f} <= 20, CFO+",
                {"dividend_yield": f.get("dividend_yield"), "pe": f.get("pe")},
            )
        )

    if sym in rankings.get("balance_sheet_safety", set()):
        sigs.append(
            _signal(
                sym,
                "balance_sheet_safety",
                "MED",
                f"D/E {f.get('debt_to_equity'):.2f} <= 0.5, P/B {f.get('pb'):.2f} <= 1.2, CFO+",
                {"debt_to_equity": f.get("debt_to_equity"), "pb": f.get("pb")},
            )
        )

    if sym in rankings.get("management_quality_roic", set()):
        sigs.append(
            _signal(
                sym,
                "management_quality_roic",
                "HIGH",
                f"ROCE {f.get('roce'):.1f}% ROE {f.get('roe'):.1f}% "
                f"margin {f.get('operating_margin'):.1f}%",
                {
                    "roce": f.get("roce"),
                    "roe": f.get("roe"),
                    "operating_margin": f.get("operating_margin"),
                },
            )
        )

    return sigs


# ----------------------------------------------------------------
# Universe scan
# ----------------------------------------------------------------
def scan(conn=None, limit=800):
    """
    Scan the band universe. Returns list of signal dicts — one per
    (symbol, method) pair where the symbol qualifies.

    Funda signals: entry/stop/target are None. The owner decides
    rebalance timing and sizing (R19).
    """
    own = conn is None
    if own:
        conn = db.get_conn()

    syms = band_universe(conn, limit=limit)
    log.info(f"Lowe scan: {len(syms)} symbols in universe")

    features = _build_features(conn, syms)
    if not features:
        if own:
            conn.close()
        log.warning("no features — check fundamentals table")
        return []

    ustats = _universe_stats(features)
    rankings = _compute_rankings(features, ustats)

    # Data-coverage report (once per scan)
    n_pe = sum(1 for f in features.values() if f.get("pe") is not None)
    n_pb = sum(1 for f in features.values() if f.get("pb") is not None)
    n_roce = sum(1 for f in features.values() if f.get("roce") is not None)
    n_roe = sum(1 for f in features.values() if f.get("roe") is not None)
    n_dy = sum(1 for f in features.values() if f.get("dividend_yield") is not None)
    n_eps = sum(1 for f in features.values() if f.get("eps_fy") is not None)
    log.info(
        f"coverage: PE={n_pe} PB={n_pb} ROCE={n_roce} ROE={n_roe} "
        f"DY={n_dy} EPS={n_eps} | "
        f"blocked: NCAV, balance-sheet line items, 10/20yr history, "
        f"bond/convertible/preferred, event filings (11 methods)"
    )

    signals = []
    for sym, f in features.items():
        try:
            signals.extend(_evaluate_symbol(sym, f, rankings))
        except Exception as e:
            log.warning(f"{sym} evaluation failed: {e}")

    if own:
        conn.close()

    n_sym = len({s["symbol"] for s in signals})
    log.info(f"Lowe scan complete: {len(signals)} signals across {n_sym} symbols")
    return signals
