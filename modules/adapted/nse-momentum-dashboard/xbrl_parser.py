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
XBRL parser for NSE integrated filings (quarterly results).

Why this exists: /api/integrated-filing-results hands you the company's
*as-reported* financials in XBRL. Parsing that beats scraping screener.in on
every axis — it's the primary source, it's timestamped, it carries the
audited/unaudited flag, and it's available the evening results drop rather
than whenever a third party gets round to updating.

Ind-AS XBRL taxonomy element names vary between filers and versions, so we
match on a set of candidate local-names per concept and take the first hit
for the right context (current quarter, consolidated where available).
"""


import datetime as dt
import xml.etree.ElementTree as ET

import nse_api
import pandas as pd

# Candidate XBRL local-names per concept (Ind-AS taxonomy, several vintages)
CONCEPTS = {
    "revenue": [
        "RevenueFromOperations",
        "Revenue",
        "RevenueFromSaleOfProducts",
        "TotalIncome",
        "RevenueFromOperationsNet",
    ],
    "other_income": ["OtherIncome"],
    "total_income": ["TotalIncome", "IncomeTotal"],
    "total_expenses": ["TotalExpenses", "ExpensesTotal", "Expenses"],
    "finance_cost": ["FinanceCosts", "FinanceCost", "InterestExpense"],
    "depreciation": [
        "DepreciationDepletionAndAmortisationExpense",
        "DepreciationAndAmortisationExpense",
        "DepreciationAmortisationExpense",
    ],
    "pbt": [
        "ProfitBeforeTax",
        "ProfitLossBeforeTax",
        "ProfitBeforeExceptionalItemsAndTax",
    ],
    "tax": ["TaxExpense", "IncomeTaxExpense", "TotalTaxExpense"],
    "pat": [
        "ProfitLossForPeriod",
        "ProfitLossFortheperiod",
        "NetProfitLoss",
        "ProfitLossForPeriodFromContinuingOperations",
        "ProfitAfterTax",
        "ProfitLossForThePeriod",  # BANKING taxonomy's exact casing
        "ProfitLossAfterTax",  # GI (General Insurance) taxonomy
        "ProfitLossAfterTaxAndExtraordinaryItems",  # LI (Life Insurance) taxonomy
    ],
    "eps_basic": [
        "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
        "BasicEarningsPerShare",
        "BasicEPS",
    ],
    "exceptional": ["ExceptionalItemsBeforeTax", "ExceptionalItems"],
    # Balance sheet + cash flow: only present in AUDITED (Q4/annual) filings,
    # not the quarterly ones — SEBI Reg 33 doesn't require these every
    # quarter. See annual_balance_sheet().
    "total_equity": ["Equity", "EquityAttributableToOwnersOfParent"],
    "borrowings_current": ["BorrowingsCurrent"],
    "borrowings_noncurrent": ["BorrowingsNoncurrent"],
    "current_assets": ["CurrentAssets"],
    "current_liabilities": ["CurrentLiabilities"],
    "operating_cash_flow": ["CashFlowsFromUsedInOperatingActivities"],
    "capex_ppe": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    "capex_intangible": ["PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
    # BANKING taxonomy — banks don't tag Equity/Revenue/CurrentAssets at all;
    # verified against a real AXISBANK filing before adding these.
    "interest_earned": ["InterestEarned"],
    "interest_expended": ["InterestExpended"],
    "advances": ["Advances"],
    "deposits": ["Deposits"],
    "gross_npa_pct": ["PercentageOfGrossNpa"],
    "net_npa_pct": ["PercentageOfNpa"],
    "bank_capital": ["Capital"],
    "reserves_and_surplus": ["ReservesAndSurplus"],
    # NBFC_INDAS taxonomy (also covers AMCs, per NSE's own classification) —
    # verified against a real MUTHOOTFIN filing. Equity/PAT tags are the same
    # as the general taxonomy so no fallback needed for those.
    "loans": ["Loans"],
    "nbfc_borrowings": ["Borrowings"],  # single figure, not current/noncurrent split
    "debt_equity_ratio_tagged": ["DebtEquityRatio"],
    # GI (General Insurance) and LI (Life Insurance) taxonomies — neither
    # tags Equity directly, same Capital+Reserves pattern as banks but with
    # different exact tag names. Verified against real ICICIGI/SBILIFE
    # filings before adding these.
    "share_capital": ["ShareCapital", "PaidUpEquityCapital", "PaidUpEquityShareCapital"],
    "solvency_ratio": ["SolvencyRatio"],  # shared by GI and LI
    "combined_ratio": ["CombinedRatio"],  # GI only
    "incurred_claim_ratio": ["IncurredClaimRatio"],  # GI only
    "gross_premium": ["GrossPremiumsWritten", "GrossPremiumIncome"],
    "net_premium": ["NetPremiumWritten", "NetPremium", "NetPremiumIncome"],
    "persistency_13m_pct": ["PersistencyRatio13ThMonth"],  # LI only
    # Shared across all taxonomies (confirmed present in general/bank/NBFC).
    "total_assets": ["Assets"],
}


def _localname(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _to_float(text):
    if text is None:
        return None
    t = str(text).strip().replace(",", "")
    if not t or t.lower() in {"nan", "none", "-"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_xbrl(path: str, prefer_annual: bool = False) -> dict:
    """Extract headline financials from one XBRL instance document.

    prefer_annual: audited Q4/annual filings tag BOTH a '3 months ended'
    (the standalone quarter) and a 'year to date' (full 12 months) period
    with the SAME end date, since Ind-AS requires both columns. Quarterly
    trend analysis (quarterly_financials) wants the standalone quarter;
    annual ratio analysis (annual_balance_sheet) wants the full year. Ties on
    end-date are broken by context duration accordingly — shortest for
    quarterly, longest for annual — instead of arbitrarily.
    """
    try:
        tree = ET.parse(path)
    except Exception as e:
        return {"_error": f"parse failed: {e}"}
    root = tree.getroot()

    # Build context map: id -> (start, end, has_segment)
    contexts = {}
    for ctx in root.iter():
        if _localname(ctx.tag) != "context":
            continue
        cid = ctx.get("id")
        start = end = instant = None
        has_segment = False
        for el in ctx.iter():
            ln = _localname(el.tag)
            if ln == "startDate":
                start = el.text
            elif ln == "endDate":
                end = el.text
            elif ln == "instant":
                instant = el.text
            elif ln in ("segment", "scenario"):
                has_segment = len(list(el)) > 0
        contexts[cid] = {"start": start, "end": end or instant, "segment": has_segment}

    # Prefer the non-segmented context ending most recently (the headline
    # consolidated period, not a business-line breakdown). Ties on end-date
    # (3-months-ended vs year-to-date, same end date on Q4 filings) are
    # broken by duration: shortest for quarterly, longest for annual.
    def ctx_rank(cid):
        c = contexts.get(cid, {})
        if c.get("segment"):
            return (-1, 0, "")
        try:
            end = dt.date.fromisoformat(c["end"][:10]) if c.get("end") else None
        except Exception:
            end = None
        try:
            start = dt.date.fromisoformat(c["start"][:10]) if c.get("start") else None
        except Exception:
            start = None
        duration = (end - start).days if (start and end) else 0
        dur_rank = duration if prefer_annual else -duration
        return (1 if end else 0, dur_rank, c.get("end") or "")

    values: dict[str, list] = {}
    for el in root.iter():
        ln = _localname(el.tag)
        cref = el.get("contextRef")
        if not cref or el.text is None:
            continue
        val = _to_float(el.text)
        if val is None:
            continue
        for concept, names in CONCEPTS.items():
            if ln in names:
                values.setdefault(concept, []).append((cref, val))

    out: dict = {}
    for concept, hits in values.items():
        hits = [h for h in hits if not contexts.get(h[0], {}).get("segment")]
        if not hits:
            continue
        best = max(hits, key=lambda h: ctx_rank(h[0]))
        out[concept] = best[1]
        c = contexts.get(best[0], {})
        out.setdefault("period_start", c.get("start"))
        out.setdefault("period_end", c.get("end"))

    return _derive_ratios(out)


def _derive_ratios(out: dict) -> dict:
    """Compute margin/leverage/liquidity/return ratios from raw extracted
    concepts. Pulled out of parse_xbrl() so the same, already-debugged logic
    can run on a single filing's concepts OR on concepts combined from
    summing 4 quarterly filings (see quarterly_summed_annual) — duplicating
    this logic in two places risks the two copies drifting apart after a
    bug fix in only one of them.
    """
    # Derived quality metrics
    rev, pat = out.get("revenue"), out.get("pat")
    pbt, tax = out.get("pbt"), out.get("tax")
    dep, fin = out.get("depreciation"), out.get("finance_cost")
    texp = out.get("total_expenses")

    if rev and texp and dep is not None:
        ebitda = rev - texp + dep + (fin or 0)
        out["ebitda"] = ebitda
        out["ebitda_margin"] = ebitda / rev * 100 if rev else None
    if rev and pat:
        out["net_margin"] = pat / rev * 100
    if pbt and tax:
        out["effective_tax_rate"] = tax / pbt * 100 if pbt else None
    if out.get("other_income") and pbt:
        # High other-income share = profit not from the actual business
        out["other_income_share_of_pbt"] = out["other_income"] / pbt * 100
    if out.get("exceptional") and pbt:
        out["exceptional_share_of_pbt"] = out["exceptional"] / pbt * 100

    # Balance sheet + cash flow derived ratios (audited annual filings only)
    equity = out.get("total_equity")
    if equity is None:
        # BANKING/GI/LI taxonomies have no direct Equity tag — Capital +
        # Reserves & Surplus is the equivalent, confirmed against real
        # filings (AXISBANK uses 'Capital'; ICICIGI/SBILIFE use 'ShareCapital'
        # or 'PaidUpEquity(Share)Capital').
        cap = out.get("bank_capital") or out.get("share_capital")
        res = out.get("reserves_and_surplus")
        if cap is not None and res is not None:
            equity = cap + res
            out["total_equity"] = equity

    bc, bn = out.get("borrowings_current"), out.get("borrowings_noncurrent")
    if bc is not None or bn is not None:
        out["total_debt"] = (bc or 0) + (bn or 0)
    elif out.get("nbfc_borrowings") is not None:
        out["total_debt"] = out["nbfc_borrowings"]  # NBFC taxonomy: one figure
    if out.get("total_debt") is not None and equity:
        # NOT using the company-tagged DebtEquityRatio here: cross-checked it
        # against Borrowings/Equity on a real NBFC filing and they disagreed
        # by ~80x (0.037 tagged vs 2.90 derived) — the tagged fact evidently
        # means something other than total-debt-to-equity. The derived ratio
        # matched real-world expectations for a leveraged lending NBFC; the
        # tagged one didn't, so it's not used.
        out["debt_to_equity"] = out["total_debt"] / equity

    ca, cl = out.get("current_assets"), out.get("current_liabilities")
    if ca is not None and cl:
        out["current_ratio"] = ca / cl
    cp, ci = out.get("capex_ppe"), out.get("capex_intangible")
    if cp is not None or ci is not None:
        # XBRL tags these purchases as positive spend amounts (not signed
        # cash-flow deltas) — confirmed against a real filing before relying
        # on this in value_score().
        out["capex"] = (cp or 0) + (ci or 0)
    ocf = out.get("operating_cash_flow")
    if ocf is not None and out.get("capex") is not None:
        out["fcf"] = ocf - out["capex"]
    if pat and equity:
        out["roe"] = pat / equity * 100
    if pat and out.get("total_assets"):
        out["roa"] = pat / out["total_assets"] * 100

    # Bank-specific: net interest income and a NIM-style proxy. No CASA or
    # capital-adequacy tag exists in this taxonomy (checked) — not attempted.
    ie, iex = out.get("interest_earned"), out.get("interest_expended")
    if ie is not None and iex is not None:
        out["net_interest_income"] = ie - iex
        if out.get("advances"):
            out["nim_proxy_pct"] = out["net_interest_income"] / out["advances"] * 100

    # XBRL percentItemType facts are decimal fractions (0.25 = 25%), not
    # percentage points — confirmed by plausibility (raw 0.0123 would be an
    # impossible Gross NPA of 0.0123%; ×100 gives a realistic 1.23%). Same
    # convention verified for GI's combined/claim ratios (×100 gives 103.4%/
    # 71.1%, both realistic).
    #
    # NOT applied to solvency_ratio or persistency_13m_pct: ×100 gives 2.67%
    # solvency (real minimum is 150% — implausible in the OTHER direction)
    # and 0.88% persistency (real range is 70-90%+). Both are "pure"-unit
    # facts same as the others, but the ×100 convention evidently doesn't
    # hold for them, and unlike debt_to_equity there's no independent figure
    # to cross-check against. Left raw/unconverted and unused in
    # general_insurance_score()/life_insurance_score() rather than guessed at.
    for k in ("gross_npa_pct", "net_npa_pct", "combined_ratio", "incurred_claim_ratio"):
        if out.get(k) is not None:
            out[k] = out[k] * 100
    return out


def quarterly_financials(
    symbol: str, max_quarters: int = 12, consolidated_only: bool = False
) -> pd.DataFrame:
    """Parse the last N quarterly XBRL filings into a tidy DataFrame.

    Falls back to Standalone on a PER-QUARTER basis when Consolidated isn't
    available for that specific quarter, same policy as annual_balance_sheet()
    and for the same reason — some companies have patchy Consolidated
    history (verified: ABB has only 3 Consolidated quarters out of 8 total
    filings). Defaults to allowing this fallback (consolidated_only=False)
    so existing callers that don't pass this argument (filing_analyst,
    the dashboard's per-symbol detail view) get the deeper history
    automatically; pass consolidated_only=True to require a consistent
    reporting basis across all returned quarters instead. Checks 'pat'
    rather than 'revenue' for validity — banks,
    NBFCs, and insurers don't tag a 'revenue' concept at all (verified: this
    was silently returning ZERO rows for every bank/insurer before, since
    revenue never populates for those taxonomies — the same bug already
    found and fixed once in annual_balance_sheet() but never propagated
    here).
    """
    filings = nse_api.integrated_filings(symbol)
    filings = [f for f in filings if f.get("type_Sub") in (None, "Original", "Revised", "Revision")]

    by_qe: dict[str, dict[str, dict]] = {}
    for f in filings:
        qe = f.get("qe_Date")
        basis = f.get("consolidated")
        if qe and basis in ("Consolidated", "Standalone"):
            _pick_filing_slot(by_qe.setdefault(qe, {}), basis, f)

    def _qe_key(qe: str):
        try:
            return dt.datetime.strptime(qe, "%d-%b-%Y")
        except ValueError:
            return dt.datetime.min

    bases_to_try = ("Consolidated", "Standalone") if not consolidated_only else ("Consolidated",)
    rows = []
    for qe in sorted(by_qe, key=_qe_key, reverse=True):
        candidates = by_qe[qe]
        d = None
        for basis in bases_to_try:
            f = candidates.get(basis)
            if not f:
                continue
            url = f.get("xbrl")
            path = nse_api.download(url, subdir="xbrl") if url else None
            if not path:
                continue
            parsed = parse_xbrl(path)
            if parsed.get("_error") or not parsed.get("pat"):
                continue
            d = parsed
            d["consolidation_basis"] = basis
            break
        if not d:
            continue
        d.update(
            {
                "symbol": symbol,
                "qe_date": qe,
                "audited": candidates[d["consolidation_basis"]].get("audited"),
                "consolidated": d["consolidation_basis"],
                "broadcast": candidates[d["consolidation_basis"]].get("broadcast_Date"),
            }
        )
        rows.append(d)
        if len(rows) >= max_quarters:
            break

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["qe_dt"] = pd.to_datetime(df["qe_date"], format="%d-%b-%Y", errors="coerce")
    # Same point-in-time discipline as annual_balance_sheet()'s known_as_of
    # (see fundamentals_asof) -- needed so a quarterly-momentum pillar can
    # be backtested without lookahead (see quarterly_asof below).
    df["known_as_of"] = df["broadcast"].apply(_parse_broadcast)
    return df.sort_values("qe_dt").reset_index(drop=True)


def earnings_quality(df: pd.DataFrame) -> dict:
    """Signals that separate real earnings growth from accounting theatre.

    These are the checks that matter for avoiding value traps and blowups:
      * YoY revenue/PAT growth and whether growth is ACCELERATING
      * margin trend (expanding = operating leverage)
      * how much profit comes from 'other income' rather than the business
      * exceptional-item dependence
      * tax rate anomalies (a suspiciously low rate flatters PAT once)
    """
    if df.empty or len(df) < 2:
        return {}

    d = df.sort_values("qe_dt")
    out: dict = {}
    latest = d.iloc[-1]

    def yoy(col):
        if col not in d or len(d) < 5:
            return None
        cur, prior = d[col].iloc[-1], d[col].iloc[-5]
        if not prior or pd.isna(cur) or pd.isna(prior) or prior == 0:
            return None
        return (cur / prior - 1) * 100

    out["rev_yoy"] = yoy("revenue")
    out["pat_yoy"] = yoy("pat")

    # acceleration: this quarter's YoY vs the previous quarter's YoY
    if len(d) >= 6 and "pat" in d:
        try:
            prev_yoy = (d["pat"].iloc[-2] / d["pat"].iloc[-6] - 1) * 100
            if out["pat_yoy"] is not None:
                out["pat_growth_accel"] = out["pat_yoy"] - prev_yoy
        except (ZeroDivisionError, TypeError):
            pass

    if "ebitda_margin" in d and d["ebitda_margin"].notna().sum() >= 4:
        m = d["ebitda_margin"].dropna()
        out["ebitda_margin_now"] = float(m.iloc[-1])
        out["ebitda_margin_trend_pp"] = float(m.iloc[-1] - m.iloc[:4].mean())

    out["other_income_share_of_pbt"] = latest.get("other_income_share_of_pbt")
    out["exceptional_share_of_pbt"] = latest.get("exceptional_share_of_pbt")
    out["effective_tax_rate"] = latest.get("effective_tax_rate")
    out["net_margin"] = latest.get("net_margin")
    out["quarters_parsed"] = len(d)
    out["latest_quarter"] = latest.get("qe_date")
    out["audited"] = latest.get("audited")

    # Consistency: share of quarters with positive YoY PAT growth. Needs
    # >=5 (not 8) to get even one valid i vs i-4 comparison — the original
    # >=8 threshold was calibrated assuming max_quarters=12 would usually be
    # reachable, but the primary NSE endpoint's real ceiling for most F&O
    # stocks turned out to be ~5 quarters (verified across a diverse sample:
    # ABB, ICICIBANK, SBIN, AUBANK, LICI, BAJFINANCE all capped at exactly
    # 5) — >=8 silently zeroed this metric out for nearly everyone.
    if len(d) >= 5 and "pat" in d:
        wins = sum(
            1
            for i in range(4, len(d))
            if pd.notna(d["pat"].iloc[i])
            and pd.notna(d["pat"].iloc[i - 4])
            and d["pat"].iloc[i] > d["pat"].iloc[i - 4]
        )
        out["yoy_win_rate_pct"] = round(100 * wins / (len(d) - 4), 1)

    # Quality warnings
    warn = []
    if (out.get("other_income_share_of_pbt") or 0) > 30:
        warn.append(
            f"{out['other_income_share_of_pbt']:.0f}% of PBT is other "
            f"income — not the core business"
        )
    if abs(out.get("exceptional_share_of_pbt") or 0) > 20:
        warn.append("large exceptional items distort PBT")
    etr = out.get("effective_tax_rate")
    if etr is not None and (etr < 10 or etr > 45):
        warn.append(f"unusual effective tax rate {etr:.0f}%")
    if (
        out.get("rev_yoy") is not None
        and out.get("pat_yoy") is not None
        and out["pat_yoy"] > 30
        and out["rev_yoy"] < 5
    ):
        warn.append("PAT growing without revenue growth — margin/one-off driven")
    out["quality_warnings"] = warn
    return out


# ---------------------------------------------------------------------------
# Value-investing score: 0-100, computed entirely from primary XBRL + a
# market price. No LLM involved — Python does arithmetic exactly and for
# free, which is the whole point of running this across the full F&O
# universe rather than only the LLM-shortlisted names.
# ---------------------------------------------------------------------------


def _parse_broadcast(s: str | None) -> dt.datetime | None:
    """Parses NSE's filing-broadcast timestamp ('DD-Mon-YYYY HH:MM:SS') --
    the actual publication moment, distinct from qe_Date/toDate (the period
    END being reported on). Used to know when a figure became publicly
    knowable, for point-in-time backtesting (see fundamentals_asof) -- a
    filing for FY24 (year ended 31-Mar-2024) is typically not knowable until
    weeks or months after that date. Returns None on missing/malformed input
    rather than guessing, since fundamentals_asof treats None as "exclude".

    Guards with pd.isna(), not `not s` -- a missing value read back through
    a pandas .apply() (e.g. quarterly_financials()'s df["broadcast"].apply)
    can surface as float('nan') rather than None depending on the pandas/
    pyarrow string-backend in use, and `not float('nan')` is FALSE (NaN is
    truthy) -- verified this reached strptime() as a raw float and crashed
    with a TypeError on the VPS's pandas build, silently NOT reproducing
    locally where the same column happened to keep None as an object dtype.
    pd.isna() catches None, NaN and NaT uniformly regardless of backend."""
    if pd.isna(s):
        return None
    try:
        return dt.datetime.strptime(s, "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return None


def _pick_filing_slot(slot: dict[str, dict], basis: str, f: dict) -> None:
    """Fills slot[basis] with `f`, preferring a candidate that actually
    carries a broadcast_Date over one that doesn't, rather than blind
    first-wins -- shared by annual_balance_sheet() and quarterly_
    financials()'s by_qe construction.

    Needed because NSE's "Revision" type_Sub filings systematically omit
    broadcast_Date (verified across the F&O universe: 152/210 symbols have
    a same qe_Date+basis Original/Revision pair where the Revision's
    broadcast_Date is None) -- once "Revision" is accepted alongside
    "Original"/"Revised" (see the type_Sub filter above this), a same-key
    Original and Revision can both be present, and plain first-wins would
    occasionally lock in whichever the feed happened to list first,
    silently losing known_as_of -- and via fundamentals_asof/
    quarterly_asof, the ENTIRE year/quarter -- for a filing that had a
    perfectly good timestamp sitting right next to it. Two candidates
    that both carry (or both lack) a timestamp still resolve by first-
    wins, unchanged from before -- this only breaks that tie when it
    would otherwise throw away real point-in-time information.
    """
    existing = slot.get(basis)
    if existing is None or (
        existing.get("broadcast_Date") is None and f.get("broadcast_Date") is not None
    ):
        slot[basis] = f


def annual_balance_sheet(symbol: str, n_years: int = 3) -> list[dict]:
    """Parse the latest N annual (~12-month) filings for balance-sheet,
    cash-flow, and full-year P&L data — only available in Q4/year-end
    filings, not the interim quarterly ones (see parse_xbrl's prefer_annual).
    Newest first.

    Primary source (integrated-filing-results) only retains ~2 years for
    any symbol — a structural limit, verified across the full F&O universe.
    When more years are requested, extends with quarter-summed
    reconstruction from NSE's older reporting system (see
    quarterly_summed_annual) for whatever older years are still needed.
    Those reconstructed years may be missing balance-sheet ratios (ROE,
    Debt-to-Equity, Current Ratio) even when P&L figures (revenue, PAT)
    are present — some pre-~2023 filings simply never tagged the full
    balance sheet via XBRL (verified: a real NMDC FY22 filing tags 162
    concepts, zero of which are Equity or CurrentAssets).

    Deliberately does NOT filter on the 'audited' flag: it turns out to be
    an unreliable proxy in both directions — some companies (e.g. TCS) audit
    every quarter, not just Q4, so a Q1/Q3 filing can show audited=True;
    others (e.g. HEROMOTOCO) show audited=False on EVERY filing including
    genuine fiscal year-ends, apparently never getting flagged audited in
    this feed at all despite the underlying data being complete year-end
    figures (verified against a real filing before dropping this filter —
    requiring it was silently excluding real large-caps with usable data).
    The period-length check below (330-400 days) is what actually
    distinguishes a true annual filing from a quarter or YTD stub, and does
    that job correctly regardless of the audited flag's reliability.

    Prefers Consolidated but falls back to Standalone on a PER-YEAR basis —
    not one global choice for the whole symbol — when Consolidated isn't
    available for that specific fiscal year end (e.g. NMDC has no
    Consolidated filing at all for 31-Mar-2025, sandwiched between
    Consolidated years on both sides; empirically checked before relying on
    this: NMDC's Standalone vs Consolidated figures differ by ~1.6% on
    revenue and ~0.1% on PAT for a year where both exist, i.e. immaterial
    subsidiary operations for this company — but that gap could be much
    larger for a company with a large subsidiary, so each row records which
    basis was actually used in 'consolidation_basis' rather than silently
    blending bases with no trace). Checks 'pat' rather than 'revenue' for
    validity — banks and NBFCs don't tag a 'revenue' concept at all.
    """
    filings = nse_api.integrated_filings(symbol)
    filings = [
        f
        for f in filings
        if f.get("type") == "Integrated Filing- Financials"
        and f.get("type_Sub") in (None, "Original", "Revised", "Revision")
    ]

    by_qe: dict[str, dict[str, dict]] = {}
    for f in filings:
        qe = f.get("qe_Date")
        basis = f.get("consolidated")
        if qe and basis in ("Consolidated", "Standalone"):
            _pick_filing_slot(by_qe.setdefault(qe, {}), basis, f)

    def _try_parse(f: dict) -> dict | None:
        url = f.get("xbrl")
        path = nse_api.download(url, subdir="xbrl") if url else None
        if not path:
            return None
        d = parse_xbrl(path, prefer_annual=True)
        if d.get("_error") or not d.get("pat"):
            return None
        ps, pe = d.get("period_start"), d.get("period_end")
        try:
            days = (dt.date.fromisoformat(pe[:10]) - dt.date.fromisoformat(ps[:10])).days
        except (TypeError, ValueError):
            days = 0
        if not (330 <= days <= 400):
            return None  # not actually a full fiscal year
        return d

    def _qe_key(qe: str):
        # qe_Date strings ("31-MAR-2026", "31-DEC-2025", ...) do NOT sort
        # correctly as plain strings — month abbreviations aren't in
        # calendar order ('DEC' < 'MAR' alphabetically despite Dec being
        # later), which silently reordered years across this function's
        # first version. Parse to a real date for sorting.
        try:
            return dt.datetime.strptime(qe, "%d-%b-%Y")
        except ValueError:
            return dt.datetime.min

    rows = []
    for qe in sorted(by_qe, key=_qe_key, reverse=True):  # newest qe_Date first
        candidates = by_qe[qe]
        d = None
        for basis in ("Consolidated", "Standalone"):
            f = candidates.get(basis)
            if f:
                d = _try_parse(f)
                if d:
                    d["consolidation_basis"] = basis
                    # known_as_of must come from this SAME winning filing dict
                    # `f`, not a different candidate for this qe -- otherwise a
                    # restated filing's timestamp could attach to a different
                    # filing's numbers. Used for point-in-time backtesting
                    # (see fundamentals_asof): this figure isn't knowable
                    # before its own broadcast date, regardless of qe_date.
                    d["known_as_of"] = _parse_broadcast(f.get("broadcast_Date"))
                    break
        if not d:
            continue
        d.update({"symbol": symbol, "qe_date": qe})
        rows.append(d)
        if len(rows) >= n_years:
            break

    # integrated-filing-results has a structural ~2-year retention window
    # (verified across the full F&O universe — nobody returns more, not just
    # this symbol), which isn't enough for a genuine multi-year CAGR. Extend
    # with quarter-summed reconstruction from NSE's older reporting system
    # (real history back to ~2008) for whatever additional years are still
    # needed. Years already covered above are skipped rather than
    # double-counted or overridden — the primary source is more reliable
    # (one file, not four summed with an implicit no-restatement assumption)
    # so it always wins when both exist for the same fiscal year.
    if len(rows) < n_years:
        seen_qe = {r["qe_date"] for r in rows}
        for r in quarterly_summed_annual(symbol, n_years=n_years):
            if r["qe_date"] in seen_qe:
                continue
            rows.append(r)
            seen_qe.add(r["qe_date"])
            if len(rows) >= n_years:
                break
    return rows


# Concepts that are period flows (income, expenses, cash flow) — summed
# across 4 quarters to reconstruct an annual figure. Everything else in
# CONCEPTS is a balance-sheet/instant value or a point-in-time ratio, where
# summing across quarters would be meaningless — those take the Q4 (fiscal
# year-end) snapshot instead. See quarterly_summed_annual().
_FLOW_CONCEPTS = {
    "revenue",
    "other_income",
    "total_income",
    "total_expenses",
    "finance_cost",
    "depreciation",
    "pbt",
    "tax",
    "pat",
    "exceptional",
    "eps_basic",
    "operating_cash_flow",
    "capex_ppe",
    "capex_intangible",
    "interest_earned",
    "interest_expended",
    "gross_premium",
    "net_premium",
}


def _fiscal_year_end(to_date: str) -> str | None:
    """Map a quarter's toDate ('30-Jun-2024' etc, from the legacy endpoint)
    to the 31-Mar fiscal-year-end it belongs to (Indian FY = Apr-Mar)."""
    try:
        d = dt.datetime.strptime(to_date, "%d-%b-%Y").date()
    except (TypeError, ValueError):
        return None
    fy_end_year = d.year if d.month <= 3 else d.year + 1
    return dt.date(fy_end_year, 3, 31).strftime("%d-%b-%Y")


def quarterly_summed_annual(symbol: str, n_years: int = 5) -> list[dict]:
    """Reconstruct annual figures by summing 4 quarters from NSE's older
    reporting system (nse_api.legacy_quarterly_results), which retains
    history back to ~2008 — far deeper than annual_balance_sheet()'s
    ~2-year window (a structural limit of integrated-filing-results, not a
    bug — verified across the full F&O universe). Each individual file in
    that older system is quarter-only (see legacy_quarterly_results'
    docstring for why its own 'Annual'/'Cumulative' labels can't be
    trusted), so there is no single file to read an annual figure from —
    it has to be assembled from 4.

    Kept deliberately SEPARATE from annual_balance_sheet() rather than
    silently merged in: this is a materially different reliability tier
    (4x the network calls per year, an approximation for revenue/PAT since
    it assumes no restatement between quarters) and callers should be able
    to tell reconstructed years apart — every row carries
    reconstructed_from_quarters=True for that reason.

    Prefers Consolidated but falls back to Non-Consolidated (this older
    endpoint's label for what the newer one calls "Standalone") per fiscal
    year, same policy and same reasoning as annual_balance_sheet().
    """
    filings = nse_api.legacy_quarterly_results(symbol)

    # Dedup: prefer the most-recently-broadcast filing per (toDate, basis) —
    # handles revisions without needing to parse a separate revision flag.
    # Compares PARSED timestamps, not raw strings: NSE's "DD-Mon-YYYY
    # HH:MM:SS" format does not sort correctly as a string (same class of
    # bug as qe_Date's month-abbreviation ordering, see _qe_key below) --
    # this was silently picking the wrong revision in some cases.
    best: dict[tuple[str, str], dict] = {}
    for f in filings:
        key = (f.get("toDate"), f.get("consolidated"))
        if key[0] is None or key[1] not in ("Consolidated", "Non-Consolidated"):
            continue
        cur = best.get(key)
        f_bc = _parse_broadcast(f.get("broadCastDate")) or dt.datetime.min
        cur_bc = _parse_broadcast(cur.get("broadCastDate")) or dt.datetime.min if cur else None
        if cur is None or f_bc > cur_bc:
            best[key] = f

    by_fy: dict[tuple[str, str], dict[str, dict]] = {}
    for (to_date, basis), f in best.items():
        fy_end = _fiscal_year_end(to_date)
        if fy_end:
            by_fy.setdefault((fy_end, basis), {})[to_date] = f

    def _quarter_dates(fy_end: str) -> list[str]:
        end = dt.datetime.strptime(fy_end, "%d-%b-%Y").date()
        y0 = end.year - 1
        return [
            dt.date(y0, 6, 30).strftime("%d-%b-%Y"),
            dt.date(y0, 9, 30).strftime("%d-%b-%Y"),
            dt.date(y0, 12, 31).strftime("%d-%b-%Y"),
            end.strftime("%d-%b-%Y"),
        ]

    fy_ends = sorted(
        {fy for fy, _ in by_fy}, key=lambda s: dt.datetime.strptime(s, "%d-%b-%Y"), reverse=True
    )

    rows = []
    for fy_end in fy_ends:
        combined, basis_used = None, None
        for basis in ("Consolidated", "Non-Consolidated"):
            quarters = by_fy.get((fy_end, basis))
            if not quarters:
                continue
            needed = _quarter_dates(fy_end)
            if not all(qd in quarters for qd in needed):
                continue  # incomplete year for this basis — skip, don't guess
            # Pre-XBRL-mandate filings (~2011 and earlier) sometimes carry a
            # placeholder like ".../xbrl/-" instead of a real file — cheaper
            # to catch that before spending an HTTP round-trip on a
            # guaranteed 404 than to let download() find out the hard way.
            urls = [quarters[qd].get("xbrl") for qd in needed]
            if not all(u and u.rstrip("/").rsplit("/", 1)[-1] not in ("-", "") for u in urls):
                continue
            parsed = []
            for qd in needed:
                path = nse_api.download(quarters[qd].get("xbrl"), subdir="xbrl_legacy")
                d = parse_xbrl(path) if path else {"_error": "download failed"}
                if d.get("_error") or not d.get("pat"):
                    parsed = None
                    break
                parsed.append(d)
            if not parsed:
                continue
            merged: dict = {}
            for concept in CONCEPTS:
                vals = [p[concept] for p in parsed if p.get(concept) is not None]
                if not vals:
                    continue
                # Flow concepts: sum all 4 quarters. Everything else: prefer
                # Q4's value (a balance/ratio isn't summable) but fall back
                # to the latest quarter that actually has it — older filings
                # often tag P&L comprehensively but skip the full balance
                # sheet even at Q4 (verified: a real FY22 NMDC Q4 file has
                # 162 tagged concepts but no Equity/CurrentAssets at all —
                # a genuine gap in that era's filings, not a bug here).
                if concept in _FLOW_CONCEPTS:
                    merged[concept] = sum(vals)
                else:
                    merged[concept] = (
                        parsed[-1].get(concept) if parsed[-1].get(concept) is not None else vals[-1]
                    )
            # Don't rely on the XBRL content's own period_start/period_end —
            # older files sometimes leave it unset even when concepts extract
            # fine (whichever concept happens to be processed first in
            # CONCEPTS decides it via setdefault, and that one context might
            # lack start/end). We already know the true boundaries from how
            # these 4 quarters were selected in the first place.
            fy_end_date = dt.datetime.strptime(fy_end, "%d-%b-%Y").date()
            merged["period_start"] = dt.date(fy_end_date.year - 1, 4, 1).isoformat()
            merged["period_end"] = fy_end_date.isoformat()
            combined = _derive_ratios(merged)
            basis_used = basis
            # The reconstructed year isn't knowable until the LAST of its 4
            # quarters is filed -- and if even one quarter's broadcast date
            # is missing/unparseable, we can't be sure when the full picture
            # was actually complete, so the whole row is excluded (None)
            # rather than guessed at (see fundamentals_asof).
            bc_dates = [_parse_broadcast(quarters[qd].get("broadCastDate")) for qd in needed]
            combined["known_as_of"] = (
                max(bc_dates) if all(bc is not None for bc in bc_dates) else None
            )
            break
        if combined is None:
            continue
        combined.update(
            {
                "symbol": symbol,
                "qe_date": fy_end.upper(),
                "consolidation_basis": "Standalone"
                if basis_used == "Non-Consolidated"
                else basis_used,
                "reconstructed_from_quarters": True,
            }
        )
        rows.append(combined)
        if len(rows) >= n_years:
            break
    return rows


def fundamentals_asof(bs_years: list[dict], date) -> list[dict]:
    """Filters an already-fetched `bs_years` list (from annual_balance_sheet
    or quarterly_summed_annual, or a combination) down to only the rows that
    were publicly knowable as of `date` -- the core no-lookahead primitive
    for backtesting with a fundamental gate.

    A row with no known_as_of (missing/unparseable broadcast timestamp) is
    excluded unconditionally, never guessed at. Same-day filings count as
    known that day (filings land after market close, so this is at most
    ~1 trading day of fuzziness relative to the multi-month gap this closes
    -- a deliberate, documented choice, not an oversight).

    Pure in-memory filtering, no network calls -- callers should fetch
    bs_years ONCE per symbol (e.g. via fundamentals_agent.build_fundamentals_
    history) and call this many times against it for different backtest
    dates, rather than re-fetching per date.
    """
    cutoff = pd.Timestamp(date).normalize()
    return [
        r
        for r in bs_years
        if r.get("known_as_of") is not None and pd.Timestamp(r["known_as_of"]).normalize() <= cutoff
    ]


def quarterly_asof(qdf: pd.DataFrame, date) -> pd.DataFrame:
    """Same no-lookahead filter as fundamentals_asof(), for quarterly_
    financials()'s DataFrame shape instead of annual_balance_sheet()'s
    list-of-dicts -- the quarterly-momentum pillar's own backtest-facing
    primitive (see quarterly_momentum_pillar). Pure in-memory filtering,
    no network calls -- fetch qdf ONCE (fundamentals_agent.
    build_fundamentals_history) and call this many times against it.

    NOTE on backtest coverage: NSE's integrated-filings endpoint only ever
    exposes each symbol's MOST RECENT ~5-6 quarters as of whenever it's
    fetched (no historical archive), so qdf itself only ever contains
    recent quarters -- for any backtest `date` more than ~1.5 years before
    the fetch, every row's known_as_of will be AFTER cutoff and this
    correctly returns empty (no quarterly pillar that far back), not a
    bug -- there is no way to see what NSE's feed would have shown on an
    old date via this endpoint.
    """
    if qdf is None or qdf.empty:
        return qdf if qdf is not None else pd.DataFrame()
    cutoff = pd.Timestamp(date).normalize()
    mask = qdf["known_as_of"].notna() & (
        pd.to_datetime(qdf["known_as_of"]).dt.normalize() <= cutoff
    )
    return qdf[mask].sort_values("qe_dt").reset_index(drop=True)


def _bucket(value: float | None, thresholds: list[tuple[float, int]]) -> int | None:
    """thresholds: [(min_value, score), ...] sorted descending by min_value.
    Returns the score for the first threshold value is >= to."""
    if value is None:
        return None
    for min_val, score in thresholds:
        if value >= min_val:
            return score
    return 0


def _aggregate_pillars(
    sub_scores: dict[str, int | None], pillars: dict[str, list[str]]
) -> tuple[dict, list, float | None]:
    """Average sub-scores (0-5) within each pillar, drop pillars with zero
    available sub-metrics rather than defaulting them, and weight the total
    /100 only over pillars that actually have data — shared by value_score,
    bank_score, nbfc_score so 'missing data lowers confidence, not the score
    itself' behaves identically across all three rubrics."""
    pillar_scores, missing = {}, []
    for pillar, keys in pillars.items():
        vals = [sub_scores[k] for k in keys if sub_scores.get(k) is not None]
        if vals:
            pillar_scores[pillar] = sum(vals) / len(vals)
        else:
            missing.append(pillar)
    total = (
        round(sum(pillar_scores.values()) / (5 * len(pillar_scores)) * 100, 1)
        if pillar_scores
        else None
    )
    return pillar_scores, missing, total


# Quarterly-momentum sub-metric thresholds -- deliberately NOT the same
# scale as the annual pat_yoy/premium_yoy buckets elsewhere in this file.
# A single quarter is structurally noisier than a full audited year (base
# effects, one-off items in the year-ago quarter, no audit requirement),
# so this grades in gradual steps through mild decline instead of that
# scale's cliff (any decline at all -> flat 0/5) -- verified against a
# real local A/B: the annual-style cliff scored a mild -6% quarterly PAT
# dip identically to a genuine -69% collapse, costing an otherwise
# fully-scored, 3-year-strong stock (RECLTD) ~20 points and 100+ ranks
# for one soft quarter. Only a >35% YoY collapse still scores 0 here.
_QUARTERLY_THRESHOLDS = ((20, 5), (10, 4), (0, 3), (-15, 2), (-35, 1))

# The quarterly pillar counts for HALF an annual pillar's weight in the
# aggregate (see add_quarterly_pillar) -- same reasoning: noisier, not
# fully audited, shouldn't move the total as much as a full year's data.
QUARTERLY_PILLAR_WEIGHT = 0.5


def quarterly_momentum_pillar(qdf: pd.DataFrame | None) -> tuple[dict, dict]:
    """The quarterly-freshness counterpart to the annual growth pillars
    elsewhere in this file -- same-quarter-one-year-ago comparison (index
    -1 vs -5 in an already as-of-filtered/sorted qdf, e.g. from
    quarterly_financials() or quarterly_asof()), NOT naive quarter-over-
    quarter, which would be dominated by seasonality for most businesses
    (same technique earnings_quality() already uses for its own pat_yoy).

    pat_yoy_q works for every rubric ('pat' is tagged everywhere).
    revenue_yoy_q only populates for the 'general' rubric -- banks/NBFCs/
    insurers don't tag a 'revenue' concept at all (see quarterly_
    financials()'s own docstring).

    Needs >=5 quarters to compute either metric (same >=5 guard as
    earnings_quality(), calibrated against the real ~5-quarter ceiling
    most F&O symbols hit on NSE's primary endpoint). Returns
    (sub_scores, extra_facts) -- extra_facts carries the raw pct figures
    and which quarter this is 'as of', for display/debugging, same shape
    as the annual scorers' own *_pct extra fields.
    """
    if qdf is None or qdf.empty or len(qdf) < 5:
        return (
            {"pat_yoy_q": None, "revenue_yoy_q": None},
            {"quarters_available": 0 if qdf is None or qdf.empty else len(qdf)},
        )

    d = qdf.sort_values("qe_dt").reset_index(drop=True)
    cur_pat, prior_pat = d["pat"].iloc[-1], d["pat"].iloc[-5]
    pat_yoy_q = None
    if pd.notna(cur_pat) and pd.notna(prior_pat) and prior_pat > 0:
        pat_yoy_q = (cur_pat / prior_pat - 1) * 100

    rev_yoy_q = None
    if "revenue" in d.columns:
        cur_rev, prior_rev = d["revenue"].iloc[-1], d["revenue"].iloc[-5]
        if pd.notna(cur_rev) and pd.notna(prior_rev) and prior_rev > 0:
            rev_yoy_q = (cur_rev / prior_rev - 1) * 100

    sub_scores = {
        "pat_yoy_q": _bucket(pat_yoy_q, _QUARTERLY_THRESHOLDS),
        "revenue_yoy_q": _bucket(rev_yoy_q, _QUARTERLY_THRESHOLDS)
        if rev_yoy_q is not None
        else None,
    }
    extra = {
        "pat_yoy_q_pct": pat_yoy_q,
        "revenue_yoy_q_pct": rev_yoy_q,
        "quarters_available": len(d),
        "latest_quarter": d["qe_date"].iloc[-1],
    }
    return sub_scores, extra


def add_quarterly_pillar(
    score: dict, q_sub: dict, q_extra: dict | None = None, weight: float = QUARTERLY_PILLAR_WEIGHT
) -> dict:
    """Folds quarterly_momentum_pillar()'s sub_scores into an already-
    computed rubric score dict (value_score/bank_score/nbfc_score/
    general_insurance_score/life_insurance_score's return value),
    weighted at `weight` relative to the annual pillars already inside
    it (each counted at 1.0) -- reusing the ORIGINAL pillar_scores as-is
    rather than re-deriving each rubric's private pillar->keys mapping.

    Returns a NEW dict (doesn't mutate `score`) with pillar_scores/
    sub_scores/missing_pillars/total_score all updated to include the
    quarterly pillar, plus a fresh 'quarterly_momentum_pct' extra field.
    A symbol with no computable quarterly pillar (empty q_sub) is
    returned with 'quarterly_momentum' appended to missing_pillars,
    total_score unchanged from the annual-only figure -- exactly the
    existing 'missing data lowers confidence, not the score' philosophy,
    just extended to this new pillar.

    q_extra (quarterly_momentum_pillar()'s own extra dict): when it has a
    resolvable 'latest_quarter', that's copied onto the output as
    'quarterly_as_of' -- 'fiscal_year_end' stays the ANNUAL filing's own
    period end (unchanged meaning, don't conflate the two), but without
    this a symbol whose score just moved from a fresher quarter would
    show the SAME 'As of' date as one that didn't move at all, with no
    visible reason why the numbers differ.
    """
    out = dict(score)
    q_vals = [v for v in q_sub.values() if v is not None]
    pillar_scores = dict(score.get("pillar_scores") or {})
    missing = list(score.get("missing_pillars") or [])
    sub_scores = dict(score.get("sub_scores") or {})
    sub_scores.update(q_sub)

    weighted_sum = sum(pillar_scores.values())
    weight_total = float(len(pillar_scores))
    if q_vals:
        q_pillar_score = sum(q_vals) / len(q_vals)
        pillar_scores["quarterly_momentum"] = q_pillar_score
        weighted_sum += weight * q_pillar_score
        weight_total += weight
        out["quarterly_as_of"] = (q_extra or {}).get("latest_quarter")
    else:
        missing = missing + ["quarterly_momentum"]

    total = (
        round(weighted_sum / (5 * weight_total) * 100, 1)
        if weight_total
        else score.get("total_score")
    )

    out["pillar_scores"] = {k: round(v, 2) for k, v in pillar_scores.items()}
    out["sub_scores"] = sub_scores
    out["missing_pillars"] = missing
    out["total_score"] = total
    return out


def value_score(bs_years: list[dict], market_price: float | None = None) -> dict:
    """0-100 weighted fundamental score from primary XBRL data — no LLM, no
    scraping. Three pillars (0-5 each, equally weighted):
      Profitability:    ROE, net margin, FCF YoY growth
      Financial Health: Debt-to-Equity, Current Ratio
      Growth/Valuation: Revenue CAGR, PEG (needs market_price)
    Balance-sheet ratios only refresh once a year (audited filings only).
    Missing sub-metrics are dropped rather than defaulted, and pillars with
    zero available sub-metrics are excluded from the total (reported in
    'missing') rather than silently scored as neutral.
    """
    latest = bs_years[0] if bs_years else {}
    prior = bs_years[1] if len(bs_years) > 1 else {}
    oldest = bs_years[-1] if len(bs_years) > 2 else None

    sub_scores: dict[str, int | None] = {}

    sub_scores["roe"] = _bucket(latest.get("roe"), [(20, 5), (15, 4), (10, 3), (5, 2), (0, 1)])
    sub_scores["net_margin"] = _bucket(latest.get("net_margin"), [(15, 5), (10, 4), (5, 3), (0, 2)])
    fcf_yoy = None
    if latest.get("fcf") is not None and prior.get("fcf"):
        fcf_yoy = (latest["fcf"] / prior["fcf"] - 1) * 100 if prior["fcf"] > 0 else None
    sub_scores["fcf_yoy"] = _bucket(fcf_yoy, [(15, 5), (5, 4), (0, 3), (-10, 2)])

    sub_scores["debt_to_equity"] = _bucket(
        -latest["debt_to_equity"] if latest.get("debt_to_equity") is not None else None,
        [(-0.3, 5), (-0.6, 4), (-1.0, 3), (-2.0, 2)],
    )  # lower D/E is better -> negate
    sub_scores["current_ratio"] = _bucket(
        latest.get("current_ratio"), [(2.0, 5), (1.5, 4), (1.2, 3), (1.0, 2)]
    )

    rev_cagr = None
    if oldest and oldest.get("revenue") and latest.get("revenue"):
        years = len(bs_years) - 1
        if years > 0 and oldest["revenue"] > 0:
            rev_cagr = ((latest["revenue"] / oldest["revenue"]) ** (1 / years) - 1) * 100
    elif prior.get("revenue") and latest.get("revenue") and prior["revenue"] > 0:
        rev_cagr = (latest["revenue"] / prior["revenue"] - 1) * 100  # YoY fallback
    sub_scores["revenue_cagr"] = _bucket(rev_cagr, [(15, 5), (10, 4), (5, 3), (0, 2)])

    peg = None
    if market_price and latest.get("eps_basic") and rev_cagr and rev_cagr > 0:
        pe = market_price / latest["eps_basic"] if latest["eps_basic"] > 0 else None
        if pe and pe > 0:
            peg = pe / rev_cagr
    sub_scores["peg"] = _bucket(
        -peg if peg is not None else None, [(-1.0, 5), (-1.5, 4), (-2.0, 3), (-3.0, 2)]
    )

    pillars = {
        "profitability": ["roe", "net_margin", "fcf_yoy"],
        "financial_health": ["debt_to_equity", "current_ratio"],
        "growth_valuation": ["revenue_cagr", "peg"],
    }
    pillar_scores, missing, total = _aggregate_pillars(sub_scores, pillars)

    return {
        "total_score": total,
        "rubric": "general",
        "pillar_scores": {k: round(v, 2) for k, v in pillar_scores.items()},
        "sub_scores": sub_scores,
        "missing_pillars": missing,
        "roe": latest.get("roe"),
        "debt_to_equity": latest.get("debt_to_equity"),
        "current_ratio": latest.get("current_ratio"),
        "fcf": latest.get("fcf"),
        "fcf_yoy_pct": fcf_yoy,
        "revenue_cagr_pct": rev_cagr,
        "peg": peg,
        "fiscal_year_end": latest.get("qe_date"),
    }


def bank_score(bs_years: list[dict]) -> dict:
    """0-100 weighted score for banks, using the BANKING XBRL taxonomy
    (verified against a real AXISBANK filing — banks don't tag Equity,
    Revenue, or CurrentAssets/Liabilities at all, so value_score() cannot be
    reused for them). Three pillars, 0-5 each:
      Profitability:  ROE, ROA, NIM (proxy: net interest income / advances)
      Asset Quality:  Gross NPA%, Net NPA% (lower is better)
      Growth:         Advances YoY, PAT YoY
    No CASA or capital-adequacy tag exists in this taxonomy — checked, not
    attempted here rather than approximated.
    """
    latest = bs_years[0] if bs_years else {}
    prior = bs_years[1] if len(bs_years) > 1 else {}

    sub_scores: dict[str, int | None] = {}
    sub_scores["roe"] = _bucket(latest.get("roe"), [(18, 5), (15, 4), (12, 3), (8, 2), (0, 1)])
    sub_scores["roa"] = _bucket(latest.get("roa"), [(1.5, 5), (1.2, 4), (1.0, 3), (0.7, 2)])
    sub_scores["nim"] = _bucket(
        latest.get("nim_proxy_pct"), [(4.0, 5), (3.5, 4), (3.0, 3), (2.5, 2)]
    )

    sub_scores["gross_npa"] = _bucket(
        -latest["gross_npa_pct"] if latest.get("gross_npa_pct") is not None else None,
        [(-1.0, 5), (-2.0, 4), (-3.0, 3), (-5.0, 2)],
    )
    sub_scores["net_npa"] = _bucket(
        -latest["net_npa_pct"] if latest.get("net_npa_pct") is not None else None,
        [(-0.3, 5), (-0.6, 4), (-1.0, 3), (-2.0, 2)],
    )

    adv_yoy = None
    if latest.get("advances") and prior.get("advances") and prior["advances"] > 0:
        adv_yoy = (latest["advances"] / prior["advances"] - 1) * 100
    sub_scores["advances_yoy"] = _bucket(adv_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])
    pat_yoy = None
    if latest.get("pat") and prior.get("pat") and prior["pat"] > 0:
        pat_yoy = (latest["pat"] / prior["pat"] - 1) * 100
    sub_scores["pat_yoy"] = _bucket(pat_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])

    pillars = {
        "profitability": ["roe", "roa", "nim"],
        "asset_quality": ["gross_npa", "net_npa"],
        "growth": ["advances_yoy", "pat_yoy"],
    }
    pillar_scores, missing, total = _aggregate_pillars(sub_scores, pillars)

    return {
        "total_score": total,
        "rubric": "banking",
        "pillar_scores": {k: round(v, 2) for k, v in pillar_scores.items()},
        "sub_scores": sub_scores,
        "missing_pillars": missing,
        "roe": latest.get("roe"),
        "roa": latest.get("roa"),
        "nim_proxy_pct": latest.get("nim_proxy_pct"),
        "gross_npa_pct": latest.get("gross_npa_pct"),
        "net_npa_pct": latest.get("net_npa_pct"),
        "advances_yoy_pct": adv_yoy,
        "pat_yoy_pct": pat_yoy,
        "fiscal_year_end": latest.get("qe_date"),
    }


