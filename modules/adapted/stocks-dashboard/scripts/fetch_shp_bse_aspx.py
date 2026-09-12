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
"""FII/DII backfill from BSE's OWN ShareholdingPattern.aspx — the live route nobody probed.

Discovery (2026-08-11): SHPQNewFormat rows for pre-XBRL quarters carry a `navigateurl`
pointing at https://www.bseindia.com/corporates/ShareholdingPattern.aspx?scripcd=<code>
&flag_qtr=1&qtrid=<q>.00&Flag=<New|Old> — and that page STILL SERVES:
  Flag=New : Clause-35 category table (same layout MC mirrored), Jun-2006 (q50) -> Mar-2016+
  Flag=Old : 1997-format table (FIIS / MF and UTI / Banks-FI-Insurance lump), <= Mar-2006 (q49)
qtrid is GLOBAL: qtrid = (year-2001)*4 + {Mar:29, Jun:30, Sep:31, Dec:32}[month].

Derivation rules are the SAME as fetch_shp_wayback_mc.cmd_ledger (both read the same
Clause-35 table): col = %of(A+B+C); dii = mf + banks + ins; inst reconciliation gate at 1pp;
fii NEVER zero-defaulted; prom fallback via pubtot>=99 complement. Flag=Old adds:
dii = mf + the Banks/FI/Insurance LUMP, ins stored as None (inside the lump — writing 0.0
would fabricate "no insurance holding"), reconciliation |mf+lump+fii - inst_sub| <= 0.10.

Stages:
  python3 fetch_shp_bse_aspx.py frontier   # missing member-qtr cells x scripcode -> frontier.json
  python3 fetch_shp_bse_aspx.py pilot N    # fetch+parse a stratified sample, gate vs stored cells
  python3 fetch_shp_bse_aspx.py harvest    # full frontier -> ledger shp_fill_bse_aspx.json.gz
Writes ONLY inside its --dir (default: alongside this script). Read-only on the repo.
"""
import argparse
import datetime
import gzip
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor

from curl_cffi import requests as cr

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/dhruvan/stocks-dashboard"
H_API = {"Referer": "https://www.bseindia.com/", "Accept": "application/json, text/plain, */*"}
H_HTML = {"Referer": "https://www.bseindia.com/", "Accept": "text/html,application/xhtml+xml"}
LAG_DAYS = 21
QOFF = {3: 29, 6: 30, 9: 31, 12: 32}
_lk = threading.Lock()
REFINE = "--refine" in sys.argv  # §22j: target EXISTING 2dp cells, not gaps


def gitshow(path):
    r = subprocess.run(["git", "show", "origin/main:" + path], capture_output=True, cwd=REPO)
    if r.returncode:
        sys.exit(f"git show failed for {path}")
    return json.loads(r.stdout)


def qtrid_of(qe):
    y, m = int(qe[:4]), int(qe[5:7])
    return (y - 2001) * 4 + QOFF[m]


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("limited", "").replace("ltd", ""))


# ---------------------------------------------------------------- frontier
def cmd_frontier(dirp, q_from="2002-12-31", q_to="2016-03-31"):
    """Missing N500 member-quarter cells in [q_from, q_to] x scripcode -> frontier.json.
    Default window = the original 2002-12-31..2016-03-31 (byte-identical behaviour). The floor was a
    hard constant for 4 weeks and IS why shp_history starts Dec-2002: Flag=Old serves Mar-2001 on
    (runbook §22f RIL, §127b pilot 54/56). WP-S1 runs --from 2001-03-31 --to 2002-09-30."""
    ih = gitshow("scripts/indices_history.json")
    rmap = gitshow("scripts/_rename_map.json")
    hist = gitshow("scripts/shp_history.json")
    skipf = gitshow("scripts/shp_no_filing.json").get("cells", {})
    names = hist.get("_names", {})
    try:
        override = gitshow("scripts/_shp_scripcode_override.json")
    except SystemExit:
        override = {}

    def norm(s):
        seen = set()
        while s in rmap and s not in seen and rmap[s] != s:
            seen.add(s)
            s = rmap[s]
        return s

    have = defaultdict(dict)
    for k, v in hist.items():
        if not k.startswith("_") and isinstance(v, dict):
            have[norm(k)].update(v)
    skip = {(norm(s), qe) for s, qs in skipf.items() for qe in qs}

    snaps = sorted(
        (s["effectiveDate"], [norm(x) for x in s["symbols"] if not x.startswith("DUMMY")]) for s in ih["Nifty 500"]
    )

    def members(qe):
        best = []
        for ed, syms in snaps:
            if ed <= qe:
                best = syms
            else:
                break
        return best

    qes = ["%d%s" % (y, s) for y in range(2001, 2017) for s in ("-03-31", "-06-30", "-09-30", "-12-31")]
    qes = [q for q in qes if q_from <= q <= q_to]
    missing = []
    for qe in qes:
        if qe in ("2015-12-31", "2016-03-31"):
            continue  # qtrid 88/89: BSE's own table has the seam defect (fabricated FII 0.00 /
            # broken inst recon — pilot-measured on ITC + 4 others). The MC-derivation
            # seam route owns those cells; a raw read here would poison them.
        for s in members(qe):
            if (s, qe) in skip:
                continue
            if REFINE:
                # §22j precision refresh: the INVERSE selection — cells we already hold but which
                # carry the filer's 2dp percentage. Same page, same derivation; parse_new now
                # recomputes %(A+B+C) from the share-count column.
                c = have.get(s, {}).get(qe)
                if c and len(c) > 2 and all(isinstance(v, (int, float)) and round(v, 2) == v for v in (c[1], c[2])):
                    missing.append((s, qe))
            elif qe not in have.get(s, {}):
                missing.append((s, qe))
    # the two named post-window holes this route was measured to serve
    for s, qe in (("MONSANTO", "2016-09-30"), ("JMTAUTOLTD", "2016-09-30")):
        if q_to >= "2016-03-31" and qe not in have.get(s, {}):
            missing.append((s, qe))

    # scripcode resolution: full master incl. Delisted/Suspended (status BLANK — §22f), + override
    mfile = os.path.join(dirp, "bse_master_all.json")
    if os.path.exists(mfile) and os.path.getsize(mfile) > 1e6:
        master = json.load(open(mfile))
    else:
        r = cr.get(
            "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry=&segment=Equity&status=",
            headers=H_API,
            impersonate="chrome",
            timeout=120,
        )
        master = json.loads(r.text)
        json.dump(master, open(mfile, "w"))
    by_id = {}
    for row in master:
        sid = str(row.get("scrip_id") or "").strip().upper()
        if sid and sid not in by_id:
            by_id[sid] = (int(row["SCRIP_CD"]), row.get("Scrip_Name") or row.get("SCRIP_NAME") or "")
    n_override = 0
    front = []
    unresolved = Counter()
    for s, qe in missing:
        code, bname = None, ""
        if s in override:
            code = int(override[s]["scripcode"] if isinstance(override[s], dict) else override[s])
            n_override += 1
        elif s in by_id:
            code, bname = by_id[s]
        if code is None:
            unresolved[s] += 1
            continue
        front.append(
            {"sym": s, "qe": qe, "code": code, "qtrid": qtrid_of(qe), "bname": bname, "lname": names.get(s, "")}
        )
    json.dump(front, open(os.path.join(dirp, "frontier.json"), "w"), indent=0)
    json.dump(dict(sorted(unresolved.items())), open(os.path.join(dirp, "unresolved.json"), "w"), indent=1)
    print(
        "MISSING member-qtr cells: %d   frontier (scripcode resolved): %d  (override %d)"
        % (len(missing), len(front), n_override)
    )
    print("UNRESOLVED symbols: %d (%d cells) -> unresolved.json" % (len(unresolved), sum(unresolved.values())))
    per_era = Counter(f["qe"][:4] for f in front)
    print("frontier by year:", dict(sorted(per_era.items())))


