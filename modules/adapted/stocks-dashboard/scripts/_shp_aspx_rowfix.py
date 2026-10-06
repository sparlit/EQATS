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
"""Page-era row-level heal, Jun-2006..Mar-2016 (DATA_RUNBOOK §160): DII = Institutions(Domestic), FII = Institutions(Foreign) in
every format, read from BSE's ShareholdingPattern.aspx tables (+ the linked shpperent.aspx >1% table for the Dec-2015/Mar-2016 seam
renderings). Companion of scripts/_shp_dii_rowfix.py (§158), which it imports for the holder-placement machinery.
Local inputs (never in the repo): <work>/aspx_pages/<code>_<qtrid>.html.gz, <work>/shpperent/<code>_<qtrid>.html.gz,
<work>/aspx_codes.json (symbol -> BSE scrip code), <work>/n500_syms.json. Environment: DII_ROWFIX_WORK (work dir, shared with §158),
DII_ROWFIX_LISTS, DII_ROWFIX_CACHES (see _shp_dii_rowfix.py). Run from <work>: classify (label rules), seam (88/89 reconstruction),
verify, write.
"""
import collections
import gzip
import html
import json
import math
import os
import re
import sys
import time
import urllib.parse

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(SCRIPTS)
HERE = os.environ.get("DII_ROWFIX_WORK") or os.path.join(SCRIPTS, "_shp_dii_rowfix_work")
os.chdir(HERE)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
import _shp_dii_rowfix as D

# Generic-row floor. §160b-§160d looked only at unresolved sub-rows >= 0.5 pp; §164r batch 7 (2026-09-29, Quantmac v5) measured the
# rows below it: 89 unresolved institutional sub-rows < 0.5 pp in 20,454 page-era cells, 21 of them the company's own neighbouring
# 'Foreign Bank' / 'Foreign Mutual Fund' / 'FPI (Corporate)' row (HINDPETRO Jun-2015 'Others' 2 holders 0.09 between 'Foreign Bank'
# 2 holders 0.09 on both sides) left out of FII. The same tiers now decide every row > 0; ASPX_GENERIC_FLOOR=0.5 reproduces the old run.
GENERIC_FLOOR = float(os.environ.get("ASPX_GENERIC_FLOOR", "0"))


def gen_ok(p):
    return p > 0 and p >= GENERIC_FLOOR


# ---- page table parser ----
def rows_of(h):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        tds = [
            html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", t))).strip()
            for t in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
        ]
        tds = [t for t in tds if t != ""]
        if len(tds) >= 1:
            out.append(tds)
    return out


def num(x):
    try:
        return float(x.replace(",", ""))
    except:
        return None


def parse(h):
    """-> dict(prom, inst, noninst, c) of (label, %(A+B+C)) rows. Blocks switch on the section headings ('(A) ...', '(1) Institutions',
    '(2) Non-Institutions', '(C) ...') so filers with no promoter block (ITC, ICICIBANK, KARURVYSYA) parse too; the 'Total shareholding
    of Promoter' / 'Sub Total' rows switch as a fallback (columns: holders, shares, demat, %(A+B), %(A+B+C), pledged...)."""
    rs = rows_of(h)
    blocks = {"prom": [], "inst": [], "noninst": [], "c": []}
    cur = "prom"
    for t in rs:
        lab = t[0]
        L = re.sub(r"\s+", " ", lab.lower()).strip()
        if re.match(r"\(a\)\s*(share|promoter)", L):
            cur = "prom"
            continue
        if re.match(r"\(b\)\s*public", L):
            continue
        bare = (
            len(t) == 1 or not any(num(v) is not None for v in t[1:])
        )  # a bare heading row carries no numbers (the promoter-foreign block has an 'Institutions' ROW)
        if re.match(r"\(1\)\s*institution", L) or (bare and L == "institutions"):
            cur = "inst"
            continue
        if re.match(r"\(2\)\s*non", L) or (bare and L in ("non-institutions", "non institutions")):
            cur = "noninst"
            continue
        if re.match(r"\(c\)\s*shares held by custodian", L) or L.startswith(
            "(c) shares held by custodians"
        ):
            cur = "c"
            continue
        vals = t[1:]
        nums = [num(v) for v in vals]
        if len(nums) >= 5 and all(n is not None for n in nums[:5]):
            pct_abc = nums[4]
        else:
            continue
        if L.startswith("total shareholding of promoter"):
            blocks["prom"].append((lab, pct_abc))
            cur = "inst"
            continue
        if L.startswith("sub total"):
            if cur == "inst":
                cur = "noninst"
            elif cur == "noninst":
                cur = "c"
            continue
        if L.startswith("total public") or L.startswith("total (a)"):
            continue
        blocks[cur].append((lab, pct_abc))
    return blocks


def parse_full(h):
    """Same block split as parse(), keeping each row's holder count and share count: [(block, label, holders, shares, pct)]."""
    out = []
    cur = "prom"
    for t in rows_of(h):
        L = re.sub(r"\s+", " ", t[0].lower()).strip()
        bare = len(t) == 1 or not any(num(v) is not None for v in t[1:])
        if re.match(r"\(a\)\s*(share|promoter)", L):
            cur = "prom"
            continue
        if re.match(r"\(b\)\s*public", L):
            continue
        if re.match(r"\(1\)\s*institution", L) or (bare and L == "institutions"):
            cur = "inst"
            continue
        if re.match(r"\(2\)\s*non", L) or (bare and L in ("non-institutions", "non institutions")):
            cur = "noninst"
            continue
        if re.match(r"\(c\)\s*shares held by custodian", L) or L.startswith(
            "(c) shares held by custodians"
        ):
            cur = "c"
            continue
        nums = [num(v) for v in t[1:]]
        if len(nums) >= 5 and all(n is not None for n in nums[:5]):
            if L.startswith("total shareholding of promoter"):
                out.append(("prom", t[0].strip(), int(nums[0]), int(nums[1]), nums[4]))
                cur = "inst"
                continue
            if L.startswith("sub total"):
                cur = {"inst": "noninst", "noninst": "c"}.get(cur, cur)
                continue
            if L.startswith("total public") or L.startswith("total (a)"):
                continue
            out.append((cur, t[0].strip(), int(nums[0]), int(nums[1]), nums[4]))
    return out


# ---- linked shpperent.aspx table (>1% holders; category lumps on the 88/89 pages) ----
H = {
    "Referer": "https://www.bseindia.com/corporates/ShareholdingPattern.aspx",
    "Accept": "text/html,application/xhtml+xml",
}


def fetch(code, qtrid, comp="X", qname="X"):
    p = "shpperent/%d_%d.html.gz" % (code, qtrid)
    if os.path.exists(p):
        return gzip.open(p, "rt", encoding="utf-8").read()
    import bse_headers as BH  # honest headers, no impersonation (§190)

    u = (
        "https://www.bseindia.com/corporates/shpperent.aspx?scripcd=%d&qtrid=%d&CompName=%s&QtrName=%s"
        % (code, qtrid, urllib.parse.quote(comp), urllib.parse.quote(qname))
    )
    for a in range(3):
        try:
            r = BH.get(u, headers=H, timeout=60)
            if r.status_code == 200 and len(r.text) > 2000:
                with gzip.open(p, "wt", encoding="utf-8") as fh:
                    fh.write(r.text)
                time.sleep(0.8)
                return r.text
        except Exception as e:
            print("  err", code, qtrid, e, file=sys.stderr)
        time.sleep(3 + 3 * a)
    return None


def rows(h):
    out = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", h, re.S):
        tds = [
            html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", t))).strip()
            for t in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)
        ]
        tds = [t for t in tds if t]
        if len(tds) >= 4 and tds[0].isdigit():
            try:
                sh = int(tds[2].replace(",", ""))
                pct = float(tds[3])
            except Exception:
                continue
            out.append((tds[1], sh, pct if pct > 0 else None))
    return out


# ---- Dec-2015 / Mar-2016 seam reconstruction ----
FIIL = re.compile(r"foreign instit|foreign port|\bfpi|\bfii\b|qualified foreign|\bqfi", re.I)
CATLIKE = re.compile(
    r"corporate|clearing|trust|foreign|partnership|margin|association|custodian|domestic|nationals?$|resident|hindu|director|employee|body|bodies|iepf|escrow|unclaimed|others?$|individual|member|institution|investor|fund$",
    re.I,
)


def total_shares(main_html):
    for t in rows_of(main_html):
        if t[0].lower().startswith("total (a)+(b)+(c)") and len(t) >= 4:
            try:
                return int(t[2].replace(",", ""))
            except Exception:
                pass
    for t in rows_of(main_html):
        if t[0].lower().startswith("total (a)+(b)") and len(t) >= 4:
            try:
                return int(t[2].replace(",", ""))
            except Exception:
                pass


HOLDERISH = re.compile(
    r" - |a/c|\b(fund|limited|ltd|llc|plc|inc|corporation|company|authority|pte|sa|bv|nv|holdings?|trust)\b",
    re.I,
)


def nkey(n):
    """Holder-name key across the filer's own spellings: 'Indium V (Mauritius) Holdings Limited' == '... Ltd'."""
    n = re.sub(r"\b(limited)\b", "LTD", n, flags=re.I)
    n = re.sub(r"\b(private)\b", "PVT", n, flags=re.I)
    n = re.sub(r"\b(company)\b", "CO", n, flags=re.I)
    n = re.sub(r"\bthe\b", "", n, flags=re.I)
    return D.norm(n)


def in_known(key, known):
    """The filer's own spellings drift between tables ('Indian V (Mauritius) Holding Ltd' vs 'INDIUM V (MAURITIUS) HOLDINGS LIMITED', names cut at 40 chars)."""
    if not known or not key:
        return False
    if key in known:
        return True
    import difflib

    for k in known:
        if len(key) >= 12 and len(k) >= 12 and (key.startswith(k) or k.startswith(key)):
            return True
        if len(key) >= 10 and difflib.SequenceMatcher(None, key, k).ratio() >= 0.85:
            return True
    return False


def sibling_foreign_names(code):
    """Holders the filer itself prefixed FII/FPI/QFI on either seam table (88 or 89): foreign on the sibling page too (POONAWALLA 'QFI - LEAPFROG' on 88, bare name on 89)."""
    out = set()
    for q in (88, 89):
        h = fetch(code, q)
        if not h:
            continue
        for n, _sh, _p in rows(h):
            m = re.match(r"^\s*(fii|fpi|qfi)s?\s*[-:]\s*(\S.*)$", n, re.I)
            if m:
                out.add(nkey(m.group(2)))
    return out


