# -*- coding: utf-8 -*-
"""Read the TRUE consolidated figure for every cell detect_con_copy flagged, from the filing.

These are cells where our con slot holds a copy of the standalone value. Screener says the real
consolidated figure differs, so it exists -- this goes and gets it from the company's own document
rather than copying screener's rounded number.

THE ANCHOR PROBLEM, and why this reader is different. Everywhere else in the campaign the column is
identified by matching our stored value for that quarter (§58). Here that is impossible: the stored
con value IS the defect. So the anchor is inverted --

    screener's con figure for the TARGET quarter locates the column,
    and a DIFFERENT column on the same rows must reproduce screener's con figure for ANOTHER
    quarter at the same scale.

One number can match by coincidence at three scales; two columns of the same row set matching two
different quarters cannot. Screener is the search key, never the value written (§60e) -- what lands
in the dataset is the filing's own figure, at filing precision.

PDF NUMBER SPLITTING. Extraction often breaks "7,796.69" into "7796" and "69" as separate tokens,
which is why an earlier attempt at TIMKEN found nothing at all. Adjacent numeric tokens closer than
~4.5pt are re-joined with a decimal point before anything is parsed.

Only pages whose own wording says the target basis are read (glyph-tolerant, and the opposite basis
excluded), so the wrong statement cannot be mistaken for the answer.

BOTH DIRECTIONS, because the flag's direction is not the defect's direction (2026-08-09). Of the
cells detect_con_copy flags, some have the copy in the CON slot (fix con) and some in the STD slot
-- the MIRROR defect, where our con value is already right and the standalone one is the copy. The
two are told apart with no PDF at all: our stored value matches screener's con => mirror; it matches
screener's std => con-copy (§59b). Running the con reader on a mirror cell can only ever return "the
value we already store", and on 4 of them it returned nothing at all, because the figure it needs is
on the STANDALONE page it is filtered never to open. Hence `--basis`:

    --basis con   (default)  scan con pages, anchor on screener's con   -> repairs the CON slot
    --basis std              scan std pages, anchor on screener's std   -> repairs the STD slot

  python -X utf8 scripts/fill2020_tools/read_con_copies.py [--limit N]
      [--basis con|std] [--flagged PATH] [--out PATH]
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)
import universal_read as U                                        # noqa: E402
import date_columns as DC                                         # noqa: E402
import screener_fetch as SF                                       # noqa: E402
import build_targets as BT                                        # noqa: E402
import geom_read as GR                                            # noqa: E402
import fitz                                                       # noqa: E402

NUM = re.compile(r"^\(?-?[\d,]+\.?\d*\)?$")
REV_RE = re.compile(r"revenue\s+fr[o0]m\s+[o0]pera|t[o0]tal\s+inc[o0]me\s+fr[o0]m\s+[o0]pera|"
                    r"revenue\s+fr[o0]m\s+c[o0]ntracts|inc[o0]me\s+fr[o0]m\s+[o0]pera|net\s+sales", re.I)
PAT_RE = re.compile(r"net\s+pr[o0][fl]i?[lt]\s+a[fl]ter\s+tax|pr[o0][fl]i?[lt]\s+a[fl]ter\s+tax|"
                    r"[o0]wners?\s+[o0]f\s+the\s+(c[o0]mpan|parent)|"
                    r"pr[o0][fl]i?[lt](?:\s*/\s*\(?l[o0]ss\)?)?\s+f[o0]r\s+the\s+(peri[o0]d|quarter|year)", re.I)
# The owners-attributable line, which is the one we store for consolidated PAT (§58). Kept separate
# from PAT_RE because PAT_RE must still MATCH the total row -- that is the row screener's figure
# locates the column on; the owners row is what we then read.
OWNERS_RE = re.compile(r"[o0]wners?\s+[o0]f\s+the\s+(c[o0]mpan|parent)|"
                       r"attributable\s+t[o0]\s+.{0,24}(?:[o0]wners|equity\s+h[o0]lders)|"
                       r"min[o0]rity\s+interest\s+and\s+share\s+[o0]f\s+pr[o0][fl]i?[lt]", re.I)
OUT = "/tmp/con_copy_reads.json"


def _val(w):
    w = w.strip()
    neg = w.startswith("(")
    w = w.strip("()").replace(",", "")
    if not w or w in ("-", "."):
        return None
    try:
        return -float(w) if neg else float(w)
    except ValueError:
        return None


def page_rows(page, ytol=3.0):
    """[(label, [(x_right, value)])] with split numbers re-joined.

    Rows come from GR.band_rows, which clusters baselines instead of bucketing them -- bucketing
    tore TIMKEN's consolidated PAT row in half and hid the column the read needed. See geom_read.
    """
    out = []
    for _y, row in GR.band_rows(page.get_text("words"), ytol):
        t = sorted(row, key=lambda z: z[0])
        merged, i = [], 0
        while i < len(t):
            x0, x1, w = t[i]
            # "7796" + "69" printed 4pt apart is one number, not two
            if NUM.match(w) and "." not in w and i + 1 < len(t) \
               and NUM.match(t[i + 1][2]) and t[i + 1][0] - x1 < 4.5:
                w = w + "." + t[i + 1][2]
                x1 = t[i + 1][1]
                i += 1
            merged.append((x0, x1, w))
            i += 1
        lab = " ".join(w for _a, _b, w in merged if _val(w) is None).strip()
        nums = [(x1, _val(w)) for _a, x1, w in merged if _val(w) is not None]
        if nums:
            out.append((lab, nums))
    return out


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def main():
    limit = int(_arg("--limit", 10 ** 9))
    basis = _arg("--basis", "con")
    if basis not in ("con", "std"):
        sys.exit("--basis must be con or std")
    out_p = _arg("--out", OUT if basis == "con" else OUT.replace(".json", "_std.json"))
    flagged = json.load(open(_arg("--flagged", "/tmp/con_copy2.json")))
    scrips = BT.scrip_map()
    done = json.load(open(out_p)) if os.path.exists(out_p) else {}

    # group by company so each screener series is fetched once
    by_sym = {}
    for b in flagged:
        by_sym.setdefault(b["sym"], []).append(b)

    n = 0
    for sym, cells in sorted(by_sym.items()):
        if n >= limit:
            break
        scrip = scrips.get(sym.upper())
        if not scrip:
            continue
        try:
            scon = SF.quarters(sym, con=(basis == "con"))
        except Exception:
            continue
        lab_r = next((L for L in ("Sales", "Revenue") if any(L in r for r in scon.values())), None)
        # every screener con quarter, as {qe: (rev, pat)} -- the confirmation pool
        pool = {}
        for dk, row in (scon or {}).items():
            pool[int(dk.replace("-", ""))] = (row.get(lab_r), row.get("Net Profit"))

        for b in cells:
            key = "%s|%d|%s" % (sym, b["qe"], b["field"])
            if key in done:
                continue
            n += 1
            want = b["screener_con"] if basis == "con" else b["screener_std"]
            is_rev = b["field"] == "revC"
            got = None
            # the quarter's own filing, then the next one, then the next year's
            for tag, a, bb in U.windows(b["qe"], None):
                fils, sess, err = U.filings(scrip, a, bb)
                for _d, url, _s2 in (fils or [])[:4]:
                    raw, _ = U.BRG.cached_pdf(sess, url)
                    if not raw:
                        continue
                    try:
                        doc = fitz.open(stream=raw, filetype="pdf")
                    except Exception:
                        continue
                    for pi in range(len(doc)):
                        pg = doc[pi]
                        # page_shows, not `== basis`: a side-by-side STANDALONE|CONSOLIDATED
                        # statement names both bases, so it used to be skipped entirely (§71k).
                        # Safe here because the column is anchored -- the value must match
                        # screener's figure for THIS basis and a second column on the same rows
                        # must reproduce another quarter, which the other basis' block will not do.
                        if len(pg.get_text().strip()) < 400 or not DC.page_shows(pg, basis):
                            continue
                        rows = page_rows(pg)
                        tgt = [r for r in rows if (REV_RE if is_rev else PAT_RE).search(r[0])]
                        for lab, nums in tgt:
                            for x, v in nums:
                                for sc in (1.0, 10.0, 100.0):
                                    if abs(v / sc - want) > max(0.6, abs(want) * 0.012):
                                        continue
                                    # CONFIRM: another column, another screener con quarter
                                    conf = None
                                    for q2, (r2, p2) in pool.items():
                                        t2 = r2 if is_rev else p2
                                        if q2 == b["qe"] or t2 is None:
                                            continue
                                        for x2, w in nums:
                                            if abs(x2 - x) > 14 and \
                                               abs(w / sc - t2) <= max(0.6, abs(t2) * 0.012):
                                                conf = "col x=%.0f == screener %s %s for %d" % (x2, basis, t2, q2)
                                                break
                                        if conf:
                                            break
                                    if conf:
                                        val, lab2 = v, lab
                                        # ★ OWNERS, NOT TOTAL (§58, added 2026-08-09). screener
                                        # quotes TOTAL consolidated PAT; we store the
                                        # owners-attributable figure. Anchoring on screener
                                        # therefore lands on the TOTAL row, and writing it is a
                                        # basis regression -- TATACOFFEE 2022-12-31 was "healed"
                                        # from a correct 26.63 (owners) to 38.40 (total = owners
                                        # 26.63 + NCI 11.77). The column is right; the ROW was
                                        # wrong. So keep the column and re-read it off the owners
                                        # row when the page has one.
                                        if basis == "con" and not is_rev:
                                            ow = next((r for r in rows if OWNERS_RE.search(r[0])
                                                       and GR.at_column(r[1], x) is not None), None)
                                            if ow:
                                                val, lab2 = GR.at_column(ow[1], x), ow[0]
                                        got = {"value": round(val / sc, 2), "scale": sc, "page": pi,
                                               "row": lab2[:44], "confirm": conf, "window": tag,
                                               "basis": basis, "doc": url.split("/")[-1][:30],
                                               "screener": want, "was": b["our"]}
                                        if lab2 is not lab:
                                            got["owners_row"] = True
                                            got["total_row_value"] = round(v / sc, 2)
                                        break
                                if got:
                                    break
                            if got:
                                break
                        if got:
                            break
                    doc.close()
                    if got:
                        break
                if got:
                    break
                time.sleep(0.3)
            done[key] = got or {"value": None, "basis": basis,
                                "why": "no confirmed %s column found" % basis,
                                "screener": want, "was": b["our"]}
            json.dump(done, open(out_p, "w"), indent=1)
            print("  %-26s %s" % (key, ("= %-10s (was %s) %s" % (got["value"], b["our"], got["confirm"][:40]))
                                  if got else "NOT FOUND"))

    ok = sum(1 for v in done.values() if v.get("value") is not None)
    print("\nread %d of %d flagged cells (basis=%s) -> %s" % (ok, len(done), basis, out_p))


if __name__ == "__main__":
    main()
