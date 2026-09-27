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
"""Shareholding (promoter / FII / DII / MF / insurance) and per-quarter SHARE COUNTS for every NSE-listed stock —
main board AND the SME platform — from NSE's own quarterly shareholding-pattern XBRL.  DATA_RUNBOOK §180.

Why this exists (user, 2026-09-26): "fill market cap and shareholding for all the stocks in our dashboard".
Measured on origin 47af401f1 before the fill (cells 2020Q1-2026Q2 vs quarters each stock traded):
  N500 99.2% · NSE main non-N500 94.7% · NSE SME 0.0% (548 symbols) · BSE-only 0.5% (2,179 symbols).
Share counts existed only as ONE latest number per symbol (shares_outstanding.json), so no stock had a
market-cap history.

Stages:
  master   <cache>/master/{equities,sme}_<QE>.json   NSE corporate-share-holdings-master, QE -> QE+180d filing
                                                     season, rows kept only when as-on == QE (§22 step 1)
  download <cache>/xbrl_nse_all/<SYM>_<QE>.xml.gz     every quarter-end filing listed; files already on disk
                                                     from earlier campaigns are REUSED, never re-downloaded
  build    scripts/shp_fill_allstocks.json.gz        fill ledger (BSE_HIST_LEDGERS, applied fill-only, LAST)
           scripts/_shp_allstocks_holds.json         every cell NOT written + the reason
           scripts/shares_history.json               {SYM: {QE: [shares, visible-date, src]}}
  The build stage is offline and read-only on the store; `fetch_shareholding.py --apply-ledgers` lands it.

Gates (each one names the past defect it prevents; checklist compiled from the runbook 2026-09-26):
  * parse = fetch_shareholding.parse_shp UNCHANGED (anchor ladder, partition [98,102], fii+dii <= pub+2,
    old-format +-0.35 reconciliation, 4dp share-count precision pass, DR line out of FII §151).
  * PROVEN ZERO (the only new rule): parse_shp refuses filings that carry no institution members at all,
    because "no institutions" and "unknown vintage" look alike (§22b — zero-DEFAULTING is forbidden). When
    the Public block's NumberOfShares EQUALS Non-institutions + Government (parent row) share for share, and
    promoter + public (+ the employee-trust / non-promoter-non-public bucket) is in [98,102], the document's own
    arithmetic (Public = Institutions + Government + Non-institutions, both the 2015 and the 2022 form) PROVES
    institutions = 0. Such a cell is written as fii = dii = mf = ins = 0 (zero_proof()).
    Hold-out test 2026-09-26 (see runbook §180): the equality never holds on any filing reporting an
    institutional holding; a 0.011pp percentage tolerance instead DID (59 filings holding 0.01-0.02%).
  * 2022-form filings whose public block does not close in SHARES (pub != inst-dom + inst-for + govt +
    non-inst) -> HOLD.
  * old-format (<= Jun-2022 submissions) filings carrying an institutional "Any Other" row or a
    non-institutional row LABELLED as a domestic/foreign institution (§158 R1/R2, §159) -> HOLD: the
    row-level placement heals exist only for Nifty-500 names and are not re-run here.
  * mf, ins <= dii + 0.05; prom + fii + dii <= 100.5.
  * nsh gate (§22g-2): shareholder count < 5% of the max over strictly earlier quarters -> HOLD (wrong class),
    unless the same filings show the share capital collapsing (insolvency capital reduction) or the symbol's event
    is on the cell_fix accept list -> the share-count-proven percentages are written WITHOUT the doubtful count.
  * continuity (§127g/§127j): fii > 5pp or dii > 10pp away from EVERY stored/candidate neighbour within two
    quarters -> HOLD; an exact 0 beside a neighbour > 1% without a partition proof -> HOLD.
  * date = the calendar day of NSE's broadcast (visible_iso, midnight rule §149), EXCEPT when the broadcast is a
    re-stamp of the original document (document created by the day after submission, broadcast more than two days
    after submission; §142h bulk re-stamps) -> the submission day. A document created after the submission is a
    re-filing and keeps its own broadcast day, so a re-filing's numbers are never served from the original's date
    (no look-ahead, §142j/§142k). Lag < 0 -> HOLD.
  * identity: the file's ISIN issuer (isin[:7]) must match an ISIN the symbol traded under (tape meta +
    the 2020+ bhavcopy symbol->ISIN map); the file's own Symbol tag, when present, must be the key or a
    rename-map relative of it. A quarter already stored under the key OR any former ticker (rename map +
    engine FUND_ALIAS) is skipped — never duplicated under a second key.
  * fill-only: a stored cell is never touched (the ledger mechanism enforces it too).
Share counts: parse_shares (whole-company NumberOfShares, fully-paid fallback), same identity gate; a count
that sits below 1/5 or above 5x BOTH neighbours within two quarters is HELD (stub / wrong-class filings).

Run:  python3 scripts/fetch_shp_allstocks.py master|download|build [--cache DIR]   (default cache ~/stocks-cache/shp/all_fill)
"""
import argparse
import collections
import datetime
import difflib
import gzip
import json
import os
import re
import statistics
import sys
import time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import contextlib

import fetch_shareholding as F  # noqa: E402

CACHE = os.path.expanduser("~/stocks-cache/shp/all_fill")
LEDGER = os.path.join(HERE, "shp_fill_allstocks.json.gz")
HOLDS = os.path.join(HERE, "_shp_allstocks_holds.json")
SHARES_HIST = os.path.join(HERE, "shares_history.json")


def _last_qe(today=None):
    """The latest quarter-end on or before today (IST): quarters the calendar has closed. Filings for it may still be
    arriving (SEBI deadline: 21 days), which the incremental `update` stage picks up run by run (§180e)."""
    d = today or (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).date()
    ends = [datetime.date(y, m, dd) for y in (d.year - 1, d.year) for m, dd in ((3, 31), (6, 30), (9, 30), (12, 31))]
    return max(e for e in ends if e <= d).isoformat()


FIRST_QE, LAST_QE = "2020-03-31", _last_qe()


def STRIP(t):
    return t.split("}", 1)[-1]


DOM_LBL = re.compile(
    r"QIB|qualified institutional|insurance|insurer|provident|pension|\bNPS\b|NBFC|non.?banking|"
    r"financial institution|\bbanks?\b|alternat\w* investment|\bAIF\b|mutual fund",
    re.IGNORECASE,
)
FOR_LBL = re.compile(
    r"\bFIIs?\b|\bFPIs?\b|foreign portfolio|foreign institution|\bQFI\b|FVCI|private equity|sovereign", re.IGNORECASE
)


def qes():
    out = []
    for y in range(2020, int(LAST_QE[:4]) + 1):
        for md in ("03-31", "06-30", "09-30", "12-31"):
            q = "%d-%s" % (y, md)
            if FIRST_QE <= q <= LAST_QE:
                out.append(q)
    return out


QES = qes()


GOV_PARENTS = (
    "GovernmentsMember",
    "GovermentsMember",
    "CentralGovernmentOrStateGovernmentSOrPresidentOfIndiaMember",
    "CentralGovernmentOrStateGovernmentSMember",
)
THIRD = (
    "SharesHeldByNonPromoterNonPublicShareholdersMember",
    "EmployeeBenefitsTrustsMember",
    "SharesHeldByEmployeeTrustsMember",
    "TradingMembersAndAssociatesOfTradingMembers",
)


INST_PARENTS = ("InstitutionsDomesticMember", "InstitutionsForeignMember", "InstitutionsMember")


def zero_proof(pct, shc):
    """True when the filing's own SHARE COUNTS prove that institutions hold nothing:
    Public == Non-institutions + Government (parent row only; its sub-rows would double count), share for share,
    and promoter + public + the non-promoter-non-public bucket closes to [98, 102]. Public is Institutions +
    Government + Non-institutions in both the 2015 and the 2022 form, so the equality leaves 0 for institutions."""
    prom = pct.get("ShareholdingOfPromoterAndPromoterGroupMember")
    pub = pct.get("PublicShareholdingMember")
    sp, sn = shc.get("PublicShareholdingMember"), shc.get("NonInstitutionsMember")
    if prom is None and sp and shc.get("ShareholdingPatternMember") == sp:
        prom = 0.0  # no promoter group: Public IS every share (share for share)
    if None in (prom, pub, sp, sn) or sp <= 0:
        return False
    # A filing that itself names institutional shares is never a proof of zero, whatever else it says (DELTA 539596
    # Jun/Sep-2024: Public == Non-institutions share for share, yet Institutions(Foreign) = 423,696 shares, 7.86 %).
    if any((shc.get(k) or 0) > 0 or (pct.get(k) or 0) > 0 for k in INST_PARENTS):
        return False
    # Government may sit in Public, or its tag may carry a PROMOTER stake (PSU / state co-promoter, TANFACIND), and a filing
    # can carry both (ELNET: CentralGovernmentOrStateGovernmentS = the promoter, Goverments = a public holding): the exact
    # identity Public == Non-institutions + SOME subset of the government tags present leaves nothing for institutions.
    govs = [shc.get(k, 0.0) for k in GOV_PARENTS if shc.get(k)]
    sums = {0.0}
    for g_ in govs:
        sums |= {x + g_ for x in sums}
    if not any(abs(sp - (sn + x)) < 0.5 for x in sums):
        return False  # share counts are integers
    tot = pct.get("ShareholdingPatternMember")
    third = max([pct.get(k, 0.0) for k in THIRD] + [0.0])
    a = tot if tot is not None else prom + pub + third
    sc = 100.0 if 0.9 <= a <= 1.1 else 1.0
    return 98.0 <= (prom + pub + third) * sc <= 102.0 or 98.0 <= (prom + pub) * sc <= 102.0


NAME_STOP = {"LIMITED", "LTD", "THE", "PVT", "PRIVATE", "CO", "COMPANY", "CORP", "CORPORATION", "INC"}


def cname_norm(x):
    x = re.sub(r"[^A-Z0-9 ]", " ", str(x or "").upper().replace("&", " AND "))
    return "".join(t for t in x.split() if t not in NAME_STOP)


def names_match(a, b):
    """Company-name identity for a filing whose ISIN field is a filer typo (§180c): equal after normalising case,
    punctuation, '&' and the legal suffix, or a >= 0.92 character match (spacing / abbreviation noise)."""
    A, B = cname_norm(a), cname_norm(b)
    return bool(A and B) and (A == B or difflib.SequenceMatcher(None, A, B).ratio() >= 0.92)


