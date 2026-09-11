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
"""Per-stock FII/DII holdings from NSE quarterly shareholding-pattern (SHP) filings.

Pipeline (DATA_RUNBOOK.md section 22):
  1. Master list per quarter-end: /api/corporate-share-holdings-master?index=equities
     &from_date=<QE>&to_date=<QE+180d, capped at today>. The window filters on the SUBMISSION
     date (it filtered on the as-on date until ~2026-08; see fetch_master), so we ask for the
     filing season and keep the rows whose as-on date is the quarter — ~2,300/qtr.
  2. Each filing carries an XBRL url (nsearchives) — parse the category percentage facts:
       promoter  = ShareholdingOfPromoterAndPromoterGroupMember
       public    = PublicShareholdingMember
       FII       = InstitutionsForeignMember      (FPI I+II, FDI, other foreign)
       DII       = InstitutionsDomesticMember     (MF, insurance, banks, PF, AIF, ...)
       MF        = MutualFundsOrUTIMember
       insurance = InsuranceCompaniesMember
     Values are pure fractions (0.1867 = 18.67%); anchored via the total/prom+pub ≈ 100 check.
     Only the NEW (post-2021) format has the Domestic/Foreign split — unparseable filings are
     skipped and logged, never guessed.
  3. Merge fill-or-newer-submission-wins into scripts/shp_history.json:
       {"_names": {SYM: co-name}, SYM: {"YYYY-MM-DD"(QE): [prom, fii, dii, mf, ins, "sub-date", nsh?]}}
     nsh = total number of shareholders (ShareholdingPatternMember context), appended only when
     the filing carries it — cells written before 2026-07-16 have 6 slots, readers index 0-5 + optional 6.
  4. Build docs/shareholding.json (slim page feed, aligned quarter arrays + mcap/sector join)
     and docs/shp_meta.json (tiny freshness marker committed every run, feeds.json watches it).
  5. Bank each filing's total share count in scripts/shares_outstanding.json — the ONLY free
     source of a market cap for companies NSE lists and BSE doesn't (see load_shares).

Runs:
  python -X utf8 scripts/fetch_shareholding.py                # daily top-up (last 3 QEs, new/revised only)
  python -X utf8 scripts/fetch_shareholding.py --backfill 4   # one-time deep fill (most-recent quarter first)
  python -X utf8 scripts/fetch_shareholding.py --backfill 4 --reparse  # re-fetch even unchanged filings (schema upgrades)
  python -X utf8 scripts/fetch_shareholding.py --quarters 2026-06-30 --fill-shares   # only symbols with no share count yet
  python -X utf8 scripts/fetch_shareholding.py --quarters 2026-06-30 --fill-shares --symbols E2E,BSE,CDSL
  python -X utf8 scripts/fetch_shareholding.py --feed-only    # rebuild docs feed from history, no network

Self-healing: a failed master call skips that quarter (history keeps yesterday's cells); XBRL
download/parse failures skip that company; the history write is add/update-only and ABORTs if
the merged file would lose cells. Resumable: flushes history every FLUSH_EVERY parses.
"""
import datetime
import gzip
import json
import os
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_fundamentals as B  # _get / nse_jar / UA (CI-proven NSE session)

HERE = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(HERE, "shp_history.json")
# Event-driven (mid-quarter) SHPs live in their OWN file, keyed by AS-ON date: shp_history.json is
# keyed by quarter-end and its consumers do calendar-quarter arithmetic (prev_qe, K-streaks), which
# a 14-Feb row would silently corrupt. Same row shape. Merged into the engine feed (§22k).
EVENTS = os.path.join(HERE, "shp_events.json")
OUT = os.path.join(HERE, "..", "docs", "shareholding.json")
META_OUT = os.path.join(HERE, "..", "docs", "shp_meta.json")
# Government holding sidecar {SYM: {QE: gov%}} — kept OUT of the shp_history cell so none of the
# cell merge/heal/backtest passes are touched. Joined into the per-stock slice by build_stock_fin.
GOV_OUT = os.path.join(HERE, "..", "docs", "shp_gov.json")
SLIM = os.path.join(HERE, "..", "docs", "dash_slim.bin")
CLASSIF = os.path.join(HERE, "..", "docs", "sector_classification.json")

TOPUP_QES = 3  # daily run: current season + 2 back (late filers / revisions)
FEED_QUARTERS = 8  # quarters shipped to the page
THREADS = 6  # parallel XBRL downloads (nsearchives is a static host)
FLUSH_EVERY = 150  # persist history every N new cells (resumable backfill)
MIN_FEED_ROWS = 500  # never overwrite a good feed with a near-empty one
MASTER_WINDOW_DAYS = 180  # submission-date window per quarter (see fetch_master)

REF = "https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern"
MON = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}

# XBRL category member -> output slot.
# NEW format (quarters >= 2022-09-30): explicit Institutions (Domestic) / (Foreign) split.
# OLD format (<= 2022-06-30): ONE InstitutionsMember bucket with per-type rows (values in
# PERCENT, not fractions) — FII = the Institutions FPI row (+FVCI), DII = the domestic rows.
# OtherInstitutionsMember assignment was CALIBRATED on the Jun→Sep-2022 seam (see runbook §22).
MEMBERS = {
    "ShareholdingOfPromoterAndPromoterGroupMember": "prom",
    "PublicShareholdingMember": "pub",
    "InstitutionsForeignMember": "fii",
    "InstitutionsDomesticMember": "dii",
    "MutualFundsOrUTIMember": "mf",
    "InsuranceCompaniesMember": "ins",
    "ShareholdingPatternMember": "total",
    # old-format members (collected when present; combined in parse_shp)
    "InstitutionsMember": "o_inst",
    "InstitutionsForeignPortfolioInvestorMember": "o_fpi",
    "ForeignVentureCapitalInvestorsMember": "o_fvci",
    "MutualFundsOrUtiMember": "o_mf",  # note Uti vs UTI casing difference
    "AlternativeInvestmentFundsMember": "o_aif",
    "VentureCapitalFundsMember": "o_vcf",
    "FinancialInstitutionOrBanksMember": "o_bank",
    "ProvidentFundsOrPensionFundsMember": "o_pf",
    "OtherInstitutionsMember": "o_other",
    # non-promoter-non-public bucket (employee benefit trusts / DR custodians) — sits OUTSIDE
    # "public" in the SEBI partition. Needed so no-promoter companies with a big ESOP trust
    # (ETERNAL 4.73%, SWIGGY, ...) pass the partition sanity instead of being skipped.
    "SharesHeldByNonPromoterNonPublicShareholdersMember": "npnp",
    "EmployeeBenefitsTrustsMember": "trust",
    "SharesHeldByEmployeeTrustsMember": "trust",  # old-format name
    # A demutualised EXCHANGE puts its restricted trading-member shares in that same third bucket
    # and tags them with this name instead. BSE Ltd Jun-2025: pub 79.43 + this 20.57 = 100.00 exact,
    # and the SAME company tagged the SAME block "SharesHeldByNonPromoterNonPublic…" at Sep-2024 —
    # so it is the npnp bucket under another label, not a public sub-category. Parent row only: its
    # children (CorporateTradingMember, IndividualTradingMember, …) sum back to it and would double-count.
    "TradingMembersAndAssociatesOfTradingMembers": "npnp2",
    # Government (Central/State/President of India) — a PUBLIC sub-category, so it never enters the
    # promoter/public/npnp partition; captured only to surface Screener's separate "Government" row.
    # Real filings spell it four ways (incl. the "Goverments" typo). Written to a sidecar, NOT the cell.
    "CentralGovernmentOrStateGovernmentSOrPresidentOfIndiaMember": "gov",
    "CentralGovernmentOrStateGovernmentSMember": "gov",
    "GovernmentsMember": "gov",
    "GovermentsMember": "gov",
}


def _third(vals):
    """The SEBI partition's third bucket (neither promoter nor public), whichever label the filer
    used: employee trust, generic non-promoter-non-public, or an exchange's trading-member block.
    max() not sum() — filings tag the same shares under more than one of these."""
    return max(vals.get("npnp") or 0.0, vals.get("trust") or 0.0, vals.get("npnp2") or 0.0)


# Where does the old format's "Other institutions" row belong? True → DII, False → FII.
# Calibrated 2026-07-17 on the format-boundary seam (Jun-2022 old vs Sep-2022 new, all stocks).
OLD_OTHER_TO_DII = True


def iso_date(s):
    """'15-JUL-2026' / '15-Jul-2026 15:04:38' -> '2026-07-15' (None if unparseable)."""
    m = re.match(r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4})", str(s or ""))
    if not m:
        return None
    mo = MON.get(m.group(2).upper())
    return "%s-%02d-%02d" % (m.group(3), mo, int(m.group(1))) if mo else None


