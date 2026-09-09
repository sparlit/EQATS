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
"""§111i — fetch the PRIMARY documents for the 59 cross-campaign disputed con cells.

WHY A NEW FETCHER. §59b rung 1 (NSE results XBRL) does not reach this window: the local XBRL cache
starts in 2018 and holds ZERO documents whose `DateOfEndOfReportingPeriod contextRef="OneD"` is
2017-03-31 (measured: 0 of 104,538). Rung 2 (BSE detres) is standalone-only (§42) and this whole
dispute is about the CONSOLIDATED slot. So rung 3 — the BSE announcement PDF, which carries both
bases in one document — is THE route here.

★ THE THIRD ATTACHMENT BASE. Pre-~Nov-2018 attachments 404 on BOTH `AttachHis` and `AttachLive`
(measured on BHARTIARTL's 2017-05-09 filing). Ask BSE instead of guessing:
`stockinfo/AnnPdfOpen.aspx?Pname=<att>` 302s to the base that holds the file
(`CorpAttachment/<YYYY>/<M>/`). memory: reference-bse-attachment-resolver.

★ THREE DOCUMENTS PER QUARTER, not one (memory: feedback-backfill-comparative-columns). A quarter
is printed in its own filing, in the NEXT quarter's filing (as the preceding-quarter column) and in
the NEXT YEAR's same-quarter filing (as the year-ago column). Fetching all three costs nothing
extra and turns a single unreadable scan into a readable cell.

Scrip codes for the 6 delisted/suspended symbols (CANDC, COX&KINGS, EROSMEDIA, FCONSUMER, PEL,
TV18BRDCST) are resolved by EXACT ISIN against BSE's all-scrips master, never by ticker (§76).

OUT: _vintage111_docs/<SYM>_<qe>_<ann>.pdf  +  _vintage111_docs.json (manifest, resumable)
RUN: python3 -X utf8 vintage111_documents.py [--only SYM,SYM] [--limit N]
"""
import gzip
import json
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
os.environ.setdefault("VPDIR", "_vp_v111")
import bse_vision as V  # noqa: E402

SP = os.environ.get("V111_WORK", HERE)
DOCS = os.path.join(SP, "_vintage111_docs")
MANI = os.environ.get("V111_MANI") or os.path.join(SP, "_vintage111_docs.json")
DECL = os.path.join(SP, "declined67.json")
BSE_MASTER = "/Users/dhruvan/stocks-wt/vintage108/scripts/_bse_master_all.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
os.makedirs(DOCS, exist_ok=True)
CAP = 6  # candidates fetched per window, RANKED first (see main); drops are logged

# Result filings hide under many headlines (§59d: "Outcome of Board Meeting" is a real results
# filing). Loose include, firm exclude, and let the content gates downstream do the filtering.
INC = re.compile(
    r"financial result|outcome of board|board meeting|audited result|un-?audited result"
    r"|standalone|consolidated|results for",
    re.IGNORECASE,
)
EXC = re.compile(
    r"xbrl|investor|press release|presentation|earnings call|transcript|intimation"
    r"|newspaper|analyst|shareholding|voting|scrutinizer|corporate governance"
    r"|reconciliation of share",
    re.IGNORECASE,
)


def qe_windows(qe):
    """(label, lo, hi) announcement windows that can print quarter `qe`.

    own      — the quarter's own filing
    next-q   — the following quarter's filing (qe appears as the PRECEDING-quarter column)
    next-y   — the same quarter one year later (qe appears as the YEAR-AGO column)
    """
    y, md = qe // 10000, qe % 10000
    nxt = {331: (y, 630), 630: (y, 930), 930: (y, 1231), 1231: (y + 1, 331)}[md]
    return [
        ("own", "%d%04d" % (y, md), _plus(y, md, 5)),
        ("next-q", "%d%04d" % nxt, _plus(nxt[0], nxt[1], 5)),
        ("next-y", "%d%04d" % (y + 1, md), _plus(y + 1, md, 5)),
    ]


