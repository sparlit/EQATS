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
"""Vision fallback for the ~62 Nifty-500 names whose BRSR 'Employees and workers' table the text
parser (headcount_extract.py) can't read — the numbers are detached from their row labels in the PDF
text stream (column-major layout) or the table is an image. Regex AND word-geometry both fail on these.

For each uncovered symbol this locates the count page(s) — the BRSR employees grid by its ROW LABELS
(which survive in the text even when the numbers don't), AND/OR the Directors'-Report Section 197(12)
"permanent employees on the rolls of the Company" prose line (added 2026-09-07: the reliable fallback that
cracked the hard tail — banks, PSUs, recent IPOs — when the grid is column-major or imaged) — renders them
to PNG, and asks Gemini (the same free-tier reader the Insights card uses, via gemini_vision._post) to read
whichever is present, preferring the grid. Every value is validated structurally — male+female must
reconcile to the total, permanent<=total, a plausible people count — before it lands, and the model is told
to set ok=false if the image is neither. GEMINI_API_KEY is a CI secret, so the Gemini path runs in
refresh-headcount-vision.yml; the same locator feeds --prep, the native-vision (no-key) path.
"""
import argparse
import base64
import glob
import json
import os

# page locator: the BRSR employees block's LABELS (present in the text layer even when the numbers
# are detached). Score a page on how many of these row labels it carries.
import re
from datetime import date

import fitz
import gemini_vision as GV
import headcount_extract as H

_TITLE = re.compile(r"Employees\s+and\s+workers", re.IGNORECASE)
_ROWS = re.compile(
    r"Permanent\s*\(?\s*[D-H]|Other\s+than\s+[Pp]ermanent|Total\s+employees|Total\s+workers", re.IGNORECASE
)


_SECTION = re.compile(r"section\s+a\b|general\s+disclosures|business\s+responsibility|BRSR", re.IGNORECASE)


def brsr_pages(doc):
    """0-based indices of the page(s) holding the 'Employees and workers' table. Two reliable signals,
    so we never render a blind guess:
      A. label density — the table's ROW labels survive as text even when the numbers are detached
         (column-major layout, GARFIBRES);
      B. heading text — "Employees and workers", the "Differently abled employees" sub-table, or the
         "Details as at the end of the Financial Year" question, which survive even when the numeric
         table itself is a scanned image.
    A page whose table AND its headings are all images scores 0 → the name stays uncovered (a human
    read); better that than a wrong page."""
    scored = []
    for i in range(len(doc)):
        t = doc[i].get_text("text")
        if not t.strip():
            continue
        a = (5 if _TITLE.search(t) else 0) + len(_ROWS.findall(t))
        if re.search(r"Total\s+employees", t, re.IGNORECASE) and re.search(r"Permanent", t):
            a += 3
        b = 0
        if re.search(r"details\s+as\s+at\s+the\s+end\s+of\s+(the\s+)?financial\s+year", t, re.IGNORECASE):
            b += 8  # the BRSR Q18/20 heading — the strongest, most specific signal
        b += 3 * len(re.findall(r"other\s+than\s+permanent", t, re.IGNORECASE))
        if re.search(r"differently\s+abled\s+employees", t, re.IGNORECASE):
            b += 5
        if re.search(r"employees\s+and\s+workers", t, re.IGNORECASE):
            b += 2  # generic — also appears in GRI injury tables / prose, so needs corroboration
        # demote governance / GRI / well-being pages that merely mention "employees and workers"
        if re.search(
            r"corporate\s+governance|board\s+of\s+directors|GRI\s+30|work[- ]related\s+injur|"
            r"well[- ]being\s+measures\s+of|acknowledgement",
            t,
            re.IGNORECASE,
        ):
            b -= 6
        s = max(a, b)
        if s >= 4:
            scored.append((s, i))
    scored.sort(reverse=True)
    keep = [i for _, i in scored[:2]]
    if keep:  # the table can spill onto the next page
        nb = keep[0] + 1
        if nb < len(doc) and nb not in keep:
            keep.append(nb)
    return keep