def reconstruct(sym, code, q, ctx, verdicts, known_foreign=None):
    """fii on a seam page = the main page's standard foreign rows + EITHER the table's FII/FPI CATEGORY lump(s) (named FPI holders
    sit inside them: FEDERALBNK Mar-16 lump 26.9 + the same names again = 58 -> held before this rule) OR, when the table carries no
    category lump, the FII/FPI-prefixed holder rows + named holders the filer's own 2022 row / SW-2 curated verdict / name markers
    place in fii (de-duplicated by normalised name). Company/individual-type category rows never join."""
    main = gzip.open("aspx_pages/%d_%d.html.gz" % (code, q), "rt", encoding="utf-8").read()
    tot = total_shares(main)
    if not tot:
        return None, "no total shares"
    b = parse(main)
    si, subi = classify_rows(b["inst"], "inst")
    sn, subn = classify_rows(b["noninst"], "noninst")
    base_fii = si.get("fii", 0) + si.get("fpi", 0) + si.get("qfi", 0) + si.get("fvci", 0)
    lumps = si.get("other", 0) + sn.get("other", 0)
    h = fetch(code, q)
    if not h:
        return None, "shpperent unavailable"
    rs = [(n, s / tot * 100) for n, s, p in rows(h)]
    cover = sum(v for n, v in rs)

    def is_fii_label(n):
        return bool(FIIL.search(n)) and "DR" not in n.upper().replace("-", " ").split()

    PREFIXED = re.compile(
        r"^\s*(fii|fpi|qfi)s?\s*[-:]\s*\S", re.I
    )  # 'FII- Samena Special Situations Mauritius' is a holder with a category prefix, not a lump
    cat = [
        (n, v)
        for n, v in rs
        if v >= 0.005 and is_fii_label(n) and not HOLDERISH.search(n) and not PREFIXED.match(n)
    ]
    add = 0.0
    ev = []
    seen = set()
    if cat:
        for n, v in cat:
            add += v
            ev.append(("lump-fii", n, round(v, 4)))
    else:
        for n, v in rs:
            if v < 0.005:
                continue
            key = nkey(re.sub(r"^\s*(fii|fpi|qfi)\s*[-:]\s*", "", n, flags=re.I))
            if key in seen:
                continue
            if is_fii_label(n):
                if re.match(r"^\s*fiis?\s*[-:]", n, re.I) and base_fii > 0.005:
                    ev.append(("prefixed-fii-inside-fii-row", n, round(v, 4)))
                    seen.add(key)
                    continue  # 'FII - X' rows are the main page's FII row itself (POONAWALLA 'FII - BAY POND' 1.62+3.29 inside 14.49)
                seen.add(key)
                add += v
                ev.append(("prefixed-fii", n, round(v, 4)))
                continue
            if re.match(
                r"^(foreign bod|foreign compan|overseas corporate|\bocb|non.?resident|\bnri|foreign national|foreign individual)",
                n.strip(),
                re.I,
            ):
                continue  # company/individual-type label -> public
            if CATLIKE.search(n) and not re.search(
                r"\b(fund|limited|ltd|llc|plc|inc|corporation|company|authority|pte|sa|bv|nv)\b",
                n,
                re.I,
            ):
                continue  # a category lump, not a holder
            c, dest, src = ctx.hclass(
                n, v
            )  # a named holder: placement by the filer's 2022 row / curated / markers
            if (c is None or dest is None) and in_known(key, known_foreign):
                c, dest, src = "foreign", "fii", "prefixed FII/FPI/QFI on the sibling seam page"
            if c == "foreign" and dest == "fii":
                seen.add(key)
                add += v
                ev.append(("named-fii", n, round(v, 4), src))
    whole_block = False
    block = si.get("other", 0)
    if (
        not cat and block >= 1.0 and add >= 0.9 * block
    ):  # §158 R1 whole-block rule: every named holder of the institutional Any-Other block is foreign -> the unnamed rest follows (POONAWALLA Dec-15: 49.62 block, 49.19 named)
        ev.append(
            (
                "whole-block-fii",
                f"institutional Any-Other block {block:.2f}, named foreign {add:.2f}",
                round(block - add, 4),
            )
        )
        add = block
        whole_block = True
    return {
        "t_fii": round(base_fii + add, 4),
        "base_fii": base_fii,
        "lumps": lumps,
        "cover": cover,
        "ev": ev,
        "whole_block": whole_block,
        "rows": [(n, round(v, 2)) for n, v in rs if v >= 0.3],
    }, None


def plausible(t, prev_fii, next_fii, stored):
    """The reconstruction must sit within the neighbours' range ±3 pp AND be closer to the next (healed XBRL) quarter than the stored value."""
    lo = min(prev_fii, next_fii) - 3.0
    hi = max(prev_fii, next_fii) + 3.0
    return lo <= t <= hi and abs(t - next_fii) < abs(stored - next_fii)


# ---- label rules, classify, seam pass, verify, write ----
FII_LAB = re.compile(
    r"foreign port\s?[fo]?olio|\bfpi|foreign institutional|\bfii|qualified foreign|\bqfi|foreign venture|\bfvci|foreign bank|foreign mutual|foreign financial|sovereign",
    re.I,
)
DR_LAB = re.compile(
    r"\bd\.?\s?r\.?\b|\bgdr|\badr|depositor", re.I
)  # depository-receipt lines never join fii (§151 user rule) -> unresolved, keep stored placement
MLT_LAB = re.compile(
    r"multilateral|bilateral|international finance|world bank|\bifc\b|asian development", re.I
)  # IFC/ADB-type rows: the SW-2 curated verdict places IFC/CDC/ADB in fii in the XBRL era (§156/§159) -> fii here too
FDI_LAB = re.compile(
    r"\bfdi\b|foreign direct invest", re.I
)  # the 2022 form lists FDI under Institutions (Foreign); our FII = InstitutionsForeignMember incl. FDI (fetch_shareholding.parse_shp)
COLLAB_LAB = re.compile(
    r"foreign collaborat", re.I
)  # a strategic foreign company in Non-Institutions — the same filers label the same holders "Foreign Corporate Bodies" (CYIENT GAGIL)


def label_class(lab):
    if DR_LAB.search(lab):
        return None
    if FDI_LAB.search(lab):
        return "fii"
    if COLLAB_LAB.search(lab):
        return "pub"
    if MLT_LAB.search(lab):
        return "fii"
    f = bool(FII_LAB.search(lab))
    pb = bool(PUB_LAB.search(lab))
    d = bool(DII_LAB.search(lab))
    if f and not pb:
        return "fii"  # 'Foreign Banks & Foreign Companies' (fii+pub) is a mixed lump -> None
    if pb and not f:
        return "pub"
    if d and not pb and not f:
        return "dii"
    return None


DII_LAB = re.compile(
    r"qualified institutional|\bqib|insurance|assurance|provident|pension|nps|alternat(e|ive) investment|venture capital fund|\bvcf|nbfc|non.?banking|mutual fund|financial institution|\bbanks?\b|\blic\b",
    re.I,
)
PUB_LAB = re.compile(
    r"overseas corporate|\bocb|foreign compan|foreign (corporate )?bod|foreign national|non.?resident|\bnri|clearing|trust|huf|director|employee|bodies corporate|individual|iepf|escrow|unclaimed|custodian|depositor|market maker|hindu",
    re.I,
)
STD_INST = {
    "mutual funds / uti": "mf",
    "financial institutions / banks": "bank",
    "insurance companies": "ins",
    "foreign institutional investors": "fii",
    "central government / state government(s)": "gov",
    "venture capital funds": "vcf",
    "foreign venture capital investors": "fvci",
    "qualified foreign investor": "qfi",
    "foreign portfolio investors": "fpi",
    "any others (specify)": "other",
    "any other (specify)": "other",
}


def qtrid(q):
    y = int(q[:4])
    m = int(q[5:7])
    return (y - 2001) * 4 + {3: 29, 6: 30, 9: 31, 12: 32}[m]


def classify_rows(rows, block):
    """rows of one block -> (std dict, subs list) where subs = rows under an 'Any Others' header with their label class."""
    std = {}
    subs = []
    in_other = False
    for lab, p in rows:
        L = re.sub(r"\s+", " ", lab.strip().lower())
        key = STD_INST.get(L)
        if key == "other":
            in_other = True
            std["other"] = std.get("other", 0.0) + p
            continue
        if key and not in_other:
            std[key] = std.get(key, 0.0) + p
            continue
        if (
            block == "noninst"
            and not in_other
            and (L.startswith("bodies corporate") or L.startswith("individual"))
        ):
            std.setdefault("std_noninst", 0.0)
            std["std_noninst"] += p
            continue
        if key and in_other:
            in_other = False
            std[key] = std.get(key, 0.0) + p
            continue
        # a sub-row (after Any Others) OR a non-standard standalone row (e.g. 'Foreign Portfolio Investors' listed as its own non-inst row)
        subs.append((lab, p, label_class(lab), in_other))
    return std, subs


HANDOFF = {  # symbol -> which row / holder the XBRL era shows to be B2-placed (FII session's measured hand-off, §159). The AMOUNT is always the
    # page's own row for that quarter, or the linked shpperent table's named holding for that quarter — never a number carried across quarters.
    "ITC": {
        "rx": re.compile(
            r"foreign (bodies )?corporate|foreign compan|overseas corporate|foreign bod", re.I
        ),
        "names": re.compile(r"tobac+o manufactur|myddleton|rothmans", re.I),
        "note": "BAT entities (Tobacco Manufacturers, Myddleton, Rothmans), FDI in the 2022 form",
    },
    # from_q: the hand-off applies only from the quarter the filer's OWN >1% table names the FPI-marked holder. ZENSARTECH's
    # 10,301,294-share block is "Electra Partners Mauritius Ltd" under Overseas Corporate Bodies Mar-2009..Sep-2015 (qtrid
    # 61-87; Foreign Venture Capital Investors row Jun-2006..Dec-2008) and "Marina Holdco (FPI) Ltd" only from Dec-2015
    # (qtrid 88): the "(FPI)" mark did not exist before, so those quarters stay public (§164r, Quantmac v4).
    "ZENSARTECH": {
        "rx": re.compile(r"overseas corporate|foreign (bodies )?corporate|foreign compan", re.I),
        "names": re.compile(r"marina holdco", re.I),
        "note": "Marina Holdco (FPI) Ltd, curated FPI",
        "from_q": 88,
    },
    "KOTAKBANK": {
        "rx": re.compile(r"foreign bank", re.I),
        "row_ok": False,
        "names": re.compile(r"sumitomo mitsui", re.I),
        "note": "Sumitomo Mitsui Banking Corp, OtherInstitutionsForeign in the 2022 form (named holding only, never the 'Foreign Banks' row)",
    },
}
DOC_EVIDENCE = {  # §160e — rows the filer's own annual reports / offer document decide (read 2026-09-25; PDFs cached in the session scratchpad)
    "INDUSTOWER": [
        {
            "blk": "inst",
            "match": lambda lab, hn, sh: (
                hn == 1 and (sh == 14422272 or lab.strip().lower() == "investment fund")
            ),
            "cls": "fii",
            "why": "Anadale Limited, incorporated under the laws of Mauritius (Bharti Infratel prospectus 19-Dec-2012, SEBI 1356088790925.pdf: p93 'Investment Fund' 1 holder "
            "18,027,840 pre-issue -> 14,422,272 post-issue; p7/p72 offer for sale 'Anadale 3,605,568'; p91 Anadale total 18,027,840; p74 domicile). Annual reports FY2012-13 p46 "
            "'Investment Fund 14,422,272 0.76%', FY2013-14 p67 'Investment Fund 8,801,595 0.47%', FY2014-15 0 -> foreign institution (B2) = fii",
        }
    ],
    "FEDERALBNK": [
        {
            "blk": "inst",
            "match": lambda lab, hn, sh: lab.strip().lower() == "any other" and hn >= 3,
            "cls": "pub",
            "why": "depository-receipt holdings by the bank's own annual reports: 'Shares held by Custodians and others against which Depository Receipts have been issued' = "
            "page (C) + this row to the share (FY2009-10 p29 4,749,763 = 3,732,941 + 1,016,822; FY2010-11 p37 4,240,472 = 3,289,222 + 951,250; FY2012-13 p71 4,517,785 = "
            "3,371,338 + 1,146,447; the same 890,000-share core throughout; FY2011-12 p56 alone counts it under Mutual Funds/UTI) -> §151: DR shares are never fii, and not a domestic institution",
        }
    ],
}
TOL = 0.10  # a stored cell must equal one reading convention of the page within this (BSE's two renderings round differently: ITC Dec-15 dii 35.21 vs 35.29)
_KNOWN = {}
# ---- generic 'Others' / 'Any Other' sub-rows: resolved ONLY by the filer's own evidence on the named >1% holders ----
OLD_AX = {
    "fii": re.compile(
        r"ForeignPortfolio|ForeignInstitutional|ForeignVentureCapital|QualifiedForeign", re.I
    ),
    "domestic": re.compile(
        r"MutualFunds|InsuranceCompanies|FinancialInstitution|IndianFinancial|VentureCapitalFunds|ProvidentFund|PensionFund|AlternateInvestment|NBFC",
        re.I,
    ),
    "public": re.compile(
        r"OthersIndianShareholders|OtherForeignShareholders|NonResidentIndividuals|IndividualsOrHUF|IndividualShareholders|EmployeeBenefitsTrusts|BodiesCorporate|Trusts|ClearingMembers|HinduUndivided",
        re.I,
    ),
    "gov": re.compile(r"CentralGovernment|StateGovernment", re.I),
}


