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


# -*- coding: utf-8 -*-
"""OFFLINE re-parse of the NSE XBRL cache to add two point-in-time quarterly metrics the
net-profit builder never extracted: RevenueFromOperations and Operating Profit (EBITDA).

This is a RE-PARSE, not a re-fetch: every filing already lives in scripts/_xbrl_cache/
(downloaded by build_fundamentals.py). We walk those ~102k files, and from each financial
filing read — for the CURRENT 3-month quarter (context "OneD", and "FourD" for the other
basis in a combined filing) — the Schedule-III lines needed to reconstruct:

  Revenue          = RevenueFromOperations
  Operating Profit = ProfitBeforeExceptionalItemsAndTax + FinanceCosts
                     + DepreciationDepletionAndAmortisationExpense - OtherIncome
                   (= Revenue - operating expenses excl. interest & depreciation; i.e. EBITDA,
                      excluding other income — the basis Trendlyne/StockView call "Operating Profit")

Both XBRL taxonomies carry the same local names: in-bse-fin: (classic INDAS filings, ~2018-2024)
and in-capmkt: (Integrated-Filing, 2025+). The company SYMBOL and quarter-end live inside the file
(OneD context: NSESymbol identifier + endDate), so we can map a cache file -> (symbol, quarter)
with no network. PAT is also re-read so we can VALIDATE against fundamentals.json (npStd/npCon).

Banks/NBFCs (InterestEarned line, or BANKING/NBFC filing) are FLAGGED financial: their "revenue"
and "operating profit" aren't comparable to industrials, so the aggregator drops them from those
two medians (keeps them in PAT) — matching how Trendlyne reports the results-season figure.

Output: scripts/revop_fundamentals.json = { SYM: { "QE": [revStd, revCon, opStd, opCon,
        patStd, patCon, fin, ebitStd, ebitCon], ... } }  (values in Rs crore; null where the
        basis wasn't filed; fin = 1 if financial). LATEST filing wins per cell (revisions
        supersede provisional results; a descriptive median wants the finalised figure).

        ★ idx4/idx5 (patStd/patCon) are a PAT MIRROR, NOT the PAT store. Authority for net profit
        is sf_fundamentals.json (npStd idx1 / npCon idx3) — runbook §70. The mirror is filled only
        where an XBRL was parsed (2018+) or the 15-min upsert touched the row, so it is INCOMPLETE:
        2026-08-23 measured 83-169 Nifty-500 quarters/yr (2018-2022) present in sf_fundamentals and
        null here. The backtest engine never loads sf_revop; the Coverage Matrix's patStd/patCon
        read sf_fundamentals. NEVER measure PAT coverage, or render PAT, from these two slots.

Run:  python -X utf8 build_revop.py [--limit N] [--fresh]
Resumable: checkpoints to scripts/_revop_progress.json every 10k files.
"""
import concurrent.futures
import contextlib
import glob
import html
import json
import os
import re
import sys

import scale_fix

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_xbrl_cache")
OUT = os.path.join(HERE, "revop_fundamentals.json")
DOCS_OUT = os.path.join(os.path.dirname(HERE), "docs", "sf_revop.json")  # web copy the daily cron maintains
PROG = os.path.join(HERE, "_revop_progress.json")
FUND = os.path.join(HERE, "fundamentals.json")

# Go back as far as the cache supports (chart starts ~2019 -> needs 2018 as the year-ago base).
MIN_QE = 20180101
MAX_QE = 20261231

CR = 1e7  # rupees -> crore

# --- compiled regexes -------------------------------------------------------------------
RE_SYM = re.compile(r'<xbrli:identifier scheme="http://www\.nseindia\.com/NSESymbol">([^<]+)</xbrli:identifier>')
RE_SYM2 = re.compile(r'<in-(?:bse-fin|capmkt):Symbol contextRef="OneD"[^>]*>([^<]+)<')


# OneD / FourD context period (entity then period; DOTALL for pretty-printed INDAS)
def _ctx_period_re(cid):
    return re.compile(
        r'<xbrli:context id="' + cid + r'">.*?<xbrli:startDate>(\d{4}-\d{2}-\d{2})</xbrli:startDate>'
        r"<xbrli:endDate>(\d{4}-\d{2}-\d{2})</xbrli:endDate>",
        re.DOTALL,
    )