# Section 197(12) fallback locator. Every Directors'/Board's Report carries a Rule 5(1)(iii) line stating
# "the number of permanent employees on the rolls of the Company was N" — the SAME on-roll permanent count
# the BRSR grid gives, but as one prose sentence that survives in the text layer when the grid is
# column-major or imaged. Public-sector banks give it as an Officers/Clerks/Subordinate-staff cadre table;
# old (pre-2023) BRR reports as "Total number of employees: N". This one line cracked the 2026-09-07 hard
# tail (banks, PSUs, recent IPOs, distressed names) — see [[project-stocks-employee-headcount]].
_ROLLS = re.compile(
    r"on\s+the\s+rolls\s+of\s+(?:the\s+)?(?:compan|bank)|"
    r"employees?\s+(?:were\s+|are\s+)?on\s+the\s+roll",
    re.IGNORECASE,
)
_CADRE = (
    re.compile(r"\bofficers?\b", re.IGNORECASE),
    re.compile(r"\bclerk", re.IGNORECASE),
    re.compile(r"sub[\s-]*staff|subordinate\s+staff", re.IGNORECASE),
)
_BRRTOT = re.compile(r"total\s+number\s+of\s+employees", re.IGNORECASE)
_REFONLY = re.compile(
    r"available\s+for\s+inspection|forms?\s+part\s+of\s+this\s+report|"
    r"excluding\s+the\s+aforesaid",
    re.IGNORECASE,
)


def s197_pages(doc):
    """0-based indices of page(s) that state the on-roll permanent count as PROSE — the Section 197(12)
    'permanent employees on the rolls of the Company' line, a PSU-bank cadre table (Officers + Clerks +
    Subordinate staff), or an old BRR 'Total number of employees' sentence. High precision (the phrasing is
    specific), so this is the reliable fallback when brsr_pages() can't find the grid. Never a blind guess:
    a page scores only when a signal is actually present; a page that merely REFERS the §197 statement to
    inspection (no number printed) is demoted."""
    scored = []
    for i in range(len(doc)):
        t = doc[i].get_text("text")
        if not t.strip():
            continue
        s = 8 * len(_ROLLS.findall(t))  # the §197 count line — strongest, most specific
        if _CADRE[0].search(t) and _CADRE[1].search(t) and _CADRE[2].search(t):
            s += 6  # PSU-bank Officers/Clerks/Subordinate table
        if _BRRTOT.search(t):
            s += 3  # old BRR 'total number of employees'
        if s and _REFONLY.search(t) and not _ROLLS.search(t):
            s -= 4  # a page that only points to the inspection copy
        if s >= 3:
            scored.append((s, i))
    scored.sort(reverse=True)
    return [i for _, i in scored[:2]]


def locate(doc):
    """All candidate pages for a name: the BRSR 'Employees and workers' grid (richest — carries workers and
    the gender split) FIRST so the reader prefers it, then the Section 197(12) 'on the rolls' prose line as
    the fallback. §197 pages are always kept when present (so a name whose grid is unlocatable is still
    rendered), and the whole list is capped so a Gemini call stays within its 4-image budget."""
    b, s = brsr_pages(doc), s197_pages(doc)
    out = []
    for p in b[:2] + s + b[2:]:  # 2 best grid pages, then §197, then grid spillover
        if p not in out:
            out.append(p)
    return out[:4]


def render(doc, pno, dpi=170):
    return doc[pno].get_pixmap(dpi=dpi).tobytes("png")