def _label_cls(lab):
    if D.LAB_FII.search(lab):
        return "fii"
    if D.LAB_PUB.search(lab):
        return "public"
    if D.DOMLAB.search(lab):
        return "domestic"
    return None


def oldmap_for(bse_rows, maxfiles=4):
    """holder key -> Counter(class) from the filer's own 2015-form XBRLs (Jun-2016..Jun-2022, nearest first): the row the filer
    itself put the holder on (typed Any-Other groups by their label, standard axes by OLD_AX)."""
    cands = sorted(
        [
            (D.qe_of(r.get("qtr")), (r.get("XbrlFile") or "").strip())
            for r in bse_rows
            if D.qe_of(r.get("qtr")) and r.get("XbrlFile")
        ]
    )
    M = collections.defaultdict(collections.Counter)
    used = 0
    for _qe, f in [c for c in cands if "2016-06-30" <= c[0] <= "2022-06-30"]:
        p = D.find_file(f)
        if not p:
            continue
        rows = D.rows_of(open(p, "rb").read())
        if not rows:
            continue
        used += 1
        for axis in ("OtherInstitutions", "OtherNonInstitutions"):
            for g in D.groups(rows, axis):
                c = _label_cls(g["label"]) or ("public" if axis == "OtherNonInstitutions" else None)
                if c:
                    for _hp, hn in g["holders"]:
                        M[nkey(hn)][c] += 1
        for ax, _seq, _pct, kind, _cat, name in rows:
            if (
                not name
                or ax in ("OtherInstitutions", "OtherNonInstitutions")
                or (kind or "").lower().startswith("categ")
            ):
                continue
            for c, rx in OLD_AX.items():
                if rx.search(ax):
                    M[nkey(name)][c] += 1
                    break
        if used >= maxfiles:
            break
    return M


def _subsets(hold, p, used, limit=3):
    idx = [i for i in range(len(hold)) if i not in used]
    out = []
    for mask in range(1, 1 << len(idx)):
        ssum = sum(hold[idx[k]][2] for k in range(len(idx)) if mask >> k & 1)
        if abs(ssum - p) <= max(0.06, 0.006 * p):
            out.append(tuple(idx[k] for k in range(len(idx)) if mask >> k & 1))
            if len(out) >= limit:
                break
    return out


def page_label_map(code, hist_sym):
    """holder key -> Counter(class) from the filer's own page era: a LABELLED sub-row (fii / dii / public) whose value is the exact,
    unique sum of named >1% holders attributes the label to those holders (POONAWALLA Mar-15 'Multilateral & Bilateral DFI' 12.08 = IFC)."""
    M = collections.defaultdict(collections.Counter)
    for q in sorted(hist_sym):
        if not ("2006-06-30" <= q <= "2016-03-31"):
            continue
        qi = qtrid(q)
        f = "aspx_pages/%d_%d.html.gz" % (code, qi)
        if not os.path.exists(f):
            continue
        h = gzip.open(f, "rt", encoding="utf-8").read()
        b = parse(h)
        labelled = []
        for blk in ("inst", "noninst"):
            si, subs = classify_rows(b[blk], blk)
            for lab, p, cls, _io in subs:
                if cls in ("fii", "dii", "pub") and p >= 0.5 and not DR_LAB.search(lab):
                    labelled.append((lab, p, cls))
        if not labelled:
            continue
        tot = total_shares(h)
        hp = fetch(code, qi)
        if not tot or not hp:
            continue
        hold = [(nkey(n), n, sh / tot * 100) for n, sh, _ in rows(hp) if sh / tot * 100 >= 0.05][
            :16
        ]
        used = set()
        HCm = holder_counts(h)
        for lab, p, cls in sorted(labelled, key=lambda x: -x[1]):
            hn = next(
                (v for (b_, l_, p_), v in HCm.items() if l_ == lab.strip() and abs(p_ - p) < 0.006),
                None,
            )
            g0 = pick_by_count(subsets_by_count(hold, p, used, hn), hn)
            if g0 is not None:
                got = [g0]
                used.update(got[0])
                for g in got[0]:
                    M[hold[g][0]][{"fii": "fii", "dii": "domestic", "pub": "public"}[cls]] += 1
                    if FDI_LAB.search(lab):
                        M[hold[g][0]]["fdi-label"] += 1
    return M


def holder_counts(h):
    """(block, label, pct rounded to 2dp) -> number of holders the page prints for that row."""
    return {(b, l.strip(), round(p, 2)): hn for b, l, hn, sh, p in parse_full(h)}


def subsets_by_count(hold, p, used, hn, cap=40):
    """Named subsets whose sum is the row (<= max(0.06, 0.6%)) and whose SIZE fits the row's holder count: hn, hn-1 ... hn-5
    (searched by size, so a long list of large near-miss combinations can never crowd out the right one: MFSL Sep-2011 FDI 22.37 =
    Parkville 9.37 + Xenok 9.10 + IFC 3.90). hn unknown -> the old any-size search."""
    import itertools

    if hn is None:
        return _subsets(hold, p, used, limit=8)
    avail = [i for i in range(len(hold)) if i not in used]
    out = []
    for k in range(min(hn, len(avail)), max(1, hn - 5) - 1, -1):
        for combo in itertools.combinations(avail, k):
            if abs(sum(hold[i][2] for i in combo) - p) <= max(0.06, 0.006 * p):
                out.append(combo)
                if len(out) >= cap:
                    return out
    return out


def pick_by_count(subsets, hn):
    """A named subset can only BE a row of `hn` holders when len(S) <= hn <= len(S)+5 (a 567-holder 'NRIs/OCBs' row is never one named holder).
    Prefers the unique subset whose size equals hn; else the unique admissible one; else None."""
    if hn is None:
        return subsets[0] if len(subsets) == 1 else None
    ok = [g for g in subsets if len(g) <= hn <= len(g) + 5]
    exact = [g for g in ok if len(g) == hn]
    if len(exact) == 1:
        return exact[0]
    if len(ok) == 1:
        return ok[0]
    return None


def _fuzzy_get(M, key):
    """Merged evidence for every spelling of this holder the filer used (exact key + fuzzy matches: 'Parrville' = 'Parkville')."""
    out = collections.Counter()
    hit = False
    for k in M:
        if k == key or in_known(key, {k}):
            out.update(M[k])
            hit = True
    return out if hit else None


def company_elsewhere(pagemap, n):
    """True when the filer's own labelled rows put this holder under a company-type label ('public') and never under FDI —
    company-labelled rows stay public in this pass, so a generic row must not move the same holder (FORTIS IFC, INDUSTOWER Merrill)."""
    m = _fuzzy_get(pagemap, nkey(re.sub(r"^\s*(fii|fpi|qfi)s?\s*[-:]\s*", "", n, flags=re.I)))
    return bool(m) and m.get("public", 0) > 0 and not m.get("fdi-label")


def holder_cls_full(ctx, n, v, oldmap, pagemap, known):
    """(class, source) for a named holder from the filer's own evidence, strongest first; None when nothing the filer itself said decides."""
    key = nkey(re.sub(r"^\s*(fii|fpi|qfi)s?\s*[-:]\s*", "", n, flags=re.I))
    c, dest, src = ctx.hclass(n, v)
    if (
        src.startswith("new-format")
        or src.startswith("documented")
        or src in ("curated", "memory", "memory~")
    ):
        if c == "foreign" and dest == "fii":
            return "fii", src
        if c == "foreign" and dest == "public":
            return "public", src
        if c == "domestic":
            return "domestic", src
    dom_name = (
        bool(D.DOMSTRONG.search(n))
        and not D.FORLAB.search(n.replace("International", "").replace("INTERNATIONAL", ""))
    )  # a domestic MF / insurer by its own name never takes a foreign class from a value coincidence
    m = _fuzzy_get(oldmap, key)
    if m and len(m) == 1 and not (dom_name and next(iter(m)) == "fii"):
        return next(iter(m)), "2015-form XBRL row"
    if not dom_name and (
        re.match(r"^\s*(fii|fpi|qfi)s?\s*[-:]", n, re.I)
        or in_known(key, known)
        or re.search(r"\((fpi|fii)\)", n, re.I)
    ):
        return "fii", "filer FII/FPI/QFI prefix"
    if not dom_name and re.search(r"\bfdi\b|\((fdi)\)", n, re.I):
        return "fii", "holder registered as FDI (name)"
    m = _fuzzy_get(pagemap, key)
    if m and m.get("fdi-label") and not dom_name:
        return "fii", "filer's own FDI row for this holder"
    if m and len(m) == 1 and not (dom_name and next(iter(m)) == "fii"):
        return next(iter(m)), "filer's own page label"
    # lowest tier — name markers, and only for names whose TYPE is unmistakable: a foreign fund-type vehicle, or a domestic MF trustee /
    # insurer (never a bare 'X Mauritius Ltd' company, which may be FDI/strategic -> public)
    if c == "foreign" and dest == "fii" and src == "regex" and FUNDLIKE.search(n):
        return "fii", "name marker (fund-type)"
    if (c == "domestic" or dom_name or MFLIKE.search(n)) and not D.FORLAB.search(
        n.replace("International", "").replace("INTERNATIONAL", "")
    ):
        return "domestic", "name marker (MF/insurer)"
    return None, None


MECH_LAB = re.compile(
    r"subsidiar|in transit|office bearer|indian public|welfare|partnership|escrow|unclaimed|iepf|suspense",
    re.I,
)  # mechanical public-type rows: a value coincidence with a named holder means nothing
COMPANY_LAB = re.compile(
    r"foreign (corporate )?bod|overseas corporate|\bocb|foreign compan|foreign collab", re.I
)
FUNDLIKE = re.compile(
    r"\bfunds?\b|\binvestors\b|portfolio|\bcapital\b|\bpartners\b|\btrust\b|\bsicav\b|\bucits\b|\bplc\b|\binc\b|\bl\.?p\.?\b|pension|\bmaster\b|global markets|securities|asset management|\bemerging\b|\bopportunit|\bequit",
    re.I,
)
MFLIKE = re.compile(
    r"trustee|mutual fund|\bmf\b|\bscheme\b|insurance|assurance|\blife\b|\bmagnum\b|\bprudential\b|\bsbi\b|\buti\b|\bhdfc\b|\bicici\b|\bkotak\b|\bbirla\b|\breliance capital\b|\bdsp\b|\bfranklin templeton mutual|\bnippon\b|\btata (mutual|aia)|\bl&t\b|\bsundaram\b|\bcanara\b|\baxis\b|\bidfc\b|\bmirae asset (india|mutual)",
    re.I,
)