def _plus(y, md, months):
    m = md // 100 + months
    while m > 12:
        m -= 12
        y += 1
    return "%d%02d%02d" % (y, m, 28)


def listing(o, code, lo, hi):
    """Announcement rows in [lo,hi] for one scrip.

    ★ AN EMPTY `Table` IS NOT AN EMPTY WINDOW. Under load BSE answers this endpoint with HTTP 200
    and zero rows, and the first pass recorded "0 candidates" for CANDC, CARBORUNIV, CEATLTD,
    CYIENT and 9 others that had filed perfectly normally — re-queried a few minutes later the same
    call returned 29-34 rows. A silent cap reads downstream as an absent filing
    (memory: feedback-endpoint-caps-are-silent, feedback-never-infer-absence-from-own-gaps).
    So a zero-row page 1 is RETRIED before it is believed.
    """
    out = []
    for pg in (1, 2):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=-1"
            "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C" % (pg, lo, code, hi)
        )
        rows = None
        for attempt in range(4 if pg == 1 else 1):
            try:
                rows = json.loads(V.get(o, u)).get("Table", [])
            except Exception as e:
                print(f"      listing ERR {e}", flush=True)
                rows = None
            if rows:
                break
            if pg == 1 and attempt < 3:
                time.sleep(5 + 6 * attempt)
        if not rows:
            if pg == 1:
                print("      listing EMPTY after 4 tries — recorded as measured-absent", flush=True)
            break
        for r in rows:
            head = "{} {}".format(r.get("NEWSSUB") or "", r.get("SUBCATNAME") or "")
            att = r.get("ATTACHMENTNAME") or ""
            if not att or EXC.search(head) or not INC.search(head):
                continue
            ann = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
            out.append((int(ann) if ann else 0, att, head.strip()[:90]))
        if len(rows) < 50:
            break
        time.sleep(0.8)
    return out


def fetch(o, att):
    """Bytes of an attachment, trying both known bases then BSE'S OWN RESOLVER.

    Validated by %PDF magic, not by a 200 (memory: feedback-validate-downloads-not-exit-codes) —
    a 302 stub is ~162 bytes and would otherwise be written to disk as a "PDF".
    """
    for base in ("AttachHis", "AttachLive"):
        try:
            d = V.get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                return d, base
        except Exception:
            pass
    # ★ RETRY THE TRANSIENT. BSE answers a burst of rapid attachment requests with 404s, not 429s:
    # the same 2018 attachment that failed 6 times in one run downloaded first try a minute later
    # (measured). A single attempt turns rate-limiting into a permanent "no document"
    # (memory: feedback-retry-the-transient-not-just-the-crash).
    err = "not-a-pdf"
    for attempt in range(3):
        try:
            u = "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=" + att
            r = o.open(
                urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}),
                timeout=90,
            )
            d = r.read()
            if d[:4] == b"%PDF":
                return d, "resolver:" + r.geturl().rsplit("/", 3)[0].rsplit("/", 1)[-1]
            err = "not-a-pdf(%d bytes)" % len(d)
        except Exception as e:
            err = f"ERR {e}"
        time.sleep(3 + 4 * attempt)
    return None, err


def codes(syms):
    sc = json.load(open(os.path.join(HERE, "bse_scrips.json"), encoding="utf-8"))["by_id"]
    out = {s: sc[s] for s in syms if s in sc}
    need = [s for s in syms if s not in out]
    if need:
        meta = json.loads(gzip.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read())).get(
            "meta", {}
        )
        by_isin = defaultdict(list)
        for r in json.load(open(BSE_MASTER, encoding="utf-8")):
            if (r.get("Segment") or "").strip() != "Equity":
                continue
            isin = (r.get("ISIN_NUMBER") or "").strip().upper()
            if len(isin) == 12:
                by_isin[isin].append(r)
        for s in need:
            isin = ((meta.get(s) or {}).get("isin") or "").strip().upper()
            hit = by_isin.get(isin, [])
            if len(hit) == 1:
                out[s] = int(hit[0]["SCRIP_CD"])
                print("  ISIN-resolved %-11s -> %s (%s)" % (s, out[s], hit[0].get("ISIN_NUMBER")))
            else:
                print("  UNRESOLVED %-11s isin=%s candidates=%d" % (s, isin or "NONE", len(hit)))
    return out