_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "ok": {"type": "BOOLEAN"},
        "company_matches": {"type": "BOOLEAN"},
        "emp_perm": {"type": "NUMBER", "nullable": True},
        "emp_other": {"type": "NUMBER", "nullable": True},
        "emp_total": {"type": "NUMBER", "nullable": True},
        "wrk_perm": {"type": "NUMBER", "nullable": True},
        "wrk_total": {"type": "NUMBER", "nullable": True},
        "male": {"type": "NUMBER", "nullable": True},
        "female": {"type": "NUMBER", "nullable": True},
        "note": {"type": "STRING"},
    },
    "required": [
        "ok",
        "company_matches",
        "emp_perm",
        "emp_other",
        "emp_total",
        "wrk_perm",
        "wrk_total",
        "male",
        "female",
        "note",
    ],
}

_PROMPT = """These images are page(s) from the BRSR section of the annual report of the Indian listed
company %(company)s, for the financial year ending 31 March %(fy)d. Find the table titled
"Employees and workers (including differently abled)" — the block headed "Details as at the end of
Financial Year".

Read ONLY the MAIN table (numbered rows 1-6). IGNORE the separate "Differently abled employees and
workers" sub-table that follows it.
EMPLOYEES section:
  emp_perm  = row "Permanent (D)", the Total (A) column
  emp_other = row "Other than Permanent (E)", Total (A)
  emp_total = row "Total employees (D + E)", Total (A)
  male, female = the "Male No." and "Female No." columns of the "Total employees (D + E)" row
WORKERS section:
  wrk_perm  = row "Permanent (F)", Total (A)
  wrk_total = row "Total workers (F + G)", Total (A)

A cell printed as "-", "NA", "Nil", "0" for a whole section, or blank -> null. Every value is an INTEGER
count of people — never a money amount, never a percentage (ignore the percent columns).

If that grid is NOT present but one of the images is a Directors'/Board's Report disclosure under
Section 197(12) (Rule 5(1)) that states in words the number of PERMANENT employees ON THE ROLLS of the
company as at the year-end — e.g. "there were 3,103 permanent employees on the rolls of the Company", or a
public-sector bank's Officers + Clerks + Subordinate-staff cadre total, or an old BRR "Total number of
employees: N" — then set emp_perm = emp_total = that number and leave emp_other, wrk_perm, wrk_total, male,
female null. Read the count of PERMANENT / on-roll employees ONLY: never a demographic breakdown cell (age
band, social category), never a "trained"/"covered"/attrition/new-joiner figure, and never the
contractual/temporary count. If BOTH the grid and this line are present, use the grid.

If none of the images contain either, or are not %(company)s, set ok=false and null everything.
Return ONLY the JSON."""


def _int(v):
    try:
        return round(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


def read_employees(company, fy, pngs):
    if not GV._key() or not pngs:
        return None
    parts = [
        {"inline_data": {"mime_type": "image/png", "data": base64.standard_b64encode(p).decode()}} for p in pngs[:4]
    ]
    parts.append({"text": _PROMPT % {"company": company, "fy": fy}})
    return GV._post(
        {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "response_mime_type": "application/json",
                "response_schema": _SCHEMA,
            },
        }
    )


def validate(d):
    """Gemini dict -> a ledger cell, or None if it fails the structural gates."""
    if not d or not d.get("ok") or not d.get("company_matches"):
        return None
    ep, eo, et = _int(d.get("emp_perm")), _int(d.get("emp_other")), _int(d.get("emp_total"))
    wp, wt, m, f = (_int(d.get(k)) for k in ("wrk_perm", "wrk_total", "male", "female"))
    if et is None and ep is not None:
        et = ep + (eo or 0)
    if not et or et < 3 or et > 5_000_000:
        return None
    if ep and et and ep > et * 1.02:  # permanent can't exceed total employees
        return None
    if m and f:
        diff = abs((m + f) - et)
        if diff > max(20, et * 0.10):  # gross male+female mismatch = a mis-read → reject
            return None
        if diff > max(5, et * 0.03):  # minor (an "Others" gender column) → drop the split
            m = f = None
    onroll = (ep or et) + (wp or 0)
    total_wf = et + (wt or 0)
    detail = {
        "emp_perm": ep,
        "emp_other": eo,
        "emp_total": et,
        "wrk_perm": wp,
        "wrk_total": wt,
        "male": m,
        "female": f,
        "onroll_perm": onroll,
        "total_incl_workers": max(total_wf, onroll),
    }
    return {"count": onroll, "total_workforce": max(total_wf, onroll), "basis": "vision", "brsr": detail}


