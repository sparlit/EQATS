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
"""FILL-2020 con-PAT: adjudicate the 12 `S'-mismatch` refusals -- bad page, or bad stored std?

GATE S' (§53a) refuses a consolidated read when the NON-consolidated page for the same quarter
disagrees with our STORED standalone PAT. That is the right default, but it conflates two very
different situations:

  * BAD PAGE      -- the archive served a different period/revision, so nothing on it is usable;
  * BAD STORED    -- the page is fine and our own standalone cell is the wrong one (restatement,
                     revised filing, an importer error), in which case the refusal is a FALSE one.

§45's fiscal-year quarter-sum identity is the documented way to tell them apart, and it is proof
rather than inference: an audited annual is not free to disagree with its own quarters.

    archive std quarters sum == audited std annual  -> the pages are coherent; stored is the odd one
    stored  std quarters sum == audited std annual  -> our series is right and the page is wrong
    neither                                         -> mixed basis / restatement; refuse either way

Two cheaper tells are reported alongside, because they catch the common failure fast:
  * PERIOD MIS-MAP: the std page's value equals our stored std for a DIFFERENT quarter (+/-4) --
    the double-indexing fingerprint of §45, and decisive evidence of a bad page.
  * SELF-CONSISTENCY: the std page's own EPS x equity / face value reproduces its own PAT, which
    says the page is an internally coherent document rather than a mis-parse.

Read-only. Writes scripts/con_pat_sprime_adjudication.json for the ledger; changes no data.

Run:  python3 -X utf8 scripts/fill2020_tools/adjudicate_sprime.py [--only SYM]
"""
import importlib.util
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)

_spec = importlib.util.spec_from_file_location("own", os.path.join(HERE, "read_con_pat_owners.py"))
OWN = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(OWN)
NAR = OWN.NAR

OUT = os.path.join(SCRIPTS, "con_pat_sprime_adjudication.json")
FY_ABS, FY_REL = 3.0, 0.03


def std_pages(sym, lo, hi):
    """{qe: link} for every NON-consolidated quarterly page the list offers in [lo, hi]."""
    out = {}
    for row in OWN._list_rows(sym):
        if not (row.get("consolidated") or "").strip().lower().startswith("non"):
            continue
        qe = NAR.iso_qe(row.get("toDate") or "")
        if qe and lo <= qe <= hi and row.get("resultDetailedDataLink"):
            out.setdefault(qe, row["resultDetailedDataLink"])
    return out


_ANN = {}