# ------------------------------------------------------------------------------------------ document analysis
def analyse(txt, qe):
    """-> dict(cell, fmt, zero_proof, partition_closes, ambiguity, flags, isin, symtag, shares, nsh)."""
    if isinstance(txt, str):
        txt = txt.encode("utf-8")
    head = txt[:8000].decode("utf-8", "ignore")
    m = re.search(r'xmlns:in-(?:bse-shp|capmkt)="([^"]+)"', head)
    schema = m.group(1) if m else ""
    root = ET.fromstring(txt)
    ctx = {}
    for c in root.iter():
        if STRIP(c.tag) != "context":
            continue
        mems, typed = [], False
        for x in c.iter():
            st = STRIP(x.tag)
            if st == "explicitMember":
                mems.append((x.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                typed = True
        ctx[c.get("id")] = (mems, typed)
    pct, shc, holders, symtag, isin, scrip, cname = {}, {}, {}, None, None, None, None
    inst_lbl, non_lbl = [], []
    for f in root.iter():
        t = STRIP(f.tag)
        if t == "Symbol" and f.text and not symtag:
            symtag = f.text.strip().upper()
        elif t == "ScripCode" and f.text and not scrip:
            scrip = f.text.strip()
        elif t == "ISIN" and f.text and not isin:
            isin = f.text.strip().upper()
        elif t == "NameOfTheCompany" and f.text and not cname:
            cname = f.text.strip()
        elif t == "CategoryOfOtherInstitutions" and f.text:
            inst_lbl.append(f.text.strip())
        elif (
            t
            in (
                "CategoryOfOtherNonInstitutions",
                "CategoryOfOtherIndianShareholders",
                "CategoryOfOtherForeignShareholders",
            )
            and f.text
        ):
            non_lbl.append(f.text.strip())
        elif t == "NumberOfShareholders":
            mems, typed = ctx.get(f.get("contextRef"), ([], True))
            if not typed and len(mems) == 1 and mems[0] in ("ShareholdingPatternMember", "PublicShareholdingMember"):
                with contextlib.suppress(TypeError, ValueError):
                    holders[mems[0]] = int(float(f.text))
        elif t in ("ShareholdingAsAPercentageOfTotalNumberOfShares", "NumberOfShares"):
            mems, typed = ctx.get(f.get("contextRef"), ([], True))
            if typed or len(mems) != 1:
                continue
            with contextlib.suppress(TypeError, ValueError):
                (pct if t.startswith("Share") else shc)[mems[0]] = float(f.text)
    mem = set(pct)
    fmt = (
        "new"
        if {"InstitutionsDomesticMember", "InstitutionsForeignMember"} & mem
        else ("old" if "InstitutionsMember" in mem else "unknown")
    )
    cell = F.parse_shp(root, qe)
    shares = F.parse_shares(root)
    out = {
        "fmt": fmt,
        "schema": schema,
        "isin": isin,
        "symtag": symtag,
        "scrip": scrip,
        "cname": cname,
        "shares": shares,
        "flags": [],
        "ambiguity": [],
        "zero_proof": False,
        "partition_closes": None,
        "cell": cell,
    }
    prom = pct.get("ShareholdingOfPromoterAndPromoterGroupMember")
    pub = pct.get("PublicShareholdingMember")
    tot = pct.get("ShareholdingPatternMember")
    pct.get("NonInstitutionsMember")

    def scale_of():
        a = tot if tot is not None else ((prom or 0) + (pub or 0))
        return 100.0 if 0.9 <= a <= 1.1 else 1.0

    sh_pub = shc.get("PublicShareholdingMember")
    out["_pct"], out["_shc"] = pct, shc  # kept for the hold-out test; dropped before output
    sh_tot, sh_prom = shc.get("ShareholdingPatternMember"), shc.get("ShareholdingOfPromoterAndPromoterGroupMember")
    if (
        cell is None
        and fmt == "unknown"
        and pub is None
        and sh_tot
        and sh_prom is not None
        and abs(sh_tot - sh_prom) < 0.5
    ):
        # §180c: promoters hold EVERY share (pre-listing / no public float: BGIL, ISERA 2022-23): no public block, so no
        # institutions — proven by the share counts themselves
        out["zero_proof"] = True
        out["cell"] = {"prom": 100.0, "pub": 0.0, "fii": 0.0, "dii": 0.0, "mf": 0.0, "ins": 0.0}
        nsh = holders.get("ShareholdingPatternMember")
        if nsh and nsh > 0:
            out["cell"]["nsh"] = nsh
    if cell is None and fmt == "unknown" and not out["zero_proof"] and zero_proof(pct, shc):
        s = scale_of()
        out["zero_proof"] = True
        p_ = prom if prom is not None else 0.0  # zero_proof proved a promoter-less company
        out["cell"] = {
            "prom": round(p_ * s, 4),
            "pub": round(pub * s, 4),
            "fii": 0.0,
            "dii": 0.0,
            "mf": 0.0,
            "ins": 0.0,
        }
        # shareholder count, same rule as parse_shp: whole-company count, dropped when below the public count
        nsh, nsh_pub = holders.get("ShareholdingPatternMember"), holders.get("PublicShareholdingMember")
        if nsh and nsh > 0 and not (nsh_pub and nsh < nsh_pub):
            out["cell"]["nsh"] = nsh
    if fmt == "new" and sh_pub is not None:
        blocks = (
            "InstitutionsDomesticMember",
            "InstitutionsForeignMember",
            "CentralGovernmentOrStateGovernmentSOrPresidentOfIndiaMember",
            "CentralGovernmentOrStateGovernmentSMember",
            "GovernmentsMember",
            "GovermentsMember",
            "NonInstitutionsMember",
        )
        no_gov = [k for k in blocks if k not in GOV_PARENTS]
        # Government tags sit in either block: a PSU's promoter stake under one tag, a public-side government holding under
        # another (GUJSTATFIN: CentralGovernmentOrStateGovernmentS 49,090,400 = the promoter; Goverments 3,742,400 = public).
        # Public closes when the non-government blocks plus SOME subset of the government tags present equal it share for share.
        gov_present = [k for k in GOV_PARENTS if shc.get(k)]
        base = sum(shc.get(k, 0.0) for k in no_gov)
        subsets = [[]]
        for g_ in gov_present:
            subsets += [[*x, g_] for x in subsets]
        out["partition_closes"] = any(abs(sh_pub - base - sum(shc.get(g_, 0.0) for g_ in sub)) < 0.5 for sub in subsets)
    if fmt == "old" and shc.get("InstitutionsMember") is not None:
        # §180c old-format split proof: the institutions total equals its sub-rows share for share, so a side whose rows are
        # all empty is PROVEN to hold nothing (APLAB Jun-2022: 2,300 shares, all MutualFundsOrUti -> no FPI).
        f_rows = ("InstitutionsForeignPortfolioInvestorMember", "ForeignVentureCapitalInvestorsMember")
        d_rows = (
            "MutualFundsOrUtiMember",
            "MutualFundsOrUTIMember",
            "AlternativeInvestmentFundsMember",
            "VentureCapitalFundsMember",
            "FinancialInstitutionOrBanksMember",
            "ProvidentFundsOrPensionFundsMember",
            "InsuranceCompaniesMember",
            "OtherInstitutionsMember",
        )
        fs, ds = sum(shc.get(k, 0.0) for k in f_rows), sum(shc.get(k, 0.0) for k in d_rows)
        out["old_split"] = {"closes": abs(shc["InstitutionsMember"] - fs - ds) < 0.5, "fii_rows": fs, "dii_rows": ds}
    if fmt == "old":
        o_other = pct.get("OtherInstitutionsMember") or 0.0
        if o_other or inst_lbl:
            out["ambiguity"].append(f"R1 institutional Any-Other {o_other:.4f} {inst_lbl[:3]}")
        for l in sorted(set(non_lbl)):
            if DOM_LBL.search(l):
                out["ambiguity"].append("R2 non-institution row labelled domestic institution: " + l)
            elif FOR_LBL.search(l):
                out["ambiguity"].append("R2-FII non-institution row labelled foreign institution: " + l)
    return out


# ------------------------------------------------------------------------------------------ inputs
def load_inputs(cache):
    hist = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))
    rename = json.load(open(os.path.join(HERE, "_rename_map.json"), encoding="utf-8"))
    js = open(os.path.join(REPO, "docs", "backtest-engine.js"), encoding="utf-8").read()
    m = re.search(r"const FUND_ALIAS\s*=\s*(\{.*?\});", js, re.DOTALL)
    fund_alias = json.loads(m.group(1)) if m else {}
    # §197: a BSE-only ticker that is also a FORMER NSE ticker of another company (docs/bse_alias_collisions.json —
    # WORTH = Worth Investment, NSE's WORTH -> WORTHPERI) is not a relative of that company: the rename edges on it are
    # NSE facts. Linking them made every WORTH quarter "stored under a former ticker" (WORTHPERI's) and never fetched.
    try:
        coll = set(
            json.load(open(os.path.join(REPO, "docs", "bse_alias_collisions.json"), encoding="utf-8"))["collisions"]
        )
    except Exception as e:
        sys.exit(f"ABORT: docs/bse_alias_collisions.json unreadable ({e})")
    rel = collections.defaultdict(set)  # every rename relative of a symbol
    for mp in (rename, fund_alias):
        for old, new in mp.items():
            if isinstance(new, str) and new != old and old not in coll and new not in coll:
                rel[old].add(new)
                rel[new].add(old)

    def relatives(sym):
        seen, todo = {sym}, [sym]
        while todo:
            for n in rel.get(todo.pop(), ()):
                if n not in seen:
                    seen.add(n)
                    todo.append(n)
        return seen - {sym}

    isins = collections.defaultdict(set)
    # symbol -> ISIN sources; a GitHub runner passes the survivorship-free tape (release asset `data/sf_stock_data.bin`,
    # meta[sym].isin, rebuilt daily) via SHP_ISIN_TAPE and has no ~/stocks-cache (§180e)
    p = os.environ.get("SHP_NSE_SYM_ISIN") or os.path.join(
        HERE, "_nse_sym_isin_2020.json"
    )  # committed copy (NSE symbol -> ISINs since 2020)
    if not os.path.exists(p):
        p = os.path.expanduser("~/stocks-cache/univ/nse_sym_isin_2020.json")
    if os.path.exists(p):
        for s, lst in json.load(open(p)).items():
            isins[s.upper()] |= {i.upper() for i in lst}
    p = os.environ.get("SHP_ISIN_TAPE") or os.path.expanduser("~/stocks-cache/univ/sf_recent_now.bin")
    if os.path.exists(p):
        tape = json.loads(gzip.open(p).read())
        for s, mt in (tape.get("meta") or {}).items():
            if mt.get("isin"):
                isins[s.upper()].add(str(mt["isin"]).upper())
    man = {}
    for mp in ("manifest_nse.json", "manifest_nse_all.json"):
        f = os.path.join(cache, mp)
        if os.path.exists(f):
            for k, v in json.load(open(f)).items():
                if "error" in v:
                    continue
                if k in man and mp == "manifest_nse_all.json" and v.get("reused"):
                    continue
                path = v.get("path") or os.path.join(cache, "xbrl_nse", k.replace("|", "_") + ".xml")
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    man[k] = dict(v, path=path)
    return hist, relatives, isins, man


def read_doc(path):
    b = open(path, "rb").read()
    return gzip.decompress(b) if path.endswith(".gz") else b


# ------------------------------------------------------------------------------------------ master + download
def stage_master(cache):
    import build_fundamentals as B

    jar = B.nse_jar()
    os.makedirs(os.path.join(cache, "master"), exist_ok=True)
    for idx in ("equities", "sme"):
        for qe in QES:
            fn = os.path.join(cache, "master", f"{idx}_{qe}.json")
            if os.path.exists(fn) and qe < QES[-1]:
                continue  # the newest season keeps filling
            recs = None
            for _attempt in range(3):
                try:
                    recs = F.fetch_master(jar, qe, index=idx)
                    break
                except Exception as e:
                    print(f"  retry {idx} {qe}: {e}")
                    time.sleep(3)
            if recs is None:
                print(f"FAILED master {idx} {qe}")
                continue
            json.dump(recs, open(fn, "w"))
            print(
                "master %s %s: %d rows, %d as-on this quarter"
                % (idx, qe, len(recs), sum(1 for r in recs if F.iso_date(r.get("date")) == qe))
            )
            time.sleep(0.4)


def stage_download(cache, workers=4):
    import threading
    import traceback
    from concurrent.futures import ThreadPoolExecutor, as_completed

    import build_fundamentals as B

    M, X, MP = (
        os.path.join(cache, "master"),
        os.path.join(cache, "xbrl_nse_all"),
        os.path.join(cache, "manifest_nse_all.json"),
    )
    os.makedirs(X, exist_ok=True)
    have = {}  # reuse every file an earlier pass already holds
    d1 = os.path.join(cache, "xbrl_nse")
    if os.path.isdir(d1):
        for f in os.listdir(d1):
            if os.path.getsize(os.path.join(d1, f)) > 0:
                s_, q_ = f[:-4].rsplit("_", 1)
                have[f"{s_}|{q_}"] = os.path.join(d1, f)
    idx2 = os.path.join(cache, "xbrl_nse2_index.json")  # FII session's NSE cache, indexed by Symbol/as-on
    if os.path.exists(idx2):
        base = os.path.expanduser("~/stocks-cache/shp/fii_session/shp_src/xbrl_nse2")
        for f, (s_, isin_, q_) in json.load(open(idx2)).items():
            if s_ and q_:
                have.setdefault(f"{s_}|{q_}", os.path.join(base, f))
    want = {}
    for f in sorted(os.listdir(M)):
        idx, qe = f[:-5].split("_", 1)
        if qe not in QES:
            continue
        for r in json.load(open(os.path.join(M, f))):
            sym = str(r.get("symbol") or "").upper().strip()
            if F.iso_date(r.get("date")) != qe or not sym or not str(r.get("xbrl") or "").startswith("http"):
                continue
            k, sub = f"{sym}|{qe}", F.visible_iso(r) or ""
            if k not in want or sub >= want[k]["sub"]:
                want[k] = {
                    "url": r["xbrl"],
                    "sub": sub,
                    "submissionDate": r.get("submissionDate"),
                    "broadcastDate": r.get("broadcastDate"),
                    "revised": str(r.get("revisedData") or ""),
                    "idx": idx,
                }
    man = json.load(open(MP)) if os.path.exists(MP) else {}
    for k, v in want.items():
        if k in have and k not in man:
            man[k] = dict(v, path=have[k], reused=True)
    todo = [(k, v) for k, v in want.items() if k not in man or "error" in man[k]]
    print(
        "download: %d listed, %d reused from disk, %d to fetch"
        % (len(want), sum(1 for k in want if k in have), len(todo))
    )
    jar = B.nse_jar()
    lk = threading.Lock()
    fail = []

    def one(k, v):
        last = None
        for attempt in range(3):
            try:
                b = F.fetch_xbrl(v["url"], jar)
                b = b.encode("utf-8") if isinstance(b, str) else b
                if len(b) < 2000 or b"Shareholding" not in b:
                    raise ValueError("short/odd body %d" % len(b))
                path = os.path.join(X, k.replace("|", "_") + ".xml.gz")
                open(path, "wb").write(gzip.compress(b))
                return dict(v, path=path, bytes=len(b))
            except Exception as e:
                last = f"{type(e).__name__}: {str(e)[:100]}"
                if "404" in last:
                    break
                time.sleep(1 + attempt)
        return dict(v, error=last)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(one, k, v): k for k, v in todo}
        for n, fut in enumerate(as_completed(futs), 1):
            k = futs[fut]
            try:
                v = fut.result()
            except Exception:
                v = {"error": traceback.format_exc()[-150:]}
            with lk:
                man[k] = v
                if "error" in v:
                    fail.append(k)
                if n % 1000 == 0:
                    json.dump(man, open(MP, "w"))
                    print("  %d/%d (%d failed)" % (n, len(todo), len(fail)))
    json.dump(man, open(MP, "w"))
    print(
        "download done: %d fetched, %d failed (404 = NSE lists the filing but serves no file)"
        % (len(todo) - len(fail), len(fail))
    )