def last_qes(n, today=None):
    """The n most recent quarter-end dates on/before today, most recent first."""
    d = today or datetime.date.today()
    out = []
    y, m = d.year, ((d.month - 1) // 3) * 3  # last completed quarter's end month
    if m == 0:
        y, m = y - 1, 12
    for _ in range(n):
        day = {3: 31, 6: 30, 9: 30, 12: 31}[m]
        out.append(datetime.date(y, m, day).isoformat())
        m -= 3
        if m == 0:
            y, m = y - 1, 12
    return out


def load_hist():
    h = {"_names": {}}
    if os.path.exists(HIST):
        try:
            h = json.load(open(HIST, encoding="utf-8"))
        except Exception as e:
            print(f"WARN history unreadable ({e}) — starting empty")
    apply_cell_fix(h)  # §22g corrections reach EVERY reader (feed, engine feed), not just the fetch
    return h


def cells_of(h):
    return sum(len(v) for k, v in h.items() if not k.startswith("_") and isinstance(v, dict))


_flush_lock = threading.Lock()


def save_hist(h):
    with _flush_lock:
        tmp = HIST + ".tmp.%d" % os.getpid()  # pid-suffixed: concurrent runs must not steal each other's tmp
        json.dump(h, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        # Windows: os.replace fails (WinError 5) while ANY other process holds the target
        # open for reading (a builder/page-feed run loading the json). Retry briefly.
        for i in range(12):
            try:
                os.replace(tmp, HIST)
                return
            except PermissionError:
                time.sleep(1 + i)
        os.replace(tmp, HIST)  # last try — surface the error if it truly won't release


# ---- share-count ledger -----------------------------------------------------------------
# {SYM: [shares_outstanding, "QE", "sub-date"]} — newest quarter wins.
# Why a ledger and not a slot in shp_history: parse_shp REJECTS filings with no institutional
# rows (it can't distinguish "no institutions" from "old format", and zero-filling would poison
# FII/DII), yet those small NSE-only companies are precisely the ones with no market cap. The
# count is a separate fact, so it gets a separate file — and shp_history's cell shape, which
# four readers index positionally, stays untouched.
# Consumer: build_compressed.py, which turns shares x latest close into mcap for the ~105
# NSE-only symbols BSE's scrip master has no row for.
SHARES = os.path.join(HERE, "shares_outstanding.json")


def load_shares():
    if os.path.exists(SHARES):
        try:
            return json.load(open(SHARES, encoding="utf-8"))
        except Exception as e:
            print(f"WARN shares ledger unreadable ({e}) — starting empty")
    return {}


def save_shares(s):
    with _flush_lock:
        tmp = SHARES + ".tmp.%d" % os.getpid()
        json.dump(s, open(tmp, "w", encoding="utf-8"), separators=(",", ":"), sort_keys=True)
        for i in range(12):
            try:
                os.replace(tmp, SHARES)
                return
            except PermissionError:
                time.sleep(1 + i)
        os.replace(tmp, SHARES)


# Coverage campaign STEP 5: historical backfills from BSE, for the quarters the NSE master API
# (fetch_master, below) cannot reach. ⚠️ It reaches FURTHER than this comment used to claim: asked
# for a filing SEASON it serves full quarters back to 2021-09-30 (1,795 as-on rows), then falls off
# a cliff — 87 rows for 2021-06-30, 62 for 2021-03-31, ~35 for 2019-2020. The old "recent rolling
# window only" reading came from querying from=to=quarter-end back when the window filtered on the
# as-on date; measured 2026-08-07 (§22f). So NSE is the right route for anything from Sep-2021 on
# and BSE remains the only route before that.
# Ledgers, applied fill-only in ORDER (earlier ledgers win where quarters overlap), idempotent:
#   1. shp_fill_hist_2016_2019.json.gz — BSE SHPQNewFormat XBRL (fetch_shp_bse_hist.py). Real
#      per-filing dates. 2016-03..2019-06.
#   2. shp_fill_hist_2010_2016.json.gz — Wayback-archived Moneycontrol Clause-35 pages
#      (fetch_shp_wayback_mc.py). 2010-12..2016-03. ⚠ sub-dates are the QE+21d SEBI-deadline
#      CONVENTION (no real dates exist anywhere — BSE deleted them); each cell carries the
#      approx tag in the ledger's provenance slot, dropped on merge like the scripcode tag.
#   3. shp_fill_n500_gaps.json.gz — the 2026-08-07 sweep of every remaining point-in-time Nifty-500
#      hole from Jun-2016 on (fetch_shp_bse_hist.py, rebuilt). Real per-filing dates. FIRST in the
#      list so its real dates beat the MC ledger's QE+21d convention wherever both have a cell.
#   4. shp_fill_nse_gaps.json.gz — NSE-sourced holes for the NSE-ONLY cohort (BSE Ltd, CDSL) that
#      no BSE route can reach (fetch_shp_nse_gaps.py). Real per-filing dates.
#   5. shp_fill_thirdparty.json.gz — THIRD-PARTY values, not parsed by us. Only for filings that have
#      NO primary file anywhere (NSE lists them with a blank xbrl name). Every cell is tied to an
#      exchange-side number before it is written; provenance names the source. Keep this list SHORT.
#   6. shp_fill_bse_aspx.json.gz — BSE's OWN ShareholdingPattern.aspx (fetch_shp_bse_aspx.py,
#      §22f 2026-08-11): Clause-35 pages Jun-2006..Sep-2015 (Flag=New) + the 1997 format
#      Dec-2002..Mar-2006 (Flag=Old — ins is None there: it sits inside the Banks/FI/Insurance
#      lump and 0.0 would be fabricated). sub-dates are the QE+21d convention. LAST in the list:
#      every earlier ledger's cell (real dates, itemised ins) wins where both have a quarter.
BSE_HIST_LEDGERS = [
    os.path.join(HERE, "shp_fill_thirdparty.json.gz"),
    os.path.join(HERE, "shp_fill_nse_gaps.json.gz"),
    os.path.join(HERE, "shp_fill_n500_gaps.json.gz"),
    os.path.join(HERE, "shp_fill_hist_2016_2019.json.gz"),
    os.path.join(HERE, "shp_fill_hist_2010_2016.json.gz"),
    os.path.join(HERE, "shp_fill_bse_aspx.json.gz"),
    os.path.join(HERE, "shp_fill_seam_aspx.json.gz"),
    # PLAN_FAV14 P2 (2026-08-24): SHP-level fill for 3 delisted N500 members
    # (MVL/SHLAKSHMI/INNOIND) — BSE ShareholdingPattern.aspx, reconciled <0.15pp.
    # Fill-only like the rest; these symbols had NO prior SHP cell.
    os.path.join(HERE, "shp_fill_fav14.json.gz"),
    # WP-S1 (2026-09-05, PLAN_STDPAT_SHP_COVERAGE_2002 / runbook §127b): the SAME
    # ShareholdingPattern.aspx route, Flag=Old (1997 format), for the quarters the
    # frontier had floored out — Mar-2001..Sep-2002, N500 point-in-time members.
    # ins is None (inside the Banks/FI/Insurance lump); sub = QE+21d convention, so
    # build_engine_feed serves these rows UN-DATED (engine qe+28d fallback, §120).
    # Fill-only; no quarter here overlaps any earlier ledger (all < Dec-2002).
    os.path.join(HERE, "shp_fill_bse_aspx_2001.json.gz"),
    # WP-S2 (2026-09-05, PLAN_STDPAT_SHP_COVERAGE_2002 §5 / runbook §127f): the SAME
    # ShareholdingPattern.aspx route over the Dec-2002..Sep-2015 cells the 2026-08-11
    # frontier never requested (roster/rename drift since + the fiiChgPp PRIOR-quarter
    # roots that fall outside the point-in-time membership) plus era names resolved by
    # NSE's own archived pages (share-capital identity test, §127f). Flag=Old cells carry
    # ins=None (inside the lump); sub = QE+21d convention, so build_engine_feed serves
    # every row UN-DATED (engine qe+28d fallback, §120). Fill-only, LAST in the list.
    os.path.join(HERE, "shp_fill_wps2_aspx.json.gz"),
    # WP-S2 pass 2 (2026-09-05, runbook §127g): the same aspx route re-read with the four
    # parser fixes (header-less promoter block, lump-only 1997 pages, foreign-note proven
    # zero, Foreign MF / Foreign FI rows) over the residue + WP-S1 refusals, plus 9 era
    # names (2001-02) resolved via _shp_aspx_resolved_era_syms. Fill-only, LAST in the list;
    # 25 continuity-flagged cells are HELD in _shp_wps2b_holds.json, not here.
    os.path.join(HERE, "shp_fill_wps2b_aspx.json.gz"),
    # WP-S2 pass 2b (2026-09-05, runbook §127h): 47 `absent` cells that were absent only because
    # the symbol resolved to the wrong/later BSE code (IDEA scrip_id collision -> 532822; ELGIRUBBER /
    # OSWALGREEN / TVSELEC same-ISIN era listing codes). Same parser and gates as wps2b. Fill-only, LAST.
    os.path.join(HERE, "shp_fill_wps2c_aspx.json.gz"),
    # WP-S2 pass 3 (2026-09-05, runbook §127k): 14 era names resolved to BSE codes from the
    # ARCHIVED results index (2000-02 scripnames); 6 matched by page name, 8 accepted on lineage
    # (same listed entity, renamed) with entity-change cutoffs. Fill-only, LAST in the list.
    os.path.join(HERE, "shp_fill_wps2d_aspx.json.gz"),
    # WP-S2 pass 4 (2026-09-05, runbook §127j): continuity holds released after the neighbour re-parse
    # test (same page family, current parser). Fill-only, LAST in the list.
    os.path.join(HERE, "shp_fill_wps2e_aspx.json.gz"),
    # NSE's OWN archived full category-wise pattern (Wayback shareholdingdetails.jsp, 2002-06;
    # fetch_shp_nse_shpdetails.py, runbook §127k): the 1997 format from the exchange that listed the
    # companies BSE never carried. Overlap-gated against the BSE-derived cells (98.6% agree ≤0.11pp),
    # point-in-time N500 member quarters only, ins=None (lump), sub=QE+21d -> served UN-DATED (§120).
    # Fill-only, LAST: every BSE-derived cell wins where both hold a quarter.
    os.path.join(HERE, "shp_fill_nse_shpdetails.json.gz"),
]


def apply_bse_hist_ledger(h):
    n_total = 0
    for path in BSE_HIST_LEDGERS:
        if not os.path.exists(path):
            continue
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                fills = json.load(fh).get("fills", {})
        except Exception as e:
            print(f"{os.path.basename(path)} unreadable ({e}) — skipped")
            continue
        n = 0
        for sym, qs in fills.items():
            dest = h.setdefault(sym, {})
            for qe, cell in qs.items():
                if qe in dest:
                    continue  # fill-only — never overwrite an existing cell
                dest[qe] = (
                    cell[:7] if cell[6] is not None else cell[:6]
                )  # drop the ledger-only provenance tag (cell[7])
                n += 1
        if n:
            print("%s applied: %d cells" % (os.path.basename(path), n))
        n_total += n
    return n_total


# §22j PRECISION REFRESH ledger (scripts/fetch_shp_bse_hist.py --refine). Cells parsed before the
# share-count pass carry the filer's 2dp percentage; these are the SAME filings re-read so
# parse_shp recomputes them at 4dp. REFINE-ONLY: a cell is replaced only when the new value is
# the same number to within one 2dp step (_cell_eq / CELL_TOL). Anything that genuinely DISAGREES
# is a different document or a real defect — it is reported for human adjudication and never
# auto-applied, because "more precise" must never become a licence to overwrite a value a human
# already adjudicated. Runs AFTER the gap ledgers and BEFORE apply_cell_fix, which outranks it.
REFINE_LEDGER = os.path.join(HERE, "shp_refine_4dp.json.gz")
REFINE_REPORT = os.path.join(HERE, "_shp_refine_disagreements.json")


def apply_refine_ledger(h, path=None):
    path = path or REFINE_LEDGER
    if not os.path.exists(path):
        return 0
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            fills = json.load(fh).get("fills", {})
    except Exception as e:
        print(f"{os.path.basename(path)} unreadable ({e}) — skipped")
        return 0
    n = skip = 0
    bad = []
    for sym, qs in fills.items():
        dest = h.get(sym)
        if not isinstance(dest, dict):
            continue  # refine never CREATES a cell
        for qe, cell in qs.items():
            cur = dest.get(qe)
            if cur is None:
                continue
            # Compare ONLY the five holding percentages. `sub` and `nsh` describe WHICH DOCUMENT
            # was read, not the holding: BSE commonly serves a company's REVISION where NSE served
            # the original, so 73% of the first pass disagreed on `sub` alone while every value
            # matched. Refining those is safe and is the whole point; overwriting our provenance
            # with the other exchange's is not — so the numbers are taken and slots 5+ are KEPT.
            # A disagreement in any of the five is a different document or a real defect: reported,
            # never auto-applied.
            new = list(cell)
            # §22i SWALLOWED FOREIGN BLOCK — REFUSE, never apply. The BSE copy files the foreign
            # block under OtherInstitutionsMember and the OLD_OTHER_TO_DII calibration sweeps it
            # into dii, so the re-read comes back fii=0 with fii+dii PRESERVED. MANAPPURAM 2018-03:
            # stored 37.78/6.57, re-read 0.00/44.35 — same sum, FII zeroed across 8 quarters. The
            # stored value is the correct one; a "more precise" read is not a licence to zero a
            # real foreign holding. Measured 161 of 1,434 held-back cells.
            try:
                swallowed = new[1] == 0.0 and cur[1] > 0.0 and abs((cur[1] + cur[2]) - (new[1] + new[2])) <= 0.02
            except (TypeError, IndexError):
                swallowed = False
            # A swallowed block condemns fii and dii ONLY. The document is genuinely ambiguous
            # about those two — MANAPPURAM 2018-03 files OtherInstitutionsMember 37.78 with NO
            # ForeignPortfolioInvestor row at all, so nothing in it says which part is foreign;
            # the stored split came from NSE, whose archive no longer reaches 2018. But prom, mf
            # and ins are read from their OWN rows and are not affected by where the lump lands,
            # so they still gain precision. Falling through to the per-field pass below refines
            # those and refuses fii/dii, instead of throwing the whole cell away.
            force_keep = ("fii", "dii") if swallowed else ()
            # PER-FIELD, not all-or-nothing. Accept band is 0.02pp — the stored value often came
            # from a 2dp LEDGER derivation while the refined one is computed from the primary
            # document's share counts, so legitimate double-rounding can reach two 2dp steps.
            # Rejecting the WHOLE cell when one field conflicts threw away good precision: 75 of
            # 172 conflicts were promoter-only (BHARATFORG prom 44.76 vs 45.25) while fii and dii
            # agreed to 0.002pp — the two fields this campaign exists for. Each of the five is
            # independently sourced from the same document, so take the ones that agree and KEEP
            # the stored value for any that does not. A conflicting field is never imported.
            merged5, refused = [], []
            for i, nm in enumerate(("prom", "fii", "dii", "mf", "ins")):
                x, y = cur[i], new[i]
                if nm in force_keep:  # §22i: ambiguous in this doc
                    refused.append(nm + "(22i)")
                    merged5.append(x)
                    continue
                if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                    if abs(float(x) - float(y)) <= 0.0200001:
                        merged5.append(y)
                        continue
                    refused.append(nm)
                    merged5.append(x)  # keep stored, refuse the field
                else:
                    merged5.append(y if x is None else x)
                    if x != y and x is not None:
                        refused.append(nm)
            if refused:
                bad.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "stored": cur,
                        "refined": new[:7],
                        "verdict": (
                            "REFUSED_swallowed_foreign_block_22i" if swallowed else "FIELD_CONFLICT_kept_stored"
                        ),
                        "fields": refused,
                    }
                )
                skip += 1
            new = merged5 + list(new[5:])
            merged = new[:5] + list(cur[5:])  # refined values, stored provenance
            if merged == cur:
                continue  # already applied — keeps the run idempotent
            dest[qe] = merged
            n += 1
    if n or skip:
        print("shp_refine_4dp applied: %d cells refined, %d disagreements held back" % (n, skip))
    if bad:
        json.dump(bad, open(REFINE_REPORT, "w", encoding="utf-8"), indent=1)
        print("  -> %s (%d rows) — adjudicate, do NOT bulk-apply" % (os.path.basename(REFINE_REPORT), len(bad)))
    return n