# ---------------------------------------------------------------- fetch + parse
CACHE_ONLY = False  # recovery passes re-parse what is on disk; no network, no retry storms


def fetch_page(dirp, code, qtrid, flag):
    cf = os.path.join(dirp, "cache", "%d_%d_%s.html.gz" % (code, qtrid, flag))
    if os.path.exists(cf):
        with gzip.open(cf, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read(), True
    if CACHE_ONLY:
        return None, False
    u = "https://www.bseindia.com/corporates/ShareholdingPattern.aspx?scripcd=%d&flag_qtr=1&qtrid=%d.00&Flag=%s" % (
        code,
        qtrid,
        flag,
    )
    for attempt in range(3):
        try:
            r = cr.get(u, headers=H_HTML, impersonate="chrome", timeout=45)
            if r.status_code == 200 and len(r.text) > 3000:  # 162-byte 302 trap: never trust tiny bodies
                os.makedirs(os.path.dirname(cf), exist_ok=True)
                with gzip.open(cf, "wt", encoding="utf-8") as fh:
                    fh.write(r.text)
                return r.text, False
        except Exception:
            pass
        time.sleep(3 * (attempt + 1))
    return None, False


ROW_LABELS = {  # ported verbatim from fetch_shp_wayback_mc (same Clause-35 table)
    "prom": r"Total shareholding of Promoter and Promoter Group\s*\(A\)",
    "mf": r"Mutual Funds\s*/\s*UTI",
    "banks": r"Financial Institutions\s*/\s*Banks",
    "govt": r"Central Government\s*/\s*State Government",
    "ins": r"Insurance Companies",
    "fii": r"Foreign Institutional Investors",
    "qfi": r"Qualified Foreign Investor",
    "vcf": r"^Venture Capital Funds",
    "fvci": r"Foreign Venture Capital Investors",
    "fpi": r"Foreign Portfolio Invest",  # 2014-15: SEBI's FPI category, printed either as
    "anyoth": r"^Any Others?\s*\(Specify\)|^Any Others?$",  # its own row or under "Any Others"
    "pubtot": r"Total Public shareholding\s*\(B\)",
    # WP-S2 pass 2 (2026-09-05, §127g): rows some 2006-13 filers itemise INSIDE the institutions block.
    # Foreign Mutual Fund / Foreign Financial Institutions-Banks are foreign institutional holders -> fii.
    # The rest are non-institutional or strategic categories mis-filed into the block (DR holders, OCBs,
    # NRIs, FDI, trusts, clearing members, market makers): neither fii nor dii under the family
    # convention, but they ARE part of the block's Sub Total, so the recon gate must see them.
    "fmf": r"^Foreign Mutual Funds?$",
    "ffi": r"^Foreign Financial Institutions?\s*/?\s*Banks?$",
    "excl": r"Foreign Bodies\s*DR|Overseas Corporate Bod|Non[- ]Resident Indian|^Foreign Compan|Foreign Corporate Bod|\bFDI\b|^Trusts?$|Clearing Members?|^Others$|Market Makers?|Nominated investors|Foreign Nationals?",
}


def _cells(html):
    text = re.sub(r"<[^>]+>", "\x01", html)
    import html as _h

    cs = [re.sub(r"[\s\xa0]+", " ", _h.unescape(c)).strip() for c in text.split("\x01")]
    return [c for c in cs if c]


def parse_new(html):
    """Clause-35 aspx table -> cols{slot: (pctAB, pctABC)}; page-name identity returned too."""
    cells = _cells(html)
    nm = ""
    for i, c in enumerate(cells):
        if c == "Shareholding Pattern" and i + 1 < len(cells):
            nm = (
                cells[i + 1] if cells[i + 1] != "Shareholding Pattern" else (cells[i + 2] if i + 2 < len(cells) else "")
            )
            break

    def row_nums(i):
        nums = []
        for c2 in cells[i + 1 : i + 9]:
            c2 = c2.replace(",", "").strip()
            if c2 in ("-", ""):
                nums.append(None)
                continue
            if re.fullmatch(r"\d+(?:\.\d+)?", c2):
                nums.append(float(c2))
            else:
                break
        return nums

    # 4dp (§22j): the printed percentage is the filer's, rounded to 2dp — anything under 0.005%
    # prints as a literal 0, and a "lowest DII" screen ranks 0 FIRST. Every Clause-35 row also
    # prints its SHARE COUNT (col 1: [holders, shares, demat, %A+B, %A+B+C]), so recompute
    # %(A+B+C) — the column val() actually reads — as shares/base. base comes from the LARGEST
    # row's own printed pct: a row at >=1% carries at most ±0.005pp of rounding, 1 part in 200.
    # Validated 2026-08-16 across 36 documents / 212 rows: every recomputed pct landed within
    # 0.0071pp of the printed one. Falls back to the printed pct when a page omits share counts.
    _base = None
    _c = []

    # A row is only real if its leading cell is a LABEL. _cells() also yields the numeric cells,
    # so scanning every index produces SHIFTED phantom rows ('32', '23546314') whose columns are
    # offset by one — some land a plausible <=100 value in the pct slot and silently poison both
    # the base candidate and the self-check. Anchor on non-numeric labels only.
    def _islabel(i):
        return not re.fullmatch(r"[\d,.]+", cells[i].strip())

    for _i in range(len(cells)):
        if not _islabel(_i):
            continue
        _n = row_nums(_i)
        # 1.0 <= pct <= 100: _cells() yields numeric cells as row starts too, so an unanchored
        # scan produces SHIFTED rows whose 'pct' is really a pledged SHARE COUNT. One such
        # candidate (24,440,172) drove base to 476 and broke every pre-2013 page.
        if len(_n) >= 5 and _n[1] and _n[4] and 1.0 <= _n[4] <= 100.0:
            _c.append((_n[4], _n[1]))
    if _c:
        _p_big, _sh_big = max(_c)
        _b = _sh_big / (_p_big / 100.0)
        # SELF-CHECK, same as parse_old: the inferred base must reproduce EVERY row's printed
        # %(A+B+C) within 0.02pp. Older Clause-35 pages (pre~2013) carry a DIFFERENT column
        # layout, so nums[1] is not the share count there and the base comes out absurd —
        # APOLLOHOSP 2011-03-31 produced prom=(34.07, 8706911.15). The refine gate refused every
        # one of those, but they showed up as 74% "out of range" refusals in a retry pass, i.e.
        # a silent loss of reach. Without a reproducible base, use the filer's printed pct.
        if _b > 0 and all(
            abs(_n[1] / _b * 100.0 - _n[4]) <= 0.02
            for _n in (row_nums(_j) for _j in range(len(cells)) if _islabel(_j))
            if len(_n) >= 5 and _n[1] and _n[4] and _n[4] <= 100.0
        ):
            _base = _b

    def pair(nums):
        abc = (nums[1] / _base * 100.0) if (_base and len(nums) >= 2 and nums[1]) else None
        if len(nums) >= 5:
            return (nums[3], abc if abc is not None else nums[4])
        if len(nums) == 4:
            return (nums[3], abc if abc is not None else nums[3])
        return None

    def find_row(rxs, lo=0, hi=None):
        rx = re.compile(rxs, re.IGNORECASE)
        for i in range(lo, hi if hi is not None else len(cells)):
            if rx.search(cells[i]):
                p = pair(row_nums(i))
                if p:
                    return p
        return None

    out = {}
    p = find_row(ROW_LABELS["prom"])
    if p:
        out["prom"] = p
    p = find_row(ROW_LABELS["pubtot"])
    if p:
        out["pubtot"] = p
    blk_lo = blk_hi = None
    for rxs in (r"\(1\)\s*Institutions?\s*$", r"^Institutions$"):
        for i, c in enumerate(cells):
            if re.search(rxs, c, re.IGNORECASE):
                blk_lo = i
                for j in range(i + 1, min(i + 160, len(cells))):
                    if re.fullmatch(r"Sub\s*Total", cells[j], re.IGNORECASE):
                        blk_hi = j + 1
                        break
                break
        if blk_lo is not None:
            break
    if blk_lo is not None:
        hi = blk_hi if blk_hi is not None else min(blk_lo + 160, len(cells))
        for slot in ("mf", "banks", "govt", "ins", "fii", "qfi", "vcf", "fvci", "fpi", "anyoth", "fmf", "ffi"):
            p = find_row(ROW_LABELS[slot], blk_lo, hi)
            if p:
                out[slot] = p
        # every excluded-category row in the block, summed (there can be several)
        _ex = 0.0
        _rx = re.compile(ROW_LABELS["excl"], re.IGNORECASE)
        for _i in range(blk_lo, hi):
            if _islabel(_i) and _rx.search(cells[_i]):
                _pp = pair(row_nums(_i))
                if _pp:
                    _ex += (_pp[1] if _pp[1] is not None else _pp[0]) or 0.0
        if _ex:
            out["excl"] = (_ex, _ex)
        if blk_hi is not None:
            p = pair(row_nums(blk_hi - 1))
            if p:
                out["inst_sub"] = p
    if "fii" not in out and "mf" not in out and "inst_sub" not in out:
        return None, nm
    return out, nm


def parse_old(html):
    """1997-format table -> dict(prom, fii, mf, lump, inst_sub) in % of grand total."""
    cells = _cells(html)
    nm = ""
    for i, c in enumerate(cells):
        if c == "Shareholding Pattern" and i + 1 < len(cells):
            nm = (
                cells[i + 1] if cells[i + 1] != "Shareholding Pattern" else (cells[i + 2] if i + 2 < len(cells) else "")
            )
            break

    def _nums_at(i):
        nums = []
        for c2 in cells[i + 1 : i + 4]:
            c2 = c2.replace(",", "").strip()
            if re.fullmatch(r"\d+(?:\.\d+)?", c2):
                nums.append(float(c2))
            else:
                break
        return nums

    # 4dp (§22j), same treatment the Clause-35 table already gets: each 1997-format row prints
    # (shares, pct) and that pct is the FILER's 2dp figure, so a sub-0.005% holding prints as a
    # literal 0 — the value a "lowest DII" screen ranks first. Recompute pct = shares/base, base
    # inferred from the LARGEST row's own printed pct (>=1% carries at most ±0.005pp of rounding).
    # SELF-CHECK: the base must reproduce EVERY row's printed pct within 0.02pp, otherwise this
    # page's two columns are not a (shares, pct) pair at all and the printed pct is used unchanged.
    _base = None

    def _islabel_o(i):
        return not re.fullmatch(r"[\d,.]+", cells[i].strip())

    _rows = [n for n in (_nums_at(i) for i in range(len(cells)) if _islabel_o(i)) if len(n) >= 2 and n[0] and n[1]]
    _cand = [(n[1], n[0]) for n in _rows if 1.0 <= n[1] <= 100.0]
    if _cand:
        _p, _s = max(_cand)
        _b = _s / (_p / 100.0)
        if _b > 0 and all(abs(n[0] / _b * 100.0 - n[1]) <= 0.02 for n in _rows if n[1] <= 100.0):
            _base = _b

    def val_after(rxs, lo=0, hi=None):
        rx = re.compile(rxs, re.IGNORECASE)
        for i in range(lo, hi if hi is not None else len(cells)):
            if rx.search(cells[i]):
                nums = _nums_at(i)
                if len(nums) >= 2:
                    if _base and nums[0]:
                        return (i, nums[0] / _base * 100.0)
                    return (i, nums[1])  # (shares, pct) -> pct
        return (None, None)

    out = {}
    # promoter block: "Promoter's Holding ... Sub Total"
    ip = next((i for i, c in enumerate(cells) if re.search(r"Promoter'?s? Holding", c, re.IGNORECASE)), None)
    inp = next((i for i, c in enumerate(cells) if re.search(r"Non Promoter'?s? Holding", c, re.IGNORECASE)), None)
    if ip is not None and inp is not None and inp > ip:
        _, v = val_after(r"^Sub\s*Total$", ip, inp)
        if v is not None:
            out["prom"] = v
    lo = inp if inp is not None else 0
    # promoter-less filers (ITC/FEDERALBNK class): the promoter block prints nothing. The page
    # still asserts prom≈0 arithmetically when the two non-promoter Sub Totals close to 100.
    if out.get("prom") is None and inp is not None:
        subs = []
        for i in range(inp, len(cells)):
            if re.fullmatch(r"Sub\s*Total", cells[i], re.IGNORECASE):
                nums = []
                for c2 in cells[i + 1 : i + 4]:
                    c2 = c2.replace(",", "").strip()
                    if re.fullmatch(r"\d+(?:\.\d+)?", c2):
                        nums.append(float(c2))
                    else:
                        break
                if len(nums) >= 2:
                    subs.append(nums[1])
        if len(subs) >= 2 and 99.5 <= subs[0] + subs[1] <= 100.5:
            out["prom"] = round(max(0.0, 100.0 - subs[0] - subs[1]), 2)
    # PROMOTER BLOCK WITHOUT ITS HEADER (WP-S2 2026-09-05, runbook §127g): some 1997-format pages print
    # the promoter rows ("Persons acting in Concert" / "Indian Promoters") and their "Sub Total" directly,
    # with NO "Promoter's Holding" label row — SOUTHBANK Mar-2003: `Persons acting in Concert 1708000 4.77 |
    # Sub Total 1708000 4.77 | Non Promoter's Holding …`. The header search above leaves prom None and the
    # promoter-less fallback cannot fire (16.65 + 78.58 = 95.23, not ~100), so the cell was refused
    # "no-prom" although the page states the figure. Take the LAST "Sub Total" BEFORE the Non-Promoter
    # header as the promoter total — and accept it ONLY when the page's own arithmetic closes:
    # prom + every non-promoter Sub Total == Grand Total (100) within 0.5pp. Strictly additive: pages that
    # carried the header are untouched.
    # (`ip` can equal `inp`: the header regex is unanchored and "Non Promoter's Holding" matches it too.)
    if out.get("prom") is None and inp is not None and (ip is None or ip >= inp):
        pre = [
            i
            for i in range(inp)
            if re.fullmatch(r"Sub\s*Total", cells[i].strip(), re.IGNORECASE) and len(_nums_at(i)) >= 2
        ]
        if pre:
            cand = _nums_at(pre[-1])[1]
            post = [
                _nums_at(i)[1]
                for i in range(inp, len(cells))
                if re.fullmatch(r"Sub\s*Total", cells[i].strip(), re.IGNORECASE) and len(_nums_at(i)) >= 2
            ]
            gt = next(
                (
                    _nums_at(i)[1]
                    for i in range(len(cells))
                    if re.fullmatch(r"Grand\s*Total", cells[i].strip(), re.IGNORECASE) and len(_nums_at(i)) >= 2
                ),
                None,
            )
            if post and gt is not None and 99.5 <= gt <= 100.5 and abs(cand + sum(post) - gt) <= 0.5:
                out["prom"] = (_nums_at(pre[-1])[0] / _base * 100.0) if (_base and _nums_at(pre[-1])[0]) else cand
    _, v = val_after(r"^FIIS?\b", lo)
    out["fii"] = v
    _, v = val_after(r"Mutual Funds? and UTI", lo)
    out["mf"] = v
    _, v = val_after(r"Banks\s*,?\s*Financial Institutions?\s*,?\s*Insurance", lo)
    out["lump"] = v
    ii = next(
        (i for i, c in enumerate(cells[lo:], lo) if re.search(r"Institutional Investors?$", c, re.IGNORECASE)), None
    )
    if ii is not None:
        _, v = val_after(r"^Sub\s*Total$", ii)
        if v is not None:
            out["inst_sub"] = v
    # The filer's own NOTE on the 1997-format page: "Total Foreign Shareholding is N equity shares
    # representing x% ... held by NRIs/OCBs". When that N equals the NRIs/OCBs row's share count, the
    # document itself states that NO other foreign holder (i.e. no FII) exists — a second, in-document
    # reader for an absent FIIS row (WP-S2 2026-09-05, runbook §127g). Captured here, judged in _attempt.
    m_note = None
    for c in cells:
        mm = re.search(r"Total Foreign Shareholding is\s*([\d,]+)\s*equity shares", c, re.IGNORECASE)
        if mm:
            try:
                m_note = float(mm.group(1).replace(",", ""))
                break
            except ValueError:
                pass
    # the Others block's Sub Total and the Grand Total pct — a page with NO institutional block proves
    # "institutions = 0" only when promoter + others close to the grand total (ELDERPHARM Dec-2002).
    _io = next(
        (i for i, c in enumerate(cells) if re.fullmatch(r"Others", c.strip(), re.IGNORECASE) and i > (inp or 0)), None
    )
    if _io is not None:
        for i in range(_io + 1, len(cells)):
            if re.fullmatch(r"Sub\s*Total", cells[i].strip(), re.IGNORECASE) and len(_nums_at(i)) >= 2:
                out["others_sub"] = (_nums_at(i)[0] / _base * 100.0) if (_base and _nums_at(i)[0]) else _nums_at(i)[1]
                break
    _gt = next(
        (
            _nums_at(i)[1]
            for i, c in enumerate(cells)
            if re.fullmatch(r"Grand\s*Total", c.strip(), re.IGNORECASE) and len(_nums_at(i)) >= 2
        ),
        None,
    )
    if _gt is not None:
        out["grand_total_pct"] = _gt
    # every FOREIGN row outside the institutional block (NRIs/OCBs, GDR/ADR custodians, foreign bodies):
    # their share counts summed, to be matched against the filer's own foreign-holding note.
    _fx = 0.0
    for i, c in enumerate(cells):
        if (
            _islabel_o(i)
            and re.search(
                r"NRIs?\s*/\s*OCBs?|\bGDR|\bADR|Overseas Corporate|Foreign (?!Institutional|Promoter)", c, re.IGNORECASE
            )
            and not re.search(r"Total Foreign Shareholding", c, re.IGNORECASE)
        ):
            _n = _nums_at(i)
            if _n:
                _fx += _n[0]
    if _fx:
        out["foreign_rows_shares"] = _fx
    if m_note is not None:
        out["foreign_note_shares"] = m_note
        inr = next((i for i, c in enumerate(cells) if re.search(r"NRIs?\s*/\s*OCBs?", c, re.IGNORECASE)), None)
        if inr is not None:
            nums = _nums_at(inr)
            if nums:
                out["nri_shares"] = nums[0]
    # A 1997-format page whose institutional block prints ONLY the Banks/FI/Insurance lump (or nothing at
    # all) has neither an FIIS nor an MF row — ASTRAZEN Dec-2002 (lump 0.01, Grand Total 100), CUB Dec-2002
    # (lump 5.10, no promoter block). 216 such pages were refused "no category rows" and journalled absent
    # (WP-S2 2026-09-05, runbook §127g) although the table is complete: the caller's proven-zero rule
    # (inst_sub == mf + lump) decides fii, mf defaults to 0, prom via the two-subtotal fallback. So refuse
    # only when NOTHING of the table parsed: no promoter, no lump, no institutional sub-total, no Grand Total.
    _has_gt = any(
        re.fullmatch(r"Grand\s*Total", c.strip(), re.IGNORECASE) and len(_nums_at(i)) >= 2 for i, c in enumerate(cells)
    )
    if (
        out.get("fii") is None
        and out.get("mf") is None
        and not (
            _has_gt and (out.get("lump") is not None or out.get("inst_sub") is not None or out.get("prom") is not None)
        )
    ):
        return None, nm
    return out, nm


def cell_of(fr, dirp, neigh=None):
    """fetch + parse + derive one frontier cell -> (status, cell|None, detail).
    Tries the era-appropriate Flag first; on ANY refusal (parse, identity, gate) tries the
    other Flag — same filing, different render — and keeps the first attempt's verdict when
    neither passes."""
    first = "New" if fr["qtrid"] >= 50 else "Old"
    verdict = None
    for flag in (first, "Old" if first == "New" else "New"):
        st, cell, det = _attempt(fr, dirp, neigh, flag)
        if st == "ok":
            return (st, cell, det)
        if verdict is None or verdict[0] == "absent":
            verdict = (st, cell, det)
    return verdict


def _attempt(fr, dirp, neigh, used):
    code, q, qe, sym = fr["code"], fr["qtrid"], fr["qe"], fr["sym"]
    html, _ = fetch_page(dirp, code, q, used)
    if not html:
        return ("absent", None, f"no page under Flag={used}")
    cols, nm = (parse_new if used == "New" else parse_old)(html)
    if cols is None:
        return ("absent", None, f"no category rows Flag={used}")

    # identity: page company name vs ledger/master name (era renames make this fuzzy —
    # containment). Override-resolved rows (bname == "") carry per-entry evidence in
    # _shp_scripcode_override.json and the aspx prints the CURRENT registered name for era
    # quarters (RUCHISOYA 2002 -> "Patanjali Foods Ltd"), so the era-name gate must not apply.
    # mc:symbol resolutions carry an exact NSE-symbol + ISIN match — stronger evidence than a
    # name comparison across era renames (SATYAMCOMP's page prints "Satyam Computer Services",
    # MC's current name is "Mahindra Satyam" — same entity, the gate must not refuse it).
    pn, ln, bn = norm_name(nm), norm_name(fr.get("lname")), norm_name(fr.get("bname"))
    if (
        fr.get("bname") != ""
        and not str(fr.get("via", "")).startswith("mc:symbol")
        and pn
        and (ln or bn)
        and not (ln and (ln in pn or pn in ln))
        and not (bn and (bn in pn or pn in bn))
    ):
        return ("identity", None, "page='{}' vs '{}'/'{}'".format(nm, fr.get("lname"), fr.get("bname")))

    sub = (datetime.date(*map(int, qe.split("-"))) + datetime.timedelta(days=LAG_DAYS)).isoformat()
    src = "bseaspx:%d:%d:%s" % (code, q, used)
    if used == "New":

        def val(slot):
            p = cols.get(slot)
            if not p:
                return None
            return p[1] if p[1] is not None else p[0]  # %of(A+B+C), stored convention

        # 2014-15 FPI rows: "Foreign Portfolio Invest*" appears as its own row or itemised under
        # "Any Others (Specify)" (ADANIPORTS Sep-15: Any-Others 9.29 == FPI 9.29 — same block,
        # count ONCE). FPI is foreign -> fii. An Any-Others row with NO FPI itemisation is
        # anonymous other-institutions -> dii (the OLD_OTHER_TO_DII calibration).
        fpi, anyoth = val("fpi"), val("anyoth")
        fpi_add = oth_add = 0.0
        if anyoth is not None and fpi is not None:
            if abs(anyoth - fpi) <= 0.02:
                fpi_add = anyoth
            else:
                fpi_add = fpi
                oth_add = max(0.0, anyoth - fpi)
        elif fpi is not None:
            fpi_add = fpi
        elif anyoth is not None:
            oth_add = anyoth
        fii = val("fii")
        prom = val("prom")
        if prom is None:
            pt = cols.get("pubtot")
            pab = pt[0] if pt and pt[0] is not None else None
            if pab is not None and pab >= 99.0:
                prom = round(max(0.0, 100.0 - pab), 4)
            else:
                return ("no-prom", None, "no promoter total")
        mf = val("mf") or 0.0
        # family convention (Wayback-MC ledger): dii = mf + banks + ins. An anonymous Any-Others
        # row folds in ONLY when reconciliation needs it — keeps the ~22k stored 2010-16 cells and
        # these on one convention, while still closing the pages where the row is material.
        # VCF = domestic Venture Capital Funds -> dii; FVCI = Foreign VC Investors -> fii (added
        # to fii below). Both rows are EXTRACTED by parse_new but were never summed into the family
        # totals, so any filer holding them failed inst-recon and was silently rejected (INNOIND
        # 2013 = recon gap == FVCI 4.36pp exactly; PLAN_FAV14 P2, 2026-08-24). Strictly additive:
        # a filer without these rows reads 0 here, unchanged.
        dii_base = round(mf + (val("banks") or 0.0) + (val("ins") or 0.0) + (val("vcf") or 0.0), 4)
        dii = dii_base
        inst = val("inst_sub")
        derived = False
        excl = val("excl") or 0.0
        if fii is not None:
            fii = round(fii + fpi_add + (val("fvci") or 0.0) + (val("fmf") or 0.0) + (val("ffi") or 0.0), 4)
            if inst is not None and oth_add:
                gap0 = abs(fii + dii_base + excl + (val("govt") or 0.0) + (val("qfi") or 0.0) - inst)
                gap1 = abs(fii + dii_base + excl + oth_add + (val("govt") or 0.0) + (val("qfi") or 0.0) - inst)
                if gap0 > 1.0 and gap1 <= 1.0:
                    dii = round(dii_base + oth_add, 4)
        else:
            # early Clause-35 pages omit empty rows (AGRODUTCH Sep-06: block = MF+banks only).
            # The block's own subtotal proves the foreign residual — same arithmetic the seam
            # derivation used, gated: ~0 accepted outright, positive only with a stored
            # neighbour within 5pp, negative refused.
            if inst is None:
                return ("no-fii", None, "fii row absent, no subtotal")
            # deriving: the residual cannot tell foreign from anonymous-other, so fold Any-Others
            # into dii FIRST (the calibrated direction) and let the remainder be foreign.
            if oth_add:
                dii = round(dii_base + oth_add, 4)
            r = inst - (
                dii
                + excl
                + (val("govt") or 0.0)
                + (val("qfi") or 0.0)
                + fpi_add
                + (val("fmf") or 0.0)
                + (val("ffi") or 0.0)
            )
            if -0.15 <= r <= 0.15:
                fii = round(max(0.0, r) + fpi_add, 4)
                derived = True
            elif r > 0.15:
                nb = [
                    neigh[k]
                    for k in ((sym, _adj(qe, -1)), (sym, _adj(qe, 1)), (sym, _adj(qe, -2)), (sym, _adj(qe, 2)))
                    if neigh and k in neigh
                ]
                if nb and min(abs(r + fpi_add - v) for v in nb) <= 5.0:
                    fii = round(r + fpi_add, 4)
                    derived = True
                else:
                    return ("no-fii", None, f"residual {r:.2f} unanchored")
            else:
                return ("recon", None, f"negative residual {r:.2f}")
        if inst is not None and not derived:
            if abs(fii + dii + excl + (val("govt") or 0.0) + (val("qfi") or 0.0) - inst) > 1.0:
                return ("recon", None, "inst recon fail")
        ins = round(val("ins") or 0.0, 4)
    else:
        fii, mf, lump, prom, inst = (
            cols.get("fii"),
            cols.get("mf"),
            cols.get("lump"),
            cols.get("prom"),
            cols.get("inst_sub"),
        )
        # NO institutional block at all (WP-S2 pass 2, §127g): the 1997 format omits an empty block entirely
        # (ELDERPHARM Dec-2002: Promoter 44.46 + Others 55.54 = Grand Total 100). The page's own arithmetic
        # then proves institutions = 0 — fii, mf and the lump are all zero. Fires only when NOTHING of the
        # block parsed and the two printed totals close to the grand total within 0.5pp.
        if (
            fii is None
            and mf is None
            and lump is None
            and inst is None
            and prom is not None
            and cols.get("others_sub") is not None
            and cols.get("grand_total_pct") is not None
            and abs(prom + cols["others_sub"] - cols["grand_total_pct"]) <= 0.5
            and 99.5 <= cols["grand_total_pct"] <= 100.5
        ):
            fii, mf, lump, inst = 0.0, 0.0, 0.0, 0.0
        if fii is None:
            # 1997 format omits empty rows. Absent FIIS = fii 0 ONLY when the block's own
            # arithmetic proves it: inst_sub == mf + lump to a print unit. Else refuse (§57).
            if inst is not None and abs(inst - ((mf or 0.0) + (lump or 0.0))) <= 0.15:
                fii = 0.0
            else:
                return ("no-fii", None, "FIIS row absent, residual unproven")
        if prom is None:
            return ("no-prom", None, "promoter subtotal absent")
        mf = mf or 0.0
        dii = mf + (lump or 0.0)
        if inst is not None and abs((mf + (lump or 0.0) + fii) - inst) > 0.15:
            return ("recon", None, f"old recon fail {mf + (lump or 0.0) + fii:.2f} vs {inst:.2f}")
        ins = None  # inside the lump — never fabricate 0.0
    if not (0 <= prom <= 100 and 0 <= fii <= 100 and 0 <= dii <= 100):
        return ("range", None, "out of range")
    # fabricated-zero guard (MONSANTO Sep-16 class): an exact fii 0.00 beside a stored
    # neighbour holding >1% is the seam defect wearing a company suit — refuse, never write.
    if fii == 0.0 and neigh:
        nb = [neigh[k] for k in ((sym, _adj(qe, -1)), (sym, _adj(qe, +1))) if k in neigh]
        if any(v > 1.0 for v in nb):
            # 1997-format exception (WP-S2 2026-09-05, §127g): the FIIS row is ABSENT, the institutional
            # sub-total proves mf+lump (so no hidden FII line), AND the filer's own note states the total
            # foreign holding == the NRIs/OCBs row — the document says twice that no FII holds anything.
            # GODAVRFERT Mar-2003 (inst 0.04%, note 3.71% = NRI row) beside a stored Jun-2003 of 1.57 is an
            # FII ENTERING the next quarter, not a fabricated zero. The seam-class fabricated "FII 0.00"
            # (qtrid 88/89, Clause-35 format) prints an explicit FII row and has no such note — unaffected.
            fn = cols.get("foreign_note_shares")
            nr = cols.get("foreign_rows_shares") or cols.get("nri_shares")
            # the note must equal the sum of EVERY foreign row printed outside the institutional block
            # (NEPCMICON Mar-2003: NRIs 865,182 + "GDR - Bankers Trust" 3,176,375 = note 4,041,557)
            if (
                used == "Old"
                and cols.get("fii") is None
                and fn is not None
                and nr is not None
                and abs(fn - nr) <= max(1.0, 0.001 * fn)
            ):
                pass  # accept the proven zero
            else:
                return ("zero-vs-neighbour", None, f"fii 0.00 beside stored {max(nb):.2f}")
    return ("ok", [round(prom, 4), round(fii, 4), round(dii, 4), round(mf, 4), ins, sub, None, src], used)


def _adj(qe, step):
    y, m = int(qe[:4]), int(qe[5:7])
    m += 3 * step
    y, m = y + (m - 1) // 12, (m - 1) % 12 + 1
    return "%04d-%02d-%s" % (y, m, {3: "31", 6: "30", 9: "30", 12: "31"}[m])


# ---------------------------------------------------------------- pilot / harvest
def run(dirp, front, workers, tag):
    hist = gitshow("scripts/shp_history.json")
    neigh = {}
    for s, qs in hist.items():
        if s.startswith("_") or not isinstance(qs, dict):
            continue
        for qe, v in qs.items():
            if isinstance(v, list) and len(v) > 1 and v[1] is not None:
                neigh[(s, qe)] = v[1]
    res, stats, rejects = {}, Counter(), {}
    t0 = time.time()

    def one(fr):
        st, cell, det = cell_of(fr, dirp, neigh)
        with _lk:
            stats[st] += 1
            if st == "ok":
                res.setdefault(fr["sym"], {})[fr["qe"]] = cell
            else:
                rejects["{}|{}".format(fr["sym"], fr["qe"])] = f"{st}: {det}"
                if stats[st] <= 8:
                    print("  [{}] {} {}: {}".format(st, fr["sym"], fr["qe"], det), flush=True)
        if not CACHE_ONLY:
            time.sleep(0.4)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(one, front))
    n = sum(len(v) for v in res.values())
    print(
        "\n%s: %d cells parsed OK of %d fetched in %.0fs — %s" % (tag, n, len(front), time.time() - t0, dict(stats)),
        flush=True,
    )
    json.dump(rejects, open(os.path.join(dirp, "rejects.json"), "w"), indent=0)
    print("rejects -> rejects.json (%d cells, not-found-via:bseaspx)" % len(rejects), flush=True)

    # overlap gate: everything we parsed that ALREADY exists in the ledger must reproduce
    diffs = []
    for sym, qs in res.items():
        for qe, cell in qs.items():
            old = (hist.get(sym) or {}).get(qe)
            if old:
                diffs.append((abs(cell[1] - old[1]), abs(cell[2] - old[2]), sym, qe, cell[1], old[1]))
    if diffs:
        bad = [d for d in diffs if d[0] > 0.11 or d[1] > 0.11]
        diffs.sort(reverse=True)
        print("OVERLAP GATE: %d overlap cells, %d disagree beyond 0.11pp" % (len(diffs), len(bad)))
        for d in (bad or diffs[:5])[:10]:
            print("   dFII={:.2f} dDII={:.2f} {} {} aspx={:.2f} stored={:.2f}".format(*d))
    return res, stats, diffs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["frontier", "pilot", "harvest"])
    ap.add_argument("n", nargs="?", type=int, default=60)
    ap.add_argument("--refine", action="store_true", help="22j: target EXISTING 2dp cells instead of gaps; own ledger")
    ap.add_argument("--dir", default=HERE)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--cache-only", action="store_true", help="re-parse pages already on disk; never fetch (recovery passes)"
    )
    ap.add_argument("--from", dest="q_from", default="2002-12-31", help="frontier window start (quarter-end ISO)")
    ap.add_argument("--to", dest="q_to", default="2016-03-31", help="frontier window end (quarter-end ISO)")
    ap.add_argument("--frontier", default="frontier.json", help="frontier file inside --dir (e.g. frontier_unres.json)")
    a = ap.parse_args()
    global CACHE_ONLY
    CACHE_ONLY = a.cache_only
    os.makedirs(os.path.join(a.dir, "cache"), exist_ok=True)
    if a.cmd == "frontier":
        cmd_frontier(a.dir, a.q_from, a.q_to)
        return
    front = json.load(open(os.path.join(a.dir, a.frontier)))
    if a.cmd == "pilot":
        # stratified: spread across years, plus deliberate OVERLAP cells (already-stored) as the gate
        hist = gitshow("scripts/shp_history.json")
        by_year = defaultdict(list)
        for f in front:
            by_year[f["qe"][:4]].append(f)
        take = []
        per = max(2, a.n // (len(by_year) + 4))
        for y in sorted(by_year):
            take += by_year[y][:per]
        # overlap sample: stored cells re-fetched deliberately (not in frontier — build ad hoc)
        gitshow("scripts/_rename_map.json")
        ov = []
        for sym in ("RELIANCE", "ITC", "HDFCBANK", "INFY", "TATASTEEL", "CAPF", "SUNPHARMA", "WIPRO"):
            qs = hist.get(sym) or {}
            for qe in sorted(qs):
                if qe <= "2016-03-31" and len(ov) < 24:
                    code = {
                        "RELIANCE": 500325,
                        "ITC": 500875,
                        "HDFCBANK": 500180,
                        "INFY": 500209,
                        "TATASTEEL": 500470,
                        "CAPF": 532938,
                        "SUNPHARMA": 524715,
                        "WIPRO": 507685,
                    }[sym]
                    ov.append({"sym": sym, "qe": qe, "code": code, "qtrid": qtrid_of(qe), "bname": sym, "lname": sym})
        print("pilot: %d frontier cells + %d overlap cells" % (len(take), len(ov)))
        run(a.dir, take + ov, a.workers, "PILOT")
        return
    if a.cmd == "harvest":
        res, _stats, _diffs = run(a.dir, front, a.workers, "HARVEST")
        out = os.path.join(a.dir, "shp_refine_aspx.json.gz" if REFINE else "shp_fill_bse_aspx.json.gz")
        with gzip.open(out, "wt", encoding="utf-8") as fh:
            json.dump({"_built": "fetch_shp_bse_aspx harvest", "fills": res}, fh)
        print("ledger -> %s  (%d syms, %d cells)" % (out, len(res), sum(len(v) for v in res.values())))


if __name__ == "__main__":
    main()