def main():
    only = None
    limit = 10**9
    for i, a in enumerate(sys.argv[1:]):
        if a == "--only":
            only = set(sys.argv[i + 2].split(","))
        if a == "--limit":
            limit = int(sys.argv[i + 2])
    sel = json.load(open(DECL, encoding="utf-8"))
    cells = sorted({(v["fix"]["sym"], int(v["fix"]["qe"])) for v in sel.values() if v["fix"]["basis"] == "con"})
    if only:
        cells = [c for c in cells if c[0] in only]
    if "--rev" in sys.argv:  # second worker, walking the list from the other end; DOCS is
        cells = cells[::-1]  # shared (filenames are unique), manifests are merged afterwards
    cells = cells[:limit]
    code = codes(sorted({c[0] for c in cells}))
    mani = json.load(open(MANI, encoding="utf-8")) if os.path.exists(MANI) else {}
    o = V.session()
    for sym, qe in cells:
        key = "%s|%d" % (sym, qe)
        got = mani.setdefault(key, {"code": code.get(sym), "docs": {}})
        if sym not in code:
            got["_err"] = "no scrip code"
            continue
        for lbl, lo, hi in qe_windows(qe):
            if any(d.get("win") == lbl for d in got["docs"].values()):
                continue
            rows = listing(o, code[sym], lo, hi)
            # ★ RANK BEFORE CAPPING. Sorting by date alone and taking the first 4 fetched
            # BHARTIARTL's three board-meeting NOTICES and missed the actual "Financial Results For
            # Quarter Ended 31/03/2017" filing that sat fourth — a silent cap that reads downstream
            # as "the filing has no owners row" (memory: feedback-a-cap-plus-a-stuck-item-is-a-wall).
            rows.sort(
                key=lambda r: (
                    0
                    if re.search(
                        r"financial result|results for|announces q|"
                        r"audited|unaudited|un-audited",
                        r[2],
                        re.IGNORECASE,
                    )
                    else 1
                    if re.search(r"outcome of board", r[2], re.IGNORECASE)
                    else 2,
                    r[0],
                )
            )
            keep, drop = rows[:CAP], rows[CAP:]
            print(
                "  %-12s %d %-7s %s..%s -> %d candidates, taking %d%s"
                % (
                    sym,
                    qe,
                    lbl,
                    lo,
                    hi,
                    len(rows),
                    len(keep),
                    ("  DROPPED: " + "; ".join(h[:40] for _, _, h in drop)) if drop else "",
                ),
                flush=True,
            )
            for ann, att, head in keep:
                fn = "%s_%d_%d_%s.pdf" % (sym, qe, ann, re.sub(r"[^0-9a-zA-Z]", "", att)[:12])
                path = os.path.join(DOCS, fn)
                if not os.path.exists(path):
                    d, how = fetch(o, att)
                    if not d:
                        print("      %-8s %s  FAIL %s" % (ann, head[:50], how), flush=True)
                        continue
                    open(path, "wb").write(d)
                    print("      %-8s %s  %d bytes via %s" % (ann, head[:50], len(d), how), flush=True)
                got["docs"][fn] = {"ann": ann, "att": att, "head": head, "win": lbl}
                time.sleep(0.4)
            time.sleep(0.5)
        json.dump(mani, open(MANI, "w"), indent=1)
    json.dump(mani, open(MANI, "w"), indent=1)
    n = sum(len(v.get("docs", {})) for v in mani.values())
    print("DONE  %d cells, %d documents on disk" % (len(mani), n))


if __name__ == "__main__":
    main()