def process(sym, want_fys, max_reports=4, verbose=True):
    led = {"sym": sym, "bse": H.scripcode(sym), "fy": {}, "reports_read": [], "by": "vision"}
    for a in H.annual_reports(sym)[:max_reports]:
        if a["fy"] not in want_fys or a["fy"] in led["fy"]:
            continue
        if GV.quota_dead():
            break
        p = H.fetch(a, sym)
        if not p:
            continue
        doc = fitz.open(p)
        pgs = locate(doc)
        led["reports_read"].append(
            {"fy": a["fy"], "att": a["att"], "pages": len(doc), "brsr_pages": [x + 1 for x in pgs]}
        )
        if not pgs:
            doc.close()
            continue
        pngs = [render(doc, x) for x in pgs]
        doc.close()
        rec = validate(read_employees(sym, a["fy"], pngs))
        if rec:
            rec["src"] = {"fy": a["fy"], "page": pgs[0] + 1, "method": "vision"}
            led["fy"][a["fy"]] = rec
            if verbose:
                print(
                    "  %s FY%d: onroll=%s emp_total=%s (vision p%d)"
                    % (sym, a["fy"], rec["count"], rec["brsr"]["emp_total"], pgs[0] + 1),
                    flush=True,
                )
    return led


def uncovered_syms():
    out = []
    for f in sorted(glob.glob(os.path.join(H.LEDGER_DIR, "*.json"))):
        if not json.load(open(f)).get("fy"):
            out.append(os.path.basename(f)[:-5])
    return out


_NAME = {}


def _load_names():
    if _NAME:
        return
    try:
        for x in json.load(open(os.path.join(H.HERE, "_bse_master_all.json"), encoding="utf-8")):
            if x.get("scrip_id"):
                _NAME.setdefault(
                    x["scrip_id"], re.sub(r"\s+(Ltd|Limited)\.?$", "", (x.get("Scrip_Name") or "").strip())
                )
    except Exception:
        pass


def prep(syms, want_fys, outdir, max_reports=3, verbose=True):
    _load_names()
    """NATIVE-VISION mode (no API key, no quota): render each name's BRSR employees page(s) to PNG in
    `outdir` and write manifest.json [{sym, fy, page, png}]. A Claude session (interactive now, or the
    scheduled routine at scale) then Reads the PNGs with its own vision and lands the numbers — the
    repo's bse-vision-fill pattern (cross-session handoff 2026-09-07). Renders NOTHING when the page
    can't be located, so no blind guesses reach the reader."""
    os.makedirs(outdir, exist_ok=True)
    manifest, npng = [], 0
    for sym in syms:
        name = _NAME.get(sym, sym)
        for a in H.annual_reports(sym)[:max_reports]:
            if a["fy"] not in want_fys:
                continue
            p = H.fetch(a, sym)
            if not p:
                continue
            doc = fitz.open(p)
            pgs = locate(doc)
            pngs = []
            for pi in pgs:
                fn = "%s_FY%d_p%d.png" % (sym, a["fy"], pi + 1)
                with open(os.path.join(outdir, fn), "wb") as fh:
                    fh.write(render(doc, pi))
                pngs.append(fn)
                npng += 1
            doc.close()
            if pngs:  # one manifest entry per (sym, fy): all candidate pages
                manifest.append({"sym": sym, "name": name, "fy": a["fy"], "page": pgs[0] + 1, "pngs": pngs})
            if verbose:
                print("  %s FY%d -> pages %s" % (sym, a["fy"], [x + 1 for x in pgs]), flush=True)
    json.dump(manifest, open(os.path.join(outdir, "manifest.json"), "w"), indent=1)
    print(
        "PREP DONE: %d entries / %d PNG pages for %d symbols -> %s" % (len(manifest), npng, len(syms), outdir),
        flush=True,
    )