def evaluate(h, cur, sym=None, qi=None, code=None, ctx=None, gctx=None):
    b = parse(h)
    if not b["inst"] and not b["noninst"]:
        return None, "no table"
    prom = b["prom"][-1][1] if b["prom"] else 0.0
    si, subi = classify_rows(b["inst"], "inst")
    sn, subn = classify_rows(b["noninst"], "noninst")
    HO = HANDOFF.get(sym)
    hand = set()
    if HO and qi is not None and qi < HO.get("from_q", 0):
        HO = None
    if HO:
        for lab, p, cls, io in subi + subn:
            if HO["rx"].search(lab.strip()) and p >= 0.005:
                hand.add(lab)
    subi = [(lab, p, ("hand" if lab in hand else cls), io) for lab, p, cls, io in subi]
    subn = [
        (lab, p, ("hand" if lab in hand else cls), io) for lab, p, cls, io in subn
    ]  # a hand-off row is decided by the hand-off rule only
    doc_ev = []
    if sym in DOC_EVIDENCE:
        full = {
            (b_, l_.strip(), round(p_, 2)): (hn_, sh_) for b_, l_, hn_, sh_, p_ in parse_full(h)
        }
        for rule in DOC_EVIDENCE[sym]:
            lst = subi if rule["blk"] == "inst" else subn
            for i_, (lab, p, cls, io) in enumerate(lst):
                hs = full.get((rule["blk"], lab.strip(), round(p, 2)))
                if hs and cls in (None, "pub") and rule["match"](lab, hs[0], hs[1]):
                    lst[i_] = (lab, p, rule["cls"], io)
                    doc_ev.append(
                        ("filer-document", lab, round(p, 4), rule["cls"] + ": " + rule["why"])
                    )
    base_dii = si.get("mf", 0) + si.get("bank", 0) + si.get("ins", 0)
    base_fii = si.get("fii", 0)
    extra_fii_std = si.get("fpi", 0) + si.get("qfi", 0) + si.get("fvci", 0)
    fii_subs_inst = sum(p for lab, p, cls, io in subi if cls == "fii")
    other_inst = si.get("other", 0.0)
    dii_subs_inst = sum(p for lab, p, cls, io in subi if cls == "dii")
    std_for_noninst = [
        (lab, p)
        for lab, p in b["noninst"]
        if STD_INST.get(re.sub(r"\s+", " ", lab.strip().lower())) in ("fii", "fpi", "qfi", "fvci")
    ]  # a standard foreign label filed INSIDE non-institutions (JUBLPHARMA Sep-15 'Foreign Portfolio Investors' 8.41)
    std_dom_noninst = [
        (lab, p)
        for lab, p in b["noninst"]
        if STD_INST.get(re.sub(r"\s+", " ", lab.strip().lower())) in ("vcf", "mf", "bank", "ins")
    ]
    fii_rows_noninst = sum(p for lab, p, cls, io in subn if cls == "fii") + sum(
        p for lab, p in std_for_noninst
    )
    dii_rows_noninst = sum(p for lab, p, cls, io in subn if cls == "dii") + sum(
        p for lab, p in std_dom_noninst
    )
    ev = list(doc_ev)
    prom_fix = None
    if abs(prom - (cur[0] or 0)) > 0.06:
        if (cur[0] or 0) == 0 and prom > 0:
            prom_fix = prom
            ev.append(("prom-from-page", f"stored promoter 0.00, page {prom:.2f}", round(prom, 4)))
        else:
            return None, f"prom mismatch page {prom:.2f} store {cur[0] or 0:.2f}"
    # which reading produced the stored cell? try the known conventions, closest wins
    fii_c = [
        ("fii-row", base_fii),
        ("fii+std", base_fii + extra_fii_std),
        ("fii+std+subs", base_fii + extra_fii_std + fii_subs_inst),
        ("fii+std+other", base_fii + extra_fii_std + other_inst),
        ("fii+std+subs+other", base_fii + extra_fii_std + fii_subs_inst + other_inst),
        ("fii+std+noninst", base_fii + extra_fii_std + fii_rows_noninst),
        ("fii+std+subs+noninst", base_fii + extra_fii_std + fii_subs_inst + fii_rows_noninst),
    ]
    dii_c = [
        ("mf+bank+ins", base_dii),
        ("mf+bank+ins+vcf", base_dii + si.get("vcf", 0)),
        ("mf+bank+ins+subs", base_dii + dii_subs_inst),
        ("mf+bank+ins+vcf+subs", base_dii + si.get("vcf", 0) + dii_subs_inst),
        ("mf+bank+ins+noninst", base_dii + dii_rows_noninst),
        ("mf+bank+ins+other", base_dii + other_inst),
        ("mf+bank+ins+vcf+other", base_dii + si.get("vcf", 0) + other_inst),
    ]  # old store readings that put the whole institutional Any-Others block into dii (129 page-era rows: BLUESTARCO Foreign Mutual Fund, CHOLAFIN IFC + foreign bodies, MFSL FDI)
    fm = min(fii_c, key=lambda x: abs(x[1] - (cur[1] or 0)))
    dm = min(dii_c, key=lambda x: abs(x[1] - (cur[2] or 0)))
    if abs(fm[1] - (cur[1] or 0)) > TOL:
        return (
            None,
            f"fii mismatch page {base_fii:.2f}(+{extra_fii_std:.2f}) store {cur[1] or 0:.2f}",
        )
    if abs(dm[1] - (cur[2] or 0)) > TOL:
        return None, f"dii mismatch page {base_dii:.2f} store {cur[2] or 0:.2f}"
    # holder rule (§158 R1 at page level): an unresolved or company-labelled sub-row >= 1pp whose value is EXACTLY the sum of named >1%
    # holders that the filer's own 2022 row / SW-2 curated verdict / the filer's own FII-FPI-QFI prefix on its seam tables place in fii
    # (never a bare name marker) -> fii. POONAWALLA Sep-15 'Others' 30.89 = Indium 8.60 + LeapFrog 7.82 + Zend 14.47 (QFI-prefixed on the Dec-15 table).
    hold_ev = []
    rowsets = []
    if ctx is not None and code and qi:
        cands = [i for i, (lab, p, cls, io) in enumerate(subi) if cls in (None, "pub") and p >= 1.0]
        candn = [
            i
            for i, (lab, p, cls, io) in enumerate(subn)
            if (cls is None or (cls == "pub" and COMPANY_LAB.search(lab))) and p >= 1.0
        ]
        if cands or candn:
            tot = total_shares(h)
            hp = fetch(code, qi)
            if code not in _KNOWN:
                _KNOWN[code] = sibling_foreign_names(code)
            known = _KNOWN[code]
            if tot and hp:
                hold = []
                for n, sh, _ in rows(hp):
                    v = sh / tot * 100
                    if v < 0.05:
                        continue
                    m = re.match(r"^\s*(fii|fpi|qfi)s?\s*[-:]\s*(\S.*)$", n, re.I)
                    if m and m.group(1).lower().startswith("fii"):
                        continue  # inside the page's FII row
                    key = nkey(m.group(2) if m else n)
                    if HO and HO["names"].search(n):
                        continue  # the hand-off moves these itself
                    c, dest, src = ctx.hclass(n, v)
                    if c == "domestic":
                        continue
                    fdi_own = bool(
                        gctx is not None
                        and ((_fuzzy_get(gctx["pagemap"], key) or {}).get("fdi-label"))
                    )
                    strong = (
                        (
                            c == "foreign"
                            and dest == "fii"
                            and (
                                src.startswith("new-format")
                                or src in ("curated", "memory", "memory~")
                            )
                        )
                        or bool(m)
                        or in_known(key, known)
                        or bool(re.search(r"\((fpi|fii)\)", n, re.I))
                        or fdi_own
                    )
                    if fdi_own and not (c == "foreign" and dest == "fii"):
                        src = "filer's own FDI row for this holder"
                    if strong and not (
                        c == "foreign" and dest == "public" and src.startswith("new-format")
                    ):
                        hold.append(
                            (
                                key,
                                n,
                                round(v, 4),
                                (
                                    src
                                    if (c == "foreign" and dest == "fii")
                                    else (
                                        "filer's own FDI row for this holder"
                                        if fdi_own
                                        else "filer FII/FPI/QFI prefix"
                                    )
                                ),
                                fdi_own,
                            )
                        )
                hold = hold[:14]
                used = set()
                HCm = holder_counts(h)

                def explain(p, lab, blk):
                    hn = HCm.get((blk, lab.strip(), round(p, 2)))
                    g = pick_by_count(subsets_by_count(hold, p, used, hn), hn)
                    return list(g) if g else None

                for lst, cand in ((subi, cands), (subn, candn)):
                    for i in sorted(cand, key=lambda i: -lst[i][1]):
                        lab, p, cls, io = lst[i]
                        got = explain(p, lab, "inst" if lst is subi else "noninst")
                        if (
                            got
                            and lst is subn
                            and cls == "pub"
                            and not any(hold[g][4] for g in got)
                        ):
                            got = None  # a company-labelled non-institution row moves only when the filer itself filed these holders under FDI elsewhere (MFSL relabel); IFC / FMO / fund holders inside 'Foreign Corporate Bodies' rows stay open (runbook §160c)
                        if got:
                            used.update(got)
                            lst[i] = (lab, p, "fii", io)
                            hold_ev.append(
                                (
                                    "row-by-holders",
                                    lab,
                                    round(p, 4),
                                    "; ".join(
                                        f"{hold[g][1][:40]} {hold[g][2]:.2f} ({hold[g][3]})"
                                        for g in got
                                    ),
                                )
                            )
    ho_vals = []
    if HO and code and qi:
        _tot = total_shares(h)
        _hp = fetch(code, qi)
        if _tot and _hp:
            ho_vals = [sh / _tot * 100 for n, sh, _ in rows(_hp) if HO["names"].search(n)]

    def is_ho_row(p):
        return bool(ho_vals) and (
            any(abs(v - p) <= max(0.06, 0.006 * p) for v in ho_vals)
            or abs(sum(ho_vals) - p) <= max(0.06, 0.006 * p)
        )

    # generic rows ('Others', 'Any Other', 'FDI', 'Private Equity'...): the row must equal the UNIQUE exact sum of named >1% holders
    # that ALL carry one class by the filer's own evidence (holder_cls_full) -> that class; anything else stays as stored
    if gctx is not None and code and qi:
        candg = [
            (lst, i)
            for lst in (subi, subn)
            for i, (lab, p, cls, io) in enumerate(lst)
            if cls is None
            and gen_ok(p)
            and not DR_LAB.search(lab)
            and not MECH_LAB.search(lab)
            and not is_ho_row(p)
        ]
        if candg:
            tot = total_shares(h)
            hp = fetch(code, qi)
            if code not in _KNOWN:
                _KNOWN[code] = sibling_foreign_names(code)
            if tot and hp:
                hold = []
                for n, sh, _ in rows(hp):
                    v = sh / tot * 100
                    if v < 0.05:
                        continue
                    if HO and HO["names"].search(n):
                        continue
                    c, src = holder_cls_full(
                        ctx, n, v, gctx["oldmap"], gctx["pagemap"], _KNOWN[code]
                    )
                    hold.append((nkey(n), n, round(v, 4), c, src))
                hold = hold[:16]
                used = {
                    g for g in range(len(hold)) if hold[g][3] is None
                }  # unclassified names can never explain a row
                rowmem = gctx.get("rowmem") or {}
                for lst, i in sorted(candg, key=lambda x: -x[0][x[1]][1]):
                    lab, p, cls, io = lst[i]
                    blk = "inst" if lst is subi else "noninst"
                    lk = (blk, re.sub(r"\s+", " ", lab.strip().lower()))
                    tb = set()
                    for q2 in (qi - 1, qi + 1):
                        for st_ in (rowmem.get(lk) or {}).get(q2, []):
                            tb |= set(st_)
                    hn_ = holder_counts(h).get((blk, lab.strip(), round(p, 2)))
                    got = subsets_by_count(hold, p, used, hn_)
                    if hn_ is not None and any(len(g) == hn_ for g in got):
                        got = [g for g in got if len(g) == hn_]
                    single = [
                        g
                        for g in got
                        if len({hold[x][3] for x in g}) == 1 and hold[g[0]][3] != "gov"
                    ]
                    choose = None
                    how = "exact"
                    if len(got) == 1 and single:
                        choose = got[0]
                    elif single and tb:
                        cs = [g for g in single if all(in_known(hold[x][0], tb) for x in g)]
                        if len(cs) == 1:
                            choose = cs[0]
                            how = "exact, composition = adjacent quarter"
                    if (
                        choose is None and tb
                    ):  # the adjacent quarter's composition is present here and the remainder is below the >1% table's floor -> the rest follows (§158 R1)
                        comp = tuple(
                            x
                            for x in range(len(hold))
                            if x not in used and in_known(hold[x][0], tb)
                        )
                        if comp and hn_ is not None and not (len(comp) <= hn_ <= len(comp) + 5):
                            comp = ()
                        if (
                            comp
                            and len({hold[x][3] for x in comp}) == 1
                            and hold[comp[0]][3] != "gov"
                        ):
                            rem = p - sum(hold[x][2] for x in comp)
                            if -0.06 <= rem <= 1.0:
                                choose = comp
                                how = f"adjacent quarter's composition, rest {max(rem, 0):.2f} follows"
                    if choose is None:
                        continue
                    c = hold[choose[0]][3]
                    if c != "public" and any(
                        company_elsewhere(gctx["pagemap"], hold[x][1]) for x in choose
                    ):
                        continue
                    used.update(choose)
                    newcls = {"fii": "fii", "domestic": "dii", "public": "pub"}[c]
                    lst[i] = (lab, p, newcls, io)
                    rowsets.append((lk, {hold[x][0] for x in choose}))
                    hold_ev.append(
                        (
                            "generic-row-by-holders",
                            lab,
                            round(p, 4),
                            newcls
                            + " ["
                            + how
                            + "]: "
                            + "; ".join(
                                f"{hold[g][1][:40]} {hold[g][2]:.2f} ({hold[g][4]})" for g in choose
                            ),
                        )
                    )
    # §160c tier — the generic rows §160b could not decide, strongest filer evidence first:
    #  A  exact decomposition: a subset of named >1% holders whose SIZE equals the row's holder count and whose sum equals the row
    #     -> each holder by its own filer placement (strong sources only); unplaced holders keep the stored placement
    #  B  the SAME row one quarter away (same block, the category absent from this page, holder count and size within bounds)
    #     carries the filer's label; both neighbours agree when both exist
    #  C  the block's sole Any-Others sub-row, persisting quarter to quarter, labelled by the filer at the nearest labelled quarter
    if gctx is not None and code and qi and gctx.get("pagefull"):
        pf = gctx["pagefull"]
        me = pf.get(qi) or []
        candc = [
            (lst, i)
            for lst in (subi, subn)
            for i, (lab, p, cls, io) in enumerate(lst)
            if cls is None
            and gen_ok(p)
            and not DR_LAB.search(lab)
            and not MECH_LAB.search(lab)
            and not is_ho_row(p)
        ]
        if candc:
            tot = total_shares(h)
            hp = fetch(code, qi)
            if code not in _KNOWN:
                _KNOWN[code] = sibling_foreign_names(code)
            named = []
            if tot and hp:
                for n, sh, _ in rows(hp):
                    v = sh / tot * 100
                    if v < 0.05:
                        continue
                    if HO and HO["names"].search(n):
                        continue  # the hand-off moves these itself
                    c, src = holder_cls_full(
                        ctx, n, v, gctx["oldmap"], gctx["pagemap"], _KNOWN[code]
                    )
                    if src and (
                        src.startswith("name marker") or src.startswith("holder registered as FDI")
                    ):
                        c = None  # a name alone never splits a row (CHOLAFIN Sep-15: 'Dynasty Acquisition FDI Ltd' sits under 'Foreign Bodies Corporate' in 2012-13)
                    named.append((n, round(v, 4), c, src))
            taken_b = set()
            for lst, i in sorted(candc, key=lambda x: -x[0][x[1]][1]):
                lab, p, cls, io = lst[i]
                blk = "inst" if lst is subi else "noninst"
                row = [
                    r for r in me if r[0] == blk and r[1] == lab.strip() and abs(r[4] - p) < 0.006
                ]
                hn = row[0][2] if row else None
                decided = None
                # A — exact decomposition by holder count
                if hn and 1 <= hn <= 6 and named:
                    fits = []
                    import itertools

                    for combo in itertools.combinations(range(len(named)), hn):
                        ssum = sum(named[k][1] for k in combo)
                        if abs(ssum - p) <= max(0.06, 0.006 * p):
                            fits.append(combo)
                        if len(fits) > 6:
                            break
                    if (
                        len(fits) > 1
                    ):  # several subsets within rounding: the one whose sum IS the row (<=0.01) decides, if unique (CEATLTD Sep-15 3.51 = WestBridge 3.51, not Kotak 3.54)
                        ex_ = [f_ for f_ in fits if abs(sum(named[k][1] for k in f_) - p) <= 0.01]
                        if len(ex_) == 1:
                            fits = ex_
                    if len(fits) == 1:
                        combo = fits[0]
                        parts = collections.defaultdict(float)
                        for k in combo:
                            parts[named[k][2]] += named[k][1]
                        if any(
                            named[k][2] in ("fii", "domestic")
                            and company_elsewhere(gctx["pagemap"], named[k][0])
                            for k in combo
                        ):
                            pass
                        elif any(c in ("fii", "domestic") for c in parts):
                            decided = (
                                "A",
                                parts,
                                "; ".join(
                                    "{} {:.2f} ({})".format(
                                        named[k][0][:40], named[k][1], named[k][3] or "unplaced"
                                    )
                                    for k in combo
                                ),
                            )
                        elif set(parts) <= {"public", None}:
                            decided = (
                                "A-pub",
                                parts,
                                "; ".join(
                                    "{} {:.2f} ({})".format(
                                        named[k][0][:40], named[k][1], named[k][3] or "unplaced"
                                    )
                                    for k in combo
                                ),
                            )
                if decided is None and hn and named:
                    import itertools

                    cl = [
                        k for k in range(len(named)) if named[k][2] in ("fii", "domestic", "public")
                    ]
                    fits = []
                    for kk in range(min(hn, len(cl)), max(1, hn - 5) - 1, -1):
                        for combo in itertools.combinations(cl, kk):
                            ssum = sum(named[k][1] for k in combo)
                            u = hn - kk
                            r = p - ssum
                            if (
                                ssum >= 0.5 * p
                                and -max(0.06, 0.006 * p) <= r <= 1.0 * u
                                and (u >= 1 or abs(r) <= max(0.06, 0.006 * p))
                            ):
                                fits.append(combo)
                            if len(fits) > 3:
                                break
                        if len(fits) > 3:
                            break
                    if (
                        len(fits) == 1
                        and len({named[k][2] for k in fits[0]}) == 1
                        and not (
                            named[fits[0][0]][2] != "public"
                            and any(
                                company_elsewhere(gctx["pagemap"], named[k][0]) for k in fits[0]
                            )
                        )
                    ):
                        c0 = named[fits[0][0]][2]
                        decided = (
                            "A-rest" if c0 != "public" else "A-pub",
                            {c0: p},
                            "%s + %d unnamed holder(s) %.2f (rest follows, §158 R1)"
                            % (
                                "; ".join(
                                    f"{named[k][0][:40]} {named[k][1]:.2f} ({named[k][3]})"
                                    for k in fits[0]
                                ),
                                hn - len(fits[0]),
                                p - sum(named[k][1] for k in fits[0]),
                            ),
                        )
                A_ = decided
                decided = None
                # B — the same row one quarter away
                if hn:
                    here = {re.sub(r"\s+", " ", r[1].lower()) for r in me if r[0] == blk}
                    picks = []
                    for q2 in (qi - 1, qi + 1):
                        cands = []
                        for r in pf.get(q2) or []:
                            if r[0] != blk or r[5] not in ("fii", "dii", "pub", "gov") or not r[2]:
                                continue
                            gen_twin = (
                                label_class(r[1]) is None
                                and STD_INST.get(re.sub(r"\s+", " ", r[1].strip().lower())) is None
                            )
                            hr = r[2] / hn
                            pr = r[4] / p if p else 0
                            if gen_twin:  # the same generic row decided one quarter away (FPI rows grew fast in 2015: NATCOPHARM 15 -> 19 -> 29 holders)
                                if not (1 / 3 <= hr <= 3 and 0.5 <= pr <= 2):
                                    continue
                            else:
                                if re.sub(r"\s+", " ", r[1].lower()) in here:
                                    continue  # that category is still on this page -> not where this row went
                                if not (1 / 3 <= hr <= 3 and 0.5 <= pr <= 2):
                                    continue
                            cands.append((abs(math.log(hr)) + abs(math.log(pr)), r))
                        cands.sort(key=lambda x: x[0])
                        if cands:
                            best = cands[0]
                            if any(
                                c[1][5] != best[1][5] and c[0] <= best[0] + 0.35 for c in cands[1:]
                            ):
                                picks.append(("ambiguous", q2, None))
                                continue
                            picks.append((best[1][5], q2, best[1]))
                    cls_set = {p_[0] for p_ in picks}
                    if picks and len(cls_set) == 1 and "ambiguous" not in cls_set:
                        c = picks[0][0]
                        key = (blk, c, tuple(sorted((p_[1], p_[2][1]) for p_ in picks)))
                        if key not in taken_b:
                            taken_b.add(key)
                            decided = (
                                "B",
                                {
                                    {
                                        "fii": "fii",
                                        "dii": "domestic",
                                        "pub": "public",
                                        "gov": "gov",
                                    }[c]: p
                                },
                                "; ".join(
                                    "%s '%s' %d holders %.2f"
                                    % (
                                        ("prev" if p_[1] < qi else "next"),
                                        p_[2][1][:34],
                                        p_[2][2],
                                        p_[2][4],
                                    )
                                    for p_ in picks
                                ),
                            )
                B_ = decided
                decided = None
                # C — the block's sole Any-Others sub-row, chained to the nearest quarter where the filer labelled it
                if B_ is None:

                    def sole(qq):
                        rows_ = [r for r in (pf.get(qq) or []) if r[0] == blk and r[6]]
                        return rows_[0] if len(rows_) == 1 else None

                    if sole(qi) is not None:
                        ends = []
                        for step in (-1, 1):
                            q2 = qi
                            for _ in range(24):
                                q2 += step
                                r = sole(q2)
                                if r is None:
                                    break
                                if r[5] in ("fii", "dii", "pub", "gov"):
                                    ends.append((r[5], q2, r))
                                    break
                        if ends and len({e[0] for e in ends}) == 1:
                            c = ends[0][0]
                            decided = (
                                "C",
                                {
                                    {
                                        "fii": "fii",
                                        "dii": "domestic",
                                        "pub": "public",
                                        "gov": "gov",
                                    }[c]: p
                                },
                                "; ".join(
                                    "qtrid %d '%s' %d holders %.2f"
                                    % (e[1], e[2][1][:34], e[2][2], e[2][4])
                                    for e in ends
                                ),
                            )
                C_ = decided
                decided = None
                # T — a single holder / small row whose stake is unchanged, walked quarter by quarter (holders within max(1,10%), size within 5% per hop)
                #     to the nearest quarter where that same row carries a label or a decision (INDUSTOWER 0.95: 'Any Other' -> 'Private Equity' -> QFI)
                T_ = None
                if B_ is None and C_ is None and hn:
                    ends = []
                    for step in (-1, 1):
                        q2 = qi
                        h0 = hn
                        p0 = p
                        for _ in range(16):
                            q2 += step
                            nxt = [
                                r
                                for r in (pf.get(q2) or [])
                                if r[0] == blk
                                and r[2]
                                and abs(r[2] - h0) <= max(1, 0.1 * h0)
                                and p0
                                and 0.95 <= r[4] / p0 <= 1.05
                            ]
                            if len(nxt) != 1:
                                break
                            r = nxt[0]
                            if r[5] in ("fii", "dii", "pub", "gov"):
                                ends.append((r[5], q2, r))
                                break
                            h0, p0 = r[2], r[4]
                    if ends and len({e[0] for e in ends}) == 1:
                        c = ends[0][0]
                        T_ = (
                            "T",
                            {
                                {"fii": "fii", "dii": "domestic", "pub": "public", "gov": "gov"}[
                                    c
                                ]: p
                            },
                            "; ".join(
                                "same row walked to qtrid %d '%s' %d holders %.2f"
                                % (e[1], e[2][1][:34], e[2][2], e[2][4])
                                for e in ends
                            ),
                        )
                # U — union twin: the row equals two or three same-class rows of the adjacent quarter together (holders and size within 10%;
                #     OFSS Jun-15 'Others' 34 holders 3.12 = Sep-15 FPI 27 holders 1.14 + 'Others' 9 holders 2.13 decided fii)
                U_ = None
                if B_ is None and C_ is None and T_ is None and hn and hn >= 3:
                    import itertools

                    here = {
                        re.sub(r"\s+", " ", r[1].lower())
                        for r in me
                        if r[0] == blk and label_class(r[1]) is not None
                    }
                    hitsU = []
                    for q2 in (qi - 1, qi + 1):
                        cand = [
                            r
                            for r in (pf.get(q2) or [])
                            if r[0] == blk
                            and r[5] in ("fii", "dii", "pub")
                            and r[2]
                            and re.sub(r"\s+", " ", r[1].lower()) not in here
                            and not (r[1].lower().startswith(("individual", "bodies corporate")))
                        ]
                        for kk in (2, 3):
                            for combo in itertools.combinations(cand, kk):
                                if len({x[5] for x in combo}) != 1:
                                    continue
                                H_ = sum(x[2] for x in combo)
                                S_ = sum(x[4] for x in combo)
                                if 0.9 <= H_ / hn <= 1.1 and 0.9 <= S_ / p <= 1.1:
                                    hitsU.append((combo[0][5], q2, combo))
                    if hitsU and len({h_[0] for h_ in hitsU}) == 1:
                        c = hitsU[0][0]
                        U_ = (
                            "U",
                            {{"fii": "fii", "dii": "domestic", "pub": "public"}[c]: p},
                            "; ".join(
                                "qtrid %d: %s"
                                % (
                                    h_[1],
                                    " + ".join(
                                        "'%s' %d holders %.2f" % (x[1][:26], x[2], x[4])
                                        for x in h_[2]
                                    ),
                                )
                                for h_ in hitsU[:2]
                            ),
                        )
                RC = B_ or C_ or T_ or U_
                if (
                    A_ is not None
                    and A_[0] == "A-rest"
                    and RC is not None
                    and set(A_[1]) != set(RC[1])
                ):
                    A_ = None  # a same-row identity beats a rest-follows reading (PIIND Sep-15: the directors' row, not GPFG + 2)
                # K — consensus: every admissible explanation by named holders (named part >= half the row, each unnamed holder < 1%) has one class
                K_ = None
                if A_ is None and RC is None and hn and named:
                    import itertools

                    cl = [
                        k for k in range(len(named)) if named[k][2] in ("fii", "domestic", "public")
                    ]
                    classes = set()
                    n_fit = 0
                    ex_k = None
                    for kk in range(1, min(len(cl), hn) + 1):
                        for combo in itertools.combinations(cl, kk):
                            ssum = sum(named[k][1] for k in combo)
                            u = hn - kk
                            r_ = p - ssum
                            if (
                                ssum >= 0.5 * p
                                and -max(0.06, 0.006 * p) <= r_ <= 1.0 * u
                                and (u >= 1 or abs(r_) <= max(0.06, 0.006 * p))
                            ):
                                n_fit += 1
                                classes |= {named[k][2] for k in combo}
                                ex_k = ex_k or combo
                    if n_fit and len(classes) == 1:
                        c0 = next(iter(classes))
                        if not (
                            c0 != "public"
                            and any(
                                company_elsewhere(gctx["pagemap"], named[k][0])
                                for k in cl
                                if named[k][2] == c0
                            )
                        ):
                            K_ = (
                                "K",
                                {c0: p},
                                "all %d admissible named-holder explanations are %s, e.g. %s"
                                % (
                                    n_fit,
                                    c0,
                                    "; ".join(
                                        f"{named[k][0][:34]} {named[k][1]:.2f} ({named[k][3]})"
                                        for k in ex_k
                                    ),
                                ),
                            )
                if A_ is not None:
                    placed = {c for c in A_[1] if c is not None}
                    unpl = A_[1].get(None, 0.0)
                    if unpl > 0.004 and RC is not None and placed <= set(RC[1]):
                        decided = (
                            RC[0],
                            RC[1],
                            f"{A_[2]} + {RC[2]}",
                        )  # the row's own identity decides the unplaced holder too (MFSL Jun-15: Xenok with IFC in the row the filer labelled FDI)
                    else:
                        decided = A_
                else:
                    decided = RC or K_
                if decided is None:
                    continue
                grade, parts, why_ = decided
                if grade in ("B", "C", "A-rest", "T", "K", "U"):
                    c = next(iter(parts))
                    newcls = {"fii": "fii", "domestic": "dii", "public": "pub", "gov": "pub"}[c]
                    lst[i] = (lab, p, newcls, io)
                    hold_ev.append(("generic-row-" + grade, lab, round(p, 4), newcls + ": " + why_))
                elif grade == "A-pub":
                    lst[i] = (lab, p, "pub", io)
                    hold_ev.append(("generic-row-A", lab, round(p, 4), "pub: " + why_))
                else:
                    fpart = parts.get("fii", 0.0)
                    dpart = parts.get("domestic", 0.0)
                    rest = p - fpart - dpart
                    # split the row: named fii / domestic parts move, the rest keeps the stored placement (cls None)
                    lst[i] = (lab, round(rest, 4), None, io)
                    if fpart > 0.004:
                        lst.append((lab + " [fii part]", round(fpart, 4), "fii", io))
                    if dpart > 0.004:
                        lst.append((lab + " [dii part]", round(dpart, 4), "dii", io))
                    hold_ev.append(
                        (
                            "generic-row-A",
                            lab,
                            round(p, 4),
                            f"fii {fpart:.2f} / dii {dpart:.2f} / rest {rest:.2f}: {why_}",
                        )
                    )
    fii_subs_inst = sum(p for lab, p, cls, io in subi if cls == "fii")
    dii_subs_inst = sum(
        p for lab, p, cls, io in subi if cls == "dii"
    )  # re-summed after the holder rule (the reading convention above was identified on the label classes alone)
    fii_rows_noninst = sum(p for lab, p, cls, io in subn if cls == "fii") + sum(
        p for lab, p in std_for_noninst
    )
    dii_rows_noninst = sum(p for lab, p, cls, io in subn if cls == "dii") + sum(
        p for lab, p in std_dom_noninst
    )
    ev.extend(hold_ev)
    # target = B2-equivalent / B1-equivalent from the page's labelled rows
    io_sum = sum(p for lab, p, cls, io in subi if io)
    other_resid = max(0.0, other_inst - io_sum)
    unres_io = sum(p for lab, p, cls, io in subi if io and cls is None)
    t_fii = (
        base_fii
        + extra_fii_std
        + fii_subs_inst
        + fii_rows_noninst
        + ((unres_io + other_resid) if "other" in fm[0] else 0.0)
    )  # unresolved / unlabelled parts of a stored-in-fii Any-Other block keep the stored placement
    unres_io_d = sum(p for lab, p, cls, io in subi if io and cls is None and not DR_LAB.search(lab))
    t_dii = (
        base_dii
        + si.get("vcf", 0)
        + dii_subs_inst
        + dii_rows_noninst
        + ((unres_io_d + other_resid) if "other" in dm[0] else 0.0)
    )  # a stored-in-dii Any-Others block keeps only its unresolved parts; fii / public-labelled sub-rows and depository-receipt lines leave dii
    add_ins = sum(
        p
        for lab, p, cls, io in subi + subn
        if cls == "dii" and re.search(r"insur|assurance|\blic\b", lab, re.I)
    )
    if extra_fii_std > 0.005 and "std" not in fm[0]:
        ev.append(("std-fii-rows", "FPI/QFI/FVCI rows in institutions", round(extra_fii_std, 4)))
    if si.get("vcf", 0) > 0.005 and "vcf" not in dm[0]:
        ev.append(("std-vcf", "Venture Capital Funds row", round(si["vcf"], 4)))
    if "other" in dm[0]:
        for lab, p, cls, io in subi:
            if (
                io
                and p >= 0.005
                and (cls in ("fii", "pub", "hand") or (cls is None and DR_LAB.search(lab)))
            ):
                ev.append(
                    (
                        "dii-block-out",
                        lab,
                        round(p, 4),
                        "stored dii held the institutional Any-Others block; this %s sub-row is not a domestic institution"
                        % (cls or "depository-receipt"),
                    )
                )
    for lab, p, cls, io in subi:
        if p < 0.005:
            continue
        if cls == "fii" and "subs" not in fm[0] and not ("other" in fm[0] and io):
            ev.append(("inst-sub-fii", lab, round(p, 4)))
        elif cls == "dii" and "subs" not in dm[0]:
            ev.append(
                ("inst-sub-dii", lab, round(p, 4))
                + (("leaves fii",) if ("other" in fm[0] and io) else ())
            )
        elif cls == "pub" and "other" in fm[0] and io:
            ev.append(("inst-sub-pub-leaves-fii", lab, round(p, 4)))
        elif cls is None:
            ev.append(
                (
                    "inst-sub-unresolved",
                    lab,
                    round(p, 4),
                    "stays in fii" if ("other" in fm[0] and io) else "stays as stored",
                )
            )
    for lab, p, cls, io in subn:
        if p < 0.005:
            continue
        if cls == "fii" and "noninst" not in fm[0]:
            ev.append(("noninst-fii", lab, round(p, 4)))
        elif cls == "dii" and "noninst" not in dm[0]:
            ev.append(("noninst-dii", lab, round(p, 4)))
    for lab, p in std_for_noninst:
        if p >= 0.005 and "noninst" not in fm[0]:
            ev.append(("noninst-fii", lab, round(p, 4)))
    for lab, p in std_dom_noninst:
        if p >= 0.005 and "noninst" not in dm[0]:
            ev.append(("noninst-dii", lab, round(p, 4)))
    # hand-off symbols: the row the XBRL era shows to be B2-placed moves IN FULL at the page's own value; when the page labels it
    # differently (ITC Jun/Sep-2015 'Others', the 88/89 seam renderings) the linked shpperent table's NAMED holding for that quarter is used
    used_shp = False
    if HO:
        moved = 0.0
        if HO.get("row_ok", True):
            for lab, p, cls, io in subi + subn:
                if cls == "hand" and p >= 0.005:
                    moved += p
                    ev.append(("handoff-fii", lab, round(p, 4), HO["note"]))
        if moved < 0.005 and qi and code:
            tot = total_shares(h)
            hp = fetch(code, qi)
            if tot and hp:
                for n, sh, _ in rows(hp):
                    if HO["names"].search(n):
                        v = sh / tot * 100
                        if v >= 0.005:
                            moved += v
                            used_shp = True
                            ev.append(("handoff-fii", n, round(v, 4), HO["note"] + " (shpperent)"))
        t_fii += moved
    generic_left = [
        (("inst" if lst is subi else "noninst"), lab, round(p, 4))
        for lst in (subi, subn)
        for lab, p, cls, io in lst
        if cls is None and gen_ok(p) and not DR_LAB.search(lab) and not MECH_LAB.search(lab)
    ]
    subs_final = [
        (("inst" if lst is subi else "noninst"), lab, round(p, 4), cls)
        for lst in (subi, subn)
        for lab, p, cls, io in lst
    ]
    generic_left = [g for g in generic_left if not is_ho_row(g[2])]
    return {
        "t_fii": round(t_fii, 4),
        "t_dii": round(t_dii, 4),
        "add_ins": round(add_ins, 4),
        "ev": ev,
        "base": (prom, base_fii, base_dii),
        "conv": (fm[0], dm[0]),
        "prom_fix": prom_fix,
        "shpperent": used_shp,
        "rowsets": rowsets,
        "generic_left": generic_left,
        "subs_final": subs_final,
    }, None