# ------------------------------------------------------------------------------------------ BSE stage (runbook §180b)
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}
QE_DAY = {3: "03-31", 6: "06-30", 9: "09-30", 12: "12-31"}


def bse_label_qe(label):
    """'June 2026' -> '2026-06-30'; event labels ('07 Jul 2026') and anything else -> None."""
    m = re.fullmatch(
        r"(January|February|March|April|May|June|July|August|September|October|November|December) (\d{4})",
        str(label or "").strip(),
    )
    if not m or MONTHS[m.group(1)] not in QE_DAY:
        return None
    return f"{m.group(2)}-{QE_DAY[MONTHS[m.group(1)]]}"


def bse_pick(rows):
    """{QE: row} — per quarter-end the ORIGINAL filing ('New', earliest filing_date_time); a quarter whose only rows are
    revisions takes the earliest revision (BSE sometimes keeps only the revision, §164b). Each picked row gains _date
    (calendar day of its own timestamp) and _kind."""
    by = collections.defaultdict(list)
    for r in rows or []:
        qe = bse_label_qe(r.get("qtr"))
        xf = str(r.get("XbrlFile") or "").strip()
        if not qe or not xf.lower().endswith(".xml") or not (FIRST_QE <= qe <= LAST_QE):
            continue
        by[qe].append(r)
    out = {}
    for qe, rs in by.items():
        new = sorted(
            [r for r in rs if str(r.get("status")) == "New" and r.get("filing_date_time")],
            key=lambda r: r["filing_date_time"],
        )
        if new:
            r = dict(new[0])
            r["_date"] = str(new[0]["filing_date_time"])[:10]
            r["_kind"] = "original"
        else:
            rev = sorted([r for r in rs if r.get("revised_date_time")], key=lambda r: r["revised_date_time"])
            if not rev:
                continue
            r = dict(rev[0])
            r["_date"] = str(rev[0]["revised_date_time"])[:10]
            r["_kind"] = "revision-only"
        out[qe] = r
    return out