RE_ONED = _ctx_period_re("OneD")
RE_FOURD = _ctx_period_re("FourD")
RE_CTX = {"OneD": RE_ONED, "FourD": RE_FOURD}
# OLDER INDAS filings (pre ~2021) don't carry the period inside the <xbrli:context> block the way
# the newer ones do; instead they tag DateOf{Start,End}OfReportingPeriod per context. Read those.
RE_DATE = {
    c: {
        b: re.compile(r"DateOf" + b + r'OfReportingPeriod contextRef="' + c + r'"[^>]*>(\d{4}-\d{2}-\d{2})')
        for b in ("Start", "End")
    }
    for c in ("OneD", "FourD")
}
RE_NAT = {
    c: re.compile(r'NatureOfReportStandaloneConsolidated contextRef="' + c + r'">([^<]+)<') for c in ("OneD", "FourD")
}
RE_TS = re.compile(r"(\d{12,14})")


def ctx_period(xml, cid):
    """(startDate, endDate) for context cid — from the <xbrli:context> block (newer files) or the
    DateOf{Start,End}OfReportingPeriod tags (older files). None if neither is present."""
    m = RE_CTX[cid].search(xml)
    if m:
        return m.group(1), m.group(2)
    ms = RE_DATE[cid]["Start"].search(xml)
    me = RE_DATE[cid]["End"].search(xml)
    if ms and me:
        return ms.group(1), me.group(1)
    return None


TAGS = (
    "RevenueFromOperations",
    "OtherIncome",
    "FinanceCosts",
    "DepreciationDepletionAndAmortisationExpense",
    "ProfitBeforeExceptionalItemsAndTax",
    "ProfitBeforeTax",
    "ProfitLossForPeriod",
    "ProfitOrLossAttributableToOwnersOfParent",
    # bank / NBFC formats (Trendlyne-parity, 2026-07-10)
    "ProfitLossForThePeriod",  # banks tag PAT with 'The'
    "InterestEarned",  # bank operating revenue (TL's bank Revenue col)
    "OperatingProfitBeforeProvisionAndContingencies",  # bank pre-provision profit (TL's bank Op Profit)
    "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates",  # bank con bottom line
    "OtherRevenueFromOperations",  # NBFC: a COMPONENT INSIDE RevenueFromOperations (see orfo_other_income)
    # insurer formats (IRDAI, INTEGRATED_FILING_LI / _GI; Trendlyne-parity 2026-07-16)
    "NetPremiumIncome",  # LIFE: policyholders' net premium
    "IncomeFromInvestmentsNet",  # LIFE+GI: policyholders' investment income
    "InvestmentIncome",  # LIFE: shareholders' investment income
    "PolicyholdersAccountOtherIncome",  # LIFE: other income (excluded from rev AND op)
    "ShareholdersAccountOtherIncome",  # LIFE: other income (excluded from op)
    "ProfitLossAfterTaxAndExtraordinaryItems",  # LIFE: PAT
    "ProfitLossBeforeTax",  # LIFE: PBT (both accounts combined)
    "PremiumEarned",  # GI: net earned premium
    "ShareholdersAccountIncomeFromInvestments",  # GI: shareholders' investment income
    "OperatingExpenses",  # GI: total policyholders'-account expenses
    "NonOperatingExpense",  # GI: shareholders'-account net expense
    "ProfitOrLossBeforeTax",  # GI: PBT ('Or' variant)
    "ProfitLossAfterTax",
)  # GI: PAT
RE_TAG = {
    t: {
        c: re.compile(r"<in-(?:bse-fin|capmkt):" + t + r' contextRef="' + c + r'"[^>]*>([-0-9.eE+]+)<')
        for c in ("OneD", "FourD")
    }
    for t in TAGS
}


def days_between(s, e):
    import datetime

    a = datetime.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    b = datetime.date(int(e[:4]), int(e[5:7]), int(e[8:10]))
    return (b - a).days


def ctx_days(xml, cid):
    """Length in days of context `cid`'s period, or None when the file states no period."""
    p = ctx_period(xml, cid)
    return days_between(p[0], p[1]) if p else None