# The mf-slot repair ledger (scripts/heal_shp_mf.py, runbook §22g). Until 2026-08-07 MEMBERS
# mapped only MutualFundsOrUTIMember, so every new-format filing spelling the member the old way
# (MutualFundsOrUtiMember — all BSE copies, every NSE filing before ~Jul-2025) stored mf = 0.0,
# i.e. "no mutual-fund holding" where the truth was "not found". parse_shp now falls back to the
# lowercase key, but the cells parsed before the fix keep their zero, so they are re-read from
# the filing and patched here. PATCHES ONE SLOT: never creates a cell, never writes a zero, and
# never touches a cell whose mf is already set (a fresh parse always wins).
MF_HEAL_LEDGER = os.path.join(HERE, "shp_mf_heal.json.gz")


def apply_mf_heal_ledger(h):
    if not os.path.exists(MF_HEAL_LEDGER):
        return 0
    try:
        with gzip.open(MF_HEAL_LEDGER, "rt", encoding="utf-8") as fh:
            heals = json.load(fh).get("heals", {})
    except Exception as e:
        print(f"shp_mf_heal.json.gz unreadable ({e}) — skipped")
        return 0
    n = stale = 0
    for sym, qs in heals.items():
        dest = h.get(sym)
        if not isinstance(dest, dict):
            continue
        for qe, rec in qs.items():
            cell = dest.get(qe)
            if not cell or len(cell) < 6 or cell[3]:
                continue  # gone, malformed, or already set
            mf, prom, fii, dii = rec[0], rec[1], rec[2], rec[3]
            if not mf or mf <= 0:
                continue  # never zero-default
            # Each heal was measured against a specific filing: if the stored cell has moved since
            # (a revision re-parsed), that filing's mf is not ours to write into it.
            if (
                abs((cell[0] or 0.0) - prom) > 0.5
                or abs((cell[1] or 0.0) - fii) > 0.5
                or abs((cell[2] or 0.0) - dii) > 0.5
                or mf > (cell[2] or 0.0) + 0.05
            ):
                stale += 1
                continue
            cell[3] = mf
            n += 1
    if n or stale:
        print("shp_mf_heal applied: %d mf cells%s" % (n, " (%d stale, left alone)" % stale if stale else ""))
    return n


