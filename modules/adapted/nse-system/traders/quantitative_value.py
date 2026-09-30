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
Wesley R. Gray & Tobias E. Carlisle — Quantitative Value (2012).
Classified: FUNDA (long-horizon, annual-rebalanced value + quality).

20 methods extracted per docs/BOOK_EXTRACTION_PROMPT.md.

The book's core thesis: (1) cleanse the universe of frauds,
manipulators, and financially distressed firms, then (2) rank the
survivors by EBIT/TEV (best price ratio), and (3) among the cheapest
decile, prefer high-quality firms (franchise power + financial strength).

Data availability (as of 2026-09-14):
  AVAILABLE NOW:
    pe, pb, roce, roe, debt_to_equity, cfo_positive,
    net_profit_margin, operating_margin, dividend_yield, mcap_cr
  NOT YET IN DB — methods degrade gracefully:
    EBIT, TEV, gross profit, total assets, current assets/liabilities,
    cash, shares history, 8-year fundamentals series,
    insider trades, short interest, 13D filings

When those land (ID52 data-source plugins), flagged methods activate
without code change. Scan() logs a data-coverage report each run.

Bug fix 2026-09-15 (batch #072):
  - `composite_price_ratios_proxy` allowed partial components in its
    ranking, but its note string used `{val:.2f}` on potentially-None
    values, raising "unsupported format string passed to NoneType".
  - Fix: new `_fmt_num(v, dp)` helper returns "—" for None.
  - Defense in depth: new `_try_emit(sigs, fn)` wraps each signal
    emission, so a single method's failure cannot kill the whole
    symbol's signal set.
"""
import db
import numpy as np
from log_utils import get_logger
from universe_helper import band_universe

log = get_logger("trader.quantitative_value")

SLUG = "quantitative_value"
NAME = "Wesley Gray & Tobias Carlisle"
PILLAR = "funda"
SOURCE = "Quantitative Value (2012)"


# ----------------------------------------------------------------
# Tunables — book-cited thresholds, India adaptations noted
# ----------------------------------------------------------------
TOP_N = 30  # book's standard portfolio size
UNIVERSE_MIN_PCT = 40  # book's NYSE 40th percentile → NSE
MIN_PRICE = 100  # book's $10 → ₹100 (penny avoidance)
GRAHAM_PE_MAX = 10
GRAHAM_DE_MAX = 0.50
ROCE_QUALITY_MIN = 15.0  # our own quality gate
PFD_ELIMINATE_PCT = 95  # top 5% → eliminate
COMBOACCRUAL_ELIMINATE_PCT = 95  # top 5% → eliminate

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
# METHODS registry — 20 total (7 scanned, 13 flagged)
# ----------------------------------------------------------------
METHODS = [
    # ---- SCANNED (7) ----
    {
        "id": "graham_simple_value",
        "name": "Graham Simple Value",
        "description": "PE ≤ 10, D/E ≤ 0.5, CFO+, positive margin. Clean.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    {
        "id": "earnings_yield_value",
        "name": "Earnings Yield (EBIT/TEV proxy)",
        "description": "Rank by 1/PE. Proxy for EBIT/TEV until EBIT lands.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "book_to_market_value",
        "name": "Book-to-Market Value",
        "description": "Rank by 1/PB.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "magic_formula_proxy",
        "name": "Magic Formula (proxy)",
        "description": "Rank by ROCE + 1/PE combined. Proxy for ROC + EBIT/TEV.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "quality_and_price_proxy",
        "name": "Quality & Price (proxy)",
        "description": "Rank by ROE + 1/PB combined. Proxy for GPA + BM.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "composite_price_ratios_proxy",
        "name": "Composite Price Ratios (proxy)",
        "description": "Avg rank of 1/PE, 1/PB, dividend_yield.",
        "direction": "long",
        "scan": True,
        "confidence": "MED",
    },
    {
        "id": "roce_quality_gate",
        "name": "ROCE Quality Gate",
        "description": "ROCE ≥ 15%, non-financial, non-utility.",
        "direction": "long",
        "scan": True,
        "confidence": "HIGH",
    },
    # ---- FLAGGED (13) — awaiting features ----
    {
        "id": "scaled_total_accruals",
        "name": "Scaled Total Accruals (STA)",
        "description": "Eliminate top 5% accruals. Needs balance-sheet changes.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "scaled_net_operating_assets",
        "name": "Scaled Net Operating Assets (SNOA)",
        "description": "Eliminate top 5% bloated balance sheets. Needs balance sheet.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "probm_manipulation",
        "name": "Probability of Manipulation (PROBM)",
        "description": "8-variable fraud detector. Needs historical financials.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "pfd_financial_distress",
        "name": "Probability of Financial Distress (PFD)",
        "description": "Campbell et al. distress model. Needs quarterly data + market history.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "piotroski_f_score",
        "name": "Piotroski F_SCORE",
        "description": "9 binary signals. Needs YoY changes. Partial only.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "fs_score",
        "name": "Financial Strength Score (FS_SCORE)",
        "description": "10 binary signals. Needs YoY changes + shares history.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "franchise_power",
        "name": "Franchise Power",
        "description": "8-year geometric ROA/ROC + margin stability. Needs 8y history.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "ebit_enterprise_multiple",
        "name": "EBIT Enterprise Multiple",
        "description": "The book's best price ratio. Needs EBIT + TEV.",
        "direction": "long",
        "scan": False,
        "confidence": "HIGH",
    },
    {
        "id": "buyback_yield",
        "name": "Buyback Yield",
        "description": "Net share repurchase. Needs shares-outstanding history.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "insider_buying_opportunistic",
        "name": "Opportunistic Insider Buying",
        "description": "Non-routine insider purchases. Needs insider feed (SAST).",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "activist_13d_filing",
        "name": "Activist 13D Filing",
        "description": "Activist stake disclosures. Needs filing feed (SAST).",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "low_short_interest",
        "name": "Low Short Interest",
        "description": "Bottom decile SIR. Needs NSE short-interest feed.",
        "direction": "long",
        "scan": False,
        "confidence": "MED",
    },
    {
        "id": "quantitative_value_model",
        "name": "Full Quantitative Value Model",
        "description": "Integrated book model. Portfolio construction, not scanned.",
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


def _fmt_num(v, dp=2):
    """Safe number formatting: returns '—' for None/NaN rather than
    raising on `.Nf` format spec."""
    if v is None:
        return "—"
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return "—"
        return f"{f:.{dp}f}"
    except (TypeError, ValueError):
        return "—"


def _try_emit(sigs, fn):
    """Call fn() and append its result to sigs. On exception, log a
    warning and skip — one method's failure must not kill the whole
    symbol's signal set."""
    try:
        s = fn()
        if s is not None:
            sigs.append(s)
    except Exception as e:
        log.warning(f"signal emit skipped: {e}")


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
    r = conn.execute("SELECT close FROM prices_daily WHERE symbol=? ORDER BY date DESC LIMIT 1", (sym,)).fetchone()
    return _safe_num(r[0]) if r else None


# ----------------------------------------------------------------
# Feature builder
# ----------------------------------------------------------------
def _build_features(conn, syms):
    """Build feature dict per symbol. Sector-excluded symbols dropped."""
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
        npm = _safe_num(f.get("net_profit_margin"))

        # Derived
        earnings_yield = (1.0 / pe) if (pe and pe > 0) else None
        book_to_market = (1.0 / pb) if (pb and pb > 0) else None

        features[sym] = {
            "symbol": sym,
            "sector": sector,
            "market_cap_cr": mcap,
            "pe": pe,
            "pb": pb,
            "roce": roce,
            "roe": roe,
            "debt_to_equity": de,
            "cfo_positive": cfo,
            "net_profit_margin": npm,
            "dividend_yield": dy,
            "earnings_yield": earnings_yield,
            "book_to_market": book_to_market,
        }
        if i % 200 == 0:
            log.info(f"  features {i}/{len(syms)}")
    log.info(f"features: kept={len(features)}, sector-excluded={excluded_sector}, no-fundamentals={missing_fund}")
    return features


# ----------------------------------------------------------------
# Cross-sectional stats + percentile rankings
# ----------------------------------------------------------------
def _percentile_rank_map(items):
    """items = list of (sym, value). Returns {sym: percentile 0-100}."""
    valid = [(s, v) for s, v in items if v is not None]
    if not valid:
        return {}
    valid.sort(key=lambda x: x[1])
    n = len(valid)
    return {s: (100.0 * i / (n - 1)) if n > 1 else 50.0 for i, (s, _) in enumerate(valid)}


def _universe_stats(features):
    mcaps = sorted([f["market_cap_cr"] for f in features.values() if f.get("market_cap_cr") is not None])
    mcap_40pct = None
    if mcaps:
        idx = max(0, int(len(mcaps) * UNIVERSE_MIN_PCT / 100.0) - 1)
        mcap_40pct = mcaps[idx]
    return {"mcap_40pct": mcap_40pct}


def _compute_rankings(features, ustats):
    """Compute top-N symbol sets for each scanned method."""
    out = {}

    # Only symbols above the 40th percentile mcap gate are eligible
    gate = ustats.get("mcap_40pct")
    eligible = {
        s: f
        for s, f in features.items()
        if f.get("market_cap_cr") is not None and gate is not None and f["market_cap_cr"] >= gate
    }
    log.info(f"universe after 40th-pct mcap gate: {len(eligible)}")

    # ---- Graham Simple Value (pure filter) ----
    graham = set()
    for s, f in eligible.items():
        pe = f.get("pe")
        de = f.get("debt_to_equity")
        cfo = f.get("cfo_positive")
        npm = f.get("net_profit_margin")
        if (
            pe is not None
            and 0 < pe <= GRAHAM_PE_MAX
            and de is not None
            and de <= GRAHAM_DE_MAX
            and cfo == 1
            and npm is not None
            and npm > 0
        ):
            graham.add(s)
    out["graham_simple_value"] = graham

    # ---- Earnings yield (1/PE) ----
    ey_items = [(s, f.get("earnings_yield")) for s, f in eligible.items()]
    ey_items = [x for x in ey_items if x[1] is not None]
    ey_items.sort(key=lambda x: -x[1])
    out["earnings_yield_value"] = {s for s, _ in ey_items[:TOP_N]}

    # ---- Book-to-market (1/PB) ----
    bm_items = [(s, f.get("book_to_market")) for s, f in eligible.items()]
    bm_items = [x for x in bm_items if x[1] is not None]
    bm_items.sort(key=lambda x: -x[1])
    out["book_to_market_value"] = {s for s, _ in bm_items[:TOP_N]}

    # ---- Magic Formula proxy: ROCE + Earnings Yield, low combined rank ----
    roce_ranks = _percentile_rank_map([(s, f.get("roce")) for s, f in eligible.items()])
    ey_ranks = _percentile_rank_map([(s, f.get("earnings_yield")) for s, f in eligible.items()])
    combined = []
    for s in eligible:
        if s in roce_ranks and s in ey_ranks:
            score = (100 - roce_ranks[s]) + (100 - ey_ranks[s])
            combined.append((s, score))
    combined.sort(key=lambda x: x[1])
    out["magic_formula_proxy"] = {s for s, _ in combined[:TOP_N]}

    # ---- Quality and Price proxy: ROE + 1/PB ----
    roe_ranks = _percentile_rank_map([(s, f.get("roe")) for s, f in eligible.items()])
    bm_ranks = _percentile_rank_map([(s, f.get("book_to_market")) for s, f in eligible.items()])
    qp = []
    for s in eligible:
        if s in roe_ranks and s in bm_ranks:
            score = (100 - roe_ranks[s]) + (100 - bm_ranks[s])
            qp.append((s, score))
    qp.sort(key=lambda x: x[1])
    out["quality_and_price_proxy"] = {s for s, _ in qp[:TOP_N]}

    # ---- Composite price ratios: 1/PE + 1/PB + Div yield ----
    # NOTE: partial components are allowed — a symbol qualifies if
    # ANY of the three ranks is available. This is by design (the
    # book's composite averaging) but means the note string must be
    # null-safe. See _fmt_num usage in _evaluate_symbol.
    dy_ranks = _percentile_rank_map([(s, f.get("dividend_yield")) for s, f in eligible.items()])
    comp = []
    for s in eligible:
        parts = []
        if s in ey_ranks:
            parts.append(ey_ranks[s])
        if s in bm_ranks:
            parts.append(bm_ranks[s])
        if s in dy_ranks:
            parts.append(dy_ranks[s])
        if parts:
            comp.append((s, sum(parts) / len(parts)))
    comp.sort(key=lambda x: -x[1])
    out["composite_price_ratios_proxy"] = {s for s, _ in comp[:TOP_N]}

    # ---- ROCE quality gate ----
    roce_gate = set()
    for s, f in eligible.items():
        roce = f.get("roce")
        if roce is not None and roce >= ROCE_QUALITY_MIN:
            roce_gate.add(s)
    out["roce_quality_gate"] = roce_gate

    return out


# ----------------------------------------------------------------
# Per-symbol evaluation — all emits go through _try_emit for safety
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

    # ---- Method 1: Graham Simple Value ----
    if sym in rankings.get("graham_simple_value", set()):
        _try_emit(
            sigs,
            lambda: _signal(
                sym,
                "graham_simple_value",
                "HIGH",
                f"Graham: PE {_fmt_num(f.get('pe'), 2)} ≤ {GRAHAM_PE_MAX}, "
                f"D/E {_fmt_num(f.get('debt_to_equity'), 2)} ≤ "
                f"{GRAHAM_DE_MAX}, CFO+, margin positive",
                {"pe": f.get("pe"), "debt_to_equity": f.get("debt_to_equity")},
            ),
        )

    # ---- Method 2: Earnings Yield ----
    if sym in rankings.get("earnings_yield_value", set()):
        ey = f.get("earnings_yield")
        ey_pct = ey * 100 if ey is not None else None
        _try_emit(
            sigs,
            lambda: _signal(
                sym,
                "earnings_yield_value",
                "MED",
                f"Earnings yield {_fmt_num(ey_pct, 2)}% (1/PE, proxy for EBIT/TEV)",
                {"earnings_yield": ey, "pe": f.get("pe")},
            ),
        )

    # ---- Method 3: Book-to-Market ----
    if sym in rankings.get("book_to_market_value", set()):
        bm = f.get("book_to_market")
        _try_emit(
            sigs,
            lambda: _signal(
                sym,
                "book_to_market_value",
                "MED",
                f"Book-to-market {_fmt_num(bm, 3)} (P/B {_fmt_num(f.get('pb'), 2)})",
                {"book_to_market": bm, "pb": f.get("pb")},
            ),
        )

    # ---- Method 4: Magic Formula proxy ----
    if sym in rankings.get("magic_formula_proxy", set()):
        roce = f.get("roce")
        ey = f.get("earnings_yield")
        ey_pct = ey * 100 if ey is not None else None
        _try_emit(
            sigs,
            lambda: _signal(
                sym,
                "magic_formula_proxy",
                "MED",
                f"Magic Formula proxy: ROCE {_fmt_num(roce, 1)}% + E/Y {_fmt_num(ey_pct, 2)}%",
                {"roce": roce, "earnings_yield": ey},
            ),
        )

    # ---- Method 5: Quality & Price proxy ----
    if sym in rankings.get("quality_and_price_proxy", set()):
        roe = f.get("roe")
        bm = f.get("book_to_market")
        _try_emit(
            sigs,
            lambda: _signal(
                sym,
                "quality_and_price_proxy",
                "MED",
                f"Q&P proxy: ROE {_fmt_num(roe, 1)}% + B/M {_fmt_num(bm, 3)}",
                {"roe": roe, "book_to_market": bm},
            ),
        )

    # ---- Method 6: Composite Price Ratios ----
    # Partial components allowed → must be null-safe in the note.
    if sym in rankings.get("composite_price_ratios_proxy", set()):
        ey = f.get("earnings_yield")
        bm = f.get("book_to_market")
        dy = f.get("dividend_yield")
        ey_pct = ey * 100 if ey is not None else None
        _try_emit(
            sigs,
            lambda: _signal(
                sym,
                "composite_price_ratios_proxy",
                "MED",
                f"Composite: E/Y {_fmt_num(ey_pct, 2)}% + B/M {_fmt_num(bm, 3)} + DY {_fmt_num(dy, 2)}%",
                {"earnings_yield": ey, "book_to_market": bm, "dividend_yield": dy},
            ),
        )

    # ---- Method 7: ROCE Quality Gate ----
    if sym in rankings.get("roce_quality_gate", set()):
        roce = f.get("roce")
        _try_emit(
            sigs,
            lambda: _signal(
                sym, "roce_quality_gate", "HIGH", f"ROCE {_fmt_num(roce, 1)}% ≥ {ROCE_QUALITY_MIN}", {"roce": roce}
            ),
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
    log.info(f"QV scan: {len(syms)} symbols in universe")

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
    n_de = sum(1 for f in features.values() if f.get("debt_to_equity") is not None)
    n_dy = sum(1 for f in features.values() if f.get("dividend_yield") is not None)
    log.info(
        f"coverage: PE={n_pe} PB={n_pb} ROCE={n_roce} ROE={n_roe} "
        f"D/E={n_de} DY={n_dy} · "
        f"blocked: EBIT/TEV (Methods 2,11), balance-sheet changes "
        f"(Methods 4,5), 8y history (Methods 8,9,10), "
        f"insider/SI/13D feeds (Methods 14,15,16)"
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
    log.info(f"QV scan complete: {len(signals)} signals across {n_sym} symbols")
    return signals