def is_quarter_ctx(xml, cid):
    """Is context `cid` a 3-MONTH period, i.e. safe to store as 'the quarter'?

    THE CUMULATIVE BUG (root-caused 2026-08-09). SEBI's Integrated Filing format, live since the
    2025-03-31 half-year, lets a company file its half-year with the SIX-MONTH figure in OneD --
    period 2025-04-01..2025-09-30, 182 days. `parse_file` has rejected that since the day it was
    written; `xbrl_revop` below was added the NEXT day (2026-07-01) as a copy of the same logic
    WITHOUT the check, and it is the function the daily updater actually calls. So 33 cells at
    2025-09-30 stored a year-to-date figure as the quarter -- UDS revC 1429.59, plus HBLENGINE,
    BELRISE, EDELWEISS, STYL, SHAH, PROSTARM and others. They were healed once through
    cumulative_heals.json while the parser was left alone, so the next half-year would repeat it.

    Measured over the 104,331-file cache: 100,217 OneD contexts are <=100 days and 871 are 101-195,
    the long ones occurring ONLY at half-year ends (2025-03-31, 2025-09-30, 2026-03-31). This is a
    half-year-end effect, not a Sep-2025 one, and it recurs every six months.

    Unknown counts as ACCEPT: ~1,220 cached filings (mostly pre-2024 BANKING/NONINDAS) carry OneD
    facts with no period stated at all, and rejecting those would delete real data.
    """
    d = ctx_days(xml, cid)
    return d is None or 0 < d <= 100


def fnum(xml, tag, ctx):
    m = RE_TAG[tag][ctx].search(xml)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


# --- NBFC "other revenue from operations" ------------------------------------------------
# Each component of that line hangs off DetailsOfOtherRevenueFromOperationsAxis in its OWN
# context, named after the parent basis context: OneD -> OneRevenue1D, OneRevenue2D, ...
# (FourD -> FourRevenue<n>D). Matching on the context NAME — not the period — keeps the two
# bases apart in a combined std+con filing, where OneD and FourD share the same dates.
RE_CTX_BLOCK = re.compile(r'<xbrli:context id="([^"]+)"[^>]*>(.*?)</xbrli:context>', re.DOTALL)
RE_ORFO_CID = {c: re.compile(r"^" + c[:-1] + r"Revenue\d+D$") for c in ("OneD", "FourD")}
ORFO_AXIS = "DetailsOfOtherRevenueFromOperationsAxis"


def _labelled_other_income(desc):
    """True only when the filer's own label for the component IS 'other income'.
    Deliberately strict: 'Other operating income' and 'Other financial charges' are REVENUE."""
    return " ".join(re.sub(r"[^a-z ]", " ", (desc or "").lower()).split()) in ("other income", "other incomes")


def orfo_other_income(xml, ctx):
    """Rupees of OtherRevenueFromOperations that the FILER ITSELF labels 'Other income'.

    OtherRevenueFromOperations is a COMPONENT INSIDE RevenueFromOperations, not an addition to
    it — every NBFC filing satisfies Income == RevenueFromOperations + OtherIncome with it
    already inside. So netting it off revenue wholesale DELETES real revenue (HDBFS Q1FY27's
    351.33 is 'Other financial charges', PIRAMALFIN's 99.61 is 'Other operating income').
    But some filers mis-slot their other income into that line and leave OtherIncome=0 — LTF's
    Q1FY27 CONSOLIDATED filing tags 30.39 labelled literally 'Other Income' while its own
    STANDALONE filing tags the same ~30cr as OtherIncome and keeps it out of revenue. Trendlyne
    reads the PDF and excludes exactly that case. So exclude only what the filer calls other
    income — mirroring the industrial rule, where op already nets OtherIncome off.
    (The old blanket subtraction was reverse-engineered from LTF alone and silently understated
    every other NBFC's revenue AND operating profit by the same amount — DATA_RUNBOOK §11.)"""
    if ORFO_AXIS not in xml:
        return 0.0
    tot = 0.0
    for cid, body in RE_CTX_BLOCK.findall(xml):
        if ORFO_AXIS not in body or not RE_ORFO_CID[ctx].match(cid):
            continue
        esc = re.escape(cid)
        mv = re.search(
            r'<in-(?:bse-fin|capmkt):OtherRevenueFromOperations contextRef="' + esc + r'"[^>]*>([-0-9.eE+]+)<', xml
        )
        md = re.search(
            r'<in-(?:bse-fin|capmkt):DescriptionOfOtherRevenueFromOperations contextRef="' + esc + r'"[^>]*>([^<]*)<',
            xml,
        )
        if mv and md and _labelled_other_income(md.group(1)):
            with contextlib.suppress(Exception):
                tot += float(mv.group(1))
    return tot


