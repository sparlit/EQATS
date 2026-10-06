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


#!/usr/bin/env python3
"""Row-level DII heal for the 2015-2022 old-format XBRL era (DATA_RUNBOOK §158): DII = Institutions(Domestic) B1 in
every format. Stages (all local; the ledger is the only repo output):
  classify  -> <work>/proposals.json   one proposal per stored N500 cell that moves >= 0.05 pp (dii or fii)
  one SYM,.. -> verbose trace of one or more symbols
  verify    -> apply the proposals to a COPY of shp_history.json, re-measure the Sep-2022 / 2016 seams
  revfix    -> <work>/revfix.json      the same rules applied to re-filing rows (scripts/shp_revisions.json)
  write     -> merge proposals into scripts/shp_cell_fix.json (+ scripts/_shp_dii_rowfix_audit.json), revfix into
               scripts/shp_revisions.json
Inputs (local, not tracked): BSE SHPQNewFormat lists per symbol (<lists>/<SYM>.json, the 2026-09-22 cache — api.bseindia.com
is 403 since 23-Sep), raw XBRLs in the cache dirs (www.bseindia.com/XBRLFILES/SHPXBRLDataXML/<file> with a bseindia Referer),
<work>/n500_syms.json (the N500 roster present in the store). Environment: DII_ROWFIX_WORK, DII_ROWFIX_LISTS,
DII_ROWFIX_CACHES (os.pathsep-separated). See the runbook section for the rules; every decision is written to the audit file.
"""
import collections
import copy
import difflib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

import _shp_registers as _REG

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
HERE = os.environ.get("DII_ROWFIX_WORK") or os.path.join(SCRIPTS, "_shp_dii_rowfix_work")
LISTS = os.environ.get("DII_ROWFIX_LISTS") or os.path.join(HERE, "bse_all")
CACHES = (os.environ.get("DII_ROWFIX_CACHES") or os.path.join(HERE, "xbrl_bse")).split(os.pathsep)
sys.path.insert(0, SCRIPTS)
sys.argv = sys.argv[:1] + sys.argv[1:]
import contextlib

import fetch_shareholding as F


def breakdown(txt):
    """{member: pct} for every single-explicit-member context (no typed members), scaled to percent."""
    root = ET.fromstring(txt) if isinstance(txt, (str, bytes)) else txt

    def strip(t):
        return t.split("}", 1)[-1]

    ctx = {}
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        mems = []
        typed = False
        for m in c.iter():
            st = strip(m.tag)
            if st == "explicitMember":
                mems.append((m.text or "").split(":")[-1].strip())
            elif st == "typedMember":
                typed = True
        ctx[c.get("id")] = mems if not typed else None
    out = {}
    for f in root.iter():
        if strip(f.tag) != "ShareholdingAsAPercentageOfTotalNumberOfShares":
            continue
        mems = ctx.get(f.get("contextRef"))
        if not mems:
            continue
        try:
            v = float(str(f.text).strip())
        except Exception:
            continue
        out["/".join(mems)] = v
    tot = out.get("ShareholdingPatternMember")
    if tot is not None and tot <= 1.5:
        out = {k: v * 100 for k, v in out.items()}
    return out


MON = {"March": 3, "June": 6, "September": 9, "December": 12}
# §164r batch 24 (2026-10-05, cell by cell vs Quantmac): filers misspell the category words - BLUESTARCO Jun-2016 'FORIGN MUTUAL FUND',
# ADANIPOWER Jun-2016 'FORIEGN CORPORATE BODIES', SHRIRAMCIT Jun-2016 'Foreign Port Folio Investor', 'Foreign Portolio Investor' -
# and the exact-spelling patterns read those rows as UNLABELLED. _FOR / _PFO accept the spellings seen in filings.
_FOR = r"(?:foreig|forieg|forign|foregin|forein|forigin|foerign|foregn|foreigh)"
_PFO = r"port\s*-?\s*f?olio"
LAB_FII = re.compile(
    r"\bfiis?\b|\bfpis?\b|\bqfi\b|"
    + _FOR
    + r"\w*\s+"
    + _PFO
    + r"|"
    + _FOR
    + r"\w*\s+instit|"
    + _FOR
    + r"\w*\s+bank|"
    + _FOR
    + r"\w*\s+venture|qualified\s+(?:"
    + _FOR
    + r"|fore\b)|sovereign",
    re.I,
)
LAB_PUB = re.compile(
    r"overseas corporate|\bocb\b|"
    + _FOR
    + r"\w* compan|"
    + _FOR
    + r"\w* (corporate )?bod|corporate bodies|"
    + _FOR
    + r"\w* nat\w*nals?|"
    + _FOR
    + r"\w* individual|non.?resident|\bnris?\b",
    re.I,
)
# §164r batch 11 (user 2026-10-04 'yes fix the label bug'): a non-institution category a company writes on a sub-row of its
# institutions 'Any Other' block - Bodies Corporate, Central / State Government, IEPF, trusts, clearing members, individuals, HUF,
# employees, directors, unclaimed / suspense accounts - is company-, government- or person-type: never FII and never DII
# (Institutions (Domestic)). These had read as UNLABELLED, so D1 / rest-follows moved them into FII: IDFC Jun-2016 'BODIES
# CORPORATE' 5.44, TNPL Jun-2016 'CENTRALGOVERNMENT /STATE GOVERNMENT' 4.07. (Not added to LAB_PUB: the R2 non-institution loop
# must keep reading named domestic institutions a company files under 'Bodies Corporate'.)
_NI_CAT = (
    r"(?:indian\s+)?bod(?:y|ies)\s*corporates?|corporate\s+bod(?:y|ies)|corporates?"
    r"|limited\s+liab\w*\s+partnerships?(?:\s*/\s*corporate\s+bod(?:y|ies))?(?:\s*-\s*llps?)?|llps?"
    r"|central\s*(?:/|and|&)?\s*state\s*gov\w*(?:\s*\(s\))?|centralgovernment\s*/?\s*state\s*government(?:\s*\(s\))?|(?:central|state)\s+gov\w*(?:\s*\(s\))?"
    r"|government(?:\s+of\s+india)?|govt\.?(?:\s+of\s+india)?|president\s+of\s+india"
    r"|iepf(?:\s+authority)?|investor\s+education\s+(?:and|&)\s+protection\s+fund(?:\s+authority)?(?:\s*\(mca\))?"
    r"|trusts?|clearing\s+members?|individuals?(?:\s*-\s*huf)?|huf|hindu\s+undivided\s+famil(?:y|ies)|employees?|directors?(?:\s+(?:and|&)\s+(?:their\s+)?relatives?)?"
    r"|unclaimed\b.*|suspense\b.*|escrow\b.*"
    # §164r batch 26 (labels scan 2026-10-05): more company- / person-type categories filers write on institutions sub-rows
    r"|(?:domestic|indian)\s+(?:compan(?:y|ies)|bod(?:y|ies)\s*corporates?|corporates?)|market\s+makers?|nris?"
    r"|non[\s-]*resident\s+indians?(?:\s*\((?:non[\s-]*)?repat\w*\))?"
)
NONINST_LAB = re.compile(rf"(?:{_NI_CAT})(?:\s*\([^)]*\))?", re.I)


def noninst_label(lab):
    """True when the WHOLE label (after the filer's 'Other / Others / Any Other' prefix) is a non-institution category - never
    for a holder's name that merely contains such a word ('GOLDMAN SACHS TRUST - ...', 'CITY OF NEW YORK GROUP TRUST',
    'PACIFIC ASSETS TRUST PLC', 'Employees Retirement plan of Duke University' are foreign institutions)."""
    core = re.sub(r"^\s*(?:(?:any\s+)?others?\b[\s:\-\u2013]*)+", "", lab or "", flags=re.I).strip(
        " .:-\u2013"
    )
    return (
        bool(core)
        and bool(NONINST_LAB.fullmatch(core))
        and not LAB_FII.search(lab or "")
        and not DOMLAB.search(lab or "")
    )


FORLAB = re.compile(
    r"foreig|forieg|forign|foregin|forein|forigin|foerign|foregn|qualified\s+fore\b|muscat|s\.?a\.?o\.?g\b|overseas|\bfpi\b|\bfii\b|\bocb\b|non.?resident|\bnri\b|mauritius|singapore|\bpte\b|\bb\.?v\.?\b|\bllc\b|\bl\.?p\.?\b|\binc\b|\bplc\b|\bltd\.? *\((uk|usa|us)\)|university|college|\bsa\b|\bag\b|\bgmbh\b|\bnv\b|luxembourg|cayman|netherlands|\busa\b|\buk\b|japan|korea|hong ?kong|cyprus|delaware|\bsarl\b|\bs\.?a\.?r\.?l\b|holdings? (ii|iii|iv|v)\b|\bpty\b|\bcapital partners\b|\bglobal\b|international|\bsicav\b|\bucits\b|\boeic\b",
    re.I,
)
DOMSTRONG = re.compile(
    r"insur|assurance|provident|pension|nps trust|national pension|mutual fund|\bmagnum\b|\blic\b|\blici\b|qualified inst|q[au]+lified|instit\w* buyers?|\bqib",
    re.I,
)
DOMLAB = re.compile(
    r"insur|assurance|provident|pension|nps trust|national pension|mutual fund|\blic\b|\blici\b|qualified inst|q[au]+lified|instit\w* buyers?|\bqib|\bnbfc|non.?banking|financial institution|\bbank|alternat(e|ive) investment|venture capital|asset reconstruct|general insurance corp",
    re.I,
)
SOVNAME = re.compile(
    r"pension fund global|government of (?!india)|monetary authority|\bnorges\b|abu dhabi|\bqatar\b|\bkuwait\b|sovereign",
    re.I,
)  # §164s part 7
# §164s part 10 (user 2026-10-05 "Count none of it"): ONE row that mixes an institution with NRIs / IEPF / non-institutions and gives
# no split (LTTS Sep-2019 'QUALIFIED INSTITUTIONAL BUYER + NON RESIDENT INDIAN' 1.57) is not a domestic-institution row - none of it is DII
MIXLAB = re.compile(
    r"non.?resident|\bnri\b|\bnrn\b|\biepf\b|investor education|non.?indian|\bhuf\b|individual",
    re.I,
)
MIXED_OUT = os.environ.get("DII_MIXED_OUT", "1") == "1"
# §164s part 10 (user 2026-10-05 "Follow IEX's own label"): a holder the company files under its own foreign-company label inside the
# Institutions block ('Overseas Corporate Bodies') is not domestic on the strength of OTHER companies' filings alone (IEX 2018-20 'India
# Business Excellence Fund IIA'); only the company's own 2022-form placement or an official register can make it domestic there
OWN_LABEL_FIRST = os.environ.get("DII_OWN_LABEL_FIRST", "1") == "1"
GROUP_OUTSIDE = (
    os.environ.get("DII_GROUP_OUTSIDE", "1") == "1"
)  # §164s part 10; env 0 = the earlier attachment
NAMED_UNPROVEN_OUT = (
    os.environ.get("DII_NAMED_UNPROVEN_OUT", "1") == "1"
)  # §164s part 7 (user 2026-10-05); env 0 = the earlier evaluation
REST_FOLLOWS = True  # §158a/§158b (2026-09-25): with the rule on, a full N500 run proposes 0 on the live store; False = the §158 (2026-09-24) evaluation
# §164 (FII session, 2026-09-25): "§164 row-level remainder rule" (D1 unnamed Any-Other rest -> fii, ex-member re-reads) and "§164a
# depository-receipt basis" (pre-2016 re-base of all five slots). These rules re-decide cells this script and _shp_aspx_rowfix.py
# would otherwise re-evaluate on their older basis and propose moving back, so both classify stages SKIP any cell whose ledger chain
# carries a §164 marker. (Prior-state alternative, if ever needed: a remainder entry's cell - was is a pure dii->fii move of
# _shp_164_audit.json cells[key]["d1"], plus ["mv159"] into fii for ex-members, carried through R1 the way ext_fii carries §159.)
MARK164 = re.compile(r"\u00a7164 row-level remainder rule|\u00a7164a depository-receipt basis")