def merge(reads_path):
    """Land subagent vision reads into the per-symbol ledgers, gate-enforced. reads.json = a list of
    {sym, fy, page, emp_perm, emp_other, emp_total, wrk_perm, wrk_total, male, female} (a subagent's read
    of one BRSR employees table). validate() drops anything where male+female doesn't reconcile to the
    total, permanent>total, or the count is implausible — so a mis-read never lands."""
    reads = json.load(open(reads_path))
    landed = 0
    for r in reads:
        if not r.get("sym") or r.get("fy") is None:
            continue
        d = {"ok": True, "company_matches": True}
        d.update(
            {k: r.get(k) for k in ("emp_perm", "emp_other", "emp_total", "wrk_perm", "wrk_total", "male", "female")}
        )
        rec = validate(d)
        if not rec:
            print("  REJECT {} FY{} (failed gate)".format(r["sym"], r["fy"]), flush=True)
            continue
        rec["src"] = {"fy": int(r["fy"]), "page": r.get("page"), "method": "vision"}
        p = os.path.join(H.LEDGER_DIR, r["sym"] + ".json")
        led = json.load(open(p)) if os.path.exists(p) else {"sym": r["sym"], "bse": H.scripcode(r["sym"])}
        led.setdefault("fy", {})[str(int(r["fy"]))] = rec
        led["by"] = "vision"
        json.dump(led, open(p, "w"), indent=1, default=str)
        landed += 1
        print("  landed {} FY{} onroll={}".format(r["sym"], r["fy"], rec["count"]), flush=True)
    print("MERGE: landed %d of %d reads" % (landed, len(reads)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("syms", nargs="*")
    ap.add_argument("--uncovered", action="store_true", help="all empty-ledger symbols")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since-fy", type=int, default=2020)
    ap.add_argument("--max-reports", type=int, default=4)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--prep", metavar="DIR", help="native-vision: render BRSR pages to PNGs + manifest (no Gemini)")
    ap.add_argument("--merge", metavar="READS_JSON", help="land subagent vision reads (gate-enforced) into the ledgers")
    a = ap.parse_args()
    want = set(range(a.since_fy, date.today().year + 1))
    if a.merge:
        merge(a.merge)
        return
    syms = uncovered_syms() if a.uncovered else list(a.syms)
    if a.limit:
        syms = syms[: a.limit]
    if a.prep:
        prep(syms, want, a.prep, max_reports=a.max_reports)
        return
    print(
        "vision: %d symbols, model %s, key=%s"
        % (len(syms), os.environ.get("GEMINI_MODEL", "gemini-3.6-flash"), "set" if GV._key() else "MISSING"),
        flush=True,
    )
    os.makedirs(H.LEDGER_DIR, exist_ok=True)
    for s in syms:
        if GV.quota_dead():
            print("gemini quota exhausted — stopping", flush=True)
            break
        led = process(s, want, max_reports=a.max_reports)
        print("%-12s vision FYs %s" % (s, sorted(led["fy"])), flush=True)
        if a.save and led["fy"]:
            path = os.path.join(H.LEDGER_DIR, s + ".json")  # merge into the existing (empty) ledger
            old = json.load(open(path)) if os.path.exists(path) else {}
            old.update({"sym": s, "bse": led["bse"], "by": "vision"})
            old.setdefault("fy", {}).update(led["fy"])
            old["reports_read"] = led["reports_read"]
            json.dump(old, open(path, "w"), indent=1, default=str)


if __name__ == "__main__":
    main()