def lender_ebit_na_symbols():
    """Symbols adjudicated NO-EBIT (banks + screener-layout lenders), from the evidence ledger.

    User decision 2026-08-16 ("show nbfc and banks like screener do" + "go ahead with the sf_revop
    data alignment"): these filers carry no ebit in the DATA, not just on the coverage page. The
    ledger (scripts/coverage_na_ledger.json) holds per-name evidence; this reads its ebit keys and
    widens through FUND_ALIAS in both directions, since a renamed lender's history lives under its
    old key and old symbols still appear in era rosters. Absent ledger = empty set (fail open to
    UNCHANGED behaviour, never to hidden stripping)."""
    import re as _re

    out = set()
    try:
        led = json.load(open(os.path.join(HERE, "coverage_na_ledger.json")))
        base = {s for s in led.get("ebit", {}) if not s.startswith("_")}
        out |= base
        eng = open(os.path.join(os.path.dirname(HERE), "docs", "backtest-engine.js")).read()
        m = _re.search(r"FUND_ALIAS\s*=\s*(\{.*?\})\s*;", eng, _re.DOTALL)
        if m:
            alias = json.loads(_re.sub(r"(\w+)\s*:", r'"\1":', m.group(1)).replace("'", '"'))
            for s in base:
                if alias.get(s):
                    out.add(alias[s])
            for k, v in alias.items():
                if v in base:
                    out.add(k)
    except Exception as e:
        print(f"[lender-ebit guard] ledger unreadable ({e}) — stripping NOTHING")
    return out


LENDER_EBIT_NA = lender_ebit_na_symbols()


def strip_lender_ebit(sym, row9):
    """Null slots 7/8 (ebitStd/ebitCon) for adjudicated no-ebit filers. EVERY writer that computes
    an ebit must pass its row through this, or a rebuild/upsert resurrects what the 2026-08-16
    alignment removed (feedback-a-heal-that-reapplies / feedback-retraction-needs-every-ledger —
    a structural guard at the writers beats N ledger annotations)."""
    if sym in LENDER_EBIT_NA and len(row9) > 7:
        row9[7] = None
        if len(row9) > 8:
            row9[8] = None
    return row9