def stage_bse(cache, cap=20000, shard="0/1", max_minutes=0, codes_file=None):
    """ONE request at a time (runbook §181): per target scrip, the SHPQNewFormat list on api.bseindia.com, then only the
    quarter-end XBRL files the store lacks from www.bseindia.com/XBRLFILES. Largest companies first; resumable (lists and
    files already on disk are never fetched again); stops after repeated refusals instead of retrying fast."""
    import urllib.error
    import urllib.request

    import bse_headers

    T = json.load(open(os.path.join(cache, "bse_targets.json")))
    LD, XD = os.path.join(cache, "bse_lists_v2"), os.path.join(cache, "xbrl_bse_v2")
    os.makedirs(LD, exist_ok=True)
    os.makedirs(XD, exist_ok=True)
    hist, relatives, _isins, _man = load_inputs(cache)
    try:
        d = json.loads(gzip.open(os.path.join(REPO, "docs", "stock_data.bin")).read())
        mc = {m.get("symbol"): (m.get("mcap") or 0) for k, m in d["meta"].items() if k.endswith(".BO")}
    except Exception:
        mc = {}
    codes = sorted((c for c, v in T.items() if not v.get("isin_conflict")), key=lambda c: -(mc.get(T[c]["sym"]) or 0))
    if codes_file:  # a later round: only the codes a list names
        want = {str(c) for c in json.load(open(codes_file))}
        codes = [c for c in codes if c in want]
    k_, n_ = (int(x) for x in shard.split("/"))
    codes = [c for c in codes if int(c) % n_ == k_]  # deterministic split across machines (--shard k/n)
    log = open(os.path.join(cache, "bse_stage.log"), "a")

    def say(*a):
        print(time.strftime("%H:%M:%S"), *a, file=log, flush=True)

    fails, n_req, n_files, n_lists = 0, 0, 0, 0

    def get(url, kind):
        nonlocal fails, n_req
        for _attempt in range(2):
            n_req += 1
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    b = r.read()
                ok = (b[:1] in (b"{", b"[")) if kind == "list" else (b"xbrl" in b[:4000].lower() and len(b) > 1500)
                if ok:
                    fails = 0
                    time.sleep(0.6)
                    return b
                why = "not %s (%d bytes)" % (kind, len(b))
            except urllib.error.HTTPError as e:
                why = "HTTP %d" % e.code
                if e.code == 404:
                    time.sleep(0.6)
                    return None
            except Exception as e:
                why = f"{type(e).__name__}: {str(e)[:60]}"
            fails += 1
            say("refused/failed", url.rsplit("/", 1)[-1], why)
            if fails >= 3:
                say("3 refusals in a row -> pausing 10 min")
                time.sleep(600)
                if fails >= 6:
                    raise SystemExit("BSE refusing repeatedly; stopped (resume later, nothing is lost)")
            time.sleep(2)
        return None

    say("start: %d target scrips (shard %s), cap %d files" % (len(codes), shard, cap))
    t_end = time.time() + max_minutes * 60 if max_minutes else None
    for i, code in enumerate(codes):
        if t_end and time.time() > t_end:
            say("time limit reached — stopping cleanly")
            return
        sym = T[code]["sym"]
        lp = os.path.join(LD, code + ".json")
        if not os.path.exists(lp):
            b = get(f"https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode={code}", "list")
            if b is None:
                say("no list", code, sym)
                continue
            open(lp, "wb").write(b)
            n_lists += 1
        try:
            rows = json.load(open(lp)).get("Table") or []
        except Exception:
            say("bad list json", code)
            continue
        fam = {sym} | relatives(sym)
        for qe, r in sorted(bse_pick(rows).items(), reverse=True):
            if any(qe in (hist.get(x) or {}) for x in fam):
                continue  # only what is missing
            xf = r["XbrlFile"].strip()
            xp = os.path.join(XD, xf + ".gz")
            if os.path.exists(xp):
                continue
            if n_files >= cap:
                say("per-run cap reached")
                return
            b = get("https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + xf, "xbrl")
            if b:
                open(xp, "wb").write(gzip.compress(b))
                n_files += 1
        if (i + 1) % 50 == 0:
            say("progress %d/%d scrips, %d lists, %d files, %d requests" % (i + 1, len(codes), n_lists, n_files, n_req))
    say("DONE %d scrips, %d lists, %d files, %d requests" % (len(codes), n_lists, n_files, n_req))


# ------------------------------------------------------------------------------------------ row-level stage (§180c)
ROWLEVEL = os.path.join(HERE, "_shp_allstocks_rowlevel.json")
GENERIC_LBL = re.compile(r"(?i)(no typed rows|any other|others?|other institutions?|)")


def stage_rowlevel(cache):
    """Row-level placement for old-format (Dec-2015..Jun-2022 form) filings the build HELD as ambiguous (institutional
    "Any Other" row, or a non-institution row labelled as an institution). Runs the SAME functions the Nifty-500 heals use,
    unchanged: §158 R1-R3 + §158a rest-follows (_shp_dii_rowfix.eval_filing), §159 R2-FII (_shp_fii_rowfix.eval_fii) and
    §164 D1 unnamed-remainder -> FII (_shp_d1_rowfix.d1_delta), with the filer's own first 2022-form filing as the holder
    map and the two-pass holder memory (newest first warms, chronological pass is final). A held quarter has no stored row,
    so the starting point is the raw reading of the held file itself (Any-Other in dii, the parser's default).
    Output: scripts/_shp_allstocks_rowlevel.json {"SYM|QE": {file, status, fii, dii, ins, parts, ev}}; the build applies a
    "resolved" entry only to the SAME file and then runs every other gate on the result."""
    import _shp_d1_rowfix as D1  # imports _shp_dii_rowfix / _shp_fii_rowfix read-only

    D, X = D1.D, D1.X
    holds = json.load(open(HOLDS, encoding="utf-8"))["holds"]
    want = {
        (s_, q_): v
        for s_, qs in holds.items()
        for q_, v in qs.items()
        if isinstance(v, dict) and str(v.get("why", "")).startswith("old-format row")
    }
    # cells an earlier run resolved are no longer in the holds file (the build applied them): keep re-evaluating them,
    # or the next build would lose their placement
    if os.path.exists(ROWLEVEL):
        for k_, e_ in (json.load(open(ROWLEVEL, encoding="utf-8")).get("cells") or {}).items():
            s_, q_ = k_.split("|")
            if (s_, q_) not in want and e_.get("file"):
                want[(s_, q_)] = {
                    "src": e_.get("src")
                    or ("bsexbrl:" + e_["file"] if not e_["file"].startswith("SHP_") else "nse:" + e_["file"])
                }
    T = json.load(open(os.path.join(cache, "bse_targets.json")))
    code_of = {v["sym"]: c for c, v in T.items()}
    man = json.load(open(os.path.join(cache, "manifest_nse_all.json")))
    LD, XD = os.path.join(cache, "bse_lists_v2"), os.path.join(cache, "xbrl_bse_v2")
    plain = os.path.join(cache, "rowlevel_xml")
    os.makedirs(plain, exist_ok=True)
    D.CACHES[:] = [plain]  # find_file() looks here (plain XML, as the heal tools expect)
    hist = json.load(open(os.path.join(HERE, "shp_history.json"), encoding="utf-8"))
    fills_led = json.load(gzip.open(LEDGER, "rt", encoding="utf-8")).get("fills", {}) if os.path.exists(LEDGER) else {}
    verdicts = D.load_verdicts()

    def held_doc(sym, qe, src):
        kind, f = src.split(":", 1)
        f = f.split()[0]
        path = os.path.join(XD, f + ".gz") if kind == "bsexbrl" else (man.get(f"{sym}|{qe}") or {}).get("path")
        return f, (read_doc(path) if path and os.path.exists(path) else None)

    out, st, sym_inputs = {}, collections.Counter(), {}
    for sym in sorted({s_ for s_, q_ in want}):
        code = code_of.get(sym)
        lp = os.path.join(LD, f"{code}.json") if code else None
        bse_rows = (json.load(open(lp)).get("Table") or []) if lp and os.path.exists(lp) else []
        for r in bse_rows:  # plain copies of this scrip's cached filings
            xf = str(r.get("XbrlFile") or "").strip()
            if xf and os.path.exists(os.path.join(XD, xf + ".gz")) and not os.path.exists(os.path.join(plain, xf)):
                open(os.path.join(plain, xf), "wb").write(read_doc(os.path.join(XD, xf + ".gz")))
        byq = D.quarter_files(bse_rows)
        ctx, fctx = D.SymCtx(sym, bse_rows, verdicts), X.FiiCtx(sym, bse_rows, verdicts)
        sym_inputs[sym] = (bse_rows, byq)
        quarters = sorted(set(byq) | {q_ for s_, q_ in want if s_ == sym})
        for qe, final in [(q_, False) for q_ in reversed(quarters)] + [(q_, True) for q_ in quarters]:
            key = (sym, qe)
            if key in want:
                f, txt = held_doc(sym, qe, want[key]["src"])
                if txt is None:
                    if final:
                        out["{}|{}".format(*key)] = {"status": "file not cached"}
                        st["file not cached"] += 1
                    continue
                bd = D.breakdown(txt)
                res = F.parse_shp(txt, qe)
                if not res:
                    if final:
                        out["{}|{}".format(*key)] = {"file": f, "status": "parse refused"}
                        st["parse refused"] += 1
                    continue
                cur = [res["prom"], res["fii"], res["dii"], res.get("mf"), res.get("ins"), None, None]
            else:
                cur = (hist.get(sym) or {}).get(qe)
                if not cur:
                    continue
                ch = D.match_filing(byq.get(qe, []), qe, cur)
                if not ch:
                    continue
                f, txt, bd, res = ch
            r = D.eval_filing(ctx, qe, txt, bd, res, cur, final, None, 0.0, 0.0)
            rf = X.eval_fii(fctx, qe, txt, bd, res, cur)
            if not final or key not in want:
                continue
            if r is None:
                out["{}|{}".format(*key)] = {"file": f, "status": "split unknown"}
                st["split unknown"] += 1
                continue
            if r.get("overflow"):
                out["{}|{}".format(*key)] = {
                    "file": f,
                    "status": "rows claim more than the block (R1 overflow)",
                    "ev": [str(e) for e in r["ev"]],
                }
                st["R1 overflow"] += 1
                continue
            ev = list(r["ev"])
            mv159 = rf["mv"] if not any(e[0] == "R2FII-overflow" for e in rf["ev"]) else 0.0
            if mv159 >= 0.005:
                ev += rf["ev"]
            dd = 0.0
            if qe >= D1.D1_FROM:
                dd, dev = D1.d1_delta(r, bd, res, cur, 0.0, 0.0)
                dd = min(dd, r["t_dii"])
                # a LABELLED row R1 could not class (Bodies Corporate, HUF, Clearing Member, Trust ...) is not an unnamed
                # remainder: it stays where the filer put it (Institutions, i.e. dii) — COSYN Jun-2022, whose Sep-2022 2022-form
                # filing keeps the same shares in Institutions (Domestic)
                lab_unres = sum(
                    float(e[2])
                    for e in r["ev"]
                    if e[0] == "R1-unresolved" and not GENERIC_LBL.fullmatch(str(e[1]).strip())
                )
                # a NAMED holder of unknown class under an unclassed label ("R1-named-unresolved-kept": SAMTELIN's I L AND FS
                # TRUST CO. LTD. 9.39 under "Bodies Corporate") stays where the filer put it — D1 moves only UNNAMED shares
                lab_unres += sum(float(e[2]) for e in r["ev"] if e[0] == "R1-named-unresolved-kept")
                dd = max(0.0, round(dd - lab_unres, 4))
                if dd >= 0.005:
                    ev += dev
                if lab_unres >= 0.005:
                    ev.append(("labelled rows kept in dii (not an unnamed remainder)", round(lab_unres, 4)))
            ins = res.get("ins")
            if r["add_ins"] > 0 and ins is not None:
                ins = round(r["ins_base"] + r["add_ins"], 4)
            out["{}|{}".format(*key)] = {
                "file": f,
                "src": want[key]["src"],
                "status": "pending",
                "raw": [round(x, 4) if isinstance(x, float) else x for x in cur[:5]],
                "fii_r": r["t_fii"],
                "dii_r": r["t_dii"],
                "m159": round(mv159, 4) if mv159 >= 0.005 else 0.0,
                "m159_labels": sorted({str(e[1]) for e in rf["ev"] if e[0] == "R2FII-label"}) if mv159 >= 0.005 else [],
                "d1": dd if dd >= 0.005 else 0.0,
                "ins": ins,
                "newmap_file": ctx.newfile,
                "ev": [str(e) for e in ev],
            }
            st["evaluated"] += 1

    # ---- the two CONVENTION moves (§159 R2-FII on an FPI-labelled non-institution row, §164c D1 unnamed remainder) are
    # taken only where the company's OWN first 2022-form filing shows where those shares sit: the form has separate
    # Institutions (Domestic) / (Foreign) blocks, so the Jun-2022 -> Sep-2022 seam is the filer's own classification.
    # Measured 2026-09-27 on these held filings: taken blindly, the two rules moved shares to FII that the filer's next
    # filing keeps outside it for 13 companies (KUNSTOFF's 0.86 % "FPI (Category III)" row sits under non-institutions in
    # its 2022-form filings too; TEAM24's unnamed 0.11 stays domestic) -> a fake FII exit at the seam. Earlier quarters take
    # the seam's decision only while the moved amount is unchanged; anything unconfirmed stays HELD.
    def store_or_fill(s_, q_):
        return (hist.get(s_) or {}).get(q_) or (fills_led.get(s_) or {}).get(q_)

    def seam_components(sym, inputs, qe):
        bse_rows, byq = inputs
        fl = byq.get(qe) or []
        for _fd, f in fl:
            if not D.find_file(f):
                try:
                    import urllib.request

                    b = urllib.request.urlopen(
                        "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + f, timeout=60
                    ).read()
                    time.sleep(0.8)
                    if b"xbrl" in b[:4000].lower():
                        open(os.path.join(plain, f), "wb").write(b)
                except Exception as e:
                    print("  seam fetch failed", sym, f, type(e).__name__)
            p_ = D.find_file(f)
            if not p_:
                continue
            txt = open(p_, "rb").read()
            bd = D.breakdown(txt)
            res = F.parse_shp(txt, qe)
            if not res or "InstitutionsMember" not in bd:
                continue
            cur = [res["prom"], res["fii"], res["dii"], res.get("mf"), res.get("ins"), None, None]
            c1, c2 = D.SymCtx(sym, bse_rows, verdicts), X.FiiCtx(sym, bse_rows, verdicts)
            r = D.eval_filing(c1, qe, txt, bd, res, cur, True, None, 0.0, 0.0)
            rf = X.eval_fii(c2, qe, txt, bd, res, cur)
            if r is None or r.get("overflow"):
                return None
            mv = rf["mv"] if not any(e[0] == "R2FII-overflow" for e in rf["ev"]) else 0.0
            dd, _ = D1.d1_delta(r, bd, res, cur, 0.0, 0.0)
            dd = min(dd, r["t_dii"])
            lab = sum(
                float(e[2]) for e in r["ev"] if e[0] == "R1-unresolved" and not GENERIC_LBL.fullmatch(str(e[1]).strip())
            )
            lab += sum(float(e[2]) for e in r["ev"] if e[0] == "R1-named-unresolved-kept")
            dd = max(0.0, round(dd - lab, 4))
            return {
                "seam_only": True,
                "fii_r": r["t_fii"],
                "dii_r": r["t_dii"],
                "m159": round(mv, 4) if mv >= 0.005 else 0.0,
                "m159_labels": sorted({str(e[1]) for e in rf["ev"] if e[0] == "R2FII-label"}) if mv >= 0.005 else [],
                "d1": dd if dd >= 0.005 else 0.0,
            }
        return None

    for sym in sorted({k.split("|")[0] for k in out}):
        cells = {k.split("|")[1]: v for k, v in out.items() if k.split("|")[0] == sym and v.get("status") == "pending"}
        if not cells:
            continue
        decided = {}  # component -> (destination, amount at the seam)
        L = max(cells)
        E = store_or_fill(sym, "2022-09-30")
        seam_cell = cells[L] if L == "2022-06-30" else None
        if E and seam_cell is None and L < "2022-06-30" and sym in sym_inputs:
            # the held chain ends before Jun-2022 (that quarter is stored): read the stored quarter's own filing for the seam
            seam_cell = seam_components(sym, sym_inputs[sym], "2022-06-30")
            if seam_cell:
                cells = dict(cells, **{"2022-06-30": seam_cell})
                L = "2022-06-30"
        if E and seam_cell:
            c = seam_cell
            fb, db, m, d = c["fii_r"], c["dii_r"], c["m159"], c["d1"]

            # m159 (an FPI-labelled NON-institution row): stays public, or fii.  d1 (unnamed institutional remainder): stays
            # dii, fii, or public — ALNATRD's filer lists its whole 27.35 % public float as institutional "Any Other" until
            # Jun-2022 and, promoter unchanged, under Non-institutions from Sep-2022: those shares were never institutional.
            def at(md, dd_):
                f_ = fb + (m if md == "fii" else 0) + (d if dd_ == "fii" else 0)
                d_ = db - (d if dd_ in ("fii", "public") else 0)
                return abs(E[1] - f_) + abs(E[2] - d_)

            variants = {
                (md, dd_): at(md, dd_)
                for md in (("stay", "fii") if m else ("stay",))
                for dd_ in (("stay", "fii", "public") if d else ("stay",))
            }
            best = sorted(variants.items(), key=lambda x: x[1])
            amt = min([x for x in (m, d) if x] or [0.0])
            if best and best[0][1] <= 0.05 + 0.1 * (m + d) and (len(best) == 1 or best[1][1] - best[0][1] >= 0.5 * amt):
                (md, dd_), _err = best[0]
                if m:
                    decided["m159"] = (md, m)
                if d:
                    decided["d1"] = (dd_, d)
        live = dict(decided)
        seam_labels = (seam_cell or {}).get("m159_labels") or []
        for q in sorted(cells, reverse=True):
            c = cells[q]
            ok, note = True, []
            if c.get("seam_only"):
                continue
            fii, dii = c["fii_r"], c["dii_r"]
            for comp in ("m159", "d1"):
                amt = c[comp]
                if not amt:
                    continue
                dec = live.get(comp)
                same_row = comp == "m159" and dec is not None and seam_labels and c.get("m159_labels") == seam_labels
                if dec is None or (not same_row and abs(amt - dec[1]) > max(0.02, 0.03 * dec[1])):
                    ok = False
                    live.pop(comp, None)
                    note.append(f"{comp} {amt:.4f} unconfirmed by the 2022-form seam")
                    continue
                if dec[0] == "fii":
                    fii += amt
                    dii -= amt if comp == "d1" else 0.0
                    note.append(f"{comp} {amt:.4f} -> fii (seam-confirmed)")
                elif dec[0] == "public":
                    dii -= amt
                    note.append(
                        f"{comp} {amt:.4f} -> public (seam: the filer's 2022 form lists it under Non-institutions)"
                    )
                else:
                    note.append(f"{comp} {amt:.4f} stays (the 2022-form seam keeps it where the raw reading has it)")
            parts = (
                ["R1-R3 (§158)"]
                + (["R2-FII (§159)"] if c["m159"] and decided.get("m159", ("stay",))[0] == "fii" else [])
                + (
                    ["D1 unnamed remainder -> FII (§164c)"]
                    if c["d1"] and decided.get("d1", ("stay",))[0] == "fii"
                    else []
                )
                + (
                    ["unnamed remainder -> public (seam)"]
                    if c["d1"] and decided.get("d1", ("stay",))[0] == "public"
                    else []
                )
            )
            if ok:
                c.update(
                    status="resolved", fii=round(max(fii, 0.0), 4), dii=round(max(dii, 0.0), 4), parts=parts, seam=note
                )
                st["resolved"] += 1
            else:
                c.update(status="convention move unconfirmed", seam=note)
                st["held: convention move unconfirmed"] += 1
    json.dump(
        {
            "_meta": {"built": time.strftime("%Y-%m-%d %H:%M IST"), "rule": stage_rowlevel.__doc__.split(". ")[0]},
            "cells": out,
        },
        open(ROWLEVEL, "w", encoding="utf-8"),
        indent=0,
        ensure_ascii=False,
    )
    print("ROWLEVEL %d held old-format cells: %s" % (len(want), dict(st)))


# ------------------------------------------------------------------------------------------ incremental update (§180e)
HONEST_UA = (
    "stocks-dashboard-research/1.0"  # our own name; NSE's master API and nsearchives serve it (measured 2026-09-27)
)
MASTER_WINDOW_DAYS = 200


def window_qes(n=2, today=None):
    """The last n quarter-ends the calendar has closed — the quarters whose filings can still be arriving."""
    last = _last_qe(today)
    out = []
    y, m = int(last[:4]), int(last[5:7])
    for _ in range(n):
        out.append("%d-%s" % (y, {3: "03-31", 6: "06-30", 9: "09-30", 12: "12-31"}[m]))
        m -= 3
        if m == 0:
            m, y = 12, y - 1
    return sorted(out)


def stage_update(cache, quarters=None, max_minutes=0):
    """§180e — keep the all-stocks fill current for the companies the daily job does not fetch holdings for: NSE SME
    (the daily SME pass banks share counts only) and BSE-only companies (nothing daily). For the open quarters only:
    NSE's SME master (honest request) -> the XBRL files of quarters not yet stored; BSE SHPQNewFormat lists (bse_headers,
    one request at a time) for BSE-only companies still missing a window quarter -> their files. Then `build` in WINDOW
    mode: every gate of the full build, new (symbol, quarter) cells only, merged onto the committed ledger."""
    import urllib.error
    import urllib.request

    import bse_headers

    qes = sorted(quarters or window_qes())
    t_end = time.time() + max_minutes * 60 if max_minutes else None
    os.makedirs(cache, exist_ok=True)
    X, LD, XD = (
        os.path.join(cache, "xbrl_nse_all"),
        os.path.join(cache, "bse_lists_v2"),
        os.path.join(cache, "xbrl_bse_v2"),
    )
    for d_ in (X, LD, XD):
        os.makedirs(d_, exist_ok=True)
    log = open(os.path.join(cache, "update.log"), "a")

    def say(*a):
        print(time.strftime("%H:%M:%S"), *a, file=log, flush=True)
        print(*a, flush=True)

    hist, relatives, _isins, _man = load_inputs(cache)
    led = json.load(gzip.open(LEDGER, "rt", encoding="utf-8")).get("fills", {}) if os.path.exists(LEDGER) else {}

    # stored under the symbol or any rename relative (a quarter kept under a former ticker is not owed again)
    def have(s_, q_):
        return any(q_ in (hist.get(x) or {}) or q_ in (led.get(x) or {}) for x in {s_} | relatives(s_))

    meta = json.loads(gzip.open(os.path.join(REPO, "docs", "stock_data.bin")).read())["meta"]
    bysym = collections.defaultdict(set)
    for k_, m_ in meta.items():
        bysym[m_.get("symbol") or k_.split(".")[0]].add(k_)
    sme = {s_ for s_, ks in bysym.items() for k_ in ks if k_.endswith(".NS") and meta[k_].get("sme")}
    say("update window %s | NSE SME symbols %d" % (qes, len(sme)))
    # ---- NSE SME board
    H = {
        "User-Agent": HONEST_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/",
    }

    def get(url, timeout=120):
        return urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=timeout).read()

    MP = os.path.join(cache, "manifest_nse_all.json")
    man = json.load(open(MP)) if os.path.exists(MP) else {}
    today = (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).date()
    n_nse = 0
    for qe in qes:
        d = datetime.date.fromisoformat(qe)
        to = max(d, min(today, d + datetime.timedelta(days=MASTER_WINDOW_DAYS)))

        def f_(x):
            return "%02d-%02d-%04d" % (x.day, x.month, x.year)

        try:
            recs = json.loads(
                get(
                    f"https://www.nseindia.com/api/corporate-share-holdings-master?index=sme&from_date={f_(d)}&to_date={f_(to)}"
                )
            )
            recs = recs if isinstance(recs, list) else recs.get("data", [])
        except Exception as e:
            say(f"NSE SME master {qe} failed: {e}")
            continue
        want = {}
        for r in recs:
            sym = str(r.get("symbol") or "").upper().strip()
            if (
                F.iso_date(r.get("date")) != qe
                or sym not in sme
                or have(sym, qe)
                or not str(r.get("xbrl") or "").startswith("http")
            ):
                continue
            k, sub = f"{sym}|{qe}", F.visible_iso(r) or ""
            if k not in want or sub >= want[k]["sub"]:
                want[k] = {
                    "url": r["xbrl"],
                    "sub": sub,
                    "submissionDate": r.get("submissionDate"),
                    "broadcastDate": r.get("broadcastDate"),
                    "revised": str(r.get("revisedData") or ""),
                    "idx": "sme",
                }
        say("NSE SME %s: %d master rows, %d new quarter-end filings to fetch" % (qe, len(recs), len(want)))
        for k, v in sorted(want.items()):
            if t_end and time.time() > t_end:
                say("time limit reached")
                break
            path = os.path.join(X, k.replace("|", "_") + ".xml.gz")
            try:
                b = get(v["url"])
                if len(b) < 2000 or b"Shareholding" not in b:
                    raise ValueError("short/odd body %d" % len(b))
                open(path, "wb").write(gzip.compress(b))
                man[k] = dict(v, path=path)
                n_nse += 1
            except Exception as e:
                man[k] = dict(v, error=f"{type(e).__name__}: {str(e)[:80]}")
            time.sleep(0.5)
    json.dump(man, open(MP, "w"))
    # ---- BSE-only companies: the committed targets + any BSE-only dashboard company bse_universe maps a code to
    T = json.load(open(os.path.join(HERE, "_shp_bse_targets.json")))
    try:
        for r_ in json.load(open(os.path.join(REPO, "docs", "bse_universe.json"), encoding="utf-8"))["rows"]:
            c_, s_ = str(r_[0]), r_[1]
            if c_ not in T and s_ and (s_ + ".NS") not in meta and any(k_.endswith(".BO") for k_ in bysym.get(s_, ())):
                T[c_] = {
                    "sym": s_,
                    "grp": "BSE-only",
                    "name": r_[2],
                    "why": "§180e: BSE-only dashboard company (bse_universe)",
                }
    except Exception as e:
        say(f"WARN bse_universe unreadable ({e})")
    json.dump(T, open(os.path.join(cache, "bse_targets.json"), "w"), indent=0)

    # a HALF-YEARLY filer (BSE SME: every cell of the last two years is a Mar/Sep quarter) owes no Jun/Dec quarter; a DORMANT
    # company (nothing in the four quarters before the window) is not re-asked every run — both measured 2026-09-27: 203
    # half-yearly filers, 57 dormant of 2,262 BSE-only companies
    def owed(sym):
        qs_ = set().union(*[set(hist.get(x) or {}) | set(led.get(x) or {}) for x in {sym} | relatives(sym)])
        lo = QES[max(0, QES.index(qes[0]) - 8)] if qes[0] in QES else "0000"
        recent = [q_ for q_ in qs_ if lo <= q_ < qes[0]]
        half = len(recent) >= 3 and all(q_[5:7] in ("03", "09") for q_ in recent)
        if qs_ and not any(QES[max(0, QES.index(qes[0]) - 4)] <= q_ for q_ in qs_ if qes[0] in QES):
            return []
        return [q_ for q_ in qes if not have(sym, q_) and not (half and q_[5:7] in ("06", "12"))]

    codes = sorted(
        c_ for c_, v in T.items() if v.get("grp") == "BSE-only" and not v.get("isin_conflict") and owed(v["sym"])
    )
    say("BSE-only companies owing a window quarter: %d" % len(codes))
    fails = n_req = n_files = 0

    def bget(url, kind):
        nonlocal fails, n_req
        for _attempt in range(2):
            n_req += 1
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    b = r.read()
                ok = (b[:1] in (b"{", b"[")) if kind == "list" else (b"xbrl" in b[:4000].lower() and len(b) > 1500)
                if ok:
                    fails = 0
                    time.sleep(0.6)
                    return b
                why = "not %s (%d bytes)" % (kind, len(b))
            except urllib.error.HTTPError as e:
                why = "HTTP %d" % e.code
                if e.code == 404:
                    time.sleep(0.6)
                    return None
            except Exception as e:
                why = f"{type(e).__name__}: {str(e)[:60]}"
            fails += 1
            say("refused/failed", url.rsplit("/", 1)[-1][:60], why)
            if fails >= 3:
                say("3 refusals in a row -> pausing 10 min")
                time.sleep(600)
                if fails >= 6:
                    raise SystemExit("BSE refusing repeatedly; stopped (the next run resumes)")
            time.sleep(2)
        return None

    for i, code in enumerate(codes):
        if t_end and time.time() > t_end:
            say("time limit reached — the next run continues")
            break
        b = bget(f"https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode={code}", "list")
        if b is None:
            continue
        open(os.path.join(LD, code + ".json"), "wb").write(b)
        try:
            rows = json.loads(b).get("Table") or []
        except Exception:
            continue
        sym = T[code]["sym"]
        for qe, r in bse_pick(rows).items():
            if qe not in qes or have(sym, qe):
                continue
            xf = r["XbrlFile"].strip()
            xp = os.path.join(XD, xf + ".gz")
            if os.path.exists(xp):
                continue
            fb = bget("https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + xf, "xbrl")
            if fb:
                open(xp, "wb").write(gzip.compress(fb))
                n_files += 1
        if (i + 1) % 100 == 0:
            say("BSE progress %d/%d, %d files, %d requests" % (i + 1, len(codes), n_files, n_req))
    say("fetched: NSE SME %d files | BSE %d files (%d requests)" % (n_nse, n_files, n_req))
    build(cache, window=qes)


# ------------------------------------------------------------------------------------------ build
def build(cache, window=None):
    hist, relatives, isins, man = load_inputs(cache)
    # WINDOW mode (§180e, stage `update`): only the given quarters are evaluated, on top of the store as it is — every
    # landed cell stays landed (fill-only), and the result is MERGED onto the committed ledger at the end.
    prev_led = json.load(gzip.open(LEDGER, "rt", encoding="utf-8")) if os.path.exists(LEDGER) else {}
    # Re-runs must reproduce the ledger: cells this ledger itself landed are treated as NOT stored (otherwise a
    # rebuild after landing sees every cell as "already stored" and writes an empty ledger that CI then applies).
    released = set()  # (sym, qe) this fill landed and now re-judges
    if os.path.exists(LEDGER) and not window:
        prev = json.load(gzip.open(LEDGER, "rt", encoding="utf-8")).get("fills", {})
        for s_, qs_ in prev.items():
            for q_ in qs_:
                if q_ in (hist.get(s_) or {}):
                    del hist[s_][q_]
                    released.add((s_, q_))
        print("previous ledger: %d cells treated as not yet stored" % sum(len(v) for v in prev.values()))
    # §180c: so is every store cell the COMMITTED ledger wrote (identical values) — a rebuild that removes a wrong cell
    # (BRIGHT: Bright Solar's quarters) must see its quarter as open, or the right company's filing is skipped as
    # "already stored" behind the wrong value it is meant to replace
    try:
        import subprocess

        _b = subprocess.run(
            ["git", "-C", REPO, "show", "HEAD:scripts/shp_fill_allstocks.json.gz"], capture_output=True
        ).stdout
        head = json.loads(gzip.decompress(_b)).get("fills", {}) if (_b and not window) else {}
    except Exception as e:
        print(f"WARN committed ledger unreadable ({e})")
        head = {}
    n_head = 0
    for s_, qs_ in head.items():
        for q_, c_ in qs_.items():
            cur_ = (hist.get(s_) or {}).get(q_)
            if cur_ is not None and list(cur_[:6]) == list(c_[:6]):
                del hist[s_][q_]
                n_head += 1
                released.add((s_, q_))
    if n_head:
        print("committed ledger: %d more stored cells written by this fill treated as open" % n_head)
    t0 = time.time()
    docs = {}  # (sym, qe) -> analysis + meta
    for k, v in man.items():
        sym, qe = k.split("|")
        if not (FIRST_QE <= qe <= LAST_QE):
            continue
        if window and qe not in window:
            continue
        try:
            a = analyse(read_doc(v["path"]), qe)
        except Exception as e:
            a = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
        a.pop("_pct", None)
        a.pop("_shc", None)
        a.update(
            {
                "sub": v.get("sub"),
                "submissionDate": v.get("submissionDate"),
                "idx": v.get("idx"),
                "revised": str(v.get("revised") or "").lower() == "revised",
                "src": "nse:" + str(v.get("url", "")).rsplit("/", 1)[-1],
            }
        )
        docs[(sym, qe)] = a
    # BSE copies (stage `bse`): only for (key, quarter) pairs NSE did not supply. Key = the dashboard symbol of the
    # target scrip (BSE-only tickers, or the NSE symbol for NSE-listed companies whose quarter NSE never served).
    T = (
        json.load(open(os.path.join(cache, "bse_targets.json")))
        if os.path.exists(os.path.join(cache, "bse_targets.json"))
        else {}
    )
    LD, XD = os.path.join(cache, "bse_lists_v2"), os.path.join(cache, "xbrl_bse_v2")
    bse_code_of, n_bse = {}, 0
    # §180c: an NSE filing must never fill a key the dashboard uses for a DIFFERENT BSE company. BRIGHT = Bright Outdoor Media
    # (BSE 543831, BRIGHT.BO only) but NSE's SME ticker BRIGHT is Bright Solar Ltd (INE684Z01010): 14 of Bright Solar's
    # quarters landed under Bright Outdoor's key (§180 NSE fill). For a BSE-only target whose own ISIN issuer differs from
    # every ISIN the NSE ticker traded under, the NSE documents are set aside (held) and the scrip's BSE copies are used.
    _bs = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))
    _code_is = collections.defaultdict(set)
    for i_, c_ in _bs.get("by_isin", {}).items():
        _code_is[str(c_)].add(i_.upper()[:7])
    try:
        for r_ in json.load(open(os.path.join(REPO, "docs", "bse_universe.json"), encoding="utf-8"))["rows"]:
            if r_[3]:
                _code_is[str(r_[0])].add(str(r_[3]).upper()[:7])
    except Exception:
        pass
    nse_other = {}
    for code_, tv_ in T.items():
        if tv_.get("grp") != "BSE-only":
            continue
        n_is = {i_[:7] for i_ in isins.get(tv_["sym"], set())}
        if n_is and _code_is.get(code_) and not (n_is & _code_is[code_]):
            nse_other[tv_["sym"]] = (
                "NSE ticker {} is another company ({}) than the dashboard's BSE scrip {} ({})".format(
                    tv_["sym"], min(n_is), code_, min(_code_is[code_])
                )
            )
    set_aside = {}
    for key_ in [k_ for k_ in docs if k_[0] in nse_other]:
        set_aside[key_] = docs.pop(key_)
    if set_aside:
        print("NSE documents set aside (another company under a dashboard BSE key): %d" % len(set_aside))
    for code, tv in T.items():
        lp = os.path.join(LD, code + ".json")
        if tv.get("isin_conflict") or not os.path.exists(lp):
            continue
        try:
            rows = json.load(open(lp)).get("Table") or []
        except Exception:
            continue
        for qe, r in bse_pick(rows).items():
            if window and qe not in window:
                continue
            xp = os.path.join(XD, r["XbrlFile"].strip() + ".gz")
            key = (tv["sym"], qe)
            # an NSE document that could not be read (NAVKARURB Dec-2024: truncated XML) yields to the BSE copy
            if (key in docs and "error" not in docs[key]) or not os.path.exists(xp):
                continue
            try:
                a = analyse(read_doc(xp), qe)
            except Exception as e:
                a = {"error": f"{type(e).__name__}: {str(e)[:80]}"}
            a.pop("_pct", None)
            a.pop("_shc", None)
            a.update(
                {
                    "sub": r["_date"],
                    "submissionDate": None,
                    "idx": "bse-" + tv["grp"],
                    "revised": r["_kind"] != "original",
                    "src": "bsexbrl:" + r["XbrlFile"].strip(),
                    "bse_code": code,
                    "bse_grp": tv["grp"],
                }
            )
            docs[key] = a
            bse_code_of[tv["sym"]] = code
            n_bse += 1
    print("analysed %d filings (%d BSE copies) in %.0fs" % (len(docs), n_bse, time.time() - t0))

    def issuers(isl):
        return {i[:7] for i in isl}

    # company names on record (§180c): dashboard meta, bse_universe, the BSE target list
    names_sym, names_code = collections.defaultdict(set), collections.defaultdict(set)
    try:
        _meta = json.loads(gzip.open(os.path.join(REPO, "docs", "stock_data.bin")).read())[
            "meta"
        ]  # one load (large file)
    except Exception as e:
        print(f"WARN stock_data.bin unreadable ({e})")
        _meta = {}
    for k_, m_ in _meta.items():
        if m_.get("name"):
            names_sym[m_.get("symbol") or k_.split(".")[0]].add(m_["name"])
    dash_keys = set(_meta)
    del _meta
    try:
        for r_ in json.load(open(os.path.join(REPO, "docs", "bse_universe.json"), encoding="utf-8"))["rows"]:
            if r_[2]:
                names_code[str(r_[0])].add(r_[2])
    except Exception as e:
        print(f"WARN bse_universe names unreadable ({e})")
    for c_, t_ in T.items():
        if t_.get("name"):
            names_code[c_].add(t_["name"])
    uni_ticker = {}  # bse_universe: scrip code -> the dashboard's ticker
    try:
        for r_ in json.load(open(os.path.join(REPO, "docs", "bse_universe.json"), encoding="utf-8"))["rows"]:
            uni_ticker[str(r_[0])] = r_[1]
    except Exception as e:
        print(f"WARN bse_universe tickers unreadable ({e})")
    _js = open(os.path.join(REPO, "docs", "backtest-engine.js"), encoding="utf-8").read()
    _m = re.search(r"const FUND_ALIAS\s*=\s*(\{.*?\});", _js, re.DOTALL)
    _fa = json.loads(_m.group(1)) if _m else {}
    fund_alias_keys = set(_fa) | {v for v in _fa.values() if isinstance(v, str)}
    # §197: an alias whose OLD key is a PROVEN BSE-ticker collision (docs/bse_alias_collisions.json — the BSE scrip's
    # ISIN issuer is none of the target's) is an NSE fact about another company; it no longer makes the key ambiguous.
    try:
        _coll = json.load(open(os.path.join(REPO, "docs", "bse_alias_collisions.json"), encoding="utf-8"))["collisions"]
    except Exception as e:
        sys.exit(f"ABORT: docs/bse_alias_collisions.json unreadable ({e})")
    fund_alias_keys -= {o for o, c in _coll.items() if _fa.get(o) == c.get("target")}

    def name_ok(a, sym, code=None):
        on_record = names_sym.get(sym, set()) | (names_code.get(str(code), set()) if code else set())
        return bool(a.get("cname")) and any(names_match(a["cname"], n_) for n_ in on_record)

    def norm_isin(i):
        """Filer typos seen in the corpus: letter O for zero, letter I for one (INEOMTP01013 for INE0MTP01013).
        Used ONLY for an exact 12-character match against an ISIN the symbol really traded under."""
        return i[:3] + i[3:11].replace("O", "0").replace("I", "1") + i[11:] if i else i

    bs = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))
    code_isins = collections.defaultdict(set)
    for isin_, code_ in bs.get("by_isin", {}).items():
        code_isins[str(code_)].add(isin_.upper())
    try:
        for r_ in json.load(open(os.path.join(REPO, "docs", "bse_universe.json"), encoding="utf-8"))["rows"]:
            if r_[3]:
                code_isins[str(r_[0])].add(str(r_[3]).upper())
    except Exception as e:
        print(f"WARN bse_universe.json unreadable ({e})")
    by_id_sym = {str(v): k for k, v in bs.get("by_id", {}).items()}

    def identity_bse(sym, a):
        """A BSE copy belongs to `sym` when the FILE's ScripCode is the scrip we asked for and its ISIN issuer is one that
        scrip (or, for an NSE key, the NSE symbol) carries. A BSE-only key must also not be an NSE ticker of another company
        (the engines and the stock page key on it), and must be the ticker bse_scrips.json gives that code (the key
        build_stock_fin folds BSE fundamentals under)."""
        code = a["bse_code"]
        fi = a.get("isin") or ""
        known = code_isins.get(code, set()) | set().union(*[isins.get(x, set()) for x in ({sym} | relatives(sym))])
        nknown = {norm_isin(k) for k in known}
        isin_ok = bool(fi) and (norm_isin(fi) in nknown or norm_isin(fi)[:7] in issuers(nknown))
        # an ISIN within two characters of the scrip's own (a typo or two transposed digits: INE209E01011 / INE290E01011)
        isin_near = bool(fi) and any(
            len(fi) == len(k) and sum(x != y for x, y in zip(norm_isin(fi), k, strict=False)) <= 2 for k in nknown
        )
        if a.get("scrip") and a["scrip"] != code:
            # a wrong ScripCode fact (WHEELS files "600001") passes only when the company name agrees AND the ISIN agrees or
            # the file carries none (BSE's own list for the requested scrip named the file)
            if not ((isin_ok or not fi) and name_ok(a, sym, code)):
                return "file ScripCode {} is not the requested scrip {}".format(a["scrip"], code), []
            a["id_note"] = "file ScripCode {} is a filer error: {}company name match".format(
                a["scrip"], "ISIN + " if fi else ""
            )
        if fi and not isin_ok:
            # the file's ISIN field is a filer typo (INR614R01014, IN8744C01028, INF759F01012 ...) or the scrip has no ISIN on
            # record: identity then rests on BSE's own ScripCode fact AND either the company name printed in the filing or an
            # ISIN within two characters of the scrip's own (renamed companies file under their former name: FRATELLI = Tinna Trade)
            if a.get("scrip") == code and name_ok(a, sym, code):
                a["id_note"] = f"file ISIN {fi} is a filer typo: ScripCode + company name match"
            elif a.get("scrip") == code and isin_near:
                a["id_note"] = (
                    f"file ISIN {fi} is a filer typo: ScripCode match + ISIN within two characters of {sorted(known)[:2]}"
                )
            elif not known:
                return f"no ISIN on record for scrip {code} / {sym}", []
            else:
                return f"file ISIN {fi} does not match scrip {code} / {sym} ISINs {sorted(known)[:3]}", []
        elif a.get("scrip") != code:
            # no ISIN in the file: only BSE's own ScripCode fact (equal to the scrip whose list named the file) proves it
            return "file carries neither ISIN nor the requested ScripCode", []
        if a["bse_grp"] == "BSE-only":
            # §180c: the key is safe when the dashboard carries ONE company under it — the BSE listing bse_universe maps to
            # this ticker (or whose name matches this filing) — no NSE listing of that ticker in the dashboard and no
            # FUND_ALIAS entry on it (WORTH -> WORTHPERI points the ticker at another company).
            # (no condition on rows already stored under the ticker: the dashboard key names the company, so a stored row
            # from another company is itself an error to heal — BRIGHT — and must not flip this decision between rebuilds)
            sole_key = (
                (sym + ".BO") in dash_keys
                and (sym + ".NS") not in dash_keys
                and sym not in fund_alias_keys
                and (uni_ticker.get(str(code)) == sym or name_ok(a, sym, code))
            )
            nse_is, own = isins.get(sym, set()), code_isins.get(code, set()) | ({fi} if fi else set())
            if nse_is and own and not (issuers(own) & issuers(nse_is)):
                if not sole_key:
                    return f"BSE ticker {sym} is also an NSE ticker of another company ({sorted(nse_is)[:2]})", []
                a["id_note"] = (
                    a.get("id_note", "") + "; " if a.get("id_note") else ""
                ) + f"NSE ticker {sym} is another company outside the dashboard; the dashboard key is this BSE scrip"
            if by_id_sym.get(code) and by_id_sym[code] != sym:
                if not sole_key:
                    return (
                        f"dashboard ticker {sym} differs from bse_scrips ticker {by_id_sym[code]} for scrip {code}",
                        [],
                    )
                a["id_note"] = (
                    a.get("id_note", "") + "; " if a.get("id_note") else ""
                ) + f"dashboard ticker {sym} (bse_universe) for scrip {code}, bse_scrips still has {by_id_sym[code]}"
        return None, []

    def identity(sym, a):
        """-> (reason or None, extra former tickers). The NSE master pairs `sym` with this document; the document's
        own ISIN must agree with an ISIN `sym` (or a rename relative) traded under — issuer prefix, or the full ISIN
        after the O/I typo repair. A different Symbol tag inside the file is then a former ticker of the same
        company (renames missing from the maps: LAWSIKHO->ADDICTIVE, SILLYMONKS->CRESTO, same ISIN)."""
        fam = {sym} | relatives(sym)
        known = set().union(*[isins.get(x, set()) for x in fam])
        fi, tag = a.get("isin"), a.get("symtag")
        tag_ok = tag and tag != "NOTLISTED" and tag not in fam
        if fi:
            nknown = {norm_isin(k) for k in known}
            if known:
                if norm_isin(fi)[:7] not in issuers(nknown) and norm_isin(fi) not in nknown:
                    if not name_ok(a, sym):
                        return f"file ISIN {fi} does not match {sym}'s ISINs {sorted(known)[:3]}", []
                    a["id_note"] = f"file ISIN {fi} is a filer typo: company name matches {sym}"
            elif not (tag_ok and (fi[:7] in issuers(isins.get(tag, set())) or norm_isin(fi) in isins.get(tag, set()))):
                if not name_ok(a, sym):
                    return f"no ISIN on record for {sym} and the file's own symbol does not vouch for {fi}", []
                a["id_note"] = f"no ISIN on record for {sym}: company name matches"
            extra = (
                [tag]
                if tag_ok and (fi[:7] in issuers(isins.get(tag, set())) or norm_isin(fi) in isins.get(tag, set()))
                else []
            )
            return None, extra
        if tag and tag not in fam and tag != "NOTLISTED":
            return f"file carries no ISIN and its Symbol {tag} is not {sym}", []
        if not known and not tag:
            return "no ISIN on either side to prove identity", []
        return None, []

    def visibility(a):
        """-> (date, note). Default = calendar day of NSE's broadcast (visible_iso, midnight rule §149). NSE keeps ONE
        record per (symbol, as-on) and re-stamps its broadcastDate on re-publication and in bulk system passes
        (§142h: 2022-01-06/07 ...), so a broadcast far after the submission day can be a re-stamp of the ORIGINAL
        document. The file name carries the document's creation stamp (SHP_<id>_<ddmmyyyyHHMMSS>_WEB.xml): when the
        document was created no later than the day after the submission day, it IS the original filing and is dated
        by the submission day (the §142i day-precision fallback). A document created later is a re-filing: it keeps
        its own later broadcast day, so a re-filing's numbers are never served from the original's date (§142j/k).
        The creation stamp is used only to classify original-vs-refiling, never as a date (memory: not a filing time)."""
        bday = a.get("sub")
        if a.get("bse_code"):
            return bday, ("bse-" + ("revision-only" if a.get("revised") else "original"))
        subd = F.iso_date(a.get("submissionDate"))
        m = re.search(r"_(\d{2})(\d{2})(\d{4})\d{6}_WEB\.xml$", a.get("src") or "")
        if not (bday and subd and m):
            return bday, ""
        try:
            made = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            sd, bd = datetime.date.fromisoformat(subd), datetime.date.fromisoformat(bday)
        except ValueError:
            return bday, ""
        if made <= sd + datetime.timedelta(days=1) and bd > sd + datetime.timedelta(days=2):
            return subd, f"dated-by-submission(broadcast {bday} is a re-stamp of the original)"
        return bday, ""

    # §180c: an old-format filing held as ambiguous takes its row-level placement (stage `rowlevel`) when one was
    # resolved for this very file; every later gate still runs on the result.
    rl = (json.load(open(ROWLEVEL, encoding="utf-8")).get("cells") or {}) if os.path.exists(ROWLEVEL) else {}
    # §180c second reading of a held quarter (Screener verify-only, or the filing's own named holders): lets THAT file pass
    # the continuity / unproven-zero / holder-count gates; identity, format and bounds gates still apply
    sr_path = os.path.join(HERE, "_shp_allstocks_second_reader.json")
    second = (json.load(open(sr_path, encoding="utf-8")).get("cells") or {}) if os.path.exists(sr_path) else {}

    def second_ok(sym_, qe_, a_):
        e_ = second.get(f"{sym_}|{qe_}")
        return e_ if e_ and str(a_.get("src", "")).split(":", 1)[-1].split()[0] == e_.get("file") else None

    n_rl = 0
    for (sym, qe), a in docs.items():
        e = rl.get(f"{sym}|{qe}")
        if not (a.get("ambiguity") and a.get("cell") and e and e.get("status") == "resolved"):
            continue
        if str(a.get("src", "")).split(":", 1)[-1].split()[0] != e["file"]:
            continue
        a["cell"] = dict(
            a["cell"], fii=e["fii"], dii=e["dii"], **({"ins": e["ins"]} if e.get("ins") is not None else {})
        )
        a["rowlevel"] = " + ".join(e["parts"])
        a["ambiguity"] = []
        n_rl += 1
    print("row-level placements applied: %d" % n_rl)

    # ---- series view for neighbour gates: stored cells + parsed candidates
    series = collections.defaultdict(dict)
    for sym, qs in hist.items():
        if sym.startswith("_") or not isinstance(qs, dict):
            continue
        for qe, c in qs.items():
            series[sym][qe] = (c[1], c[2], c[6] if len(c) > 6 else None, "store")
    for (sym, qe), a in docs.items():
        c = a.get("cell")
        if c and qe not in series[sym]:
            series[sym][qe] = (c["fii"], c["dii"], c.get("nsh"), "cand")

    # A NEW store key that equals an unrelated BSE-only scrip id changes what build_stock_fin folds into that slug
    # (its "taken" set counts shareholding keys): hold the whole symbol rather than silently move a page's data.
    def slug(x):
        return re.sub(r"[^A-Za-z0-9._-]", "_", x)

    claimed = {slug(k) for k in hist if not k.startswith("_")}
    for fn in ("sf_fundamentals.json", "sf_revop.json"):
        try:
            claimed |= {slug(k) for k in json.load(open(os.path.join(REPO, "docs", fn), encoding="utf-8"))}
        except Exception as e:
            print(f"WARN {fn} unreadable ({e})")
    bs = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))
    code_isin = {str(v): k for k, v in bs.get("by_isin", {}).items()}
    bse_clash, bse_clash_code = {}, {}
    for sym_, code_ in bs.get("by_id", {}).items():
        if sym_ in hist or slug(sym_) in claimed:
            continue
        bi = code_isin.get(str(code_), "")
        if bi and isins.get(sym_) and bi[:7] not in issuers(isins[sym_]):
            bse_clash[sym_] = (
                f"ticker {sym_} is also BSE scrip {code_} ({bi}), a different company; landing would change the "
                "fundamentals build_stock_fin folds into that slug"
            )
            bse_clash_code[sym_] = str(code_)

    accept_syms = set(json.load(open(os.path.join(HERE, "shp_cell_fix.json"), encoding="utf-8")).get("accept") or {})
    share_series = collections.defaultdict(dict)  # total shares per filing, for the capital-collapse test
    for (s_, q_), a_ in docs.items():
        if a_.get("shares"):
            share_series[s_][q_] = [a_["shares"]]
    if window and os.path.exists(SHARES_HIST):  # window mode: earlier quarters come from the stored series
        for s_, qs_ in json.load(open(SHARES_HIST, encoding="utf-8")).items():
            if s_ == "_meta":
                continue
            for q_, v_ in qs_.items():
                share_series[s_].setdefault(q_, [v_[0]])
    fills, holds = collections.defaultdict(dict), collections.defaultdict(dict)
    stat = collections.Counter()
    why = collections.Counter()
    for (sym_, qe_), a_ in set_aside.items():
        if (sym_, qe_) not in docs:
            holds[sym_][qe_] = {
                "why": "identity: " + nse_other[sym_],
                "src": a_.get("src"),
                "cell": a_.get("cell"),
                "fmt": a_.get("fmt"),
            }
            why["identity"] += 1
    for (sym, qe), a in sorted(docs.items()):

        def hold(reason):
            holds[sym][qe] = {"why": reason, "src": a.get("src"), "cell": a.get("cell"), "fmt": a.get("fmt")}
            stat[(a.get("idx"), "hold")] += 1
            why[reason.split(":")[0][:60]] += 1

        stored = hist.get(sym) or {}
        if qe in stored:
            stat[(a.get("idx"), "already stored")] += 1
            continue
        if "error" in a:
            hold("unreadable XML: " + a["error"])
            continue
        # the clash protects the BSE scrip that owns this ticker from ANOTHER company's filings; that scrip's own filings
        # (same scrip code: SIIL = 540132 Sabrimala, INNOVATIVE = 541983) are exactly what belongs under it
        if sym in bse_clash and str(a.get("bse_code") or "") != bse_clash_code[sym]:
            hold("slug collision: " + bse_clash[sym])
            continue
        bad, extra = identity_bse(sym, a) if a.get("bse_code") else identity(sym, a)
        if bad:
            hold("identity: " + bad)
            continue
        former = [x for x in (relatives(sym) | set(extra)) if qe in (hist.get(x) or {})]
        # a cell this fill already landed under `sym` is re-judged even when a rename merged later brings the same quarter
        # under a former ticker (HEG -> HEGAM §199: HEG's NSE rows joined the six HEGAM quarters this fill had landed from
        # BSE 509631) — the landed cell stays in the ledger; only a quarter nobody has landed yet is skipped here
        if former and (sym, qe) not in released:
            stat[(a.get("idx"), "stored under a former ticker")] += 1
            continue
        c = a.get("cell")
        if c is None:
            hold("parser refused (format {}) and no partition proof".format(a["fmt"]))
            continue
        if a["ambiguity"]:
            hold("old-format row needing row-level placement: " + "; ".join(a["ambiguity"])[:160])
            continue
        if a["fmt"] == "new" and a["partition_closes"] is False:
            hold("public block does not close")
            continue
        if c["mf"] > c["dii"] + 0.05 or c["ins"] > c["dii"] + 0.05:
            hold("mf/ins exceeds dii")
            continue
        if c["prom"] + c["fii"] + c["dii"] > 100.5:
            hold("promoter + fii + dii exceeds 100")
            continue
        sub, how = visibility(a)
        if not sub:
            hold("no visibility date")
            continue
        lag = (datetime.date.fromisoformat(sub) - datetime.date.fromisoformat(qe)).days
        if lag < 0:
            hold(f"visibility date {sub} before quarter end")
            continue
        nsh = c.get("nsh")
        earlier = [v[2] for q, v in sorted(series[sym].items()) if q < qe and v[2]]
        later = [v[2] for q, v in sorted(series[sym].items()) if q > qe and v[2]]
        nsh_note = ""
        # §180c one-quarter SPIKE: far above BOTH neighbours while they agree — the filer typed share counts into a holder
        # field (PARMAX Sep-2022: KeyManagerialPersonnel "100000" holders -> company total 101,650 between 1,590 and 2,035)
        if (
            nsh
            and earlier
            and later
            and max(earlier[-1], later[0]) <= 3 * min(earlier[-1], later[0])
            and nsh > 20 * max(earlier[-1], later[0])
        ):
            nsh_note = " nsh-withheld(%d one-quarter spike vs %d / %d: holder fields carry share counts)" % (
                nsh,
                earlier[-1],
                later[0],
            )
            nsh = None
        # the collapse test compares with the MEDIAN of earlier quarters, so one spiked quarter cannot hold every later one
        if nsh and earlier and nsh < 0.05 * statistics.median(earlier):
            # §22g-2: a collapsed holder count can mean the filing describes another share class. When the SAME
            # filings show the share capital itself collapsing (insolvency capital reduction: PUNJLLOYD 335.6 M -> 0.5 M
            # shares, acquirer 95 %) or the symbol's event is already adjudicated on the cell_fix accept list
            # (DSKULKARNI), the percentages stand on share counts; only the holder count is doubtful -> write the cell
            # WITHOUT it. Anything else is held.
            n_now = a.get("shares") or 0
            n_before = [v[0] for q, v in (share_series.get(sym) or {}).items() if q < qe and v]
            collapsed = bool(n_now and n_before and n_now < 0.5 * max(n_before))
            # §180c: the SAME share capital as the earlier filings (within 5 % of their median) means the same share class,
            # so the percentages stand; only the holder count is doubtful (AARCON Dec-2025: 2,245 -> 85 after an open offer)
            same_class = bool(
                n_now and n_before and abs(n_now - statistics.median(n_before)) <= 0.05 * statistics.median(n_before)
            )
            sr_ = second_ok(sym, qe, a)
            if sr_ and sr_.get("nsh_confirmed"):
                nsh_note = " nsh-corroborated(second reader)"
            elif collapsed or sym in accept_syms or same_class or sr_:
                nsh_note = " nsh-withheld(%d vs %d earlier; %s)" % (
                    nsh,
                    statistics.median(earlier),
                    "capital collapse"
                    if collapsed
                    else "accept-list event"
                    if sym in accept_syms
                    else "same share capital"
                    if same_class
                    else "second reader: percentages",
                )
                nsh = None
            else:
                hold("nsh gate: %d vs %d earlier" % (nsh, statistics.median(earlier)))
                continue
        i = QES.index(qe)
        nb = [series[sym][QES[j]] for j in (i - 2, i - 1, i + 1, i + 2) if 0 <= j < len(QES) and QES[j] in series[sym]]
        sr_ = second_ok(sym, qe, a)
        if sr_:
            nsh_note += " second-reader"
        if not sr_ and nb and all(abs(c["fii"] - n[0]) > 5 for n in nb):
            hold("continuity: fii >5pp from every neighbour")
            continue
        if not sr_ and nb and all(abs(c["dii"] - n[1]) > 10 for n in nb):
            hold("continuity: dii >10pp from every neighbour")
            continue
        proven = a["zero_proof"] or a["partition_closes"]
        osp = a.get("old_split") or {}

        def slot_proven(s_, ix_):
            if proven:
                return True
            if not (osp.get("closes") and osp.get(s_ + "_rows", 1) == 0):
                return False
            # a FLIP is not an exit: the other slot here equals this slot in a neighbour (GLOBUSCON: the same 17,810,728 shares
            # filed as FPI in Jun-2021 and as Financial Institutions/Banks in Sep-2021)
            other = c["dii" if s_ == "fii" else "fii"]
            return not any(n[ix_] > 1.0 and abs(n[ix_] - other) <= max(0.05, 0.005 * other) for n in nb)

        if not sr_ and any(
            c[s] == 0.0 and nb and any(n[ix] > 1.0 for n in nb) and not slot_proven(s, ix)
            for s, ix in (("fii", 0), ("dii", 1))
        ):
            hold("exact 0 beside a neighbour above 1% without a partition proof")
            continue
        tag = (
            a["src"]
            + (" proven-zero" if a["zero_proof"] else "")
            + (" nse-refiling" if a["revised"] else "")
            + (" " + how if how else "")
            + (" lag%dd" % lag if lag > 120 else "")
            + nsh_note
        )
        if a.get("rowlevel"):
            tag += " rowlevel:" + a["rowlevel"]
        if a.get("id_note"):
            tag += " id:" + a["id_note"]
        fills[sym][qe] = [
            round(c["prom"], 4),
            round(c["fii"], 4),
            round(c["dii"], 4),
            round(c["mf"], 4),
            round(c["ins"], 4),
            sub,
            nsh or None,
            tag,
        ]
        stat[(a.get("idx"), "FILL")] += 1

    # ---- §180c re-filings: a filled BSE quarter whose company later REVISED it. The store keeps the original at its own
    # date; the latest revision goes to shp_revisions.json (option C, §142k) dated by ITS OWN publication day, so a screen
    # sees the original until the correction was public and the correction after (the stock page shows the correction).
    # Same identity / format gates as an original; an old-format revision that would need row-level placement is left out
    # (never guessed); only a revision whose numbers differ is recorded (Screener shows the revision: 186 of 198 FARs).
    revisions, rev_stat = collections.defaultdict(dict), collections.Counter()
    for sym, qs in fills.items():
        code = bse_code_of.get(sym)
        lp = os.path.join(LD, f"{code}.json") if code else None
        if not lp or not os.path.exists(lp):
            continue
        try:
            rows = json.load(open(lp)).get("Table") or []
        except Exception:
            continue
        tv = T.get(code) or {}
        for qe, cell in qs.items():
            if not cell[7].startswith("bsexbrl") or "bse-original" not in cell[7]:
                continue
            rv = sorted(
                [
                    r
                    for r in rows
                    if bse_label_qe(r.get("qtr")) == qe and str(r.get("status")) != "New" and r.get("revised_date_time")
                ],
                key=lambda r: r["revised_date_time"],
            )
            if not rv:
                continue
            r = rv[-1]
            xf = str(r.get("XbrlFile") or "").strip()
            xp = os.path.join(XD, xf + ".gz")
            if not os.path.exists(xp):
                rev_stat["revision file not cached"] += 1
                continue
            try:
                ra = analyse(read_doc(xp), qe)
            except Exception:
                rev_stat["revision unreadable"] += 1
                continue
            ra.pop("_pct", None)
            ra.pop("_shc", None)
            ra.update({"bse_code": code, "bse_grp": tv.get("grp"), "src": "bsexbrl:" + xf})
            bad, _ = identity_bse(sym, ra)
            rc = ra.get("cell")
            if bad:
                rev_stat["revision identity: " + bad[:40]] += 1
                continue
            if rc is None:
                rev_stat["revision parser refused"] += 1
                continue
            if ra["ambiguity"]:
                rev_stat["revision needs row-level placement (left out)"] += 1
                continue
            if ra["fmt"] == "new" and ra["partition_closes"] is False:
                rev_stat["revision public block does not close"] += 1
                continue
            if (
                rc["mf"] > rc["dii"] + 0.05
                or rc["ins"] > rc["dii"] + 0.05
                or rc["prom"] + rc["fii"] + rc["dii"] > 100.5
            ):
                rev_stat["revision fails the bounds"] += 1
                continue
            rdate = str(r["revised_date_time"])[:10]
            # a SAME-DAY correction (EPUJA Dec-2024, HBGHOTELS Mar-2026: revised hours after the original) was public that
            # day under the midnight rule — recorded with that date; only a "revision" dated BEFORE the original is dropped
            if rdate < cell[5]:
                rev_stat["revision dated before the original"] += 1
                continue
            new = [
                round(rc["prom"], 4),
                round(rc["fii"], 4),
                round(rc["dii"], 4),
                round(rc["mf"], 4),
                round(rc["ins"], 4),
            ]
            if max(abs(new[i] - cell[i]) for i in range(5)) < 0.005:
                rev_stat["revision repeats the original"] += 1
                continue
            revisions[sym][qe] = [*new, rdate, rc.get("nsh"), f"bsexbrl:{xf} bse-revision"]
            rev_stat["revision recorded"] += 1
    print(f"RE-FILINGS {dict(rev_stat)}")

    # ---- share counts: one per (sym, qe), identity-gated, stub/wrong-class screen against neighbours
    sh = collections.defaultdict(dict)
    for (sym, qe), a in docs.items():
        n = a.get("shares")
        if "error" in a or not n or n <= 0 or (identity_bse(sym, a) if a.get("bse_code") else identity(sym, a))[0]:
            continue
        sh[sym][qe] = [int(n), visibility(a)[0], a["src"]]
    sh_hold = 0
    prev_sh = {}
    if window and os.path.exists(SHARES_HIST):
        prev_sh = json.load(open(SHARES_HIST, encoding="utf-8"))
        prev_sh.pop("_meta", None)
    for sym, qs in sh.items():
        if window:  # neighbours = the stored series + this window
            for q_, v_ in (prev_sh.get(sym) or {}).items():
                qs.setdefault(q_, v_)
        ks = sorted(qs)
        bad = []  # decide on the untouched series, drop afterwards
        for idx, qe in enumerate(ks):
            if window and qe not in window:
                continue
            nb = [qs[ks[j]][0] for j in (idx - 2, idx - 1, idx + 1, idx + 2) if 0 <= j < len(ks)]
            n = qs[qe][0]
            if nb and all(n < x / 5 or n > x * 5 for x in nb):
                holds[sym].setdefault(qe, {})["shares"] = "share count %d is >5x off every neighbour %s" % (n, nb)
                bad.append(qe)
        for qe in bad:
            qs[qe] = None
            sh_hold += 1
    sh = {s: {q: v for q, v in qs.items() if v} for s, qs in sh.items()}
    sh = {s: qs for s, qs in sh.items() if qs}

    built = (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M IST")
    if not window and (prev_led or head):
        # §180e: a full build re-judges only the quarters whose FILING it read (or set aside) this run. A ledger cell whose
        # document is not on this machine — landed by the GitHub update job, whose files live only on its runner — is
        # carried over unchanged, never dropped for a missing local file (measured: a local full build after the first CI
        # run would have dropped all 9 cells that run landed).
        judged = set(docs) | set(set_aside)
        carried = 0
        for src_ in ((prev_led.get("fills") or {}), head):  # the ledger on disk and the committed one
            for s_, qs_ in src_.items():
                for q_, c_ in qs_.items():
                    if (s_, q_) not in judged and q_ not in fills.get(s_, {}):
                        fills[s_][q_] = c_
                        carried += 1
        for s_, qs_ in (prev_led.get("revisions") or {}).items():
            for q_, c_ in qs_.items():
                if (s_, q_) not in judged and q_ not in revisions.get(s_, {}):
                    revisions[s_][q_] = c_
        if os.path.exists(SHARES_HIST):
            for s_, qs_ in json.load(open(SHARES_HIST, encoding="utf-8")).items():
                if s_ == "_meta":
                    continue
                for q_, v_ in qs_.items():
                    if (s_, q_) not in judged and q_ not in (sh.get(s_) or {}):
                        sh.setdefault(s_, {})[q_] = v_
        if carried:
            print("carried over %d ledger cells whose filing is not on this machine" % carried)
    if window:
        # MERGE onto the committed ledger: landed cells are never replaced here (fill-only), a window quarter evaluated
        # this run takes this run's hold (or loses a stale one), and share counts / re-filings are added the same way
        n_new = sum(len(v) for v in fills.values())
        merged = {s_: dict(q_) for s_, q_ in (prev_led.get("fills") or {}).items()}
        for s_, qs_ in fills.items():
            for q_, c_ in qs_.items():
                merged.setdefault(s_, {}).setdefault(q_, c_)
        fills = merged
        rv = {s_: dict(q_) for s_, q_ in (prev_led.get("revisions") or {}).items()}
        for s_, qs_ in revisions.items():
            for q_, c_ in qs_.items():
                rv.setdefault(s_, {})[q_] = c_
        revisions = rv
        ph = (json.load(open(HOLDS, encoding="utf-8")).get("holds") or {}) if os.path.exists(HOLDS) else {}
        evaluated = set(docs)
        for s_, qs_ in ph.items():
            for q_, v_ in qs_.items():
                if (s_, q_) not in evaluated and q_ not in holds.get(s_, {}):
                    holds[s_][q_] = v_
        for s_, qs_ in prev_sh.items():
            for q_, v_ in qs_.items():
                sh.setdefault(s_, {}).setdefault(q_, v_)
        print("WINDOW %s: %d new cells merged onto the committed ledger" % (window, n_new))
    n_cells = sum(len(v) for v in fills.values())
    # BSE-only tickers, and NSE listings of 2026 whose NSE symbol IS their BSE id (grp NSE-new): their own SHP rows must
    # not make build_stock_fin treat the slug as taken and skip the same scrip's BSE fundamentals.
    bse_keys = {
        s_: bse_code_of[s_]
        for s_ in fills
        if s_ in bse_code_of and T.get(bse_code_of[s_], {}).get("grp") in ("BSE-only", "NSE-new")
    }
    if window:
        bse_keys = dict(prev_led.get("_bse_keys") or {}, **bse_keys)
    led = {
        "_bse_keys": dict(sorted(bse_keys.items())),
        "_meta": {
            "source": "NSE corporate-share-holdings-master XBRL (equities + SME boards) + BSE SHPQNewFormat XBRL",
            "built": built,
            "runbook": "§180",
            "symbols": len(fills),
            "cells": n_cells,
            "rule": "fill-only; parse_shp unchanged + partition-proven zeros; holds in _shp_allstocks_holds.json",
        },
        "fills": {s: dict(sorted(q.items())) for s, q in sorted(fills.items())},
        "revisions": {s: dict(sorted(q.items())) for s, q in sorted(revisions.items()) if q},
    }
    with gzip.open(LEDGER, "wt", encoding="utf-8") as fh:
        json.dump(led, fh, separators=(",", ":"), sort_keys=False)
    json.dump(
        {
            "_meta": {"built": built, "cells": sum(len(v) for v in holds.values())},
            "holds": {s: dict(sorted(q.items())) for s, q in sorted(holds.items()) if q},
        },
        open(HOLDS, "w", encoding="utf-8"),
        indent=0,
        default=str,
    )
    json.dump(
        {
            "_meta": {
                "built": built,
                "source": "NSE SHP XBRL whole-company NumberOfShares (parse_shares)",
                "shape": "{SYM: {QE: [shares, visible_date, src]}}",
                "symbols": len(sh),
                "cells": sum(len(v) for v in sh.values()),
                "held": sh_hold,
                "runbook": "§180",
            },
            **{s: dict(sorted(q.items())) for s, q in sorted(sh.items())},
        },
        open(SHARES_HIST, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print("LEDGER %s: %d cells / %d symbols" % (os.path.basename(LEDGER), n_cells, len(fills)))
    for k in sorted(stat, key=str):
        print("  ", k, stat[k])
    print("hold reasons:", dict(why.most_common()))
    print(
        "SHARES %s: %d cells / %d symbols, %d held"
        % (os.path.basename(SHARES_HIST), sum(len(v) for v in sh.values()), len(sh), sh_hold)
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["master", "download", "bse", "rowlevel", "build", "update"])
    ap.add_argument(
        "--quarters", default=None, help="update/build: comma list of quarter-ends (default: the last two closed)"
    )
    ap.add_argument("--cache", default=CACHE)
    ap.add_argument(
        "--shard", default="0/1", help="bse stage: k/n — this machine takes scrip codes with code %% n == k"
    )
    ap.add_argument("--cap", type=int, default=20000, help="bse stage: per-run file cap (runbook §181)")
    ap.add_argument("--max-minutes", type=int, default=0, help="bse stage: stop cleanly after this many minutes (CI)")
    ap.add_argument(
        "--codes", default=None, help="bse stage: JSON list of scrip codes to restrict this run to (later rounds)"
    )
    a = ap.parse_args()
    if a.stage == "bse":
        stage_bse(a.cache, cap=a.cap, shard=a.shard, max_minutes=a.max_minutes, codes_file=a.codes)
    elif a.stage == "update":
        stage_update(a.cache, quarters=a.quarters.split(",") if a.quarters else None, max_minutes=a.max_minutes)
    else:
        {"master": stage_master, "download": stage_download, "rowlevel": stage_rowlevel, "build": build}[a.stage](
            a.cache
        )