# The pre-Jun-2006 `ins` slot (runbook §22m). Every cell parsed from the era 1997-format tables
# (BSE Flag=Old aspx, NSE shareholdingdetails.jsp — Mar-2001..Mar-2006) stores ins = None because
# that format prints insurance INSIDE the "Banks, Financial Institutions, Insurance Companies" lump.
# No 1997-format FILING itemises it. Two document proofs recover the slot from holder-level data:
#   lump-absent  — BSE Flag=Old page has NO lump row (the format omits empty rows) AND the
#                  institutions Sub Total closes as MF + FIIS (<=0.15) -> the whole category is 0
#                  -> ins = 0.
#   nse-closes   — NSE's era ">1% holders" page (shareholding1.jsp) lists every holder in that
#                  category BY NAME with a Sub Total; when that Sub Total equals the BSE lump
#                  (dii - mf) to print rounding, nobody in the category is <1% -> every insurer is
#                  listed -> ins = sum of the insurer rows exactly (0 when none is an insurer).
# PATCHES ONE SLOT: never creates a cell, never overwrites a set ins, and a zero is written ONLY
# when the record carries one of those proof tags (a "not found" is never a 0.0). The record also
# carries the prom/fii/dii/mf the proof was measured against; if the stored cell has moved since
# (a revision), the proof no longer describes it and the cell is left alone.
INS_FILL_LEDGER = os.path.join(HERE, "shp_fill_ins_pre2006.json.gz")
INS_PROOFS = ("lump-absent", "nse-closes")


def apply_ins_fill_ledger(h):
    if not os.path.exists(INS_FILL_LEDGER):
        return 0
    try:
        with gzip.open(INS_FILL_LEDGER, "rt", encoding="utf-8") as fh:
            fills = json.load(fh).get("fills", {})
    except Exception as e:
        print(f"shp_fill_ins_pre2006.json.gz unreadable ({e}) — skipped")
        return 0
    n = stale = unproven = 0
    for sym, qs in fills.items():
        dest = h.get(sym)
        if not isinstance(dest, dict):
            continue
        for qe, rec in qs.items():
            cell = dest.get(qe)
            if not cell or len(cell) < 6 or cell[4] is not None:
                continue  # gone, malformed, or already set
            ins, proof = rec.get("ins"), rec.get("proof")
            if ins is None or ins < 0 or proof not in INS_PROOFS:
                unproven += 1
                continue
            ref = rec.get("ref") or []
            if (
                len(ref) < 4
                or any(abs((cell[i] or 0.0) - (ref[i] or 0.0)) > 0.5 for i in range(4))
                or ins > (cell[2] or 0.0) + 0.05
            ):
                stale += 1
                continue
            cell[4] = ins
            n += 1
    if n or stale or unproven:
        print(
            "shp_fill_ins_pre2006 applied: %d ins cells%s%s"
            % (
                n,
                " (%d stale, left alone)" % stale if stale else "",
                " (%d unproven, refused)" % unproven if unproven else "",
            )
        )
    return n


# ---- per-cell correction ledger + the write-time scale gate (runbook §22g) ---------------
# A handful of filings do not describe the company's ordinary equity at all — a different
# share class, or a stub. GHCL 2022-12-31 is the type specimen: NSE serves exactly ONE
# filing for that quarter and it covers 29.67M shares / 58 holders against a real 95.59M /
# 94,479. So this is NOT "newest-submission-wins picked the wrong row" (duplicate rows exist
# for only ~0.1% of symbols per quarter, and none of them is affected) — the only document
# the source has is the wrong one, and the correction has to come from BSE.
CELL_FIX = os.path.join(HERE, "shp_cell_fix.json")
NSH_FLOOR_FRAC = 0.05  # a filing whose holder count is below this x the symbol's own
# EARLIER maximum is not the ordinary-equity pattern. Replayed over
# the whole history (57,362 cells carry a count): 20 hits / 5 symbols
# raw, of which 18 are the real post-insolvency collapses now on the
# ledger's accept-list => 2 rejections, both adjudicated defects.

QUARANTINE = []  # filings held back by nsh_gate this run — written to shp_quarantine.json


def load_cell_fix():
    if os.path.exists(CELL_FIX):
        try:
            return json.load(open(CELL_FIX, encoding="utf-8"))
        except Exception as e:
            print(f"WARN shp_cell_fix unreadable ({e}) — no corrections applied")
    return {}


CELL_TOL = 0.0100001  # one 2dp ulp — see _cell_eq


def _cell_eq(a, b):
    """Cell comparison to within one 2dp step. The §22j precision pass recomputes values from
    share counts, so an EXACT match would make every ledger entry read "neither the fix nor the
    recorded bad value" and skip — silently retiring the whole cell_fix ledger the moment a
    re-parse ran. The ledger's intent is "this cell held THIS value"; a precision refinement of
    the same number is still that number.

    Rounding to 2dp is NOT enough: the filer rounds from its own internal figure, so our
    share-count value can land a half-step the other way — CELEBRITY Mar-2025 computes 14.3256
    (rounds to 14.33) where the filer filed 14.32. That is the same holding, not a disagreement.
    A tolerance of one full 2dp step absorbs the double-rounding while still separating real
    corrections by a mile (CELEBRITY's fix moves prom 33.47 -> 35.32, MODIRUBBER's 62.69 -> 62.2).
    Non-numeric fields stay EXACT, so a differing submission date still warns and re-adjudicates
    (ATLANTAA Mar-2025: stored 2025-04-03 vs the ledger's recorded 2026-04-04)."""
    if a is None or b is None:
        return a is b
    if len(a) != len(b):
        return False
    for x, y in zip(a, b, strict=False):
        if isinstance(x, bool) or isinstance(y, bool):
            if x != y:
                return False
        elif isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if abs(float(x) - float(y)) > CELL_TOL:
                return False
        elif x != y:
            return False
    return True


def apply_cell_fix(h, led=None):
    """Override known-wrong cells. Runs AFTER the fetch so a --reparse cannot re-poison them."""
    led = load_cell_fix() if led is None else led
    n = 0
    for sym, qs in (led.get("fix") or {}).items():
        for qe, ent in qs.items():
            cur = (h.get(sym) or {}).get(qe)
            want, was = ent.get("cell"), ent.get("was")
            if cur is None:
                continue  # correct only what exists — a fix
            if _cell_eq(cur, want):
                continue  # ledger must never INVENT a cell
            if was is not None and not _cell_eq(cur, was):
                print(
                    f"WARN cell_fix {sym} {qe}: stored cell is neither the fix nor the recorded bad "
                    f"value ({cur}) — leaving it alone, re-adjudicate"
                )
                continue
            h.setdefault(sym, {})[qe] = list(want)
            n += 1
    if n:
        print("shp_cell_fix applied: %d cells" % n)
    return n


def nsh_gate(h, sym, qe, nsh, accept):
    """-> reason string if this filing's holder count says it is not the ordinary equity.

    Deliberately compares against the symbol's own EARLIER quarters only, never a
    whole-history median: a median is not a scale reference for a series with a trend, and
    these series trend hard. An SME that grew 94 -> 50,417 holders, and the last pre-IPO
    pattern of a company about to list (MAZDOCK 7, CLEAN 31, AVALON 19), are both perfectly
    real and both look tiny against their own median — that rule flags 302 cells of which
    only 2 are defects. Against the running maximum of EARLIER quarters, a growth ramp and a
    first filing cannot trip at all, and only a genuine collapse does."""
    if not nsh:
        return None
    if qe in ((accept.get("accept") or {}).get(sym) or {}):
        return None
    prior = [c[6] for q, c in (h.get(sym) or {}).items() if q < qe and len(c) > 6 and c[6]]
    if not prior:
        return None
    top = max(prior)
    if nsh < NSH_FLOOR_FRAC * top:
        return "nsh %d < %.0f%% of the symbol's earlier max %d" % (nsh, NSH_FLOOR_FRAC * 100, top)
    return None