def page_rows_classed(h):
    """[(block, label, holders, shares, pct, class, is_any_other_subrow)] — class from the standard category or the label rule; 'hdr' for the Any-Others header."""
    out = []
    in_other = {"inst": False, "noninst": False}
    for blk, lab, hn, sh, p in parse_full(h):
        if blk not in ("inst", "noninst"):
            continue
        L = re.sub(r"\s+", " ", lab.strip().lower())
        std = STD_INST.get(L)
        if std == "other":
            in_other[blk] = True
            continue
        if std:
            in_other[blk] = False
            out.append(
                (
                    blk,
                    lab.strip(),
                    hn,
                    sh,
                    p,
                    {
                        "fii": "fii",
                        "fpi": "fii",
                        "qfi": "fii",
                        "fvci": "fii",
                        "mf": "dii",
                        "bank": "dii",
                        "ins": "dii",
                        "vcf": "dii",
                        "gov": "gov",
                    }.get(std),
                    False,
                )
            )
            continue
        if (
            blk == "noninst"
            and not in_other[blk]
            and (L.startswith("bodies corporate") or L.startswith("individual"))
        ):
            out.append((blk, lab.strip(), hn, sh, p, "pub", False))
            continue
        c = label_class(lab)
        c = {"fii": "fii", "dii": "dii", "pub": "pub"}.get(c) if c else None
        if c is None and MECH_LAB.search(lab):
            c = "pub"
        bare_other = bool(
            re.match(r"^(any )?others?$", L)
        )  # a header-less 'Any Other' row is itself the block's Any-Others sub-row (FEDERALBNK 2009-13)
        out.append((blk, lab.strip(), hn, sh, p, c, in_other[blk] or bare_other))
    return out