def std_annual_link(sym, fy):
    """The AUDITED STANDALONE ANNUAL page for FY<fy>.

    ⚠️ It cannot be found in the quarterly list: the FY row and the Q4 row share a `toDate` of
    31-Mar, so picking by toDate silently returns the QUARTER (that mistake made every verdict in
    the first run an artifact -- a 3-month figure compared against a 4-quarter sum). The list API
    has its own `period=Annual` feed; the row is then span-checked to ~12 months from fromDate."""
    import urllib.parse

    if sym not in _ANN:
        rows = []
        for s in [sym, *NAR.aliases(sym)]:
            lp = os.path.join(NAR.CACHE, "annlist_{}.json".format(re.sub(r"[^A-Z0-9]", "_", s.upper())))
            try:
                raw = NAR.get(
                    "https://www.nseindia.com/api/corporates-financial-results"
                    "?index=equities&symbol={}&period=Annual".format(urllib.parse.quote(s, safe="")),
                    lp,
                )
                got = json.loads(raw)
                if isinstance(got, list):
                    rows.extend(got)
            except Exception:
                pass
            time.sleep(0.5)
        _ANN[sym] = rows
    for row in _ANN[sym]:
        if not (row.get("consolidated") or "").strip().lower().startswith("non"):
            continue
        to_qe = NAR.iso_qe(row.get("toDate") or "")
        fr_qe = NAR.iso_qe(row.get("fromDate") or "")
        if to_qe != fy * 10000 + 331 or not row.get("resultDetailedDataLink"):
            continue
        if fr_qe is None:
            continue
        months = (to_qe // 10000 - fr_qe // 10000) * 12 + ((to_qe // 100) % 100 - (fr_qe // 100) % 100)
        if 10 <= months <= 13:  # a real 12-month span, §53d's declared-span gate
            return row["resultDetailedDataLink"], months
    return None, None


def read_std(sym, qe, link, tag="adjs"):
    # ⚠️ the cache key is (sym, qe, tag): the audited ANNUAL and the Q4 page share a qe of 31-Mar,
    # so they MUST NOT share a tag or the second fetch silently re-reads the first page's HTML.
    try:
        html, meta, rows = OWN.fetch(link, sym, qe, tag)
    except Exception as ex:
        return None, f"fetch:{type(ex).__name__}"
    time.sleep(0.6)
    bad = OWN.validate_page(html, meta, sym, qe, False)
    if bad:
        return None, bad
    pat, src, _ = OWN.owners_of(rows)
    if pat is None:
        return None, src
    eg, note = OWN.eps_gate(pat, rows)
    return (pat, eg, note), "ok"


def main():
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    old = json.load(open(OWN.OLD_READS))
    json.load(open(OWN.INV))
    fund = json.load(open(OWN.DOCS))
    work = [
        (k.split("|")[0], int(k.split("|")[1]), v)
        for k, v in sorted(old.items())
        if "S'-mismatch" in (v.get("skip") or "")
    ]
    if only:
        work = [w for w in work if w[0] in only]
    print("adjudicating %d S'-mismatch refusals\n" % len(work), flush=True)

    out = {}
    for sym, qe, rec in work:
        stored = {r[0]: r[1] for r in fund.get(sym, [])}
        fy = OWN.fy_of(qe)
        quarters = [(fy - 1) * 10000 + 630, (fy - 1) * 10000 + 930, (fy - 1) * 10000 + 1231, fy * 10000 + 331]
        links = std_pages(sym, (fy - 1) * 10000 + 401, fy * 10000 + 331)
        print("=" * 100)
        print("%-12s %d  (FY%d)  stored_std=%s" % (sym, qe, fy, stored.get(qe)))

        page, _verdicts = {}, {}
        for q in quarters:
            if q not in links:
                print("   %d  no std page listed" % q)
                continue
            got, why = read_std(sym, q, links[q])
            if got is None:
                print("   %d  std page unusable: %s" % (q, why))
                continue
            pat, eg, note = got
            page[q] = pat
            st = stored.get(q)
            print(
                "   %d  page=%-11.2f stored=%-11s  eps=%s %s"
                % (
                    q,
                    pat,
                    f"{st:.2f}" if st is not None else None,
                    {True: "PASS", False: "FAIL", None: "n/a"}[eg],
                    note,
                )
            )

        # cheap tell 1 -- does the disputed page value belong to a NEIGHBOURING quarter?
        mis = None
        if qe in page:
            for q, v in sorted(stored.items()):
                if v is None or q == qe:
                    continue
                if abs(q // 10000 - qe // 10000) <= 1 and abs(page[qe] - v) <= max(0.05, abs(v) * 0.005):
                    mis = q
                    break
        # the §45 test itself
        annlink, months = std_annual_link(sym, fy)
        ann = None
        if annlink:
            got, why = read_std(sym, fy * 10000 + 331, annlink, tag="adja")
            if got is None:
                print(f"   audited std annual unusable: {why}")
            else:
                ann = got[0]
                print("   audited std annual (%d-month span) = %.2f" % (months, ann))
        else:
            print("   no 12-month standalone annual row listed for FY%d" % fy)
        have_page = all(q in page for q in quarters)
        have_stored = all(stored.get(q) is not None for q in quarters)
        psum = sum(page[q] for q in quarters) if have_page else None
        ssum = sum(stored[q] for q in quarters) if have_stored else None

        def hit(total):
            return total is not None and ann is not None and abs(total - ann) <= max(FY_ABS, abs(ann) * FY_REL)

        verdict = "inconclusive"
        if mis is not None:
            verdict = "BAD-PAGE(period mis-map: page value == stored %d)" % mis
        elif ann is None:
            verdict = "inconclusive(no audited std annual)"
        elif hit(psum) and not hit(ssum):
            verdict = "BAD-STORED(archive quarters tile the audited annual, ours do not)"
        elif hit(ssum) and not hit(psum):
            verdict = "BAD-PAGE(our quarters tile the audited annual, the archive's do not)"
        elif hit(psum) and hit(ssum):
            verdict = "inconclusive(both tile within tolerance)"
        else:
            verdict = "REFUSE(neither series tiles the audited annual)"
        print(
            "   annual(std)={} | archive qtr sum={} | stored qtr sum={}".format(
                f"{ann:.2f}" if ann is not None else None,
                f"{psum:.2f}" if psum is not None else None,
                f"{ssum:.2f}" if ssum is not None else None,
            )
        )
        print(f"   -> {verdict}\n")
        # How much of the FISCAL YEAR does the archive family reproduce exactly? GATE S' asks that
        # question of one quarter; asking it of the whole year separates "this filer's pages are the
        # wrong documents" (GITANJALI: 0 of 4 exact) from "one quarter was later revised"
        # (BLISSGVS/NOIDATOLL: 3 of 4 exact to the paisa).
        exact = sum(
            1 for q in quarters if q in page and stored.get(q) is not None and q != qe and OWN.near(page[q], stored[q])
        )
        rel = None
        if qe in page and stored.get(qe):
            rel = abs(page[qe] - stored[qe]) / abs(stored[qe])
        print(
            "   sibling quarters of FY%d reproduced exactly by the archive: %d of 3 | "
            "disputed quarter off by %s" % (fy, exact, "%.2f%%" % (rel * 100) if rel is not None else "n/a")
        )
        out["%s|%d" % (sym, qe)] = {
            "fy": fy,
            "stored_std": stored.get(qe),
            "std_page": page.get(qe),
            "audited_std_annual": ann,
            "archive_qtr_sum": psum,
            "stored_qtr_sum": ssum,
            "page_matches_stored_quarter": mis,
            "verdict": verdict,
            "sibling_quarters_exact": exact,
            "disputed_rel_miss": rel,
            "stored_tiles_annual": hit(ssum),
            "archive_tiles_annual": hit(psum),
            "con_candidate": rec.get("con"),
        }
    json.dump(out, open(OUT, "w"), indent=1, sort_keys=True)
    print(f"-> {os.path.basename(OUT)}")


if __name__ == "__main__":
    main()