def chain_has(prior, rx=MARK164, depth=12):
    """True when any entry in a ledger cell's superseded chain carries `rx` in its why."""
    link = prior
    d = 0
    while isinstance(link, dict) and d < depth:
        if rx.search(str(link.get("why") or "")):
            return True
        link = link.get("superseded")
        d += 1
    return False


INSURER = re.compile(r"insur|assurance|\blic\b|\blici\b|life ins", re.I)


def qe_of(qtr):
    q = (qtr or "").strip().split()
    if len(q) != 2 or q[0] not in MON:
        return None
    m = MON[q[0]]
    return "%s-%02d-%02d" % (q[1], m, 31 if m in (3, 12) else 30)


def find_file(f):
    for c in CACHES:
        p = os.path.join(c, f)
        if os.path.exists(p):
            return p
    return None


def rows_of(txt):
    """Typed rows in filer order: [(axis, seq, pct, kind, cat, name)]. Values scaled to percent."""
    root = ET.fromstring(txt)

    def strip(t):
        return t.split("}", 1)[-1]

    ctx = {}
    for c in root.iter():
        if strip(c.tag) != "context":
            continue
        for m in c.iter():
            if strip(m.tag) == "typedMember":
                dim = (
                    (m.get("dimension") or "")
                    .split(":")[-1]
                    .replace("DetailsOfSharesHeldBy", "")
                    .replace("DetailsSharesHeldBy", "")
                    .replace("Axis", "")
                )
                val = "".join((x.text or "") for x in m.iter() if x is not m).strip()
                ctx[c.get("id")] = (dim, val)
    R = {}
    frac = True
    for f in root.iter():
        t = strip(f.tag)
        k = ctx.get(f.get("contextRef"))
        if t == "ShareholdingAsAPercentageOfTotalNumberOfShares" and not k:
            try:
                if float(f.text) > 1.5:
                    frac = False
            except:
                pass
        if not k:
            continue
        r = R.setdefault(k, {})
        if t == "ShareholdingAsAPercentageOfTotalNumberOfShares":
            with contextlib.suppress(BaseException):
                r["p"] = float(f.text)
        elif t.startswith("CategoryOf"):
            r["cat"] = (f.text or "").strip()
        elif t.startswith("NameOf"):
            r["name"] = (f.text or "").strip()
        elif t.startswith("WhetherACategory"):
            r["kind"] = (f.text or "").strip()
    out = []
    for (ax, val), v in R.items():
        if "p" not in v:
            continue
        seq = int(re.sub(r"\D", "", val) or 0)
        out.append(
            (
                ax,
                seq,
                v["p"] * (100 if frac else 1),
                (v.get("kind") or ""),
                (v.get("cat") or ""),
                (v.get("name") or ""),
            )
        )
    return sorted(out)


def groups(rows, axis, total=None):
    """Category rows on one axis with their attached >=1% holders. A holder row carries the filer's own
    category text; it is attached to the category row with the SAME text that has room for it (the nearest
    preceding one first), then to any same-text row, then to the preceding row if it fits, else it forms
    an orphan group (pct 0) so it is never counted twice. Filers list holders before OR after the row."""
    cats = []
    holders = []
    for ax, seq, p, kind, cat, name in rows:
        if ax != axis:
            continue
        is_cat = kind.lower().startswith("categ") or (not kind and not name)
        # §164r batch 10: runs of spaces collapse in the label the rules read (BHARATFIN Sep-2016 'Other Foreign  Bodies Corporates' - two
        # spaces - missed the company-type pattern and fell through to the FII reading); attachment still compares the raw text
        if is_cat:
            cats.append(
                {
                    "seq": seq,
                    "pct": p,
                    "label": re.sub(r"\s+", " ", cat + " " + name).strip(),
                    "cat": cat,
                    "name": name,
                    "holders": [],
                }
            )
        else:
            holders.append((seq, p, name or cat, cat))

    def room(g, p):
        return sum(h[0] for h in g["holders"]) + p <= g["pct"] + 0.02

    outside = [(total - sum(g["pct"] for g in cats)) if total is not None else 0.0]
    for seq, p, name, cat in sorted(holders, key=lambda x: -x[1]):
        same = [g for g in cats if norm(g["cat"]) == norm(cat)]
        prev = [g for g in same if g["seq"] < seq]
        nxt = [g for g in same if g["seq"] > seq]
        target = None
        for g in sorted(prev, key=lambda g: -g["seq"]) + sorted(nxt, key=lambda g: g["seq"]):
            if room(g, p):
                target = g
                break
        if target is None:
            # no same-text row has room: the holder still belongs to SOME row on this axis (the filer changed
            # its label between the category row and the holder row) — nearest preceding row with room, else next
            # §164s part 10: when the axis TOTAL the filer reports has room OUTSIDE its category rows for this holder, the holder is
            # not inside any of them (GABRIEL Sep-2021: categories 4.66 of a 6.19 Any-Other total, 'ICICI Lombard' 1.52 filed under
            # 'Others' with no such row) - it forms its own group instead of borrowing a different label's row. When the category rows
            # already add up to the total (CREDITACC / IEX / SRF), every holder sits inside one of them and the borrowing stands.
            if GROUP_OUTSIDE and total is not None and outside[0] >= p - 0.02:
                outside[0] -= p
                target = {
                    "seq": seq,
                    "pct": 0.0,
                    "label": re.sub(r"\s+", " ", cat).strip(),
                    "cat": cat,
                    "name": "",
                    "holders": [],
                    "orphan": True,
                }
                cats.append(target)
                target["holders"].append((p, name))
                continue
            before = [g for g in cats if g["seq"] < seq and room(g, p)]
            after = [g for g in cats if g["seq"] > seq and room(g, p)]
            if before:
                target = before[-1]
            elif after:
                target = after[0]
        if target is None:
            target = {
                "seq": seq,
                "pct": 0.0,
                "label": re.sub(r"\s+", " ", cat).strip(),
                "cat": cat,
                "name": "",
                "holders": [],
                "orphan": True,
            }
            cats.append(target)
        target["holders"].append((p, name))
    return sorted([g for g in cats if g["pct"] > 0.0049 or g["holders"]], key=lambda g: g["seq"])


def norm(n):
    return re.sub(r"[^A-Z0-9]", "", (n or "").upper())


FORWORD = re.compile(
    r"for[ei]{0,2}g[nh]|" + _FOR + r"|overseas", re.I
)  # §164s part 9: also the filers' misspellings (BLUESTARCO Jun-2016 'FORIGN MUTUAL FUND' 0.53, IPCALAB Jun-2017 'Foreigh Mutual Fund' 0.55, 'Foriegn')      # §164j: a label naming a FOREIGN institution ("Foreign Mutual Fund", "Foreign Financial Institutions / Banks", "Bank Foreign") is never a domestic label, whatever domestic keyword it also carries


def _load_evidence():
    """§164j (user 2026-09-26: named foreign holders need DOCUMENTARY proof): norm(name) -> entry from scripts/shp_foreign_holder_evidence.json."""
    try:
        e = (
            json.load(
                open(
                    os.path.join(REPO, "scripts", "shp_foreign_holder_evidence.json"),
                    encoding="utf-8",
                )
            ).get("names")
            or {}
        )
    except (OSError, ValueError):
        e = {}
    return {norm(k): v for k, v in e.items()}


EVIDENCE = _load_evidence()


def _evidence(n):
    """The documented entry for a normalised name: exact, a >= 20-char prefix of the other (filers truncate names at ~40
    chars), or a >= 0.92 match sharing the first 12 characters."""
    e = EVIDENCE.get(n)
    if e is None and len(n) >= 12:
        for k, v in EVIDENCE.items():
            if k[:12] != n[:12]:
                continue
            if (
                (len(n) >= 20 and k.startswith(n))
                or (len(k) >= 20 and n.startswith(k))
                or difflib.SequenceMatcher(None, n, k).ratio() >= 0.92
            ):
                e = v
                break
    return e


_SER = re.compile(r"^(?:[IVX]+|\d+|FII|FPI|FDI|ODI|[A-H])$")


def _series(name):
    return tuple(sorted(t for t in re.split(r"[^A-Z0-9]+", str(name).upper()) if _SER.match(t)))