def pre160(prior, cur, eq):
    """The cell before any §160-family entry: walk the superseded chain while entries carry the §160 marker and return the lowest one's
    'was' (a §160c entry's 'was' is the §160/§160b healed value, not the page's own reading). cur itself when the top entry is not §160
    or the store no longer holds the entry's cell."""
    if not (
        prior
        and "\u00a7160" in prior.get("why", "")
        and prior.get("was")
        and eq(cur, prior.get("cell"))
    ):
        return cur
    link = prior
    base = prior["was"]
    depth = 0
    while (
        isinstance(link, dict)
        and "\u00a7160" in link.get("why", "")
        and link.get("was")
        and depth < 10
    ):
        base = link["was"]
        link = link.get("superseded")
        depth += 1
    return base


def F_cell_eq_(a, b):
    if not a or not b:
        return False
    return all(
        abs((a[i] or 0) - (b[i] or 0)) <= 1e-9 + 1e-6 * abs(b[i] or 0)
        for i in range(min(len(a), len(b), 5))
        if isinstance(a[i], (int, float)) and isinstance(b[i], (int, float))
    )


def scan_generic_rows():
    """(sym, qe, block, label, pct) for every unresolved sub-row >= 0.5 pp on the cached pages; cached in generic_rows.json (112 symbols on 2026-09-24)."""
    gp = "generic_rows.json" if GENERIC_FLOOR >= 0.5 else f"generic_rows_f{GENERIC_FLOOR:g}.json"
    if os.path.exists(gp):
        return json.load(open(gp))
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    codes = json.load(open("aspx_codes.json"))
    syms = json.load(open("n500_syms.json"))
    gen = []
    for s in syms:
        c = codes.get(s)
        if not c:
            continue
        for q in sorted(hist.get(s, {})):
            if not ("2006-06-30" <= q <= "2016-03-31"):
                continue
            f = "aspx_pages/%d_%d.html.gz" % (c, qtrid(q))
            if not os.path.exists(f):
                continue
            b = parse(gzip.open(f, "rt", encoding="utf-8").read())
            for blk in ("inst", "noninst"):
                for lab, p, cls, _io in classify_rows(b[blk], blk)[1]:
                    if cls is None and gen_ok(p) and not DR_LAB.search(lab):
                        gen.append((s, q, blk, lab, p))
    json.dump(gen, open(gp, "w"))
    return gen


