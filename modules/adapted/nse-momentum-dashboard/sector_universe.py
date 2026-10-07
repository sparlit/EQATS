from __future__ import annotations

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
Sector relative-strength: identifies which NSE market sectors are currently
outperforming, using REAL historical sector-index price data (not just
today's NSE heatmap snapshot), for use as an optional scoring input
alongside each stock's own momentum.

Why this is point-in-time safe: NSE's heatmap-index/heatmap-symbols APIs
only return today's snapshot, but most of NSE's sectoral indices are
themselves tradeable Kite instruments (segment == "INDICES") with full
historical daily candles -- exactly like the NIFTY 50 benchmark already
used everywhere else in this app. Sector strength is computed with the
same indicators.relative_strength() formula already used for every stock's
rs_3m/rs_6m vs NIFTY, just applied to sector indices instead.

Sector CLASSIFICATION (which index is a stock's "sector") comes from NSE's
own ground-truth index-constituent data (resolve_sector_profiles()), not a
heatmap scrape or a hand-curated guess: for each stock, take its
highest-weightage membership in a real "SECTORAL INDICES"-category index
(NSE's allIndices endpoint's own category label), falling back to its
highest-weightage "THEMATIC INDICES" membership only if it has none --
e.g. WIPRO is a member of both NIFTY IT (sectoral) and NIFTY IND DIGITAL
(thematic), and resolves to NIFTY IT. A stock still only ever gets ONE
ground-truth sector this way, unlike NSE's sectoral indices themselves,
which are NOT a clean partition of the market (e.g. SBIN sits in NIFTY
BANK, NIFTY FIN SERVICE, NIFTY FINSRV25 50, and NIFTY PSU BANK
simultaneously -- resolve_sector_profiles() picks the one it's most
heavily weighted in).
"""


import json
import os
import time

import kite_client
import nse_api
import pandas as pd

import indicators

CACHE_MAX_AGE_DAYS = 7
ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
INDEX_TRACKER_URL = "https://www.nseindia.com/api/NextApi/apiClient/indexTrackerApi"
INDEX_CATALOG_CACHE_PATH = os.path.join("cache", "nse_index_catalog.json")
INDEX_CONSTITUENTS_CACHE_PATH = os.path.join("cache", "nse_index_constituents.json")

# NIFTY BANK / NIFTY FIN SERVICE are real sector indices, but NSE files
# them under allIndices' "INDICES ELIGIBLE IN DERIVATIVES" key instead of
# "SECTORAL INDICES" -- added explicitly so they aren't silently dropped.
_EXTRA_SECTORAL_INDICES = ["NIFTY BANK", "NIFTY FIN SERVICE"]

# THEMATIC-category indices that are ownership/liquidity/compliance/
# recency SCREENS, not real industries -- would otherwise win a stock's
# sector fallback purely on weightage (e.g. BEL -> "NIFTY CPSE"
# [government-owned] instead of "NIFTY IND DEFENCE" [its real industry],
# or SUZLON -> "NIFTY MID LIQ 15" [a liquidity bucket] instead of "NIFTY
# ENERGY"). Identified by building and hand-inspecting a 208-symbol F&O
# sector-resolution CSV, 2026-08-08 -- every other THEMATIC index left
# unexcluded is a genuine sub-industry (NIFTY IND DEFENCE, NIFTY ENERGY,
# NIFTY INTERNET, NIFTY IND TOURISM, etc).
_NON_INDUSTRY_THEMES = {
    "NIFTY MNC",
    "NIFTY CPSE",
    "NIFTY PSE",
    "NIFTY TATA 25 CAP",
    "NIFTYCONGLOMERATE",
    "NIFTY100 LIQ 15",
    "NIFTY MID LIQ 15",
    "NIFTY CORP MAATR",
    "NIFTY SHARIAH 25",
    "NIFTY50 SHARIAH",
    "NIFTY500 SHARIAH",
    "NIFTY100 ESG",
    "NIFTY100 ENH ESG",
    "NIFTY100ESGSECLDR",
    "NIFTY IPO",
    "NIFTY SME EMERGE",
}

# Groups tracked sector index names by broader real-world industry.
# Several tracked indices are overlapping cuts of the SAME underlying
# industry -- confirmed on real data 2026-08-08: NIFTY MIDSML HLTH, NIFTY500
# HEALTH, NIFTY PHARMA, NIFTY HEALTHCARE were simultaneously 4 of the
# strongest sectors, and a per-raw-index-name diversification cap still let
# a test portfolio end up 100% healthcare-themed since each variant got its
# own independent cap. Capping/gating by industry_group() below instead of
# the raw index name fixes that. Curated by hand -- this is a
# classification judgment call, not derivable from the index data itself.
# Anything not listed here deliberately stays ungrouped -- industry_group()'s
# fallback to the raw name handles it correctly rather than forcing a bad
# classification onto a sector with no obvious near-duplicate sibling.
SECTOR_INDUSTRY_GROUPS: dict[str, str] = {
    "NIFTY BANK": "Financials",
    "NIFTY FIN SERVICE": "Financials",
    "NIFTY FINSRV25 50": "Financials",
    "NIFTY PSU BANK": "Financials",
    "NIFTY PVT BANK": "Financials",
    "NIFTY FINSEREXBNK": "Financials",
    "NIFTY MS FIN SERV": "Financials",
    "NIFTY CAPITAL MKT": "Financials",
    "NIFTY PHARMA": "Healthcare",
    "NIFTY HEALTHCARE": "Healthcare",
    "NIFTY MIDSML HLTH": "Healthcare",
    "NIFTY500 HEALTH": "Healthcare",
    "NIFTY IT": "Technology",
    "NIFTY MS IT TELCM": "Technology",
    "NIFTY IND DIGITAL": "Technology",
    "NIFTY INTERNET": "Technology",
    "NIFTY FMCG": "Consumer",
    "NIFTY CONSR DURBL": "Consumer",
    "NIFTY CONSUMPTION": "Consumer",
    "NIFTY RURAL": "Consumer",
    "NIFTY IND TOURISM": "Consumer",
    "NIFTY NONCYC CONS": "Consumer",
    "NIFTY MS IND CONS": "Consumer",
    "NIFTY METAL": "Materials",
    "NIFTY COMMODITIES": "Materials",
    "NIFTY CHEMICALS": "Materials",
    "NIFTY CEMENT": "Materials",
    "NIFTY OIL AND GAS": "Energy",
    "NIFTY ENERGY": "Energy",
    "NIFTY INFRA": "Industrials",
    "NIFTY INDIA MFG": "Industrials",
    "NIFTY TRANS LOGIS": "Industrials",
    "NIFTY IND DEFENCE": "Industrials",
    "NIFTY MULTI MFG": "Industrials",
    "NIFTY MULTI INFRA": "Industrials",
    "NIFTY RAILWAYSPSU": "Industrials",
}


def industry_group(sector_name: str) -> str:
    """Maps a raw tracked sector index name to its broader industry group
    (SECTOR_INDUSTRY_GROUPS) -- falls back to the raw name itself for
    anything not in the mapping, so an unclassified sector name never
    breaks this, it's just ungrouped (its own singleton group) until
    classified."""
    return SECTOR_INDUSTRY_GROUPS.get(sector_name, sector_name)


def fetch_index_catalog(force_refresh: bool = False, verbose: bool = True) -> dict[str, str]:
    """index name -> NSE's own category ('SECTORAL INDICES'/'THEMATIC
    INDICES'), from NSE's allIndices endpoint -- the authoritative source
    for which index names are real sector/sub-industry groupings, as
    opposed to the strategy, broad-market, and fixed-income indices also
    returned by the same endpoint. This naming convention (indexSymbol)
    matches indexTrackerApi's own (getConstituents/getAllIndicesSymbols)
    exactly -- verified live, 2026-08-08 -- unlike GetQuoteApi's indexList
    field, which uses a different, fuller naming for some indices (e.g.
    "NIFTY INDIA DEFENCE" there vs "NIFTY IND DEFENCE" here).

    NIFTY BANK / NIFTY FIN SERVICE are added explicitly (see
    _EXTRA_SECTORAL_INDICES) -- real sector indices, but NSE files them
    under allIndices' "INDICES ELIGIBLE IN DERIVATIVES" key instead.

    Cached CACHE_MAX_AGE_DAYS -- index composition/categorization changes
    rarely."""
    age_days = (
        (time.time() - os.path.getmtime(INDEX_CATALOG_CACHE_PATH)) / 86400
        if os.path.exists(INDEX_CATALOG_CACHE_PATH)
        else 1e9
    )
    if not force_refresh and age_days < CACHE_MAX_AGE_DAYS:
        with open(INDEX_CATALOG_CACHE_PATH) as f:
            return json.load(f)

    s = nse_api.session()
    r = s.get(ALL_INDICES_URL, timeout=15)
    r.raise_for_status()
    catalog = {
        row["indexSymbol"]: row["key"]
        for row in r.json()["data"]
        if row["key"] in ("SECTORAL INDICES", "THEMATIC INDICES")
    }
    for name in _EXTRA_SECTORAL_INDICES:
        catalog[name] = "SECTORAL INDICES"

    os.makedirs(os.path.dirname(INDEX_CATALOG_CACHE_PATH), exist_ok=True)
    with open(INDEX_CATALOG_CACHE_PATH, "w") as f:
        json.dump(catalog, f, indent=1)
    if verbose:
        n_sectoral = sum(1 for k in catalog.values() if k == "SECTORAL INDICES")
        print(
            f"[sector_universe] index catalog: {n_sectoral} sectoral + "
            f"{len(catalog) - n_sectoral} thematic indices"
        )
    return catalog


def fetch_index_constituents(force_refresh: bool = False, verbose: bool = True) -> dict[str, dict]:
    """index name -> {symbol: weightage}, via NSE's getConstituents, for
    every index in fetch_index_catalog(). Real, NSE-published index
    weights -- the same basis a passive index fund would size positions
    on -- rather than an equal-weight guess at each stock's importance to
    its sector.

    Cached CACHE_MAX_AGE_DAYS. On a partial failure, keeps whatever
    constituents were already cached for indices that fail this round."""
    catalog = fetch_index_catalog(force_refresh=force_refresh, verbose=verbose)
    cached: dict[str, dict] = {}
    if os.path.exists(INDEX_CONSTITUENTS_CACHE_PATH):
        with open(INDEX_CONSTITUENTS_CACHE_PATH) as f:
            cached = json.load(f)
        age_days = (time.time() - os.path.getmtime(INDEX_CONSTITUENTS_CACHE_PATH)) / 86400
        if (
            not force_refresh
            and age_days < CACHE_MAX_AGE_DAYS
            and all(name in cached for name in catalog)
        ):
            return cached

    s = nse_api.session()
    constituents = dict(cached)
    ok = 0
    for name in catalog:
        try:
            r = s.get(
                INDEX_TRACKER_URL,
                params={"functionName": "getConstituents", "index": name, "noofrecords": 0},
                timeout=15,
            )
            rows = r.json().get("data", [])
            constituents[name] = {
                row["cmSymbol"]: row.get("weightage") for row in rows if row.get("cmSymbol")
            }
            ok += 1
        except Exception as e:
            if verbose:
                print(f"[sector_universe] {name}: constituents fetch failed ({e})")
        time.sleep(0.3)

    os.makedirs(os.path.dirname(INDEX_CONSTITUENTS_CACHE_PATH), exist_ok=True)
    with open(INDEX_CONSTITUENTS_CACHE_PATH, "w") as f:
        json.dump(constituents, f, indent=1)
    if verbose:
        print(
            f"[sector_universe] index constituents: {ok}/{len(catalog)} "
            f"fetched fresh, {len(constituents)} total cached"
        )
    return constituents


def resolve_sector_profiles(
    symbols: list[str], force_refresh: bool = False, verbose: bool = True
) -> dict[str, dict]:
    """Each symbol's ground-truth PRIMARY sector: highest-weightage
    SECTORAL-category membership, falling back to highest-weightage
    THEMATIC-category membership (excluding _NON_INDUSTRY_THEMES) only if
    it has no sectoral one. Broader (sectoral) sector first, sub-sector as
    fallback, weightage breaks ties -- e.g. WIPRO -> NIFTY IT (sectoral,
    weightage 5.14) over NIFTY IND DIGITAL (thematic, weightage 2.74),
    even though it's a member of both.

    Returns {symbol: {"primary_sector":..., "primary_category":...,
    "primary_weightage":..., "sectoral": [(name,cat,w),...],
    "thematic": [(name,cat,w),...]}}. A symbol with no tracked-index
    membership at all gets primary_sector=None (~2% of F&O stocks in
    practice -- thin/very-recent listings)."""
    catalog = fetch_index_catalog(force_refresh=force_refresh, verbose=verbose)
    constituents = fetch_index_constituents(force_refresh=force_refresh, verbose=verbose)

    sym_memberships: dict[str, list[tuple]] = {}
    for name, mem in constituents.items():
        cat = catalog.get(name)
        for sym, w in mem.items():
            sym_memberships.setdefault(sym, []).append((name, cat, w))

    profiles = {}
    for sym in symbols:
        mems = sym_memberships.get(sym, [])
        sectoral = sorted(
            (m for m in mems if m[1] == "SECTORAL INDICES"), key=lambda m: -(m[2] or 0)
        )
        thematic = sorted(
            (m for m in mems if m[1] == "THEMATIC INDICES" and m[0] not in _NON_INDUSTRY_THEMES),
            key=lambda m: -(m[2] or 0),
        )
        if sectoral:
            name, cat, w = sectoral[0]
        elif thematic:
            name, cat, w = thematic[0]
        else:
            name, cat, w = None, None, None
        profiles[sym] = {
            "primary_sector": name,
            "primary_category": cat,
            "primary_weightage": w,
            "sectoral": sectoral,
            "thematic": thematic,
        }
    return profiles


def sector_membership_only(
    symbols: list[str], force_refresh: bool = False, verbose: bool = True
) -> dict[str, list[str]]:
    """symbol -> [primary_sector] (single-item list) -- shaped to match
    stock_sector_rs()/stock_top_sector()'s membership format (designed
    for a stock potentially belonging to multiple sectors; a single
    ground-truth primary sector is just the 1-item case, so no other
    function needs to change). Symbols with no resolvable sector are
    omitted."""
    profiles = resolve_sector_profiles(symbols, force_refresh=force_refresh, verbose=verbose)
    return {sym: [p["primary_sector"]] for sym, p in profiles.items() if p["primary_sector"]}


def sector_membership_and_candles(
    symbols: list[str], days: int, force_refresh: bool = False, verbose: bool = True
) -> tuple[dict, dict]:
    """One-call convenience: resolves ground-truth primary sectors, then
    fetches Kite candles for only the sectors actually in use (not the
    full ~60-index catalog)."""
    membership = sector_membership_only(symbols, force_refresh=force_refresh, verbose=verbose)
    used_names = sorted({m[0] for m in membership.values()})
    candles = fetch_sector_index_candles(used_names, days=days)
    return membership, candles


def _naive(frame: pd.DataFrame) -> pd.DataFrame:
    """Kite's timestamps are tz-aware (IST); backtest.py's stock candles and
    benchmark are normalized to tz-naive right after load (see
    load_candles_cached); comparing/slicing against them raises TypeError
    unless sector candles get the same treatment here."""
    if not frame.empty and frame.index.tz is not None:
        frame = frame.copy()
        frame.index = frame.index.tz_localize(None)
    return frame


def fetch_sector_index_candles(names: list[str], days: int = 1200) -> dict[str, pd.DataFrame]:
    """Real historical daily candles for each given sector index (each
    one's own Kite INDICES-segment instrument, same as the NIFTY 50
    benchmark) -- this is what makes point-in-time sector strength
    possible, not just today's NSE snapshot. A handful of THEMATIC names
    (e.g. NIFTY CEMENT, NIFTY RAILWAYSPSU, NIFTY COREHOUSING -- confirmed
    2026-08-08) have no Kite instrument at all; those come back empty and
    are skipped by sector_rs_asof(), degrading gracefully to "no sector_rs
    for this stock" rather than a crash."""
    out = {}
    for name in names:
        try:
            out[name] = _naive(kite_client.fetch_index_candles(name, days))
        except Exception as e:
            print(f"[sector_universe] {name}: candle fetch failed: {e}")
            out[name] = pd.DataFrame()
        time.sleep(0.35)
    return out


def sector_rs_asof(
    sector_candles: dict[str, pd.DataFrame], bench: pd.DataFrame, date, lookback_days: int
) -> pd.Series:
    """Point-in-time relative strength (vs NIFTY 50) for every sector index,
    as of `date` -- the exact indicators.relative_strength() formula already
    used for every stock's rs_3m/rs_6m, just applied to sector indices.
    Sectors with insufficient history as of this date are dropped, not
    defaulted -- callers (stock_sector_rs) treat a missing sector as
    unknown, not zero.

    Normalizes tz-awareness internally (both `bench` and each sector frame)
    rather than trusting every caller to have done it -- some callers go
    through backtest.load_candles_cached (already tz-naive), others call
    kite_client.benchmark_candles directly (still tz-aware); a single
    caller forgetting that distinction shouldn't crash this function.
    """
    date = pd.Timestamp(date).tz_localize(None) if pd.Timestamp(date).tz else pd.Timestamp(date)
    bench = _naive(bench)
    bench_close = bench.loc[:date, "close"] if not bench.empty else bench
    scores = {}
    for name, df in sector_candles.items():
        if df.empty:
            continue
        sliced = _naive(df).loc[:date]
        rs = indicators.relative_strength(sliced["close"], bench_close, lookback_days)
        if pd.notna(rs):
            scores[name] = rs
    return pd.Series(scores, dtype=float).sort_values(ascending=False)


def stock_sector_rs(
    symbol: str, membership: dict[str, list[str]], sector_rank: pd.Series
) -> float | None:
    """A stock's sector-strength signal: the MAX relative strength across
    every sector basket it belongs to (in practice, its single ground-truth
    primary sector -- see sector_membership_only()). None if the stock has
    no membership, or its sector has no computed rank yet (e.g. too early
    in a backtest for that sector's own lookback window, or no Kite
    instrument exists for it)."""
    secs = membership.get(symbol, [])
    vals = [sector_rank[s] for s in secs if s in sector_rank.index]
    return max(vals) if vals else None


def stock_top_sector(
    symbol: str, membership: dict[str, list[str]], sector_rank: pd.Series
) -> str | None:
    """The NAME of the sector basket that produced stock_sector_rs()'s max
    -- not the value itself. Used by the sector-diversification gate/cap
    (backtest.py) to check whether a stock's best sector is currently
    among the top-N overall, and to count per-sector position occupancy.
    None under the same conditions stock_sector_rs() returns None."""
    secs = membership.get(symbol, [])
    ranked_secs = [(s, sector_rank[s]) for s in secs if s in sector_rank.index]
    return max(ranked_secs, key=lambda kv: kv[1])[0] if ranked_secs else None


def sector_breadth(membership: dict[str, list[str]], gate_status: pd.Series) -> pd.Series:
    """% of each raw sector index's own tracked members that pass
    `gate_status` (a bool Series indexed by symbol -- pass the caller's
    PRE-sector-filter gate result, e.g. apply_gates()'s all_gates computed
    before sector_diversify_ok exists in `tech`, so this doesn't circularly
    depend on the sector selection it's meant to help make). Practitioner
    rationale (IBD/O'Neil "Group Relative Strength" methodology): a
    sector's RS number can be carried by one or two outlier stocks --
    broad participation is a stronger, more repeatable signal that the
    NEXT pick from that sector is also likely to work. Sectors with no
    tracked members in gate_status are omitted."""
    sector_members: dict[str, list[str]] = {}
    for sym, secs in membership.items():
        if sym not in gate_status.index:
            continue
        for s in secs:
            sector_members.setdefault(s, []).append(sym)
    return pd.Series(
        {sec: gate_status.loc[members].mean() for sec, members in sector_members.items()},
        dtype=float,
    )


def sector_composite_score(
    sector_rank: pd.Series,
    sector_candles: dict[str, pd.DataFrame],
    date,
    breadth: pd.Series,
    rs_weight: float = 0.5,
    high_weight: float = 0.25,
    breadth_weight: float = 0.25,
) -> pd.Series:
    """Composite sector-quality score blending three research-backed
    signals, each cross-sectionally z-scored across the tracked sector
    universe before combining (same standardization screener.score()
    already uses for stock-level factors) -- an alternative to ranking
    sectors on sector_rank (raw RS) alone:

    - RS (sector_rank): medium-term relative strength vs NIFTY. Moskowitz
      & Grinblatt (1999) "Do Industries Explain Momentum?" found industry
      momentum is a primary driver of individual stock momentum, often
      MORE robust than stock-level momentum directly.
    - 52-week-high proximity of the sector index itself. George & Hwang
      (2004) "The 52-Week High and Momentum Investing" found nearness to
      the 52-week high predicts continuation BETTER than past returns
      alone (an anchoring/underreaction effect) -- an independent signal
      RS can miss (e.g. a sector sitting at its high whose 6-month return
      hasn't caught up yet).
    - Breadth (see sector_breadth()): practitioner-established (IBD/
      O'Neil) evidence that broad participation beats a narrow, outlier-
      driven RS number.

    Returns a Series indexed by raw sector name, NaN-dropped -- a sector
    missing any one component (e.g. no candle data for 52w-high) is
    excluded entirely rather than scored on partial data."""
    pct52 = {}
    for name, df in sector_candles.items():
        d = df.loc[:date] if not df.empty else df
        if not d.empty:
            v = indicators.pct_of_52w_high(d["close"])
            if pd.notna(v):
                pct52[name] = v
    pct52_s = pd.Series(pct52, dtype=float)

    idx = sector_rank.index

    def z(s: pd.Series) -> pd.Series:
        s = s.reindex(idx)
        std = s.std(ddof=0)
        return (s - s.mean()) / std if std else s * 0

    score = rs_weight * z(sector_rank) + high_weight * z(pct52_s) + breadth_weight * z(breadth)
    return score.dropna()


if __name__ == "__main__":
    import config

    profiles = resolve_sector_profiles(config.UNIVERSE, force_refresh=True)
    n_classified = sum(1 for p in profiles.values() if p["primary_sector"])
    n_sectoral = sum(1 for p in profiles.values() if p["primary_category"] == "SECTORAL INDICES")
    print(
        f"\n{n_classified}/{len(profiles)} symbols classified "
        f"({n_sectoral} via a sectoral index, {n_classified - n_sectoral} via thematic fallback)"
    )
    unclassified = [s for s, p in profiles.items() if not p["primary_sector"]]
    if unclassified:
        print(f"unclassified: {unclassified}")