_ABBR = [
    (r"\bLIMITED\b", "LTD"),
    (r"\bPRIVATE\b", "PVT"),
    (r"\bCOMPANY\b", "CO"),
    (r"\bCORPORATION\b", "CORP"),
    (r"\bINCORPORATED\b", "INC"),
]


def anorm(name):
    """norm() after spelling legal-form words one way (LIMITED = LTD, PRIVATE = PVT, COMPANY = CO ...): the same legal name
    written 'Ltd' by one filer and 'Limited' by another (Morgan Stanley Mauritius Company Ltd / Limited) is one holder."""
    s = re.sub(r"^\W*[ivx]+\)\s*", "", str(name).upper())
    for a, b in _ABBR:
        s = re.sub(a, b, s)
    return re.sub(r"[^A-Z0-9]", "", s)


_AIDX = None


def _ev_matches(name):
    """§164r batch 10: every evidence entry that names the same legal holder - the exact spelling (legal-form words spelled one
    way), every spelling >= 0.96 alike with the same series markers (batch 7's corpus test), and - for a holder name the filer cut
    off at ~40 characters - the full names it is the start of. Counts across the matched spellings are summed, as batch 7 did."""
    global _AIDX
    if _AIDX is None:
        _AIDX = {}
        for k, v in EVIDENCE.items():
            _AIDX.setdefault(anorm(v.get("name") or k), []).append(v)
    a = anorm(name)
    out = list(_AIDX.get(a, []))
    if len(a) >= 10:
        ser = _series(name)
        cut = len(str(name).strip()) >= 38 and len(a) >= 25
        for k, vs in _AIDX.items():
            if k == a or k[:8] != a[:8]:
                continue
            if (
                difflib.SequenceMatcher(None, a, k).ratio() >= 0.96
                and _series(vs[0].get("name", k)) == ser
            ) or (cut and k.startswith(a)):
                out += vs
    return out


def _ev_counts(name):
    vs = _ev_matches(name)
    if not vs:
        return None
    f = sum(v.get("inst_n") or 0 for v in vs)
    d = sum(v.get("domestic_n") or 0 for v in vs)
    c = sum(v.get("company_n") or 0 for v in vs)
    reg = any(v.get("proof") == "sebi-register" for v in vs)
    return f, d, c, reg


def inst_documented(name):
    """§164r batch 7 (user 2026-09-29 'Documents only') + batch 8 (user 2026-10-04, Quantmac's standard): a holder filed among
    ordinary shareholders is an institution on another company's filing only with >= 90 % of >= 5 classified listings under
    Institutions (Foreign), or a registry document (SEBI FPI / FVCI register). Identity: see _ev_matches."""
    x = _ev_counts(name)
    if not x:
        return False
    f, d, c, reg = x
    return reg or (f + d + c >= 5 and f >= 0.9 * (f + d + c))


def inst_listed(name):
    """§164r batch 8 scope (user 2026-10-04, option A): the proof a holder needs when the COMPANY ITSELF lists it inside its
    Institutions block (on a company-type or unlabelled sub-row): the company's own placement plus at least one other filing
    listing the same legal name under Institutions (Foreign) (never a domestic-dominated name), or a registry document. The strict
    >= 90 %-of->= 5 proof (inst_documented) is for holders the company lists among ordinary shareholders only - as Quantmac applies
    it. IEX's Rimco (Mauritius) 4.55 inside IEX's Institutions block: 13 institution listings -> FII."""
    x = _ev_counts(name)
    if not x:
        return False
    f, d, c, reg = x
    return reg or (f >= 1 and (d == 0 or f >= 0.9 * (f + d)))


# §164r batch 10 (user 2026-10-04 'fix the open items'): a holder the company ITSELF files as a foreign investor in another of its
# filings - on an FPI / FDI / FVCI row, or on a row it labels FII / FPI / QFI - stays FII in a quarter where the same company lists
# it on an UNLABELLED institutions row: option A must not make the silent quarters public against the company's own label on both
# sides (POONAWALLA Jun-2016..Jun-2017: 'QFI - ZEND / INDIUM V / LEAPFROG' on BSE's Dec-2015 holder list, 'QFI-Corporate' from
# Sep-2017). SymCtx.own_fii reads the symbol's own XBRLs; OWN_FII_EXTRA carries the company marks that only BSE's pre-2016 pages or a
# spelling variant show (each checked 2026-10-04 on the cached pages / filings).
OWN_FII_EXTRA = {
    "POONAWALLA": [
        "INDIUM V (MAURITIUS) HOLDINGS LIMITED"
    ],  # 'QFI - INDIUM V (MAURITIUS) HOLDINGS LIMITED', BSE Dec-2015 list
    "JISLJALEQS": [
        "MKCP INSTITUTIONAL INVESTOR (MAURITIUS) II LTD"
    ],  # its 7.93 % fits only the FII (121) / QFI (3 holders) rows of the Jun/Sep-2015 pages
    "BRITANNIA": ["ARISAG PARTNERS (ASIA)PTE LTD A/C ARISAG"],
}  # = 'Arisaig Partners (Asia) Pte Ltd A/C Arisaig India Fund', BRITANNIA's own 'Foreign Institutional Investors' row Sep-2016..Jun-2017
# §164r batch 13 (user 2026-10-04 'yes fix all three'): a holder name the company cut short in ONE filing is read as the full
# legal name the SAME company prints for the same holding (same share count) in its neighbouring filings, before the evidence
# test - the short form can collide with a different vehicle's listings. SHILPAMED Mar-2017 'BARING INDIA PRIVATE EQUITY FUND III'
# 6,000,000 shares (7.4881) = 'BARING INDIA PRIVATE EQUITY FUND III LIMITED' 6,000,000 shares in Dec-2016 and Sep-2017, filed on
# company-type rows (Foreign / Overseas Corporate Bodies) with no institution listing under that name; the short form's 12
# institution listings are other companies' FPI rows (e.g. 531213). Checked on the cached filings 2026-10-04.
OWN_NAME = {
    "SHILPAMED": {
        "BARING INDIA PRIVATE EQUITY FUND III": "BARING INDIA PRIVATE EQUITY FUND III LIMITED"
    },
    # §164r batch 14: 'Internation Finance Corporation' on PARAGMILK's FDI line (29-Sep-2025 filing) = 'International Finance
    # Corporation' on its Foreign Companies line Dec-2025..Jun-2026 - the same 5,733,713 shares (checked 2026-10-04)
    "PARAGMILK": {"INTERNATION FINANCE CORPORATION": "INTERNATIONAL FINANCE CORPORATION"},
    # §164r batch 14, same share count in the company's adjacent filings (checked 2026-10-04): SMLMAH Mar-2020 'ISUZU MOTORSLIMITED'
    # 2,170,747 = 'ISUZU MOTORS LIMITED' Dec-2019; SWANCORP Mar/Sep-2018 '2I CAPITAL PCC - Foreign Company' 23,077,000 = '2I CAPITAL PCC'
    # Dec-2017 / Jun-2018; JSWSTEEL: JFE moved its block to its Dutch subsidiary - 'JFE Steel Corporation' 33,467,580 shares in
    # Mar-2012, 'JFE Steel International Europe B V' 33,467,580 in Jun-2012 (BSE >1% lists, qtrid 73 / 74)
    "SMLMAH": {"ISUZU MOTORSLIMITED": "ISUZU MOTORS LIMITED"},
    "SWANCORP": {"2I CAPITAL PCC - FOREIGN COMPANY": "2I CAPITAL PCC"},
    "JSWSTEEL": {"JFE STEEL CORPORATION": "JFE STEEL INTERNATIONAL EUROPE B.V."},
    # §164r batch 19 (2026-10-05): Thai Union Frozen Products PCL renamed itself Thai Union Group PCL in 2015. AVANTIFEED's own
    # Dec-2015 Table III files 'Foreign Corporate Bodies- Thai Union Fro...' 11,410,210 shares; Dec-2016..Dec-2017 file the same
    # 11,410,210 shares as 'THAI UNION FROZEN PRODUCTS PUBLIC CO LTD' inside Institutions - Any Other; from Mar-2018 the company
    # files 'THAI UNION GROUP PUBLIC COMPANY LTD' under 'Overseas Corporate Bodies' and in its 2022 form under Foreign Companies
    "AVANTIFEED": {
        "THAI UNION FROZEN PRODUCTS PUBLIC CO LTD": "THAI UNION GROUP PUBLIC COMPANY LIMITED",
        "THAI UNION FROZEN PRODUCTS PUBLIC COMPANY LIMITED": "THAI UNION GROUP PUBLIC COMPANY LIMITED",
        "THAI UNION FORZEN PRODUCTS PLC": "THAI UNION GROUP PUBLIC COMPANY LIMITED",
    },  # Jun-2017's misspelling, same 11,410,210 shares
    # 2026-10-05: HEXAWARE files T. Rowe Price International Discovery Fund as 'T ROWE PRICE DISCVERY FUND' (Jun-2016, 5,786,515) and
    # 'T ROWE PRICE INTERNATIONAL DISCVERY FUND' (Dec-2016, 6,213,210 = the 6,213,210 of Sep-2016's correctly spelt row)
    "HEXAWARE": {
        "T ROWE PRICE DISCVERY FUND": "T ROWE PRICE INTERNATIONAL DISCOVERY FUND",
        "T ROWE PRICE INTERNATIONAL DISCVERY FUND": "T ROWE PRICE INTERNATIONAL DISCOVERY FUND",
    },
}


def own_name(sym, hn):
    return (OWN_NAME.get(sym) or {}).get(re.sub(r"\s+", " ", str(hn or "")).strip().upper(), hn)


OWN_FOR_AX = (
    "InstitutionsForeignPortfolioInvestor",
    "ForeignPortfolioInvestor",
    "ForeignDirectInvestment",
    "ForeignVentureCapital",
    "SovereignWealthFunds",
    "OtherInstitutionsForeign",
    "InstitutionsForeign",
    "ForeignInstitutionalInvestors",
)
# §164r batch 10: some filers write their category in front of the holder ('Foreign Bodies Corporate- Jomei Investments Limited',
# ABCAPITAL 2020-22; 'QFI - ZEND ...' on BSE's 2015 lists). The bare name is what the company's own 2022-form row and its other
# filings carry ('Jomei Investments Limited' on ABCAPITAL's Foreign Direct Investment row from Sep-2022).
_CATPFX = re.compile(
    r"^\s*(?:(?:foreign|overseas)\s+(?:bod(?:y|ies)\s+corporates?|corporate\s+bod(?:y|ies)|compan(?:y|ies))|fiis?|fpis?|qfis?|fdi|fvci|ocb)\s*[-\u2013:]\s*",
    re.I,
)