GENERIC_SYMS = {g[0] for g in scan_generic_rows()}


def classify():
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    codes = json.load(open("aspx_codes.json"))
    syms = json.load(open("n500_syms.json"))
    led = json.load(open(os.path.join(REPO, "scripts", "shp_cell_fix.json"), encoding="utf-8")).get(
        "fix", {}
    )
    F_cell_eq = D.F._cell_eq
    verdicts = D.load_verdicts()
    P = {}
    stats = collections.Counter()
    reasons = collections.Counter()
    unres = collections.Counter()
    left_log = []
    # a missing BSE list silently drops a symbol's holder evidence (ctx=None), which can turn live §160 cells into revert proposals.
    # 2026-09-26: the /private/tmp cleanup deleted 385 of the 500 current lists and api.bseindia.com refuses plain clients. Refuse
    # a run that would degrade more than 2% of the roster; DII_ROWFIX_ALLOW_MISSING_LISTS=1 overrides.
    miss = [
        x for x in syms if codes.get(x) and not os.path.exists(os.path.join(D.LISTS, x + ".json"))
    ]
    if miss:
        print(
            "WARNING: no BSE list for %d/%d symbols in %s (e.g. %s)"
            % (len(miss), len(syms), D.LISTS, ", ".join(miss[:8])),
            file=sys.stderr,
        )
        if len(miss) > 0.02 * len(syms) and os.environ.get("DII_ROWFIX_ALLOW_MISSING_LISTS") != "1":
            raise SystemExit(
                "refusing a partial run: %d of %d symbols have no BSE list (set DII_ROWFIX_ALLOW_MISSING_LISTS=1 to run anyway)"
                % (len(miss), len(syms))
            )
    for s in syms:
        c = codes.get(s)
        if not c:
            continue
        ctx = None
        gctx = None
        lp = os.path.join(D.LISTS, s + ".json")
        if os.path.exists(lp):
            dd = json.load(open(lp))
            bse_rows = dd.get("Table") if isinstance(dd, dict) else dd
            ctx = D.SymCtx(s, bse_rows, verdicts)
            if s in GENERIC_SYMS:
                gctx = {
                    "oldmap": oldmap_for(bse_rows),
                    "pagemap": page_label_map(c, hist.get(s, {})),
                    "pagefull": {},
                }
                for q_ in sorted(hist.get(s, {})):
                    if not ("2006-06-30" <= q_ <= "2016-03-31"):
                        continue
                    f_ = "aspx_pages/%d_%d.html.gz" % (c, qtrid(q_))
                    if os.path.exists(f_):
                        gctx["pagefull"][qtrid(q_)] = page_rows_classed(
                            gzip.open(f_, "rt", encoding="utf-8").read()
                        )
        if (
            gctx is not None
        ):  # pass 1: collect each generic row's holder composition per quarter (no tie-break yet)
            gctx["rowmem"] = {}
            for q in sorted(hist.get(s, {})):
                if not ("2006-06-30" <= q <= "2016-03-31"):
                    continue
                f = "aspx_pages/%d_%d.html.gz" % (c, qtrid(q))
                if not os.path.exists(f):
                    continue
                prior = (led.get(s) or {}).get(q)
                cur = hist[s][q]
                base = pre160(prior, cur, F_cell_eq)
                try:
                    r, why = evaluate(
                        gzip.open(f, "rt", encoding="utf-8").read(), base, s, qtrid(q), c, ctx, gctx
                    )
                except Exception:
                    continue
                for lk, keys in (r or {}).get("rowsets") or []:
                    gctx["rowmem"].setdefault(lk, {}).setdefault(qtrid(q), []).append(keys)
                # a generic row decided in pass 1 carries that class as a label for its neighbours in pass 2
                dec = {
                    (b_, l_.strip(), round(p_, 2)): c_
                    for b_, l_, p_, c_ in ((r or {}).get("subs_final") or [])
                    if c_ in ("fii", "dii", "pub")
                }
                pf_ = gctx["pagefull"].get(qtrid(q)) or []
                gctx["pagefull"][qtrid(q)] = [
                    (
                        x[0],
                        x[1],
                        x[2],
                        x[3],
                        x[4],
                        (dec.get((x[0], x[1], round(x[4], 2))) if x[5] is None else x[5]),
                        x[6],
                    )
                    for x in pf_
                ]
        for q in sorted(hist.get(s, {})):
            if not ("2006-06-30" <= q <= "2016-03-31"):
                continue
            f = "aspx_pages/%d_%d.html.gz" % (c, qtrid(q))
            if not os.path.exists(f):
                stats["no_page"] += 1
                continue
            stats["pages"] += 1
            cur = hist[s][q]
            prior = (led.get(s) or {}).get(q)
            base = pre160(
                prior, cur, F_cell_eq
            )  # a page already healed by §160 is re-read from the cell BEFORE the first §160-family entry (walks the superseded chain), so every rule is re-derived together
            try:
                h = gzip.open(f, "rt", encoding="utf-8").read()
                r, why = evaluate(h, base, s, qtrid(q), c, ctx, gctx)
            except Exception as e:
                stats["parse_err"] += 1
                print("  err", s, q, repr(e)[:120], file=sys.stderr)
                continue
            if D.chain_has(prior):
                stats["skip_164"] += 1
                continue  # re-decided by §164 (FII session, e.g. §164a DR re-base): never re-judged here
            if prior and "(§160f)" in (prior.get("why") or ""):
                stats["skip_160f_doc"] += 1
                continue  # §160f cells come from the filer's annual reports (one class per holder, doc_cells_160f), not from these rules: never re-judged here
            own160 = bool(
                prior
                and "\u00a7160 page-era" in prior.get("why", "")
                and "resolved by the FII session" not in prior.get("why", "")
                and "seam-fii-reconstruction" not in prior.get("why", "")
                and base is not cur
            )
            if own160 and (r is None or not (r["ev"] or r["prom_fix"])):
                # a live §160/§160b cell the current rules no longer support (APOLLOHOSP Jun/Sep-15: the 'Others' row is the Mar-15 'Foreign Corporate
                # Bodies' row, 4 holders 11.78 = Integrated (Mauritius) Healthcare 10.85 + 3 small; §160b had matched three fund names by sum alone)
                P[f"{s}|{q}"] = {
                    "file": os.path.basename(f),
                    "was": cur,
                    "cell": list(base),
                    "d_dii": round((base[2] or 0) - (cur[2] or 0), 4),
                    "d_fii": round((base[1] or 0) - (cur[1] or 0), 4),
                    "add_ins": 0.0,
                    "ev": [
                        (
                            "revert-unsupported",
                            "the earlier §160 move is not supported under the holder-count rules: "
                            + (why or "no rule fires"),
                            round((base[1] or 0) - (cur[1] or 0), 4),
                        )
                    ],
                    "prior_entry": True,
                    "shpperent": False,
                }
                stats["revert"] += 1
                continue
            if r is None:
                stats["no_match"] += 1
                reasons[why.split(" page")[0]] += 1
                continue
            for blk, lab, p in r.get("generic_left", []):
                stats["generic_rows_left"] += 1
                stats["generic_pp_left"] += p
                left_log.append((s, q, blk, lab, p))
            for e in r["ev"]:
                if e[0] == "generic-row-by-holders":
                    stats["generic_rows_resolved"] += 1
            for e in r["ev"]:
                if e[0] == "inst-sub-unresolved":
                    unres[e[1][:40]] += 1
            stats["conv:" + r["conv"][0]] += 1
            if not (r["ev"] or r["prom_fix"]):
                stats["unchanged"] += 1
                continue
            new = list(
                base
            )  # (a re-read of a §160 cell starts from the entry's original cell; otherwise base is cur) a slot that does not move >= 0.05 keeps the STORED value: shp_refine_4dp re-derives dii/ins at 4 dp after apply_cell_fix and would otherwise diverge from the ledger (89 cells aligned by hand on 2026-09-24)
            if abs(r["t_fii"] - (base[1] or 0)) >= 0.05:
                new[1] = r["t_fii"]
            if abs(r["t_dii"] - (base[2] or 0)) >= 0.05:
                new[2] = r["t_dii"]
            if r["prom_fix"]:
                new[0] = round(r["prom_fix"], 4)
            if base[4] is not None and r["add_ins"] > 0:
                new[4] = round((base[4] or 0) + r["add_ins"], 4)
            if (
                abs(new[1] - (cur[1] or 0)) < 0.05
                and abs(new[2] - (cur[2] or 0)) < 0.05
                and abs(new[0] - (cur[0] or 0)) < 0.05
            ):
                stats["unchanged"] += 1
                continue
            if base is not cur:
                for i_ in (
                    1,
                    2,
                    0,
                ):  # an unchanged slot keeps the served value (refine-aligned) when it matches within 0.05
                    if abs((new[i_] or 0) - (cur[i_] or 0)) < 0.05:
                        new[i_] = cur[i_]
            P[f"{s}|{q}"] = {
                "file": os.path.basename(f),
                "was": cur,
                "cell": new,
                "d_dii": round(r["t_dii"] - (cur[2] or 0), 4),
                "d_fii": round(r["t_fii"] - (cur[1] or 0), 4),
                "add_ins": r["add_ins"],
                "ev": r["ev"],
                "prior_entry": bool(prior),
                "shpperent": r.get("shpperent", False),
            }
            stats["proposed"] += 1
    json.dump(P, open("proposals_aspx.json", "w"), indent=0)
    json.dump(left_log, open("generic_left.json", "w"))
    stats["generic_pp_left"] = round(stats["generic_pp_left"])
    print("aspx classify", dict(stats))
    print(" no-match reasons:", reasons.most_common(6))
    print(" unresolved inst sub-row labels:", unres.most_common(10))
    return P