def metrics_for(xml, ctx):
    """Reconstruct (revenue_cr, op_cr, ebit_cr, pat_total_cr, pat_owners_cr) for one context.
    Returns rupee->crore values. Three formats (all Trendlyne-verified to the paisa, 2026-07-11):
      Industrial: op   = PBET + FinanceCosts + Depreciation - OtherIncome  (= Trendlyne 'Oper Profit',
                         matched per-stock to the paisa — NOT their 'EBIDT', which is a proprietary calc we
                         do NOT reproduce; see DATA_RUNBOOK §11);
                  ebit = op - Depreciation (after-depreciation operating profit).
      BANK (InterestEarned + OperatingProfitBeforeProvisionAndContingencies): rev = InterestEarned,
                  op = pre-provision operating profit (both = TL's bank columns), ebit = None;
                  owners = ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates —
                  the con P&L bottom row incl. associates (TL's Net Profit; the plain PAT tag
                  EXCLUDES RRB-associate share, MAHABANK Q1FY27 2020.54 vs 2023.32).
      NBFC Ind-AS (InterestEarned, no bank op tag): rev = RevenueFromOperations, op = PBET + FC + Dep - OI,
                  ebit = None — each MINUS only the OtherRevenueFromOperations components the filer itself
                  labels 'Other income' (see orfo_other_income; LTF con 5212.92 / 3238.64, HDBFS 4937.90 /
                  2863.20, PIRAMALFIN con 3368.27 / 2072.74 — all Trendlyne-exact)."""
    # LIFE INSURER (IRDAI 'LI' format, e.g. HDFCLIFE/ICICIPRULI/SBILIFE/LICI):
    #   rev = NetPremiumIncome + IncomeFromInvestmentsNet (policyholders) + InvestmentIncome
    #         (shareholders) — matches Trendlyne's 'Operating Revenue' to the paisa (HDFCLIFE
    #         Q1FY27 con 33758.51, std 33545.32; ICICIPRULI std 28512.71 — all verified exact).
    #   op  = ProfitLossBeforeTax − other income (both accounts). Trendlyne's insurer op is
    #         PBT − their 'Other Income' row; their OI/PBT come from the PDF and differ from the
    #         XBRL by small regroupings (HDFCLIFE std: TL 505.8 vs this 532.2), so op is CLOSE
    #         but not paisa-exact for life insurers — rev and PAT are exact.
    npi = fnum(xml, "NetPremiumIncome", ctx)
    if npi is not None:
        inv = fnum(xml, "IncomeFromInvestmentsNet", ctx) or 0.0
        shinv = fnum(xml, "InvestmentIncome", ctx) or 0.0
        rev = npi + inv + shinv
        pbt = fnum(xml, "ProfitLossBeforeTax", ctx)
        oi = (fnum(xml, "PolicyholdersAccountOtherIncome", ctx) or 0.0) + (
            fnum(xml, "ShareholdersAccountOtherIncome", ctx) or 0.0
        )
        op = (pbt - oi) if pbt is not None else None
        pat = fnum(xml, "ProfitLossAfterTaxAndExtraordinaryItems", ctx)
        return (rev / CR, op / CR if op is not None else None, None, pat / CR if pat is not None else None, None)
    # GENERAL INSURER (IRDAI 'GI' format, e.g. ICICIGI/GODIGIT/STARHEALTH/NIACL):
    #   rev = PremiumEarned + IncomeFromInvestmentsNet + ShareholdersAccountIncomeFromInvestments
    #   op  = rev − OperatingExpenses − NonOperatingExpense
    #   Both verified EXACT vs Trendlyne (ICICIGI Q1FY27: rev 7088.22, op 522.10).
    pe = fnum(xml, "PremiumEarned", ctx)
    if pe is not None:
        rev = (
            pe
            + (fnum(xml, "IncomeFromInvestmentsNet", ctx) or 0.0)
            + (fnum(xml, "ShareholdersAccountIncomeFromInvestments", ctx) or 0.0)
        )
        opexp = fnum(xml, "OperatingExpenses", ctx)
        nonop = fnum(xml, "NonOperatingExpense", ctx) or 0.0
        op = (rev - opexp - nonop) if opexp is not None else None
        pat = fnum(xml, "ProfitLossAfterTax", ctx)
        return (rev / CR, op / CR if op is not None else None, None, pat / CR if pat is not None else None, None)
    pat = fnum(xml, "ProfitLossForPeriod", ctx)
    if pat is None:
        pat = fnum(xml, "ProfitLossForThePeriod", ctx)  # banks tag with 'The'
    owners = fnum(xml, "ProfitOrLossAttributableToOwnersOfParent", ctx)
    if owners is None:
        owners = fnum(xml, "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates", ctx)
    ie = fnum(xml, "InterestEarned", ctx)
    bank_op = fnum(xml, "OperatingProfitBeforeProvisionAndContingencies", ctx)
    if ie is not None and bank_op is not None:  # bank format
        return (
            ie / CR,
            bank_op / CR,
            None,  # ebit not reproduced for banks
            pat / CR if pat is not None else None,
            owners / CR if owners is not None else None,
        )
    rev = fnum(xml, "RevenueFromOperations", ctx)
    oi = fnum(xml, "OtherIncome", ctx) or 0.0
    fc = fnum(xml, "FinanceCosts", ctx) or 0.0
    dep = fnum(xml, "DepreciationDepletionAndAmortisationExpense", ctx) or 0.0
    pbet = fnum(xml, "ProfitBeforeExceptionalItemsAndTax", ctx)
    if pbet is None:
        pbet = fnum(xml, "ProfitBeforeTax", ctx)
    if ie is not None:  # NBFC Ind-AS format
        oir = orfo_other_income(xml, ctx)  # only the part the filer labels 'Other income'
        nrev = (rev - oir) if rev is not None else None
        nop = (pbet + fc + dep - oi - oir) if pbet is not None else None
        return (
            nrev / CR if nrev is not None else None,
            nop / CR if nop is not None else None,
            None,  # ebit not reproduced for NBFCs
            pat / CR if pat is not None else None,
            owners / CR if owners is not None else None,
        )
    op = (pbet + fc + dep - oi) if (pbet is not None) else None
    ebit = (pbet + fc - oi) if (pbet is not None) else None
    return (
        rev / CR if rev is not None else None,
        op / CR if op is not None else None,
        ebit / CR if ebit is not None else None,
        pat / CR if pat is not None else None,
        owners / CR if owners is not None else None,
    )