def _bare_name(name):
    b = _CATPFX.sub("", str(name or ""), count=1).strip()
    return b if len(b) >= 3 else str(name or "")


def _same_holder(a, b):
    """Strict legal-name identity (as the evidence test): exact after legal-form normalisation, >= 0.96 alike with the same series
    markers, or the start of a name cut off at >= 25 characters."""
    x, y = anorm(a), anorm(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if min(len(x), len(y)) >= 25 and (x.startswith(y) or y.startswith(x)):
        return True
    return difflib.SequenceMatcher(None, x, y).ratio() >= 0.96 and _series(a) == _series(b)


# §164r batch 14 (user 2026-10-04 'yes go with A'): the company's own 'Foreign Direct Investment' line (2022 form, B2 Institutions
# (Foreign)) in ANY of its filings - not only the FIRST 2022-form filing newmap_for reads - decides that holder in every quarter.
# Companies moved the same shares between 'Foreign Companies' and the FDI line (JSWSTEEL: JFE Steel 15.00 under Foreign Companies in
# Sep-2022, on the FDI line from Dec-2022; DELHIVERY 49.78 at Mar-2023; PPLPHARMA: CA Alchemy back to Foreign Companies in Jun-2026),
# so a first-filing read made FII jump or drop with no trade. Registry scripts/shp_fdi_holders.json: per company, every holder it
# files on its FDI line, with the first and last such filing (quarter, %, XBRL). Strict identity (_same_holder on the bare name).
def _load_fdi_reg():
    try:
        return (
            json.load(
                open(os.path.join(REPO, "scripts", "shp_fdi_holders.json"), encoding="utf-8")
            ).get("holders")
            or {}
        )
    except (OSError, ValueError):
        return {}


FDI_REG = _load_fdi_reg()


def fdi_line(sym, hn):
    """The registry entry when the company itself files `hn` on its FDI line in some 2022-form filing, else None."""
    regs = FDI_REG.get(sym)
    if not regs or not hn:
        return None
    hb = _bare_name(own_name(sym, hn))
    for h in regs:
        if _same_holder(hb, _bare_name(own_name(sym, h["name"]))):
            return h
    return None


def _documented_foreign(n, what):
    """A name whose only sign of being foreign is the name itself: FII only with a document on file (GLEIF / another filing's
    foreign-institution row); otherwise unresolved — never foreign by name alone."""
    e = _evidence(n)
    if e and e.get("class", "foreign") == "foreign":
        return "foreign", "fii", "documented:" + e.get("proof", "")
    if e and e.get("class") == "domestic":
        return "domestic", None, "documented:" + e.get("proof", "")
    return None, None, f"name-only ({what}; no document)"


def load_verdicts():
    a = json.load(open(os.path.join(REPO, "scripts", "_shp_other_inst_audit.json")))
    return {norm(k): v for k, v in (a.get("name_verdicts") or {}).items()}


def holder_class(name, verdicts, newmap, pct=None):
    """-> (cls 'foreign'|'domestic'|None, dest 'fii'|'public'|None, evidence). Priority: the filer's own
    new-format placement > curated verdict > strong domestic markers (insurer/NPS/LIC/MF/QIB) > foreign
    markers (jurisdiction, plc/llc/pte, 'global', university...) > weak domestic markers (bank, FI, AIF)."""
    n = norm(name)
    newmap = newmap or {}
    nb = norm(_bare_name(name))
    hit = None
    if n in newmap:
        pr = pick_row(newmap[n], pct)
        hit = (pr, "new-format:" + pr[1])
    elif nb != n and nb in newmap:
        pr = pick_row(newmap[nb], pct)
        hit = (pr, "new-format:" + pr[1])  # §164r batch 10: category-prefixed name
    else:
        best = None
        for k, rows in newmap.items():
            if len(n) >= 10 and len(k) >= 10 and abs(len(n) - len(k)) <= 8:
                r = difflib.SequenceMatcher(None, n, k).ratio()
                if r >= 0.85 and (best is None or r > best[0]):
                    best = (r, pick_row(rows, pct))
        if best:
            hit = (best[1], "new-format~:" + best[1][1])
    if hit:
        (cls, src), how = hit
        if cls == "fii":
            return "foreign", "fii", how
        # §164s part 9 (rule 4, user 2026-10-04 "use registers"): a holder an official register proves to be an Indian institution
        # (IRDAI insurer, PFRDA NPS Trust, RBI bank / NBFC) is domestic even when the company's 2022 form files it among
        # non-institutions - BAJAJCON 2020 'ICICI Lombard General Insurance' 1.40 inside its QIB row had been read as foreign
        if cls == "public" and _REG.register(name):
            return "domestic", None, "register:" + _REG.register(name)[:60]
        if cls == "public":
            return "foreign", "public", how
        return "domestic", None, how
    if n in verdicts:
        return verdicts[n], ("fii" if verdicts[n] == "foreign" else None), "curated"
    e = _evidence(
        n
    )  # §164n: a documented holder takes its class whatever its name looks like (Bluewater Investment Ltd, GLEIF MU)
    if e:
        return (
            ("foreign", "fii", "documented:" + e.get("proof", ""))
            if e.get("class", "foreign") == "foreign"
            else ("domestic", None, "documented:" + e.get("proof", ""))
        )
    if DOMSTRONG.search(name) and not FORLAB.search(
        name.replace("International", "").replace("INTERNATIONAL", "")
    ):
        return "domestic", None, "regex"
    if DOMSTRONG.search(name) and re.search(
        r"pension fund global|government of|monetary authority|\bsingapore\b|\bnorges\b|abu dhabi|\bqatar\b|\bkuwait\b",
        name,
        re.I,
    ):
        return _documented_foreign(n, "sovereign name")
    if DOMSTRONG.search(name):
        return "domestic", None, "regex"
    if FORLAB.search(name):
        return _documented_foreign(n, "name marker")
    if DOMLAB.search(name):
        return "domestic", None, "regex"
    return None, None, ""


NEWFOR = {
    "InstitutionsForeignPortfolioInvestorCatergoryOneMember",
    "InstitutionsForeignPortfolioInvestorCatergoryTwoMember",
    "ForeignDirectInvestmentMember",
    "ForeignVentureCapitalInvestorsMember",
    "SovereignWealthFundsMember",
    "OtherInstitutionsForeignMember",
    "ForeignPortfolioInvestorMember",
}


def newmap_for(sym, bse_rows):
    """Holder -> [( 'fii'|'public'|'domestic', axis, pct ), ...] from the filer's FIRST new-format filing (Sep-2022+).
    ALL rows a name appears on are kept (ASTERDM Sep-2022: Olympus Capital 20.36 under ForeignCompanies AND 2.60 under
    FVCI); pick_row chooses the row whose size is closest to the old-form holding, else the largest."""
    cands = sorted(
        [
            (
                qe_of(r.get("qtr")),
                (r.get("XbrlFile") or "").strip(),
                r.get("filing_date_time") or "",
            )
            for r in bse_rows
            if qe_of(r.get("qtr")) and qe_of(r.get("qtr")) >= "2022-09-30" and r.get("XbrlFile")
        ]
    )
    for _qe, f, _fd in cands[:3]:
        p = find_file(f)
        if not p:
            try:
                import bse_headers as BH  # honest headers, no impersonation (§190)

                x = BH.get(
                    "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + f,
                    headers={"Referer": "https://www.bseindia.com/"},
                    timeout=60,
                )
                if x.status_code == 200 and len(x.content) > 2000:
                    open(os.path.join(CACHES[-1], f), "wb").write(x.content)
                    p = os.path.join(CACHES[-1], f)
                    time.sleep(0.5)
            except Exception as e:
                print("  newmap fetch err", sym, f, e, file=sys.stderr)
        if not p:
            continue
        txt = open(p, "rb").read()
        bd = breakdown(txt)
        if "InstitutionsDomesticMember" not in bd and "InstitutionsForeignMember" not in bd:
            continue
        M = {}
        for ax, _seq, pct, kind, _cat, name in rows_of(txt):
            if kind.lower().startswith("categ") or not name:
                continue
            if ax.startswith("ForeignPortfolioInvestor") or ax in (
                "ForeignDirectInvestment",
                "ForeignVentureCapitalInvestors",
                "SovereignWealthFunds",
                "OtherInstitutionsForeign",
                "InstitutionsForeign",
            ):
                cls = "fii"
            elif ax in (
                "ForeignCompanies",
                "ForeignNationals",
                "OtherForeignShareholders",
                "BodiesCorporate",
                "OtherNonInstitutions",
                "NonResidentIndians",
            ):
                cls = "public"
            elif ax in (
                "MutualFundsOrUti",
                "MutualFundsOrUTI",
                "AlternativeInvestmentFunds",
                "InsuranceCompanies",
                "Banks",
                "ProvidentFundsOrPensionFunds",
                "NBFCsRegisteredWithRbi",
                "OtherFinancialInstitutions",
                "OtherInstitutionsDomestic",
                "SovereignWealthFundsDomestic",
                "VentureCapitalFunds",
                "AssetReconstructionCompanies",
            ):
                cls = "domestic"
            else:
                continue
            M.setdefault(norm(name), []).append((cls, ax, pct))
        return M, f
    return {}, None


def pick_row(rows, pct=None):
    """The (cls, axis) for a holder with several new-format rows: closest size to the old holding, else the largest."""
    if pct is not None:
        return min(rows, key=lambda r: abs(r[2] - pct))[:2]
    return max(rows, key=lambda r: r[2])[:2]


class SymCtx:
    """Per-symbol state: the filer's first new-format holder map, holder memory, label memory."""

    def __init__(self, sym, bse_rows, verdicts):
        self.sym = sym
        self.bse_rows = bse_rows
        self.verdicts = verdicts
        self.newmap = None
        self.newfile = None
        self.memory = {}
        self.label_memory = {}
        self._ownfii = None

    def own_fii(self, hn):
        """§164r batch 10: True when this company files the same holder as a foreign investor in any of its own filings."""
        if self._ownfii is None:
            names = list(OWN_FII_EXTRA.get(self.sym, []))
            for r in self.bse_rows or []:
                f = (r.get("XbrlFile") or "").strip()
                p = find_file(f) if f else None
                if not p:
                    continue
                try:
                    rr = rows_of(open(p, "rb").read())
                except Exception:
                    continue
                for ax in sorted({x[0] for x in rr}):
                    fa = any(ax.startswith(a) for a in OWN_FOR_AX)
                    for g in groups(rr, ax):
                        if fa or (LAB_FII.search(g["label"]) and not LAB_PUB.search(g["label"])):
                            names += [n for _, n in g["holders"]]
            self._ownfii = names
        hb = _bare_name(hn)
        return any(_same_holder(hb, _bare_name(n)) for n in self._ownfii)

    def hclass(self, hn, pct=None):
        if fdi_line(self.sym, hn):
            return (
                "foreign",
                "fii",
                "new-format:ForeignDirectInvestment(any filing)",
            )  # §164r batch 14; not kept in memory (no fuzzy spread)
        if self.newmap is None:
            self.newmap, self.newfile = newmap_for(self.sym, self.bse_rows)
        c, dest, src = holder_class(
            own_name(self.sym, hn), self.verdicts, self.newmap, pct
        )  # §164r batch 19: the company's own name for the holder (OWN_NAME) reaches its 2022-form placement too
        n = norm(hn)
        if src.startswith("new-format") or src == "curated" or src.startswith("documented"):
            self.memory[n] = (c, dest, src)
        elif n in self.memory:
            c, dest, src = self.memory[n]
            src = "memory"
        else:
            for k, v in self.memory.items():
                if len(n) >= 8 and difflib.SequenceMatcher(None, n, k).ratio() >= 0.85:
                    c, dest, src = v
                    src = "memory~"
                    break
        return c, dest, src


def eval_filing(ctx, qe, txt, bd, res, cur, final=True, unres_log=None, ext_fii=0.0, add_prev=0.0):
    """Apply R1/R2/R3 to one old-format filing whose parse `res` describes the stored row `cur`.
    -> dict(t_fii,t_dii,add_ins,ev,split,mv_fii,mv_pub,keep,unres,add_dii,overflow) or None (split unknown)."""
    oth_inst = bd.get("OtherInstitutionsMember") or 0.0
    dom_only = res["dii"] - oth_inst
    # how much of the Any-Other block the STORE already holds in fii (0 = raw parse; oth_inst = a whole-block
    # heal such as §22i / SW-2; anything between = a labelled-part heal such as the FII session's §156).
    fii_shift = (cur[1] or 0) - ext_fii - res["fii"]
    if fii_shift < -0.03 or fii_shift > oth_inst + 0.03:
        return None
    fii_shift = min(max(fii_shift, 0.0), oth_inst)
    split = "a" if fii_shift <= 0.03 else ("b" if abs(fii_shift - oth_inst) <= 0.03 else "p")
    rows = rows_of(txt)
    gi = groups(rows, "OtherInstitutions", bd.get("OtherInstitutionsMember"))
    gn = groups(rows, "OtherNonInstitutions", bd.get("OtherNonInstitutionsMember"))
    ev = []
    mv_fii = mv_pub = keep = unres = unp = 0.0
    overflow = False
    if oth_inst >= 0.005:
        if not gi:
            unres += oth_inst
            ev.append(("R1-unresolved", "no typed rows", round(oth_inst, 4)))
        for g in gi:
            lab = g["label"]
            hs = [(hp, hn) + ctx.hclass(hn, hp) for hp, hn in g["holders"]]
            lab_kind = (
                "domestic"
                if (
                    DOMLAB.search(lab)
                    and not LAB_FII.search(lab)
                    and not FORWORD.search(lab)
                    and not SOVNAME.search(lab)
                )
                else "public"
                if (LAB_PUB.search(lab) or noninst_label(lab))
                else "fii"
                if (LAB_FII.search(lab) or FORLAB.search(lab))
                else None
            )
            lab_src = "keyword"
            if SOVNAME.search(lab) and not g["holders"]:
                lab_kind = (
                    None  # §164s part 7: the label is a sovereign fund's NAME, not a category
                )
            if lab_kind is None and not g["holders"]:
                ltxt = re.sub(r"^(other|others|any other)\s*", "", lab, flags=re.I).strip()
                c, dest, src = ctx.hclass(ltxt, g["pct"]) if ltxt else (None, None, "")
                if c == "foreign":
                    lab_kind = dest or "fii"
                    lab_src = "label-as-holder:" + src
                elif c == "domestic":
                    lab_kind = "domestic"
                    lab_src = "label-as-holder:" + src
                elif c is None and SOVNAME.search(ltxt):
                    # §164s part 7: a row whose label IS a sovereign / foreign public fund's name (MHRIL Sep-2016 'Government Pension
                    # Fund Global' 0.54 - Norway's fund; 'pension' had made it a domestic label) is that named holder, of unknown
                    # class without a document - it follows the named-holder rules below, never the domestic-label rule
                    hs = [(g["pct"], ltxt, None, None, "label-as-holder")]
                elif norm(lab) in ctx.label_memory:
                    lab_kind = ctx.label_memory[norm(lab)]
                    lab_src = "label-memory"
            hs_pre = hs  # the placements before option A: the unnamed rest below follows THESE (D1), not the option-A outcome
            hs2 = []
            for hp, hn, c, dest, src in hs:
                inst_tag = (
                    bool(
                        re.search(
                            r"\((fpi|fii|fdi)\)|\bfpi\b|\bfii\b|\bfdi\b|"
                            + _FOR
                            + r"\w*\s+direct|"
                            + _FOR
                            + r"\w*\s+"
                            + _PFO
                            + r"|"
                            + _FOR
                            + r"\w*\s+institutional|\bfvci\b|"
                            + _FOR
                            + r"\w*\s+venture|"
                            + _FOR
                            + r"\w*\s+bank|sovereign",
                            hn,
                            re.I,
                        )
                    )
                    or bool(
                        re.search(r"\b" + _FOR + r"\w*\b", hn, re.I)
                        and re.search(
                            r"mutual funds?|financial institutions?|\bbanks?\b|insurance|pension",
                            hn,
                            re.I,
                        )
                    )
                )  # §164r batch 10: a line named like a foreign-institution category (BSOFT Mar-2018 'Foreign Mutual Fund' 1.61)
                # §164r batch 10 (user 2026-10-04 'fix the open items'): option A covers a holder the company lists on an UNLABELLED
                # institutions sub-row too (lab_kind None) - the curated list / a Mauritius name had kept CDC Group (NH, UJJIVAN),
                # JP Morgan Mauritius IV (NH), Arcee 'OCB' (TCI) and DEG (JKPAPER) in FII there with no institution listing anywhere
                if (
                    (c == "foreign" or (c != "domestic" and inst_tag))
                    and not src.startswith("new-format")
                    and src not in ("memory", "memory~")
                    and lab_kind in ("public", "fii", None)
                ):
                    # the label decides an unnamed-type holder; an institution-type holder (FPI/FII tag in its own name, or a
                    # curated FPI fund) is FII whatever the row was called — the 2022 form would list it in B2
                    # §164r batch 7 (user 2026-09-29 'Documents only'): a curated verdict alone no longer counts — the holder needs an
                    # institution tag in its own name or another company's filing listing it under Institutions (Foreign)
                    if (
                        inst_tag
                        or inst_listed(own_name(ctx.sym, hn))
                        or lab_kind is None
                        and ctx.own_fii(hn)
                    ):
                        dest = "fii"  # §164r batch 8 option A: inside the Institutions block the company's own placement + one institution listing
                    else:
                        dest = lab_kind or "public"
                hs2.append((hp, hn, c, dest, src))
            hs = hs2
            # §164j: a named holder that is foreign ONLY by its name and has no document on file (holder_class -> "name-only")
            # is not foreign by inference. Under a labelled row it follows the filer's own label (the label documents the row);
            # in an unlabelled group it keeps the stored split (unres) — never swept into fii by the rest-follows rule below.
            # §164n: EVERY named holder of unknown class (not only name-only ones) — a named holder is never swept into fii by the
            # rest-follows rule (MAXINDIA XENOK 9.02, BHARATFIN Sandstone/Kismet, LAURUSLABS Bluewater before its GLEIF record)
            lh = [h for h in hs if h[2] is None]
            lsum = sum(h[0] for h in lh)
            if lsum > 0.0:
                if lab_kind == "domestic":
                    keep += lsum
                elif lab_kind == "fii":
                    mv_fii += lsum
                elif lab_kind == "public":
                    mv_pub += lsum
                else:
                    unres += lsum
                    unp += lsum
                    ev.append(
                        (
                            "R1-named-unresolved-kept",
                            lab,
                            round(lsum, 4),
                            "; ".join(f"{h[1]} {h[0]:.2f}" for h in lh),
                        )
                    )
            fh = [h for h in hs if h[2] == "foreign"]
            dh = [h for h in hs if h[2] == "domestic"]
            named_f_pub = sum(h[0] for h in fh if h[3] == "public")
            named_f_fii = sum(h[0] for h in fh if h[3] == "fii")
            named_d = sum(h[0] for h in dh)
            contained = sum(h[0] for h in hs) <= g["pct"] + 0.02
            rest = max(0.0, g["pct"] - (sum(h[0] for h in hs) if contained else 0.0))
            desc = "; ".join(
                "{} {:.2f} {}->{}({})".format(h[1], h[0], h[2] or "?", h[3] or "-", h[4] or "-")
                for h in hs
            )
            if lab_kind == "domestic":
                mv_pub += named_f_pub
                mv_fii += named_f_fii
                keep += rest + named_d
                ev.append(
                    (
                        "R1-domestic-label" if not fh else "R1-foreign-holder-under-domestic-label",
                        lab,
                        round(g["pct"], 4),
                        f"public={named_f_pub:.2f} fii={named_f_fii:.2f}",
                        desc,
                        lab_src,
                    )
                )
            elif lab_kind == "fii":
                mv_pub += named_f_pub
                mv_fii += named_f_fii + rest
                keep += named_d
                ev.append(
                    (
                        "R1-fii-label",
                        lab,
                        round(g["pct"], 4),
                        f"public={named_f_pub:.2f} fii={named_f_fii + rest:.2f}",
                        desc,
                        lab_src,
                    )
                )
            elif lab_kind == "public":
                if OWN_LABEL_FIRST:
                    weak = [
                        h for h in dh if str(h[4]).startswith("documented") and FORWORD.search(lab)
                    ]
                    if weak:
                        named_d -= sum(h[0] for h in weak)
                        named_f_pub += sum(h[0] for h in weak)
                        ev.append(
                            (
                                "R1-own-label-first",
                                lab,
                                round(sum(h[0] for h in weak), 4),
                                "; ".join(f"{h[1]} {h[0]:.2f} ({h[4]})" for h in weak),
                            )
                        )
                mv_pub += named_f_pub + rest
                mv_fii += named_f_fii
                keep += named_d
                ev.append(
                    (
                        "R1-public-label",
                        lab,
                        round(g["pct"], 4),
                        f"public={named_f_pub + rest:.2f} fii={named_f_fii:.2f}",
                        desc,
                        lab_src,
                    )
                )
            else:
                if fh and not dh:
                    fh_pre = [h for h in hs_pre if h[2] == "foreign"]
                    rest_dest = "public" if all(h[3] == "public" for h in fh_pre) else "fii"
                    ctx.label_memory.setdefault(norm(lab), rest_dest)
                    mv_pub += named_f_pub + (rest if rest_dest == "public" else 0.0)
                    mv_fii += named_f_fii + (rest if rest_dest == "fii" else 0.0)
                    ev.append(
                        (
                            "R1-foreign-holders",
                            lab,
                            round(g["pct"], 4),
                            "public={:.2f} fii={:.2f}".format(
                                named_f_pub + (rest if rest_dest == "public" else 0.0),
                                named_f_fii + (rest if rest_dest == "fii" else 0.0),
                            ),
                            desc,
                        )
                    )
                elif dh and not fh:
                    keep += g["pct"] if contained else named_d + g["pct"]
                    ev.append(("R1-domestic-holders", lab, round(g["pct"], 4), desc))
                    ctx.label_memory.setdefault(norm(lab), "domestic")
                elif fh and dh:
                    mv_pub += named_f_pub
                    mv_fii += named_f_fii
                    keep += named_d + rest
                    ev.append(
                        (
                            "R1-mixed",
                            lab,
                            round(g["pct"], 4),
                            f"public={named_f_pub:.2f} fii={named_f_fii:.2f}",
                            desc,
                        )
                    )
                else:
                    unres += g["pct"]
                    ev.append(("R1-unresolved", lab, round(g["pct"], 4), desc, lab_src))
                    if g["pct"] >= 0.5 and final and unres_log is not None:
                        unres_log.append((ctx.sym, qe, lab, round(g["pct"], 2), [h[1] for h in hs]))
        rem = oth_inst - (mv_fii + mv_pub + keep + unres)
        # §158a rest-follows (user 2026-09-25 "fix the remaining 86 cells too"): a filing whose >=1% holders form orphan
        # groups (no category row on the axis) left the unnamed rest of the block uncovered. When every CLASSIFIED named
        # holder is foreign and no row is domestic (label or holders), that rest follows them to fii, as a single foreign-
        # holders row's rest already does. A named holder of unknown class under a foreign label is part of this rest.
        f_named = any(re.search(r"foreign->(fii|public)", str(e)) for e in ev)
        d_named = any(str(e[0]).startswith("R1-domestic") or "domestic->" in str(e) for e in ev)
        if rem > 0.02 and REST_FOLLOWS and f_named and not d_named:
            mv_fii += rem
            ev.append(("R1-rest-follows-foreign-holders", round(rem, 4)))
        elif rem > 0.02:
            unres += rem
            ev.append(("R1-uncovered-remainder", round(rem, 4)))
        tot = mv_fii + mv_pub + keep + unres
        if tot > oth_inst + 0.05:
            overflow = True
            ev.append(("R1-overflow", round(tot, 2), round(oth_inst, 2)))
            mv_fii = mv_pub = keep = 0.0
            unres = oth_inst
            unp = 0.0
    add_dii = add_ins = 0.0
    for g in gn:
        lab = g["label"]
        if (LAB_PUB.search(lab) or LAB_FII.search(lab) or FORLAB.search(lab)) and (
            not DOMLAB.search(lab) or FORWORD.search(lab)
        ):
            continue
        hs = [(hp, hn) + ctx.hclass(hn, hp) for hp, hn in g["holders"]] if g["holders"] else []
        dh = [
            h
            for h in hs
            if h[2] == "domestic" and (DOMLAB.search(h[1]) or h[4].startswith("new-format"))
        ]
        fh = [h for h in hs if h[2] == "foreign"]
        contained = sum(h[0] for h in hs) <= g["pct"] + 0.02
        if (
            DOMLAB.search(lab)
            and not re.search(r"trust", lab, re.I)
            and not (MIXED_OUT and MIXLAB.search(lab))
        ):
            take = g["pct"] - (sum(h[0] for h in fh) if contained else 0.0)
            if not contained:
                take += sum(h[0] for h in dh)
            if take > 0.005:
                add_dii += take
                add_ins += sum(h[0] for h in dh if INSURER.search(h[1]))
                ev.append(
                    ("R2-label", lab, round(take, 4), "; ".join(f"{h[1]} {h[0]:.2f}" for h in hs))
                )
        elif dh:
            take = sum(h[0] for h in dh)
            add_dii += take
            add_ins += sum(h[0] for h in dh if INSURER.search(h[1]))
            ev.append(
                (
                    "R2-named",
                    lab,
                    round(take, 4),
                    "; ".join(f"{h[1]} {h[0]:.2f}({h[4]})" for h in dh),
                )
            )
    nbfc = bd.get("NBFCsRegisteredWithRbiMember") or 0.0
    if nbfc >= 0.005:
        add_dii += nbfc
        ev.append(("R3-nbfc", "NBFCsRegisteredWithRbi", round(nbfc, 4)))
    # the unresolved part stays where the STORE has it (dii, fii or public): `left` = how much of the block the store
    # already holds outside dii; whatever my resolved moves do not explain is the unresolved part's current home
    # `add_prev` = the non-inst/NBFC adds a previous §158 entry already put into the stored dii (from its audit record);
    # the block's part the store holds OUTSIDE dii = raw dii + add_prev - stored dii
    left = min(oth_inst, max(0.0, res["dii"] + add_prev - (cur[2] or 0)))
    u_out = min(unres, max(0.0, left - (mv_fii + mv_pub)))
    u_fii = min(u_out, max(0.0, fii_shift - mv_fii))
    u_pub = u_out - u_fii
    u_dii = unres - u_out
    # §164s part 7 (user 2026-10-05 'Take them out'): DII counts only holders shown to be Indian. A NAMED holder of unknown
    # class (no new-form placement, no curated verdict, no register / filing document - holder_class -> None) that the store
    # holds in dii leaves dii for public ("neither"); FII takes it only with a foreign document (the FII session's rules).
    # UJJIVAN Sep-2019: Alena Pvt Ltd 8.88 + Elevar Equity Mauritius 1.66 + CX Partners Fund 1 2.14 -> dii 27.23 -> 14.55.
    unp_out = min(unp, u_dii) if NAMED_UNPROVEN_OUT else 0.0
    if unp_out > 0.004:
        u_dii -= unp_out
        unres -= unp_out
        u_pub += unp_out
        ev.append(("R1-named-unproven-out-of-dii", round(unp_out, 4)))
    else:
        unp_out = 0.0
    t_dii = dom_only + keep + u_dii + add_dii
    t_fii = res["fii"] + mv_fii + u_fii + ext_fii
    return {
        "t_fii": round(max(0.0, t_fii), 4),
        "t_dii": round(max(0.0, t_dii), 4),
        "add_ins": round(add_ins, 4),
        "ins_base": round(res.get("ins") or 0.0, 4),
        "ev": ev,
        "split": split,
        "mv_fii": round(mv_fii, 4),
        "mv_pub": round(mv_pub, 4),
        "keep": round(keep, 4),
        "unres": round(unres, 4),
        "add_dii": round(add_dii, 4),
        "overflow": overflow,
    }


def quarter_files(bse_rows, lo="2015-06-30", hi="2022-06-30"):
    byq = {}
    for r in bse_rows or []:
        qe = qe_of(r.get("qtr"))
        f = (r.get("XbrlFile") or "").strip()
        if not qe or not f or not (lo <= qe <= hi):
            continue
        byq.setdefault(qe, []).append(((r.get("filing_date_time") or ""), f))
    return {q: sorted(v) for q, v in byq.items()}


def match_filing(fl, qe, cur, stats=None, ext_fii=0.0, healed=False):
    """The filing among `fl` whose parse describes the row `cur` (raw or already healed by a row-level pass):
    prom within 0.06; stored fii within [parse_fii - 0.06, parse_fii + inst Any-Other + non-inst Any-Other + 0.06];
    stored dii within [parse_dii - inst Any-Other - 0.06, parse_dii + non-inst Any-Other + NBFC + 0.06]."""
    for _fd, f in fl:
        p = find_file(f)
        if not p:
            continue
        txt = open(p, "rb").read()
        try:
            bd = breakdown(txt)
            res = F.parse_shp(txt, qe)
        except Exception:
            if stats is not None:
                stats["parse_err"] += 1
            continue
        if not res:
            if stats is not None:
                stats["parse_none"] += 1
            continue
        if "InstitutionsMember" not in bd or "InstitutionsDomesticMember" in bd:
            if stats is not None:
                stats["not_old_fmt"] += 1
            continue
        oi = bd.get("OtherInstitutionsMember") or 0.0
        on = bd.get("OtherNonInstitutionsMember") or 0.0
        nb = bd.get("NBFCsRegisteredWithRbiMember") or 0.0
        sf = (cur[1] or 0) - ext_fii
        sd = cur[2] or 0
        if abs((res["prom"] or 0) - (cur[0] or 0)) <= 0.06:
            if healed:
                if (
                    res["fii"] - 0.06 <= sf <= res["fii"] + oi + on + 0.06
                    and res["dii"] - oi - 0.06 <= sd <= res["dii"] + on + nb + 0.06
                ):
                    return f, txt, bd, res
            elif abs((sf + sd) - (res["fii"] + res["dii"])) <= 0.06:
                return f, txt, bd, res  # a raw or whole-block-moved cell keeps the document's total
        if stats is not None:
            stats["value_mismatch_try"] += 1
    return None


AUDIT = {}
try:
    AUDIT = (
        json.load(open(os.path.join(REPO, "scripts", "_shp_dii_rowfix_audit.json"))).get("cells")
        or {}
    )
except Exception:
    AUDIT = {}


def classify(limit=0, start=0, only=None, verbose=False):
    syms = json.load(open(os.path.join(HERE, "n500_syms.json")))
    if only:
        syms = [x for x in syms if x in only]
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    led = json.load(open(os.path.join(REPO, "scripts", "shp_cell_fix.json"))).get("fix", {})
    verdicts = load_verdicts()
    P = {}
    stats = collections.Counter()
    t0 = time.time()
    unres_log = []
    # A missing BSE list silently drops the symbol (stats "no_bse_list"). On 2026-09-26 the macOS /private/tmp cleanup deleted
    # 1,477 of 2,192 cached lists (385 of the 500 current N500), and api.bseindia.com refuses plain clients, so they cannot be
    # re-fetched. Refuse a run that would quietly skip more than 2% of the roster; DII_ROWFIX_ALLOW_MISSING_LISTS=1 overrides.
    miss = [x for x in syms if not os.path.exists(os.path.join(LISTS, x + ".json"))]
    if miss:
        print(
            "WARNING: no BSE list for %d/%d symbols in %s (e.g. %s)"
            % (len(miss), len(syms), LISTS, ", ".join(miss[:8])),
            file=sys.stderr,
        )
        if len(miss) > 0.02 * len(syms) and os.environ.get("DII_ROWFIX_ALLOW_MISSING_LISTS") != "1":
            raise SystemExit(
                "refusing a partial run: %d of %d symbols have no BSE list (set DII_ROWFIX_ALLOW_MISSING_LISTS=1 to run anyway)"
                % (len(miss), len(syms))
            )
    for si, sym in enumerate(syms):
        if si < start:
            continue
        lp = os.path.join(LISTS, sym + ".json")
        if not os.path.exists(lp):
            stats["no_bse_list"] += 1
            continue
        d = json.load(open(lp))
        bse_rows = d.get("Table") if isinstance(d, dict) else d
        byq = quarter_files(bse_rows)
        ctx = SymCtx(sym, bse_rows, verdicts)
        order = [(q, f, False) for q, f in sorted(byq.items(), reverse=True)] + [
            (q, f, True) for q, f in sorted(byq.items())
        ]
        for qe, fl, final in order:
            if final:
                stats["rows"] += 1
            cur = (hist.get(sym) or {}).get(qe)
            if not cur:
                if final:
                    stats["no_store_row"] += 1
                continue
            prior = (led.get(sym) or {}).get(qe)
            ext_fii = 0.0
            add_prev = 0.0
            if (
                prior
                and "\u00a7159 row-level FII heal" in (prior.get("why") or "")
                and F._cell_eq(cur, prior.get("cell"))
                and prior.get("was")
            ):
                ext_fii = round(
                    float(prior["cell"][1]) - float(prior["was"][1]), 4
                )  # the FII session's non-inst move, not ours to re-judge
            chain = prior
            depth = 0
            while chain and depth < 6:
                if "\u00a7158 row-level DII heal" in (chain.get("why") or ""):
                    add_prev = float((AUDIT.get(f"{sym}|{qe}") or {}).get("add_dii") or 0.0)
                    break
                chain = (
                    chain.get("superseded") if isinstance(chain.get("superseded"), dict) else None
                )
                depth += 1
            healed = False
            chain = prior
            depth = 0
            while chain and depth < 6:
                if F.VALUE_HEAL_MARK.search(str(chain.get("why") or "")):
                    healed = True
                    break
                chain = (
                    chain.get("superseded") if isinstance(chain.get("superseded"), dict) else None
                )
                depth += 1
            chosen = match_filing(fl, qe, cur, stats if final else None, ext_fii, healed)
            if not chosen:
                if final:
                    if not any(find_file(f) for fd, f in fl):
                        stats["not_cached"] += 1
                    else:
                        stats["no_matching_filing"] += 1
                        verbose and print(
                            f"  {qe} NO MATCHING FILING stored={cur[:3]} files={[x[1] for x in fl]}"
                        )
                continue
            f, txt, bd, res = chosen
            r = eval_filing(ctx, qe, txt, bd, res, cur, final, unres_log, ext_fii, add_prev)
            if not final:
                continue
            if chain_has(prior):
                stats["skip_164"] += 1
                continue  # re-decided by §164 (FII session): never re-judged here
            stats["matched"] += 1
            if r is None:
                stats["split_unknown"] += 1
                continue
            if r["overflow"]:
                stats["r1_overflow"] += 1
            stats["split_" + r["split"]] += 1
            dd = r["t_dii"] - (cur[2] or 0)
            df = r["t_fii"] - (cur[1] or 0)
            if verbose:
                print(
                    "  {} {} split={} res(fii {:.2f} dii {:.2f}) -> t_fii {:.2f} t_dii {:.2f} | {}".format(
                        qe,
                        f,
                        r["split"],
                        res["fii"],
                        res["dii"],
                        r["t_fii"],
                        r["t_dii"],
                        "; ".join(str(e)[:160] for e in r["ev"]),
                    )
                )
            if abs(dd) < 0.05 and abs(df) < 0.05:
                stats["unchanged"] += 1
                continue
            new = list(cur)
            new[1] = r["t_fii"]
            new[2] = r["t_dii"]
            if cur[4] is not None and r["add_ins"] > 0:
                new[4] = round(
                    r["ins_base"] + r["add_ins"], 4
                )  # absolute: filing's insurance row + named insurers, idempotent
            P[f"{sym}|{qe}"] = {
                "file": f,
                "was": cur,
                "cell": new,
                "split": r["split"],
                "ext_fii": ext_fii,
                "d_dii": round(dd, 4),
                "d_fii": round(df, 4),
                "to_public": r["mv_pub"],
                "to_fii": r["mv_fii"],
                "keep_dom": r["keep"],
                "unresolved": r["unres"],
                "add_dii": r["add_dii"],
                "add_ins": r["add_ins"],
                "ev": r["ev"],
                "prior_entry": bool(prior),
                "prior_applied": bool(prior and F._cell_eq(cur, prior.get("cell"))),
                "newmap_file": ctx.newfile,
            }
            stats["proposed"] += 1
        if si % 50 == 0:
            print(
                "  %d/%d %s %s %.0fs" % (si, len(syms), sym, dict(stats), time.time() - t0),
                file=sys.stderr,
            )
        if limit and si >= limit:
            break
    outp = "proposals_one.json" if only else "proposals.json"
    json.dump(P, open(os.path.join(HERE, outp), "w"), indent=0)
    if not only:
        json.dump(unres_log, open(os.path.join(HERE, "unresolved.json"), "w"), indent=0)
    print("classify done", dict(stats), "unresolved>=0.5:", len(unres_log))
    return P


def revfix():
    """Re-filing rows (scripts/shp_revisions.json) of proposal cells: heal them the same way, from THEIR filing."""
    P = json.load(open(os.path.join(HERE, "proposals.json")))
    revs = json.load(open(os.path.join(REPO, "scripts", "shp_revisions.json")))
    verdicts = load_verdicts()
    out = {}
    stats = collections.Counter()
    for k, v in sorted(P.items()):
        sym, qe = k.split("|")
        rc = (revs.get(sym) or {}).get(qe)
        if not rc:
            continue
        stats["rev_rows"] += 1
        # (i) same raw fii/dii as the original -> same healed values
        if (
            abs(float(rc[1]) - float(v["was"][1])) <= 0.0100001
            and abs(float(rc[2]) - float(v["was"][2])) <= 0.0100001
        ):
            new = list(rc)
            new[1] = v["cell"][1]
            new[2] = v["cell"][2]
            if rc[4] is not None and v["cell"][4] is not None and v["was"][4] is not None:
                new[4] = round(float(rc[4]) + (float(v["cell"][4]) - float(v["was"][4])), 4)
            out[k] = {
                "was": rc,
                "cell": new,
                "how": "same raw fii/dii as the original -> original's healed values",
            }
            stats["same_raw"] += 1
            continue
        # (ii) different numbers -> evaluate the re-filing's own document
        lp = os.path.join(LISTS, sym + ".json")
        d = json.load(open(lp))
        bse_rows = d.get("Table") if isinstance(d, dict) else d
        fl = quarter_files(bse_rows).get(qe, [])
        ctx = SymCtx(sym, bse_rows, verdicts)
        chosen = match_filing([x for x in fl if x[1] != v["file"]], qe, rc) or match_filing(
            fl, qe, rc
        )
        if not chosen:
            out[k] = {"was": rc, "how": "NO MATCHING DOCUMENT for the re-filing row (left as is)"}
            stats["no_doc"] += 1
            continue
        f, txt, bd, res = chosen
        r = eval_filing(ctx, qe, txt, bd, res, rc)
        if r is None:
            out[k] = {"was": rc, "how": "split unknown (left as is)"}
            stats["split_unknown"] += 1
            continue
        if abs(r["t_dii"] - float(rc[2])) < 0.05 and abs(r["t_fii"] - float(rc[1])) < 0.05:
            stats["rev_unchanged"] += 1
            continue
        new = list(rc)
        new[1] = r["t_fii"]
        new[2] = r["t_dii"]
        if rc[4] is not None and r["add_ins"] > 0:
            new[4] = round(r["ins_base"] + r["add_ins"], 4)
        out[k] = {
            "was": rc,
            "cell": new,
            "how": "re-filing document {} re-read: {}".format(
                f, "; ".join(" ".join(str(x) for x in e) for e in r["ev"])[:600]
            ),
        }
        stats["re_read"] += 1
    json.dump(out, open(os.path.join(HERE, "revfix.json"), "w"), indent=0)
    print("revfix", dict(stats))
    return out


def seam_stats(hist, syms, qa="2022-06-30", qb="2022-09-30"):
    import statistics as st

    ds = []
    for s in syms:
        a = (hist.get(s) or {}).get(qa)
        b = (hist.get(s) or {}).get(qb)
        if a and b and a[2] is not None and b[2] is not None:
            ds.append((b[2] - a[2], s, a[2], b[2]))
    v = sorted(x[0] for x in ds)

    def q(p):
        return v[int(p * (len(v) - 1))]

    return {
        "n": len(v),
        "median": round(st.median(v), 2),
        "p5": round(q(0.05), 2),
        "p95": round(q(0.95), 2),
        "ge3": sum(1 for x in v if abs(x) >= 3),
        "ge3pct": round(100 * sum(1 for x in v if abs(x) >= 3) / len(v), 1),
    }, sorted(ds, key=lambda x: -abs(x[0]))[:20]


def verify():
    P = json.load(open(os.path.join(HERE, "proposals.json")))
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    syms = json.load(open(os.path.join(HERE, "n500_syms.json")))
    before, _ = seam_stats(hist, syms)
    H = copy.deepcopy(hist)
    n = bad = 0
    for k, v in P.items():
        sym, qe = k.split("|")
        cur = H[sym][qe]
        if not F._cell_eq(cur, v["was"]):
            bad += 1
            continue
        H[sym][qe] = list(v["cell"])
        n += 1
        c = v["cell"]
        if (
            c[1] + c[2] > 100 - c[0] + 2
            or c[2] < 0
            or c[1] < 0
            or (c[4] is not None and c[4] > c[2] + 0.05)
            or (c[3] or 0) > c[2] + 0.05
        ):
            print("SANITY", k, c)
    after, top = seam_stats(H, syms)
    print("applied %d (was-mismatch %d)" % (n, bad))
    print("Sep-2022 seam before", before)
    print("Sep-2022 seam after ", after)
    for d, s, a, b in top:
        print("   %-12s %7.2f -> %7.2f (%+.2f)" % (s, a, b, d))
    for qa, qb in (
        ("2016-03-31", "2016-06-30"),
        ("2016-06-30", "2016-09-30"),
        ("2021-12-31", "2022-03-31"),
    ):
        b0, _ = seam_stats(hist, syms, qa, qb)
        a0, t0 = seam_stats(H, syms, qa, qb)
        print(f"{qa}->{qb} before {b0} after {a0}")
        print("   top after:", [(s, round(d, 2)) for d, s, a, b in t0[:6]])

    # fii seam too
    def fseam(h):
        ds = []
        for s in syms:
            a = (h.get(s) or {}).get("2022-06-30")
            b = (h.get(s) or {}).get("2022-09-30")
            if a and b:
                ds.append(b[1] - a[1])
        return sum(1 for x in ds if abs(x) >= 3), len(ds)

    print(f"fii |seam|>=3pp before {fseam(hist)} after {fseam(H)}")
    json.dump(H, open(os.path.join(HERE, "shp_history_healed.json"), "w"), separators=(",", ":"))


def write(stamp=None):
    stamp = stamp or time.strftime("%Y-%m-%d")
    P = json.load(open(os.path.join(HERE, "proposals.json")))
    path = os.path.join(REPO, "scripts", "shp_cell_fix.json")
    raw = open(path, encoding="utf-8").read()
    led = json.loads(raw)
    fix = led.setdefault("fix", {})
    ascii_only = (
        "\\u00" in raw
    )  # the file's own style: json.dump(ensure_ascii=True) escapes every non-ASCII char
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    n_new = n_sup = n_skip = 0
    audit = {
        "_doc": [
            f"§158 row-level DII heal ({stamp}), old-format XBRL era Jun-2015..Jun-2022, Nifty 500. DII = Institutions(Domestic) in every format.",
            "R1 Institutions->Any Other rows: foreign label/holders leave dii (destination = the filer's own placement of that holder in its first new-format filing: FDI/FPI -> fii, non-inst Foreign Companies -> public; OCB/Foreign Corporate Bodies/Foreign Nationals labels -> public; FII/FPI labels -> fii). Domestic labels/holders (QIB, LIC, insurers, NPS, PF, banks, AIF) stay. Unresolved rows keep the stored split.",
            "R2 Non-institutions->Any Other rows labelled as domestic institutions (Qualified Institutional Buyer, insurance, provident/pension, NBFC, FI, bank, AIF) join dii in full; generic labels contribute only their NAMED domestic-institution holders (>=1% rows). Named insurers also raise the ins slot.",
            "R3 the old-format NBFC row joins dii (the 2022 form lists NBFCs inside Institutions(Domestic)).",
            "Materiality: a cell is entered only when dii or fii moves >= 0.05pp. Evidence per cell: file, stored split, every rule hit with labels and holder names.",
            '§158a (2026-09-25) R1 rest-follows: where the block\'s >=1% holders form orphan groups (no category row) the unnamed rest was left uncovered in the stored split; when every classified named holder is foreign and no row is domestic, the rest joins fii (evidence tag R1-rest-follows-foreign-holders). Written for the 86 cells the user approved (§158a, 63 moved) and then the 48 same-pattern cells the 86-count had missed (§158b, user: "fix the remaining 48 cells too").',
        ],
        "cells": {},
    }
    for k, v in sorted(P.items()):
        sym, qe = k.split("|")
        cur = (hist.get(sym) or {}).get(qe)
        if cur is None or not F._cell_eq(cur, v["was"]):
            n_skip += 1
            continue
        why = (
            "§158 row-level DII heal ({}, DII = Institutions(Domestic) in every format): dii {:.2f} -> {:.2f}, fii {:.2f} -> {:.2f}. ".format(
                stamp, cur[2], v["cell"][2], cur[1], v["cell"][1]
            )
            # remainder / rest-follows first: the why is cut at 900 chars, and a cut tail hid IEX 2018-19's remainder from a ledger-text count
            + "; ".join(
                " ".join(str(x) for x in e)
                for e in sorted(
                    v["ev"],
                    key=lambda e: (
                        0
                        if e[0] in ("R1-rest-follows-foreign-holders", "R1-uncovered-remainder")
                        else 1
                    ),
                )
            )[:900]
            + ". Evidence: _shp_dii_rowfix_audit.json"
        )
        ent = {
            "cell": list(v["cell"]),
            "was": list(cur),
            "src": "bsexbrl:{}".format(v["file"]),
            "why": why,
        }
        prior = (fix.get(sym) or {}).get(qe)
        if prior:
            if not F._cell_eq(cur, prior.get("cell")):
                n_skip += 1
                continue
            ent["superseded"] = prior
            n_sup += 1
        else:
            n_new += 1
        fix.setdefault(sym, {})[qe] = ent
        audit["cells"][k] = {
            x: v[x]
            for x in (
                "file",
                "split",
                "d_dii",
                "d_fii",
                "to_public",
                "to_fii",
                "keep_dom",
                "unresolved",
                "add_dii",
                "add_ins",
                "ev",
                "newmap_file",
            )
        }
    # re-filing rows: same rules, from their own document (revfix stage); the sidecar is edited in place
    rp = os.path.join(HERE, "revfix.json")
    n_rev = 0
    if os.path.exists(rp):
        R = json.load(open(rp))
        rpath = os.path.join(REPO, "scripts", "shp_revisions.json")
        revs = json.load(open(rpath, encoding="utf-8"))
        audit["revisions"] = {}
        for k, v in sorted(R.items()):
            if not v.get("cell"):
                audit["revisions"][k] = {"how": v["how"], "row": v["was"]}
                continue
            sym, qe = k.split("|")
            rc = (revs.get(sym) or {}).get(qe)
            if not rc or [round(float(x), 4) for x in rc[:5] if x is not None] != [
                round(float(x), 4) for x in v["was"][:5] if x is not None
            ]:
                audit["revisions"][k] = {
                    "how": "sidecar row moved since revfix — left as is",
                    "row": rc,
                }
                continue
            new = list(rc)
            new[1] = v["cell"][1]
            new[2] = v["cell"][2]
            new[4] = v["cell"][4]
            if len(new) > 7 and isinstance(new[7], str) and "§158" not in new[7]:
                new[7] = (
                    new[7]
                    + " §158 heal:"
                    + ("inherited" if v["how"].startswith("same raw") else "re-read")
                )
            revs[sym][qe] = new
            n_rev += 1
            audit["revisions"][k] = {"how": v["how"], "was": rc, "cell": new}
        json.dump(revs, open(rpath, "w", encoding="utf-8"), separators=(",", ":"), sort_keys=True)
    json.dump(led, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=ascii_only)
    # MERGE into the existing evidence (a partial re-write must never drop earlier cells: 9609c489a replaced 2,574 cells with 2; restored 2026-09-25).
    # The classify stage reads these cells back (add_prev), so a stripped audit also corrupts any later re-run.
    apath = os.path.join(REPO, "scripts", "_shp_dii_rowfix_audit.json")
    try:
        prev = json.load(open(apath, encoding="utf-8"))
    except Exception:
        prev = {}
    merged = dict(prev)
    merged.setdefault("_doc", [])
    for d in audit["_doc"]:
        if d not in merged["_doc"]:
            merged["_doc"].append(d)
    merged.setdefault("cells", {}).update(audit["cells"])
    if "revisions" in audit:
        merged.setdefault("revisions", {}).update(audit["revisions"])
    json.dump(merged, open(apath, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print(
        "write: %d new, %d superseding earlier entries, %d skipped (store moved), %d re-filing rows healed"
        % (n_new, n_sup, n_skip, n_rev)
    )


if __name__ == "__main__":
    st = sys.argv[1]
    if st == "classify":
        classify(int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif st == "one":
        classify(only=sys.argv[2].split(","), verbose=True)
    elif st == "revfix":
        revfix()
    elif st == "verify":
        verify()
    elif st == "write":
        write()