# ------------------------------------------------------------------ NSE fetch
def fetch_master(jar, qe_iso, events=False):
    """All SHP filings whose AS-ON date == qe (events=True: the MID-quarter ones instead).
    Returns [] on failure (self-healing).

    ⚠️ from_date/to_date filter on the SUBMISSION date, NOT the pattern's as-on date. It was
    the other way round when this was written (runbook §22), and the switch was silent: the
    daily top-up kept asking from=to=quarter-end, which matches only filings submitted ON the
    quarter end — 2 rows for Jun-2026 instead of 2,284, so the top-up quietly stopped adding
    anything. Ask for a submission window that opens at the quarter end and runs to today
    (capped: SEBI's deadline is 21d, revisions trail by months, and the API doesn't truncate —
    a 6-month window returns ~4,800 rows), then keep the rows whose as-on date IS this quarter.
    Mid-quarter as-on dates are event-based SHPs (capital changes) — deliberately dropped."""
    d = datetime.date.fromisoformat(qe_iso)
    to = max(d, min(datetime.date.today(), d + datetime.timedelta(days=MASTER_WINDOW_DAYS)))

    def fmt(x):
        return "%02d-%02d-%04d" % (x.day, x.month, x.year)

    url = (
        "https://www.nseindia.com/api/corporate-share-holdings-master?index=equities"
        f"&from_date={fmt(d)}&to_date={fmt(to)}"
    )
    hdr = {"User-Agent": B.UA, "Accept": "application/json, text/plain, */*", "Referer": REF}
    try:
        j = json.loads(B._get(url, headers=hdr, jar=jar, timeout=180))
        recs = j if isinstance(j, list) else j.get("data", [])
        if not isinstance(recs, list):
            return []
    except Exception as e:
        print(f"ERR master {qe_iso}: {e!r}")
        return []
    if events:
        # Mid-quarter as-on dates = EVENT-driven SHPs (capital changes, SAST). Strictly AFTER this
        # quarter end and at or before the next one, so each filing is claimed by exactly one
        # window. These were dropped outright until 2026-08-13 — and they are not a rounding
        # error: this window keeps 2,122 quarter-end rows and threw away 2,479 event rows.
        # STRICTLY between this quarter end and the next: the next quarter end is a REGULAR filing
        # and belongs to that quarter's own pass, where the ledgers (cell_fix, nsh_gate, bse_hist)
        # apply. An inclusive upper bound pulled it in here too — 93.8% of the first backfill was
        # quarter-end rows that bypass every one of those gates if they ever fill a hist gap.
        nxt = (d + datetime.timedelta(days=100)).replace(day=1) - datetime.timedelta(days=1)
        nxt_iso = nxt.isoformat()
        out = [r for r in recs if qe_iso < (iso_date(r.get("date")) or "") < nxt_iso]
        print("  master %s: %d filings, %d EVENT rows (as-on %s..%s]" % (qe_iso, len(recs), len(out), qe_iso, nxt_iso))
        return out
    out = [r for r in recs if iso_date(r.get("date")) == qe_iso]
    print(
        "  master %s: %d filings submitted %s..%s, %d as-on this quarter"
        % (qe_iso, len(recs), fmt(d), fmt(to), len(out))
    )
    return out


def fetch_xbrl(url, jar):
    """XBRL from nsearchives — plain fetch first (static host), session fallback."""
    hdr = {"User-Agent": B.UA, "Accept": "*/*", "Referer": REF}
    try:
        return B._get(url, headers=hdr, jar=None, timeout=120)
    except Exception:
        return B._get(url, headers=hdr, jar=jar, timeout=120)