def xbrl_revop(xml, basis_hint=None):
    """(rev_std, op_std, ebit_std, rev_con, op_con, ebit_con, fin) in Rs crore for the CURRENT quarter
    from ONE filing, mirroring build_fundamentals.xbrl_profit's OneD/FourD + NatureOfReport logic — so
    the daily incremental updater can read revenue + operating profit straight from the XBRL it already
    fetches for PAT, no disk cache needed.
      op   = PBET + FinanceCosts + Depreciation - OtherIncome  (= Trendlyne 'Oper Profit', paisa-matched;
             NOT their 'EBIDT' card, which is proprietary/irreproducible — see DATA_RUNBOOK §11)
      ebit = PBET + FinanceCosts - OtherIncome  (after depreciation)
    Banks/NBFCs (InterestEarned) keep fin=1 AND carry their own rev/op (bank: interest earned +
    pre-provision profit; NBFC: core revenue + operating profit — see metrics_for); ebit None for them.
    Consumers decide whether to mix them with industrials (Results Season only aggregates fin rev/op
    inside bank universes)."""
    nat = {}
    for m in re.finditer(r'NatureOfReportStandaloneConsolidated contextRef="([^"]+)"[^>]*>([^<]+)<', xml):
        nat[m.group(1)] = m.group(2).strip().lower()
    hint = (basis_hint or "").lower()
    fin = 1 if ("InterestEarned" in xml or "NetPremiumIncome" in xml or "PremiumEarned" in xml) else 0
    rev_std = op_std = ebit_std = rev_con = op_con = ebit_con = None
    one_nat = nat.get("OneD", "") or hint
    # Only read a context whose period IS a quarter -- a 182-day OneD is the half-year cumulative
    # and storing it as the quarter is the Sep-2025 bug (see is_quarter_ctx).
    if is_quarter_ctx(xml, "OneD"):
        rev, op, ebit, _, _ = metrics_for(xml, "OneD")
        if rev is not None or op is not None:
            if "consol" in one_nat:
                rev_con, op_con, ebit_con = rev, op, ebit
            else:
                rev_std, op_std, ebit_std = rev, op, ebit
    four_nat = nat.get("FourD", "")
    if four_nat and four_nat != one_nat and is_quarter_ctx(xml, "FourD"):
        rev, op, ebit, _, _ = metrics_for(xml, "FourD")  # combined filing: FourD is the OTHER basis
        if "consol" in four_nat and rev_con is None:
            rev_con, op_con, ebit_con = rev, op, ebit
        elif "consol" not in four_nat and rev_std is None:
            rev_std, op_std, ebit_std = rev, op, ebit

    def r2(x):
        return round(x, 2) if x is not None else None

    return r2(rev_std), r2(op_std), r2(ebit_std), r2(rev_con), r2(op_con), r2(ebit_con), fin


def ts_key(fname):
    m = RE_TS.search(fname)
    if not m:
        return fname
    d = m.group(1)
    if len(d) == 14:  # DDMMYYYYHHMMSS -> sortable YYYYMMDDHHMMSS
        return d[4:8] + d[2:4] + d[0:2] + d[8:]
    return d