def nbfc_score(bs_years: list[dict]) -> dict:
    """0-100 weighted score for NBFCs (also covers AMCs, per NSE's own
    filing classification), using the NBFC_INDAS XBRL taxonomy (verified
    against a real MUTHOOTFIN filing). Three pillars, 0-5 each:
      Profitability: ROE, ROA
      Leverage:      Debt-to-Equity (NBFCs run 3-6x by design — thresholds
                     reflect that, unlike value_score's manufacturing-company
                     thresholds which would flag every healthy NBFC as
                     over-levered)
      Growth:        Loan book YoY, PAT YoY
    The company-tagged DebtEquityRatio fact is NOT used — cross-checked
    against Borrowings/Equity on real data and they disagreed by ~80x; see
    parse_xbrl for detail. Derived Borrowings/Equity is used instead.
    """
    latest = bs_years[0] if bs_years else {}
    prior = bs_years[1] if len(bs_years) > 1 else {}

    sub_scores: dict[str, int | None] = {}
    sub_scores["roe"] = _bucket(latest.get("roe"), [(20, 5), (15, 4), (10, 3), (5, 2), (0, 1)])
    sub_scores["roa"] = _bucket(latest.get("roa"), [(3.0, 5), (2.0, 4), (1.5, 3), (1.0, 2)])

    sub_scores["debt_to_equity"] = _bucket(
        -latest["debt_to_equity"] if latest.get("debt_to_equity") is not None else None,
        [(-3.0, 5), (-4.5, 4), (-6.0, 3), (-8.0, 2)],
    )

    loan_yoy = None
    if latest.get("loans") and prior.get("loans") and prior["loans"] > 0:
        loan_yoy = (latest["loans"] / prior["loans"] - 1) * 100
    sub_scores["loan_yoy"] = _bucket(loan_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])
    pat_yoy = None
    if latest.get("pat") and prior.get("pat") and prior["pat"] > 0:
        pat_yoy = (latest["pat"] / prior["pat"] - 1) * 100
    sub_scores["pat_yoy"] = _bucket(pat_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])

    pillars = {
        "profitability": ["roe", "roa"],
        "leverage": ["debt_to_equity"],
        "growth": ["loan_yoy", "pat_yoy"],
    }
    pillar_scores, missing, total = _aggregate_pillars(sub_scores, pillars)

    return {
        "total_score": total,
        "rubric": "nbfc",
        "pillar_scores": {k: round(v, 2) for k, v in pillar_scores.items()},
        "sub_scores": sub_scores,
        "missing_pillars": missing,
        "roe": latest.get("roe"),
        "roa": latest.get("roa"),
        "debt_to_equity": latest.get("debt_to_equity"),
        "loan_yoy_pct": loan_yoy,
        "pat_yoy_pct": pat_yoy,
        "fiscal_year_end": latest.get("qe_date"),
    }