# ------------------------------------------------------------------ XBRL parse
def parse_shares(txt):
    """-> total equity shares outstanding (int), or None.

    Deliberately independent of parse_shp. A company with NO institutional holding files only
    promoter/public rows, which parse_shp must reject (it can't tell "no institutions" from
    "old format", and guessing zero would poison FII/DII — runbook §22b). Their share count is
    still perfectly good, and those SME-ish names are exactly the ones missing a market cap.
    NumberOfShares is the full base (fully paid + partly paid + DRs); the fully-paid tag is the
    fallback for filers who omit it. Both sit on the whole-company context."""
    root = txt if hasattr(txt, "iter") else ET.fromstring(txt)

    def strip(t):
        return t.split("}", 1)[-1]

    whole = set()
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        mems, typed = [], False
        for m in c.iter():
            st = strip(m.tag)
            if st == "explicitMember":
                mems.append((m.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                typed = True
        if not typed and mems == ["ShareholdingPatternMember"]:
            whole.add(c.get("id"))
    best = {}
    for f in root.iter():
        tag = strip(f.tag)
        if tag not in ("NumberOfShares", "NumberOfFullyPaidUpEquityShares"):
            continue
        if f.get("contextRef") not in whole:
            continue
        try:
            v = int(float(str(f.text).strip()))
        except (TypeError, ValueError):
            continue
        if v > 0:
            best[tag] = v
    return best.get("NumberOfShares") or best.get("NumberOfFullyPaidUpEquityShares")


def parse_shp(txt, qe_iso):
    """-> dict(prom, fii, dii, mf, ins) as % (2dp) or None if not anchored.
    Category facts sit in contexts with exactly ONE explicit member and no typed member
    (typed members = the named >1% shareholders)."""
    root = txt if hasattr(txt, "iter") else ET.fromstring(txt)

    def strip(t):
        return t.split("}", 1)[-1]

    ctx = {}  # id -> member localname | None(invalid)
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        mems, typed = [], False
        for m in c.iter():
            st = strip(m.tag)
            if st == "explicitMember":
                mems.append((m.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                typed = True
        ctx[c.get("id")] = mems[0] if (not typed and len(mems) == 1) else None

    vals = {}
    shares = {}  # slot -> NumberOfShares for that category (see the precision pass below)
    nsh = None  # total no. of shareholders (whole-company context)
    nsh_pub = None  # public-only count, used purely as a consistency check on nsh
    for f in root.iter():
        tag = strip(f.tag)
        if tag == "NumberOfShareholders":
            who = ctx.get(f.get("contextRef")) or ""
            if who in ("ShareholdingPatternMember", "PublicShareholdingMember"):
                try:
                    n = int(float(str(f.text).strip()))
                except (TypeError, ValueError):
                    n = None
                if n is not None:
                    if who == "ShareholdingPatternMember":
                        nsh = n
                    else:
                        nsh_pub = n
            continue
        if tag == "NumberOfShares":
            # Per-category share counts, used below to recompute the percentage at full precision.
            slot = MEMBERS.get(ctx.get(f.get("contextRef")) or "")
            if slot:
                try:
                    n = int(float(str(f.text).strip()))
                except (TypeError, ValueError):
                    n = None
                if n is not None and n >= 0:
                    shares[slot] = n
            continue
        if tag != "ShareholdingAsAPercentageOfTotalNumberOfShares":
            continue
        slot = MEMBERS.get(ctx.get(f.get("contextRef")) or "")
        if not slot:
            continue
        try:
            v = float(str(f.text).strip())
        except (TypeError, ValueError):
            continue
        vals[slot] = v  # duplicate facts for a member are identical in practice; last wins

    if not vals:
        return None
    prom, pub = vals.get("prom"), vals.get("pub")
    if prom is None and pub is None:
        return None
    # scale anchor: total ≈ 1 (fractions, new format) or ≈ 100 (percent, old format + some filers).
    # Candidates in descending order of trust, FIRST ONE IN A BAND WINS — a filing that already
    # anchored on its declared total parses exactly as before, so this can only turn a REFUSAL into
    # a parse, never change an accepted value.
    # Why the fallbacks: BSE Ltd files a junk whole-company percentage (Sep-2024: total = 6.9) on top
    # of a perfectly clean percent partition — prom 0.00 + pub 77.09 + npnp 22.90 = 100 — and the
    # single-candidate anchor threw the whole filing away. 23 quarters of a current N500 member were
    # missing for that reason alone (Screener publishes those same numbers off the same file).
    # The partition gate at the bottom (prom+pub+extra ∈ [98,102]) is what actually keeps a wrong
    # scale out; this ladder only decides which number gets tested against the two bands.
    part = (prom or 0) + (pub or 0)
    scale = None
    for anchor in (vals.get("total"), part, part + _third(vals)):
        if anchor is None:
            continue
        if 0.90 <= anchor <= 1.10:
            scale = 100.0
            break
        if 90.0 <= anchor <= 110.0:
            scale = 1.0
            break
    if scale is None:
        return None

    is_new = ("fii" in vals) or ("dii" in vals)  # explicit Domestic/Foreign facts
    is_old = (not is_new) and ("o_inst" in vals)  # single Institutions bucket
    if not (is_new or is_old):
        return None  # unknown vintage — SKIP, never zero-fill
    # BSE's copy of a NEW-format filing spells the mutual-fund member the OLD way
    # (MutualFundsOrUtiMember, lowercase "ti") — see runbook §22g. Without this the mf slot
    # comes back 0.00 for every BSE-sourced post-Sep-2022 filing (GHCL Dec-2022: 10.22 -> 0).
    if "mf" not in vals and "o_mf" in vals:
        vals["mf"] = vals["o_mf"]

    prom = (prom or 0) * scale
    pub = (pub if pub is not None else max(0.0, 100.0 - prom)) * (scale if vals.get("pub") is not None else 1)
    out = {"prom": prom, "pub": pub}
    if is_new:
        for k in ("fii", "dii", "mf", "ins"):
            out[k] = (vals.get(k) or 0.0) * scale
        # ⚠️ New-format filings spell the MF member BOTH ways — MutualFundsOrUTIMember and the
        # old-format's MutualFundsOrUtiMember (the lowercase-ti one is what BSE's copies and every
        # NSE filing before ~Jul-2025 carry). Mapping only the uppercase spelling silently wrote
        # mf=0.0 on those, which reads as "no mutual-fund holding" instead of "not found"
        # (MCX Mar-2025: dii 58.1 with mf 0.0). fii/dii were never affected — they come from the
        # Domestic/Foreign facts directly. Found 2026-08-07 while backfilling.
        if not out["mf"] and vals.get("o_mf"):
            out["mf"] = vals["o_mf"] * scale
    else:

        def g(k):
            return (vals.get(k) or 0.0) * scale

        fii = g("o_fpi") + g("o_fvci")
        dii = g("o_mf") + g("o_aif") + g("o_vcf") + g("o_bank") + g("ins") + g("o_pf")
        other = g("o_other")
        if OLD_OTHER_TO_DII:
            dii += other
        else:
            fii += other
        # old bucket must reconcile: fii+dii ≈ total Institutions (± rounding)
        if abs((fii + dii) - g("o_inst")) > 0.35:
            return None
        out.update({"fii": fii, "dii": dii, "mf": g("o_mf"), "ins": g("ins")})
    if out["fii"] + out["dii"] > out["pub"] + 2.0:
        return None  # institutions can't exceed public
    # partition sanity: promoter + public + non-promoter-non-public ≈ 100. The third bucket
    # (ESOP trusts / DR custodians) can be large for no-promoter companies (ETERNAL 4.73%).
    extra = _third(vals) * scale
    # Two legitimate presentations, accept EITHER: the modern one where the third bucket is inside
    # the base (prom + pub + extra = 100) and the 2016-era one where prom + pub already make 100 and
    # the third bucket is quoted on top as a % of (A+B) — RELIANCE Jun-2016: 46.49 + 53.51 = 100.00
    # with a 3.03 GDR block, which summed to 103.03 and got the whole filing thrown away. Requiring
    # the two main buckets to reconcile to 100 is the actual check; which base the third bucket uses
    # is a presentation choice, not evidence of a bad parse.
    base = out["prom"] + out["pub"]
    if not (98.0 <= base + extra <= 102.0 or 98.0 <= base <= 102.0):
        return None
    # ---- PRECISION PASS: recompute the institutional slots from SHARE COUNTS ------------------
    # The filer's own ShareholdingAsAPercentageOfTotalNumberOfShares is rounded to 2dp, so ANY
    # holding below 0.005% is filed as a literal "0". ITI Mar-2022 files pct=0 on every domestic
    # row while carrying 31,695 (banks) + 39,332 (MF) + 800 (insurance) real shares = 0.0077% of
    # 933,522,869. Reading the percentage stored dii=0.00 — and a "lowest DII %" screen ranks 0.00
    # FIRST, so a filer's rounding artefact became a BUY. 13,463 of 88,767 DII cells (15.2%) sit at
    # exactly 0.00; this is how an unknown share of them got there. Verified 2026-08-13 against the
    # filings: ITI -> 0.0077 and TRIDENT -> 0.0080, both matching an independent reader to 4dp.
    # shares/total is also immune to the fraction-vs-percent scale ambiguity anchored above.
    # Runs AFTER every gate, so which filings are accepted is bit-for-bit unchanged.
    # The denominator is NOT the whole-company NumberOfShares: that is the full base (fully paid +
    # partly paid + depositary receipts), while the filer computes its percentages on a SMALLER
    # base that excludes DRs. Using it understated every ADR-heavy large cap — HDFCBANK Mar-2026
    # fii 44.05 -> 38.16 (base 15.4% too big), INFY 28.45 -> 26.31, LT/RELIANCE/SBIN likewise.
    # So infer the filer's OWN base from its LARGEST category that reports a usable percentage:
    # base = shares / (pct/100). A category at >=1% carries at most ±0.005pp of rounding, i.e. 1
    # part in 200 — negligible against the sub-0.005% rows this pass exists to recover.
    tot_sh = None
    _cand = [
        (shares[s], (vals.get(s) or 0.0) * scale)
        for s in shares
        if s != "total" and shares.get(s) and (vals.get(s) or 0.0) * scale >= 1.0
    ]
    if _cand:
        n_big, p_big = max(_cand)
        b = n_big / (p_big / 100.0)
        whole = shares.get("total")
        # sane only if it lands at or below the full base and within a plausible DR/partly-paid gap
        if not whole or 0.70 * whole <= b <= 1.02 * whole:
            tot_sh = b
    if tot_sh:

        def _sum(slots):
            """Sum those slots from share counts — None unless EVERY contributor that reported a
            percentage also reported a count, since a missing count would silently undercount."""
            n = 0
            seen = False
            for s in slots:
                if s in shares:
                    n += shares[s]
                    seen = True
                elif vals.get(s):
                    return None  # contributed a percentage but no count -> bail
            return n if seen else None

        if is_new:
            groups = {"fii": ["fii"], "dii": ["dii"], "mf": ["mf"], "ins": ["ins"]}
            if "mf" not in shares and "o_mf" in shares:
                groups["mf"] = ["o_mf"]
        else:
            f_slots = ["o_fpi", "o_fvci"]
            d_slots = ["o_mf", "o_aif", "o_vcf", "o_bank", "ins", "o_pf"]
            (d_slots if OLD_OTHER_TO_DII else f_slots).append("o_other")
            groups = {"fii": f_slots, "dii": d_slots, "mf": ["o_mf"], "ins": ["ins"]}
        for key, slots in groups.items():
            n = _sum(slots)
            if n is not None:
                out[key] = n / tot_sh * 100.0
    # Government row (public sub-category) for the sidecar — share-count precision where available,
    # else the filer's own 2dp percentage. Present only when the filing carried the member AND the
    # value is a genuine PUBLIC government holding. In a PSU the SAME GovernmentsMember tag carries the
    # PROMOTER government stake (President of India owns e.g. UCOBANK 90.95% = the promoter row); that
    # must not surface as a public "Government" row. A public government holding is part of Public &
    # others, so it can never exceed 100 − promoter − FII − DII.
    if "gov" in vals:
        gov_raw = (shares["gov"] / tot_sh * 100.0) if (tot_sh and "gov" in shares) else (vals["gov"] or 0.0) * scale
        pub_noninst = 100.0 - out.get("prom", 0.0) - out.get("fii", 0.0) - out.get("dii", 0.0)
        if gov_raw <= pub_noninst + 0.5:
            out["gov"] = gov_raw
    out = {k: round(v, 4) for k, v in out.items()}
    # nsh is OPTIONAL, so an implausible one gets dropped rather than published: the grand total
    # can never be below the public-shareholder count. BSE Ltd Sep-2024 files 248 against 539,914
    # public holders (its own grand total is broken, like its 6.9 "total %"), which would have
    # rendered "248 shareholders" on the stock page between two quarters reading ~540k.
    if nsh and nsh > 0 and not (nsh_pub and nsh < nsh_pub):
        out["nsh"] = nsh
    return out


# ------------------------------------------------------------------ main fetch
def refresh_quarters(qes, reparse=False, only=None, fill_shares=False):
    jar = B.nse_jar()
    hist = load_hist()
    apply_bse_hist_ledger(hist)  # STEP 5 2016-2019 backfill — fill-only, no-ops once applied
    apply_refine_ledger(hist)  # §22j 4dp precision refresh — refine-only, no-ops once applied
    apply_mf_heal_ledger(hist)  # mf-slot repair — patch-only, no-ops once applied
    apply_ins_fill_ledger(hist)  # §22m pre-2006 ins slot — patch-only, document-proven, no-ops once applied
    cellfix = load_cell_fix()  # load_hist already applied it; re-applied post-fetch below
    names = hist.setdefault("_names", {})
    shares = load_shares()
    gov = {}  # Government sidecar, fill-or-newer-submission-wins
    if os.path.exists(GOV_OUT):
        try:
            gov = json.load(open(GOV_OUT, encoding="utf-8"))
        except Exception:
            gov = {}
    before = cells_of(hist)
    stats = []

    for qe in qes:
        recs = fetch_master(jar, qe)
        # newest submission per symbol wins (revisions re-file the same (sym, qe))
        best = {}
        for r in recs:
            sym = str(r.get("symbol") or "").strip().upper()
            sub = iso_date(r.get("submissionDate")) or iso_date(r.get("broadcastDate"))
            xb = str(r.get("xbrl") or "").strip()
            if not sym or not sub or not xb.lower().startswith("http"):
                continue
            cur = best.get(sym)
            if cur is None or sub >= cur["sub"]:
                best[sym] = {"sub": sub, "xb": xb, "name": re.sub(r"\s+", " ", str(r.get("name") or "")).strip()}
        todo = []
        for sym, r in best.items():
            if only is not None and sym not in only:
                continue
            have = (hist.get(sym) or {}).get(qe)
            if fill_shares:
                # re-read only the filings whose share count we never captured
                if (shares.get(sym) or [None, ""])[1] >= qe:
                    continue
            elif have and str(have[5]) >= r["sub"] and not reparse:
                continue  # already have this or newer
            todo.append((sym, r))
        print("%s: %d filings, %d new/revised to parse" % (qe, len(best), len(todo)))
        stats.append((qe, len(best), len(todo)))

        done = skip = nsh_new = quar = 0

        def work(item):
            sym, r = item
            try:
                root = ET.fromstring(fetch_xbrl(r["xb"], jar))
                return sym, r, parse_shp(root, qe), parse_shares(root)
            except Exception as e:
                return sym, r, ("ERR", repr(e)), None

        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            for fut in as_completed([ex.submit(work, it) for it in todo]):
                sym, r, res, nshares = fut.result()
                # A filing that describes a different share class carries a share count to
                # match, and shares_outstanding feeds market cap (§22e) — so a quarantined
                # filing must not bank its count either, or the stock gets a mcap several
                # times too low. Gate FIRST, then bank.
                bad = nsh_gate(hist, sym, qe, res.get("nsh") if isinstance(res, dict) else None, cellfix)
                if bad:
                    quar += 1
                    QUARANTINE.append(
                        {
                            "sym": sym,
                            "qe": qe,
                            "sub": r["sub"],
                            "why": bad,
                            "cell": res,
                            "shares": nshares,
                            "xbrl": r["xb"],
                        }
                    )
                    if quar <= 12:
                        print(f"  QUARANTINE {sym} {qe}: {bad}")
                    continue
                # Share count is banked whether or not the FII/DII parse survived its gates.
                if nshares and (shares.get(sym) or [None, ""])[1] <= qe:
                    if shares.get(sym) != [nshares, qe, r["sub"]]:
                        nsh_new += 1
                    shares[sym] = [nshares, qe, r["sub"]]
                if isinstance(res, dict):
                    cell = [res["prom"], res["fii"], res["dii"], res["mf"], res["ins"], r["sub"]]
                    if res.get("nsh"):
                        cell.append(res["nsh"])
                    hist.setdefault(sym, {})[qe] = cell
                    # Government sidecar (separate file, never in the cell): newest submission wins.
                    if res.get("gov") is not None:
                        g = gov.setdefault(sym, {})
                        prev = g.get(qe)
                        if not (isinstance(prev, list) and len(prev) > 1 and str(prev[1]) > r["sub"]):
                            g[qe] = [res["gov"], r["sub"]]
                    if r["name"]:
                        names[sym] = r["name"]
                    done += 1
                    if done % FLUSH_EVERY == 0:
                        save_hist(hist)
                        print("  ... %d/%d parsed (flushed)" % (done, len(todo)))
                else:
                    skip += 1
                    why = res[1] if isinstance(res, tuple) else "no-anchor/old-format"
                    if skip <= 12:
                        print(f"  SKIP {sym} {qe}: {why}")
        print("%s: +%d cells, %d skipped, %d quarantined, %d share counts" % (qe, done, skip, quar, nsh_new))
        save_hist(hist)
        save_shares(shares)
        # persist the Government sidecar per-quarter too, so a long backfill survives an interruption
        _gtmp = GOV_OUT + ".tmp"
        json.dump(gov, open(_gtmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        os.replace(_gtmp, GOV_OUT)

    after = cells_of(hist)
    if after < before:
        print("ABORT: history would shrink %d -> %d — not writing" % (before, after))
        sys.exit(1)
    apply_cell_fix(hist, cellfix)
    save_hist(hist)
    tmp = GOV_OUT + ".tmp"
    json.dump(gov, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    os.replace(tmp, GOV_OUT)
    print(
        "government sidecar: %d symbols -> %s"
        % (sum(1 for k in gov if not k.startswith("_")), os.path.basename(GOV_OUT))
    )
    if QUARANTINE:
        json.dump(QUARANTINE, open(os.path.join(HERE, "shp_quarantine.json"), "w"), ensure_ascii=False, indent=1)
        print(
            "QUARANTINE: %d filing(s) held back for review -> scripts/shp_quarantine.json "
            "(adjudicate, then add to shp_cell_fix.json 'fix' or 'accept')" % len(QUARANTINE)
        )
    print(
        "history: %d cells (%+d), %d symbols" % (after, after - before, sum(1 for k in hist if not k.startswith("_")))
    )
    return stats


def load_events():
    try:
        return json.load(open(EVENTS, encoding="utf-8"))
    except Exception:
        return {}


def save_events(e):
    tmp = EVENTS + ".tmp"
    json.dump(e, open(tmp, "w", encoding="utf-8"), separators=(",", ":"), sort_keys=True)
    os.replace(tmp, EVENTS)


def refresh_events(qes, only=None, reparse=False):
    """Ingest EVENT-driven (mid-quarter) SHP filings into scripts/shp_events.json.

    Companies re-file a full shareholding pattern between quarters on capital changes and SAST
    events, and NSE serves them from the same master endpoint — we simply threw them away, so a
    stake sale stayed invisible until the next quarterly. AWL: DII was 0.05 at Dec-2024 and 8.76
    on an as-on 14-Feb-2025 filing SUBMITTED 28-Feb, but our series only learned it on 11-Apr —
    six weeks of a "lowest DII" screen holding a stock whose real DII was 170x what we showed.

    Stored {SYM: {ASON_ISO: [prom, fii, dii, mf, ins, sub, nsh]}} — the shp_history row shape, so
    the engine feed can merge the two without a second format. No ledgers are applied: those are
    all keyed by quarter-end and none of them describes an event row."""
    jar = B.nse_jar()
    ev = load_events()
    before = sum(len(v) for v in ev.values())
    for qe in qes:
        recs = fetch_master(jar, qe, events=True)
        best = {}  # (sym, as-on) -> newest submission wins
        for r in recs:
            sym = str(r.get("symbol") or "").strip().upper()
            ason = iso_date(r.get("date"))
            sub = iso_date(r.get("submissionDate")) or iso_date(r.get("broadcastDate"))
            xb = str(r.get("xbrl") or "").strip()
            if not sym or not ason or not sub or not xb.lower().startswith("http"):
                continue
            if only is not None and sym not in only:
                continue
            k = (sym, ason)
            if k not in best or sub >= best[k]["sub"]:
                best[k] = {"sub": sub, "xb": xb}
        todo = [
            (k, v)
            for k, v in best.items()
            if reparse
            or not (ev.get(k[0]) or {}).get(k[1])
            or str(((ev.get(k[0]) or {}).get(k[1]) or [None] * 6)[5]) < v["sub"]
        ]
        if not todo:
            print(f"  events {qe}: nothing new")
            continue

        def work(item):
            (sym, ason), r = item
            try:
                return sym, ason, r, parse_shp(ET.fromstring(fetch_xbrl(r["xb"], jar)), ason)
            except Exception as e:
                return sym, ason, r, ("ERR", repr(e))

        done = 0
        with ThreadPoolExecutor(max_workers=THREADS) as ex:
            for fut in as_completed([ex.submit(work, it) for it in todo]):
                sym, ason, r, res = fut.result()
                if not isinstance(res, dict):
                    continue
                cell = [res["prom"], res["fii"], res["dii"], res["mf"], res["ins"], r["sub"]]
                if res.get("nsh"):
                    cell.append(res["nsh"])
                ev.setdefault(sym, {})[ason] = cell
                done += 1
        print("  events %s: %d parsed of %d" % (qe, done, len(todo)))
        save_events(ev)
    after = sum(len(v) for v in ev.values())
    print("shp_events.json: %d rows (%+d), %d symbols" % (after, after - before, len(ev)))
    return ev


# ------------------------------------------------------------------ page feed
def build_feed():
    hist = load_hist()
    names = hist.get("_names", {})
    meta = {}
    try:
        slim = json.loads(gzip.decompress(open(SLIM, "rb").read()))
        for k, m in (slim.get("meta") or {}).items():
            sym = str(m.get("symbol") or k.split(".")[0]).upper()
            meta[sym] = (m.get("name"), m.get("mcap"))
    except Exception as e:
        print(f"WARN dash_slim unavailable ({e}) — names from master, no mcap")
    try:
        cl = json.load(open(CLASSIF, encoding="utf-8"))
        sector = {s: (v.get("macro") or "") for s, v in cl.items()}
    except Exception:
        sector = {}

    all_qes = sorted({qe for s, qs in hist.items() if not s.startswith("_") for qe in qs}, reverse=True)
    quarters = all_qes[:FEED_QUARTERS]
    rows = []
    for sym, qs in hist.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        cells = [qs.get(qe) or 0 for qe in quarters]
        if not any(cells):
            continue
        nm, mc = meta.get(sym, (None, None))
        rows.append([sym, nm or names.get(sym) or sym, mc or 0, sector.get(sym) or "", cells])
    rows.sort(key=lambda r: -(r[2] or 0))
    if len(rows) < MIN_FEED_ROWS and os.path.exists(OUT) and os.path.getsize(OUT) > 200000:
        print("ABORT feed: only %d rows — keeping existing docs/shareholding.json" % len(rows))
        return False
    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    out = {"updated": ist.strftime("%Y-%m-%d %H:%M IST"), "quarters": quarters, "rows": rows}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(
        "WROTE %s: %d rows x %d quarters, %.1f KB"
        % (os.path.normpath(OUT), len(rows), len(quarters), os.path.getsize(OUT) / 1e3)
    )
    return True


UNDATED_SUB = 99999999  # sentinel: value is real, its visibility date is NOT evidenced —
# never satisfies `sub <= screenDate`, so PIT screens exclude the row.


def _is_conv21(qi, sub):
    """True when sub is exactly quarter-end + 21 calendar days (the placeholder signature)."""
    try:
        d0 = datetime.date(qi // 10000, (qi // 100) % 100, qi % 100)
        d1 = datetime.date(sub // 10000, (sub // 100) % 100, sub % 100)
    except ValueError:
        return False
    return (d1 - d0).days == 21


def build_engine_feed():
    """docs/shp_engine.json — the backtest engines' point-in-time FII/DII series:
    {SYM: [[qeInt, fii, dii, subInt, prom, mf], ...] sorted by quarter}. ALL quarters (not the page's 8);
    (prom/mf added 2026-09-06 — promoter & mutual-fund holding %, source shp_history cols 0 & 3;
     may be null on old rows, e.g. mf None pre-2006 — the engine drops a null-factor stock, correct);
    the engines gate on subInt <= rebalance date so there is no look-ahead.

    ★ UN-DATED PRE-JUN-2016 ROWS (SW-1 quantmac round 5, 2026-08-30 — supersedes §105's
    'keep + document' state): a row whose sub is only the qe+21d CONVENTION (the era's filing
    DEADLINE, never a measurement) is served with sub = UNDATED_SUB so a point-in-time screen
    can never select it. An unfalsifiable date is a look-ahead in exactly the tail cases —
    late filers (PAISALO Dec-2015 really filed 2016-03-17, 77 days after quarter end). The
    VALUES stay in the row; only the claim 'public by date X' is withdrawn.
    Evidence test per cell — a pre-Jun-2016 row keeps a real sub iff:
      (a) its stored sub is NOT the convention (Mar-2016 SHPQNewFormat-era filing dates), or
      (b) scripts/shp_sub_dates.json holds a measured date for SYM|qe — the P2-P4 SHPQNewFormat
          entries plus the 2014-16 BSE announcement-stream recovery (src 'ann-stream';
          the stream carries SHP filings from Jan-2014 ONLY — 2013 and earlier measured empty
          on every route, PLAN_SHP_DATES.md / runbook §105)."""
    hist = load_hist()
    events = load_events()
    out = {}
    try:
        led_keys = {
            k
            for k in json.load(open(os.path.join(HERE, "shp_sub_dates.json"), encoding="utf-8"))
            if not k.startswith("_")
        }
    except Exception as e:
        led_keys = set()
        print(
            f"WARN shp_sub_dates.json unreadable ({e}) — every convention-dated pre-2016 row "
            "will be served UN-DATED (conservative direction)"
        )
    # §135 (2026-09-05): RE-ASSERT the SHP visibility-date ledgers at serve time — rebuild-proof, the same
    # contract ann_date_fills.json has via --reapply. The Aug-23 P4 reconcile (shp_lag_fix.json, 26,018
    # entries) was written into history slot 5 ONLY; a later NSE re-capture of the same quarter rewrote 71
    # of those slots with NSE's LATER submissionDate (measured 2026-09-05, all 2025-26 quarters). Rules:
    #   lag heal ('days_earlier')   -> earlier-only: serve the ledger date when the stored one is later;
    #   gate shift ('days_later')   -> raw->gated of the SAME filing: serve it only when stored == its 'was';
    #   shp_sub_dates entry         -> serve it when the stored date regressed to the convention it replaced.
    # A stored date EARLIER than a lag-heal ledger date is left alone (a possibly-genuine earlier disclosure).
    lag_led, sub_led = {}, {}
    try:
        lag_led = json.load(open(os.path.join(HERE, "shp_lag_fix.json"), encoding="utf-8"))
        sub_led = {
            k: v
            for k, v in json.load(open(os.path.join(HERE, "shp_sub_dates.json"), encoding="utf-8")).items()
            if not k.startswith("_")
        }
    except Exception as e:
        print(f"WARN SHP date ledgers unreadable ({e}) — visibility dates served as stored")
    n_reassert = [0]

    def _reassert_sub(sym, qi, sub):
        k = "%s|%d" % (sym, qi)
        e = lag_led.get(k)
        if isinstance(e, dict) and isinstance(e.get("sub"), int):
            if "days_earlier" in e:
                if sub != UNDATED_SUB and sub > e["sub"]:
                    n_reassert[0] += 1
                    return e["sub"]
                if sub == e["sub"]:
                    return sub  # already at the healed (earliest-disclosure) date: an older BSE-only
                    # shp_sub_dates entry must not move it later again
            if "days_later" in e and sub == e.get("was"):
                n_reassert[0] += 1
                return e["sub"]
        e = sub_led.get(k)
        if isinstance(e, dict) and isinstance(e.get("sub"), int) and sub != e["sub"] and sub == e.get("was"):
            n_reassert[0] += 1
            return e["sub"]
        return sub

    n_undated = [0]

    def rows_of(qs, sym):
        rows = []
        for qe, c in (qs or {}).items():
            try:
                qi = int(qe.replace("-", ""))
                sub = int(str(c[5]).replace("-", ""))
                if qi <= 20160331 and _is_conv21(qi, sub) and "%s|%d" % (sym, qi) not in led_keys:
                    sub = UNDATED_SUB
                    n_undated[0] += 1
                sub = _reassert_sub(sym, qi, sub)
                rows.append([qi, c[1], c[2], sub, c[0], c[3]])
            except (ValueError, TypeError, IndexError):
                continue
        return rows

    for sym in set(hist) | set(events):
        if sym.startswith("_"):
            continue
        qs = hist.get(sym)
        rows = rows_of(qs if isinstance(qs, dict) else None, sym)
        # EVENT rows carry an AS-ON date in the same slot as a quarter end, so they sort into the
        # series by date and the engines' "latest row whose sub <= screen date" picks them up with
        # no engine change. A quarter-end row wins a same-date collision (it is the fuller filing).
        seen = {r[0] for r in rows}
        rows += [r for r in rows_of(events.get(sym), sym) if r[0] not in seen]
        if rows:
            out[sym] = sorted(rows)
    print("  engine feed: %d pre-Jun-2016 rows served UN-DATED (no evidenced visibility date)" % n_undated[0])
    print(
        "  engine feed: %d visibility dates re-asserted from shp_lag_fix.json / shp_sub_dates.json (§135)"
        % n_reassert[0]
    )
    n_ev = sum(len(v) for v in events.values())
    if n_ev:
        print("  engine feed: merged %d event rows from %d symbols" % (n_ev, len(events)))
    ep = os.path.join(HERE, "..", "docs", "shp_engine.json")
    if len(out) < MIN_FEED_ROWS and os.path.exists(ep) and os.path.getsize(ep) > 200000:
        print("ABORT engine feed: only %d symbols — keeping existing shp_engine.json" % len(out))
        return
    json.dump(out, open(ep, "w", encoding="utf-8"), separators=(",", ":"))
    print("WROTE %s: %d symbols, %.0f KB" % (os.path.normpath(ep), len(out), os.path.getsize(ep) / 1e3))


def write_meta(stats):
    """Tiny always-changing marker so feeds.json can watch pipeline liveness cheaply."""
    ist = datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)
    hist = load_hist()
    out = {
        "checked": ist.strftime("%Y-%m-%d %H:%M IST"),
        "cells": cells_of(hist),
        "quarters": {qe: n for qe, n, _ in stats},
    }
    json.dump(out, open(META_OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"WROTE {os.path.normpath(META_OUT)}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--hist" in args:  # write to an alternate history file (staging for conflict-free backfills)
        HIST = os.path.abspath(args[args.index("--hist") + 1])
        print("history file:", HIST)
    if "--apply-ledgers" in args:
        # Merge the BSE_HIST_LEDGERS into shp_history + rebuild both feeds, no network.
        # Idempotent (fill-only) — the normal path does this too, this is the offline entry point
        # used right after a backfill lands a new ledger.
        h = load_hist()
        before = cells_of(h)
        n = apply_bse_hist_ledger(h)
        apply_refine_ledger(h)
        apply_mf_heal_ledger(h)
        apply_ins_fill_ledger(h)
        apply_cell_fix(h)  # §22g per-cell corrections (load_hist applied them too)
        after = cells_of(h)
        if after < before:
            print("ABORT: history would shrink %d -> %d" % (before, after))
            sys.exit(1)
        save_hist(h)
        print("history: %d cells (%+d) after ledgers" % (after, after - before))
        build_feed()
        build_engine_feed()
    elif "--events" in args:
        # Ingest mid-quarter (event-driven) SHPs, then rebuild the engine feed so they are visible
        # to the backtest engines. --backfill N / --quarters walk older windows. (runbook §22k)
        n = TOPUP_QES
        if "--backfill" in args:
            n = int(args[args.index("--backfill") + 1])
        if "--quarters" in args:
            qes = [q.strip() for q in args[args.index("--quarters") + 1].split(",") if q.strip()]
        else:
            qes = last_qes(n)
        only = None
        if "--symbols" in args:
            only = {s.strip().upper() for s in args[args.index("--symbols") + 1].split(",") if s.strip()}
        print("event quarters:", ", ".join(qes))
        refresh_events(qes, only=only, reparse="--reparse" in args)
        build_engine_feed()
    elif "--feed-only" in args:
        build_feed()
        build_engine_feed()
    else:
        n = TOPUP_QES
        if "--backfill" in args:
            n = int(args[args.index("--backfill") + 1])
        if "--quarters" in args:
            qes = [q.strip() for q in args[args.index("--quarters") + 1].split(",") if q.strip()]
        else:
            qes = last_qes(n)
        print("quarter-ends:", ", ".join(qes))
        only = None
        if "--symbols" in args:
            only = {s.strip().upper() for s in args[args.index("--symbols") + 1].split(",") if s.strip()}
            print("symbols:", len(only))
        stats = refresh_quarters(qes, reparse="--reparse" in args, only=only, fill_shares="--fill-shares" in args)
        if "--hist" in args:
            print("(staging run — docs feed/meta NOT rebuilt)")
        else:
            build_feed()
            build_engine_feed()
            write_meta(stats)