def parse_file(path, fname):
    xml = open(path, encoding="utf-8", errors="replace").read()
    per = ctx_period(xml, "OneD")
    if not per:
        return None  # no current-quarter financial context (governance / balance-sheet-only)
    s, e = per
    if not (0 < days_between(s, e) <= 100):
        return None  # OneD must be the 3-month quarter, not an annual/YTD period
    qe = int(e.replace("-", ""))
    if qe < MIN_QE or qe > MAX_QE:
        return None
    sm = RE_SYM.search(xml) or RE_SYM2.search(xml)
    if not sm:
        return None
    # ★★★ XBRL IS XML, SO A FILER'S `&` ARRIVES ESCAPED (2026-08-26, runbook §115 — THE ROOT CAUSE).
    # This line is where the 13 phantom symbol keys were born. The regex captures raw element text,
    # so `<xbrli:identifier ...>J&amp;KBANK</xbrli:identifier>` yields `J&amp;KBANK`, and .upper()
    # turns it into `J&AMP;KBANK` — a ticker no exchange ever listed, given its own key in
    # sf_revop.json + revop_fundamentals.json, and from there into sf_fundamentals, the per-stock
    # slices and the discovery buckets. Only `&`-containing tickers are affected, which is exactly
    # why it hid for years. Proven against the cache: J&KBANK, S&SPOWER, GET&D, SURANAT&P all
    # capture escaped, and one of the hits is a 2026 filing — this was STILL producing phantoms.
    # unescape BEFORE upper(): `&amp;` -> `&` -> `M&M`. (Upper-first also happens to work because
    # HTML5 defines `&AMP;`, but relying on that is how the bug reads as harmless.)
    sym = html.unescape(sm.group(1)).strip().upper()
    fin = (
        1
        if (
            "InterestEarned" in xml
            or "NetPremiumIncome" in xml
            or "PremiumEarned" in xml
            or fname.startswith("BANKING")
            or "NBFC" in fname
            or "_LI_" in fname
            or "_GI_" in fname
        )
        else 0
    )

    one_nat = RE_NAT["OneD"].search(xml) or [None, ""]
    one_nat = one_nat.group(1).strip().lower() if hasattr(one_nat, "group") else ""
    # A few filers' XBRL is scaled by a power of ten — every monetary tag 10^k too big. The file
    # is wrong, not us, so re-parsing reproduces it; scale_fix.json is the reviewed ledger of
    # those filings and this is the one place the correction enters (DATA_RUNBOOK §11).
    sc = scale_fix.factor(fname)

    def _sc(t):
        return tuple(None if v is None else v / sc for v in t) if sc else t

    out = {"std": None, "con": None, "fin": fin, "qe": qe, "sym": sym, "ts": ts_key(fname)}
    rev, op, ebit, pat, owners = _sc(metrics_for(xml, "OneD"))
    one = {"rev": rev, "op": op, "ebit": ebit, "pat": pat, "owners": owners}
    if "consol" in one_nat:
        out["con"] = one
    else:
        out["std"] = one
    # combined filing: FourD is the OTHER basis, current quarter (only if a real 3-month quarter)
    pf = ctx_period(xml, "FourD")
    if pf and 0 < days_between(pf[0], pf[1]) <= 100:
        four_nat = RE_NAT["FourD"].search(xml)
        four_nat = four_nat.group(1).strip().lower() if four_nat else ""
        if four_nat and four_nat != one_nat:
            rev, op, ebit, pat, owners = _sc(metrics_for(xml, "FourD"))
            d = {"rev": rev, "op": op, "ebit": ebit, "pat": pat, "owners": owners}
            if "consol" in four_nat and out["con"] is None:
                out["con"] = d
            elif "consol" not in four_nat and out["std"] is None:
                out["std"] = d
    return out


def _worker(fname):
    try:
        return parse_file(os.path.join(CACHE, fname), fname)
    except Exception:
        return None


def main():
    args = sys.argv[1:]
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    fresh = "--fresh" in args

    files = sorted(os.listdir(CACHE), key=ts_key)  # ascending -> last (latest) write wins
    # pre-filter: a filing can only carry a quarter >= MIN_QE (2018-01) if it was FILED in 2018+.
    # ts_key is YYYYMMDDHHMMSS (or the filename when unparseable, which sorts > "2018" -> kept).
    files = [f for f in files if ts_key(f)[:4] >= "2018"]
    if limit:
        # sample across the whole set, biased to recent (where revenue matters), for validation
        files = files[-limit:]
    total = len(files)

    data = {}  # sym -> { qe(str) -> [revStd,revCon,opStd,opCon,patStd,patCon,fin,ebitStd,ebitCon] }
    #   op* = Trendlyne 'Oper Profit' (paisa-matched); ebit* = after-dep operating profit
    start_i = 0
    if not fresh and not limit and os.path.exists(PROG):
        try:
            p = json.load(open(PROG))
            data = json.load(open(OUT))
            start_i = p.get("done", 0)
            print("resuming from %d/%d" % (start_i, total))
        except Exception:
            data, start_i = {}, 0

    def cell(sym, qe):
        d = data.setdefault(sym, {})
        row = d.setdefault(str(qe), [None, None, None, None, None, None, 0, None, None])
        if len(row) < 9:  # pad legacy 7-element rows (resume/merge path)
            row += [None] * (9 - len(row))
        return row

    def put(row, idx, val):
        if val is not None:  # latest-filing-wins (files sorted asc -> last overwrites)
            row[idx] = round(val, 2)

    def accumulate(r):
        if not r:
            return
        row = cell(r["sym"], r["qe"])
        if r["fin"]:
            row[6] = 1
        if r["std"]:
            put(row, 0, r["std"]["rev"])
            put(row, 2, r["std"]["op"])
            put(row, 4, r["std"]["pat"])
            put(row, 7, r["std"]["ebit"])
        if r["con"]:
            put(row, 1, r["con"]["rev"])
            put(row, 3, r["con"]["op"])
            put(row, 8, r["con"]["ebit"])
            # consolidated PAT = owners-attributable (matches the backtest basis), else total.
            # Guard a mis-tagged owners=0 (real profit sits only in ProfitLossForPeriod) — same
            # guard as apply_owners_full.py: owners ~0 while total is material -> use total.
            ow, tot = r["con"]["owners"], r["con"]["pat"]
            con_pat = tot if (ow is None or (abs(ow) < 0.005 and tot is not None and abs(tot) > 2)) else ow
            put(row, 5, con_pat)
        strip_lender_ebit(r["sym"], row)  # adjudicated no-ebit filers — see the guard's docstring

    todo = files[start_i:]
    processed = 0
    if limit:  # validation runs: simple sequential
        for fname in todo:
            accumulate(_worker(fname))
            processed += 1
    else:  # full walk: process pool (order preserved -> latest-wins holds)
        workers = min(8, (os.cpu_count() or 4))
        print("parsing %d files with %d workers" % (len(todo), workers), flush=True)
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            for r in ex.map(_worker, todo, chunksize=64):
                accumulate(r)
                processed += 1
                if processed % 10000 == 0:
                    json.dump(data, open(OUT, "w"), separators=(",", ":"))
                    json.dump({"done": start_i + processed}, open(PROG, "w"))
                    print("  %d/%d files, %d symbols" % (start_i + processed, total, len(data)), flush=True)

    nbad = normalize_ebit(data)
    if nbad:
        print(
            "[ebit<=op guard] nulled %d impossible ebit slot(s) (ebit = op - depreciation, so "
            "ebit > op cannot occur; op and ebit had come from different filings)" % nbad
        )
    json.dump(data, open(OUT, "w"), separators=(",", ":"))
    if not limit:
        json.dump({"done": total}, open(PROG, "w"))
        json.dump(data, open(DOCS_OUT, "w"), separators=(",", ":"))  # web copy (daily cron maintains it)
    print("Wrote %s + %s: %d symbols, %d files processed" % (OUT, DOCS_OUT, len(data), processed))

    validate(data)