def general_insurance_score(bs_years: list[dict]) -> dict:
    """0-100 weighted score for general (non-life) insurers, using the GI
    XBRL taxonomy (verified against a real ICICIGI filing). Three pillars:
      Profitability: ROE, ROA
      Underwriting:  Combined Ratio, Incurred Claim Ratio (lower is better —
                     a combined ratio under 100% means underwriting profit)
      Growth:        Gross Premium YoY, PAT YoY
    Solvency Ratio is deliberately NOT scored despite being directly tagged:
    the raw value, scaled the same way as combined/claim ratio, comes out to
    2.67% on a real filing — implausible (IRDAI's minimum is 150%) — and
    there was no independent figure to cross-check it against the way
    debt_to_equity was. Reported as a diagnostic field only.
    """
    latest = bs_years[0] if bs_years else {}
    prior = bs_years[1] if len(bs_years) > 1 else {}

    sub_scores: dict[str, int | None] = {}
    sub_scores["roe"] = _bucket(latest.get("roe"), [(18, 5), (15, 4), (12, 3), (8, 2), (0, 1)])
    sub_scores["roa"] = _bucket(latest.get("roa"), [(3.0, 5), (2.0, 4), (1.5, 3), (1.0, 2)])

    sub_scores["combined_ratio"] = _bucket(
        -latest["combined_ratio"] if latest.get("combined_ratio") is not None else None,
        [(-95.0, 5), (-100.0, 4), (-105.0, 3), (-110.0, 2)],
    )  # lower is better
    sub_scores["incurred_claim_ratio"] = _bucket(
        -latest["incurred_claim_ratio"] if latest.get("incurred_claim_ratio") is not None else None,
        [(-60.0, 5), (-70.0, 4), (-80.0, 3), (-90.0, 2)],
    )  # lower is better

    premium_yoy = None
    if latest.get("gross_premium") and prior.get("gross_premium") and prior["gross_premium"] > 0:
        premium_yoy = (latest["gross_premium"] / prior["gross_premium"] - 1) * 100
    sub_scores["premium_yoy"] = _bucket(premium_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])
    pat_yoy = None
    if latest.get("pat") and prior.get("pat") and prior["pat"] > 0:
        pat_yoy = (latest["pat"] / prior["pat"] - 1) * 100
    sub_scores["pat_yoy"] = _bucket(pat_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])

    pillars = {
        "profitability": ["roe", "roa"],
        "underwriting": ["combined_ratio", "incurred_claim_ratio"],
        "growth": ["premium_yoy", "pat_yoy"],
    }
    pillar_scores, missing, total = _aggregate_pillars(sub_scores, pillars)

    return {
        "total_score": total,
        "rubric": "general_insurance",
        "pillar_scores": {k: round(v, 2) for k, v in pillar_scores.items()},
        "sub_scores": sub_scores,
        "missing_pillars": missing,
        "roe": latest.get("roe"),
        "roa": latest.get("roa"),
        "combined_ratio_pct": latest.get("combined_ratio"),
        "incurred_claim_ratio_pct": latest.get("incurred_claim_ratio"),
        "premium_yoy_pct": premium_yoy,
        "pat_yoy_pct": pat_yoy,
        "solvency_ratio_UNVERIFIED": latest.get("solvency_ratio"),
        "fiscal_year_end": latest.get("qe_date"),
    }