def seam_pass(names=None, dip=5.0):
    """Phase 2b: qtrid 88/89 FII reconstruction for names whose fii dips >= `dip` pp at Dec-15/Mar-16 vs both neighbours, the Sep-15
    neighbour taken AFTER the label-rule proposals (ZENSARTECH: Sep-15 13.93 -> 36.99 makes the stored 14.11 a dip). A cell whose
    label-rule proposal already sits inside the neighbours' range is left to that proposal (ITC/ZENSARTECH hand-off by name)."""
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    codes = json.load(open("aspx_codes.json"))
    syms = json.load(open("n500_syms.json"))
    P = json.load(open("proposals_aspx.json")) if os.path.exists("proposals_aspx.json") else {}
    verdicts = D.load_verdicts()
    out = {}
    stats = collections.Counter()
    for s in syms:
        if names and s not in names:
            continue
        pa = P.get(s + "|2015-09-30")
        a = pa["cell"] if pa else (hist.get(s) or {}).get("2015-09-30")
        c = (hist.get(s) or {}).get("2016-06-30")
        if not a or not c or a[1] is None or c[1] is None:
            continue
        ctx = None
        for q, qe in ((88, "2015-12-31"), (89, "2016-03-31")):
            b = (hist.get(s) or {}).get(qe)
            if not b or b[1] is None:
                continue
            pb = P.get(f"{s}|{qe}")
            if pb and plausible(pb["cell"][1], a[1], c[1], b[1]):
                stats["label_rule_already_plausible"] += 1
                continue
            if not (a[1] - b[1] >= dip and c[1] - b[1] >= dip):
                continue
            stats["dip_cells"] += 1
            if not os.path.exists("aspx_pages/%d_%d.html.gz" % (codes[s], q)):
                stats["no_page"] += 1
                continue
            if ctx is None:
                lp = os.path.join(D.LISTS, s + ".json")
                dd = json.load(open(lp))
                bse_rows = dd.get("Table") if isinstance(dd, dict) else dd
                ctx = D.SymCtx(s, bse_rows, verdicts)
            r, why = reconstruct(
                s, codes[s], q, ctx, verdicts, known_foreign=sibling_foreign_names(codes[s])
            )
            if r is None:
                stats["no_recon"] += 1
                out[f"{s}|{qe}"] = {"held": why}
                continue
            ok = (
                plausible(r["t_fii"], a[1], c[1], b[1])
                or (r.get("whole_block") and abs(r["t_fii"] - c[1]) < abs(b[1] - c[1]))
            )  # the whole-block rule is the page's own total: the neighbour band is waived, closer-to-Jun-16 kept
            if not ok:
                stats["held"] += 1
                out[f"{s}|{qe}"] = {
                    "held": "outside neighbours' range or not closer to Jun-16",
                    "t_fii": r["t_fii"],
                    "sep15": a[1],
                    "jun16": c[1],
                    "ev": r["ev"],
                }
                continue
            new = list(b)
            new[1] = r["t_fii"]
            out[f"{s}|{qe}"] = {
                "file": "%d_%d.html.gz" % (codes[s], q),
                "was": b,
                "cell": new,
                "d_fii": round(r["t_fii"] - b[1], 4),
                "d_dii": 0.0,
                "add_ins": 0.0,
                "ev": [
                    (
                        "seam-fii-reconstruction",
                        "base {:.2f}".format(r["base_fii"]),
                        round(r["t_fii"] - r["base_fii"], 4),
                    )
                ]
                + r["ev"],
                "shpperent": True,
                "prior_entry": False,
            }
            stats["proposed"] += 1
    json.dump(out, open("proposals_seam.json", "w"), indent=0)
    print("seam pass", dict(stats))
    return out


def write_aspx(stamp=None, tag=""):
    """Merge page-era proposals (proposals_aspx.json + proposals_seam.json) into scripts/shp_cell_fix.json with the §160 marker."""
    stamp = stamp or time.strftime("%Y-%m-%d")
    P = json.load(open("proposals_aspx.json"))
    S = (
        {k: v for k, v in json.load(open("proposals_seam.json")).items() if v.get("cell")}
        if os.path.exists("proposals_seam.json")
        else {}
    )
    for k, v in S.items():
        P[k] = v  # a seam reconstruction supersedes the label-rule proposal for the same cell
    path = os.path.join(REPO, "scripts", "shp_cell_fix.json")
    raw = open(path, encoding="utf-8").read()
    led = json.loads(raw)
    fix = led.setdefault("fix", {})
    ascii_only = "\\u00" in raw
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    codes = json.load(open("aspx_codes.json"))
    apath = os.path.join(REPO, "scripts", "_shp_aspx_rowfix_audit.json")
    audit = (
        json.load(open(apath, encoding="utf-8"))
        if os.path.exists(apath)
        else {"_doc": [], "cells": {}}
    )  # merged: later passes add cells, never drop earlier evidence
    audit["_doc"].append(
        f"§160{tag} page-era row-level heal ({stamp}): BSE ShareholdingPattern.aspx (Clause-35 / 88-89 layouts) + shpperent.aspx; rules in DATA_RUNBOOK §160{tag}."
    )
    n_new = n_sup = n_skip = 0
    for k, v in sorted(P.items()):
        sym, qe = k.split("|")
        cur = (hist.get(sym) or {}).get(qe)
        if cur is None or not D.F._cell_eq(cur, v["was"]):
            n_skip += 1
            continue
        src = "bseaspx:{}".format(v["file"].replace(".html.gz", "")) + (
            " shpperent" if v.get("shpperent") else ""
        )
        why = (
            "§160 page-era row-level heal ({}, DII = Institutions(Domestic), FII = Institutions(Foreign) in every format): fii {:.2f} -> {:.2f}, dii {:.2f} -> {:.2f}{}. ".format(
                stamp,
                cur[1],
                v["cell"][1],
                cur[2],
                v["cell"][2],
                (
                    ", prom {:.2f} -> {:.2f}".format(cur[0], v["cell"][0])
                    if abs(v["cell"][0] - cur[0]) > 0.005
                    else ""
                ),
            )
            + "; ".join(" ".join(str(x) for x in e) for e in v["ev"])[:900]
            + ". Evidence: _shp_aspx_rowfix_audit.json"
            + (f" (§160{tag})" if tag else "")
        )
        ent = {"cell": list(v["cell"]), "was": list(cur), "src": src, "why": why}
        prior = (fix.get(sym) or {}).get(qe)
        if (
            prior
            and prior.get("cell")
            and all(abs((prior["cell"][i] or 0) - (v["cell"][i] or 0)) < 0.05 for i in (0, 1, 2))
        ):
            n_same = locals().get("n_same", 0) + 1
            continue  # already healed to the same values
        if prior:
            if not D.F._cell_eq(cur, prior.get("cell")) and not (
                prior.get("was") and D.F._cell_eq(cur, prior.get("was"))
            ):
                n_skip += 1
                continue
            ent["superseded"] = prior
            n_sup += 1
        else:
            n_new += 1
        fix.setdefault(sym, {})[qe] = ent
        audit["cells"][k] = {
            x: v.get(x) for x in ("file", "d_dii", "d_fii", "add_ins", "ev", "shpperent")
        }
    json.dump(led, open(path, "w", encoding="utf-8"), indent=1, ensure_ascii=ascii_only)
    json.dump(audit, open(apath, "w", encoding="utf-8"), indent=0, ensure_ascii=False)
    print("write_aspx: %d new, %d superseding, %d skipped" % (n_new, n_sup, n_skip))


def verify():
    """Seam / QoQ statistics before vs after the proposals (label rule + seam) applied on the store; writes shp_history_aspx_healed.json."""
    hist = json.load(open(os.path.join(REPO, "scripts", "shp_history.json")))
    syms = json.load(open("n500_syms.json"))
    P = json.load(open("proposals_aspx.json"))
    S = (
        {k: v for k, v in json.load(open("proposals_seam.json")).items() if v.get("cell")}
        if os.path.exists("proposals_seam.json")
        else {}
    )
    P.update(S)
    heal = {s: {q: list(v) for q, v in hist.get(s, {}).items()} for s in syms}
    for k, v in P.items():
        s, q = k.split("|")
        heal[s][q] = v["cell"]

    def seam(store, a, b, idx, th):
        n = 0
        movers = []
        tot = 0
        for s in syms:
            x = (store.get(s) or {}).get(a)
            y = (store.get(s) or {}).get(b)
            if not x or not y or x[idx] is None or y[idx] is None:
                continue
            tot += 1
            d = y[idx] - x[idx]
            if abs(d) >= th:
                n += 1
                movers.append((s, round(d, 2)))
        return n, tot, sorted(movers, key=lambda m: -abs(m[1]))

    def qoq(store, idx, th, lo="2006-06-30", hi="2016-06-30"):
        n = 0
        tot = 0
        ex = []
        for s in syms:
            qs = sorted(q for q in (store.get(s) or {}) if lo <= q <= hi)
            for a, b in zip(qs, qs[1:], strict=False):
                x = store[s][a]
                y = store[s][b]
                if x[idx] is None or y[idx] is None:
                    continue
                tot += 1
                if abs(y[idx] - x[idx]) >= th:
                    n += 1
                    ex.append((s, b, round(y[idx] - x[idx], 2)))
        return n, tot, sorted(ex, key=lambda m: -abs(m[2]))

    res = {}
    for name, idx in (("fii", 1), ("dii", 2)):
        for a, b in (
            ("2016-03-31", "2016-06-30"),
            ("2015-06-30", "2015-09-30"),
            ("2015-09-30", "2015-12-31"),
            ("2015-12-31", "2016-03-31"),
        ):
            n0, t0, m0 = seam(hist, a, b, idx, 3.0)
            n1, t1, m1 = seam(heal, a, b, idx, 3.0)
            res[f"{name} seam {a[:7]}->{b[:7]}"] = (n0, n1, t1)
            print(
                "%s seam %s->%s  >=3pp: %d/%d -> %d/%d   top after: %s"
                % (name, a[:7], b[:7], n0, t0, n1, t1, m1[:6])
            )
        n0, t0, e0 = qoq(hist, idx, 5.0)
        n1, t1, e1 = qoq(heal, idx, 5.0)
        res[f"{name} qoq5"] = (n0, n1, t1)
        print(
            "%s QoQ >=5pp Jun-06..Jun-16: %d/%d -> %d/%d   top after: %s"
            % (name, n0, t0, n1, t1, e1[:8])
        )
    json.dump(heal, open("shp_history_aspx_healed.json", "w"))
    return res


if __name__ == "__main__":
    st_ = sys.argv[1] if len(sys.argv) > 1 else "classify"
    if st_ == "classify":
        classify()
    elif st_ == "seam":
        seam_pass(dip=float(sys.argv[2]) if len(sys.argv) > 2 else 5.0)
    elif st_ == "verify":
        verify()
    elif st_ == "write":
        write_aspx()