def normalize_ebit(data):
    """Null any ebit slot that exceeds its op slot. ebit is defined op - Depreciation (after-dep
    operating profit) and depreciation >= 0, so ebit > op is impossible by construction. It arises
    because op (slot 2/3) and ebit (slot 7/8) are filled latest-filing-wins INDEPENDENTLY, so a
    revised op can leave a stale ebit above it (audit 2026-09-01, 169 cells). The value is
    unreconstructable (we don't keep depreciation), so the provably-wrong ebit is dropped, not kept.
    Returns the number of slots nulled. Small epsilon so filer rounding (ebit == op to the paisa,
    zero depreciation) is not disturbed."""
    EPS = 0.01
    n = 0
    for qmap in data.values():
        if not isinstance(qmap, dict):
            continue
        for row in qmap.values():
            if not isinstance(row, list) or len(row) < 9:
                continue
            for op_i, eb_i in ((2, 7), (3, 8)):  # (opStd, ebitStd), (opCon, ebitCon)
                op, eb = row[op_i], row[eb_i]
                if op is not None and eb is not None and eb > op + EPS:
                    row[eb_i] = None
                    n += 1
    return n


def validate(data):
    """Compare re-parsed PAT against fundamentals.json npStd/npCon to confirm the file->(symbol,qe)
    mapping is correct."""
    try:
        fund = json.load(open(FUND))
    except Exception:
        print("(no fundamentals.json to validate against)")
        return
    ok = bad = 0
    examples = []
    for sym, rows in fund.items():
        dd = data.get(sym)
        if not dd:
            continue
        for r in rows:
            qe, npStd, npCon = r[0], r[1], r[3]
            cell = dd.get(str(qe))
            if not cell:
                continue
            for stored, idx, lbl in ((npStd, 4, "std"), (npCon, 5, "con")):
                got = cell[idx]
                if stored is None or got is None:
                    continue
                base = max(1.0, abs(stored))
                if abs(got - stored) / base <= 0.02:
                    ok += 1
                else:
                    bad += 1
                    if len(examples) < 12:
                        examples.append("%s %d %s: parsed %.2f vs stored %.2f" % (sym, qe, lbl, got, stored))
    tot = ok + bad
    print(
        "\nPAT validation vs fundamentals.json: %d/%d match within 2%% (%.1f%%), %d mismatches"
        % (ok, tot, 100.0 * ok / tot if tot else 0, bad)
    )
    for ex in examples:
        print("   MISMATCH", ex)


if __name__ == "__main__":
    main()