def life_insurance_score(bs_years: list[dict]) -> dict:
    """0-100 weighted score for life insurers, using the LI XBRL taxonomy
    (verified against a real SBILIFE filing). Two pillars:
      Profitability: ROE
      Growth:        Net Premium YoY, PAT YoY
    Two metrics directly tagged in this taxonomy are deliberately NOT
    scored: 13th-month persistency (the industry's headline quality metric)
    scales to an implausible 0.88% on a real filing (real range is
    70-90%+), and Solvency Ratio scales to an implausible 2.67% (IRDAI's
    minimum is 150%). Neither had an independent figure to cross-check
    against the way debt_to_equity did — both reported as diagnostic fields
    only rather than guessed at. This leaves profitability thin (ROE alone)
    until their true scale/meaning is established.
    """
    latest = bs_years[0] if bs_years else {}
    prior = bs_years[1] if len(bs_years) > 1 else {}

    sub_scores: dict[str, int | None] = {}
    sub_scores["roe"] = _bucket(latest.get("roe"), [(18, 5), (15, 4), (12, 3), (8, 2), (0, 1)])

    premium_yoy = None
    if latest.get("net_premium") and prior.get("net_premium") and prior["net_premium"] > 0:
        premium_yoy = (latest["net_premium"] / prior["net_premium"] - 1) * 100
    sub_scores["premium_yoy"] = _bucket(premium_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])
    pat_yoy = None
    if latest.get("pat") and prior.get("pat") and prior["pat"] > 0:
        pat_yoy = (latest["pat"] / prior["pat"] - 1) * 100
    sub_scores["pat_yoy"] = _bucket(pat_yoy, [(15, 5), (10, 4), (5, 3), (0, 2)])

    pillars = {
        "profitability": ["roe"],
        "growth": ["premium_yoy", "pat_yoy"],
    }
    pillar_scores, missing, total = _aggregate_pillars(sub_scores, pillars)

    return {
        "total_score": total,
        "rubric": "life_insurance",
        "pillar_scores": {k: round(v, 2) for k, v in pillar_scores.items()},
        "sub_scores": sub_scores,
        "missing_pillars": missing,
        "roe": latest.get("roe"),
        "premium_yoy_pct": premium_yoy,
        "pat_yoy_pct": pat_yoy,
        "solvency_ratio_UNVERIFIED": latest.get("solvency_ratio"),
        "persistency_13m_UNVERIFIED": latest.get("persistency_13m_pct"),
        "fiscal_year_end": latest.get("qe_date"),
    }


if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "HCLTECH"
    df = quarterly_financials(sym)
    if df.empty:
        print(f"No parseable XBRL for {sym}")
    else:
        cols = [
            c
            for c in [
                "qe_date",
                "revenue",
                "ebitda_margin",
                "pat",
                "net_margin",
                "eps_basic",
                "audited",
            ]
            if c in df
        ]
        print(df[cols].to_string(index=False))
        print("\nEarnings quality:", earnings_quality(df))

    bs = annual_balance_sheet(sym)
    print(f"\nAnnual filings parsed: {[b.get('qe_date') for b in bs]}")
    print("Value score:", value_score(bs))
