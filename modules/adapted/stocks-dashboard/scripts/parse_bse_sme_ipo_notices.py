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
"""Parse BSE Index Services notices into BSE SME IPO add/drop events  (runbook §195).

INPUT   ~/stocks-cache/bse_index_notices/<notice_no>.pdf  (scripts/fetch_bse_index_notices.py) + list.json
OUTPUT  {"events":[{notice, notice_date, action: add|drop, code, eff}], "unparsed":[...]}  (stdout / --out FILE)

Layouts handled (measured on the cached PDFs):
  2013-2016  table rows  "BSE SME IPO | <excl code+name | - NO EXCLUSION -> | <incl code+name | - NO INCLUSION -> | FFF | date"
             one row per line, index name at the start of the row, dates like 15-Jan- 2013 / 08/Feb/2013 / 05/APR/2013
  2017→      blocks  "INDEX ADD" / "DROP" headings, an index-name line ("S&P BSE SME IPO" / "BSE SME IPO") followed by
             code lines until the next index name; the effective date is the row's "Month DD, YYYY" or the notice's
             "Effective at the open of <Weekday>, <Month> <DD>, <YYYY>".
  mid-2024→  some reconstitutions carry only a count table ("BSE SME IPO Index 0 4") and put names in an Excel file
             that is NOT in the PDF → reported under "count_only" so the builder falls back to the rule for those drops.
Anything with an SME IPO mention the parser cannot turn into events is listed under "unparsed" — never dropped silently.
"""
import datetime
import json
import os
import re
import sys

import pypdf

CACHE = os.path.expanduser("~/stocks-cache/bse_index_notices")
MON = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
CODE = re.compile(r"(?<!\d)(5\d{5})(?!\d)")
SME_NAME = re.compile(r"(?i)\bSME\s*IPO\b")
OTHER_IDX = re.compile(
    r"(?i)^\W*(?:S&P\s+)?BSE\b(?!\s+SME)|^\W*S&P BSE|^\W*\?\s*S&P|SENSEX|BSE[- ]?\d{2,3}\b|small[- ]?cap|mid[- ]?cap|BSE IPO\b"
)
D1 = re.compile(
    r"(?i)\b(\d{1,2})\s*[-/ ]\s*([A-Za-z]{3,9})\s*[-/ ,]\s*(\d{4})\b"
)  # 15-Jan- 2013, 08/Feb/2013
D2 = re.compile(
    r"(?i)\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})\s*,?\s*(\d{4})"
)
OPEN = re.compile(
    r"(?i)(?:effective|w\.?e\.?f\.?)[^.]{0,60}?(?:open of\s+)?(?:[A-Za-z]+\s*,\s*)?"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\s*,?\s*\d{4}"
    r"|\d{1,2}\s*[-/ ]\s*[A-Za-z]{3,9}\s*[-/ ,]\s*\d{4})"
)


def text_of(no):
    t = "\n".join(
        (p.extract_text() or "") for p in pypdf.PdfReader(os.path.join(CACHE, no + ".pdf")).pages
    )
    return re.sub(
        r"(?i)SME\s*\n\s*IPO", "SME IPO", t
    )  # 2026 layout wraps "BSE SME" / "IPO" (20260410-28)


def to_date(s):
    m = D2.search(s)
    if m:
        return datetime.date(
            int(m.group(3)), MON[m.group(1)[:3].lower()], int(m.group(2))
        ).isoformat()
    m = D1.search(s)
    if m and m.group(2)[:3].lower() in MON:
        return datetime.date(
            int(m.group(3)), MON[m.group(2)[:3].lower()], int(m.group(1))
        ).isoformat()
    return None


def body(t):
    i = t.find("Content")
    t = t[i + 7 :] if i >= 0 else t
    for stop in (
        "About ASIA INDEX",
        "About BSE INDEX",
        "About BSE",
        "Change in constituents is made",
        "For more information",
    ):
        j = t.find(stop)
        if j > 0:
            t = t[:j]
    return t


OPEN_OF = re.compile(
    r"(?i)open\s+of\s+(?:[A-Za-z]+\s*,\s*)?((?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2}\s*,?\s*\d{4}|\d{1,2}\s*[-/ ]\s*[A-Za-z]{3,9}\s*[-/ ,]\s*\d{4})"
)
PLACE = re.compile(r"(?i)^\s*(?:--|—|–|-\s+-|-\s*NO\s+(?:EXCLUSION|INCLUSION)\s*-)")
ACT = re.compile(r"(?i)\b(exclusions?|drops?|deletions?|inclusions?|adds?|additions?)\b")


def _act(word):
    return "drop" if word.lower()[:2] in ("ex", "dr", "de") else "add"


def parse(no, t, subject=""):
    """-> (events, flags). Reads each table by its HEADER: the column words in order (Exclusion/Drop … Inclusion/Add)
    decide which slot a code sits in; '--' / '- NO EXCLUSION -' mark an empty slot. A row's date is on the row, on the
    next line (wrapped names), or the table's 'effective at the open of' sentence."""
    b = body(t)
    lines = [l.strip() for l in b.split("\n") if l.strip()]
    ev, flags = [], []
    flat = " ".join(lines)
    m = OPEN_OF.search(flat) or OPEN.search(flat)
    notice_eff = to_date(m.group(1)) if m else None
    subj_act = None
    if re.search(r"(?i)exclusion|deletion|drop", subject or "") and not re.search(
        r"(?i)inclusion|addition|add\b", subject or ""
    ):
        subj_act = "drop"
    elif re.search(r"(?i)inclusion|addition|\badd", subject or "") and not re.search(
        r"(?i)exclusion|deletion|drop", subject or ""
    ):
        subj_act = "add"
    cols = None  # e.g. ["drop","add"] / ["add"] from the latest header line
    idx = None
    para_eff = None
    row_eff = None
    for n, l in enumerate(lines):
        win = " ".join(lines[max(0, n - 3) : n + 1])
        mo = OPEN_OF.search(win)
        if mo and re.search(r"(?i)open\s+of", l + " " + (lines[n - 1] if n else "")):
            para_eff = to_date(mo.group(1))
            row_eff = None
        if re.search(
            r"(?i)exchange\s+ticker\s*[-–:]|notice\s*no|being listed|is listed|new listing|necessitates|will be migrated|has completed|is excluded|excluded from|retain",
            l,
        ) and not re.match(r"(?i)^\W*(?:S&P\s+)?BSE\s+SME\s+IPO\b\s+5\d{5}", l):
            continue  # narrative sentence: its code is not a table row
        has_code = bool(CODE.search(l))
        # header line: column words, no code
        if not has_code:
            words = list(ACT.findall(l))
            only_words = re.fullmatch(
                r"(?i)[\s·•:]*(?:(?:exclusions?|drops?|deletions?|inclusions?|adds?|additions?)[\s:]*)+",
                l,
            )
            if (
                words
                and (
                    only_words
                    or re.search(
                        r"(?i)\b(INDICES|INDEX|CODE|EFFECTIVE|^DROPS?\b|^ADDS?\b|^Drop\b)", l
                    )
                )
                and len(l) < 80
            ):
                c = []
                for w in words:
                    a = _act(w)
                    if not c or c[-1] != a:
                        c.append(a)
                cols = c
                row_eff = None
                if re.search(r"\bDROPS\b.*\bADDS\b", l.upper()) and not SME_NAME.search(l):
                    cols = ["drop", "add"]
        if SME_NAME.search(l) and not re.search(
            r"(?i)announces|results for|reconstitution|notice|listed|platform|criteria|methodology|index is|please",
            l,
        ):
            idx = "sme"
            mc = re.search(r"(?i)SME\s*IPO(?:\s*Index)?\s+(\d+)\s+(\d+)\s*$", l)
            if mc:
                flags.append(f"count_only adds={mc.group(1)} drops={mc.group(2)}")
                idx = None
                continue
        elif OTHER_IDX.search(l) and not SME_NAME.search(l):
            idx = "other"
        if not has_code or idx != "sme":
            continue
        codes = CODE.findall(l)
        rest = re.sub(r"(?i)^\W*(?:S&P\s+)?BSE\s+SME\s+IPO(?:\s+Index)?", "", l).strip()
        eff = to_date(l)
        if not eff and n + 1 < len(lines) and not CODE.search(lines[n + 1]):
            eff = to_date(lines[n + 1])
        eff = eff or row_eff or para_eff or notice_eff
        row_eff = eff
        act_cols = cols or ([subj_act] if subj_act else None)
        if not act_cols:
            flags.append("code-without-action: " + l[:120])
            continue
        if len(act_cols) == 1:
            ev += [(act_cols[0], c, eff) for c in codes]
        elif len(codes) >= 2:
            ev += [(act_cols[0], codes[0], eff), (act_cols[1], codes[1], eff)]
        elif PLACE.match(rest):
            ev.append((act_cols[1], codes[0], eff))
        elif re.search(
            r"(?i)(--|—|-\s+-|no\s+inclusion|no\s+exclusion)", rest[rest.find(codes[0]) + 6 :]
        ):
            ev.append((act_cols[0], codes[0], eff))
        else:
            flags.append("row-unclear: " + l[:120])
    return ev, flags


NARR = re.compile(
    r"(?i)ticker\s*[-–:]?\s*(5\d{5})\s*\)?[^.]{0,200}?SME\s+platform[^.]{0,200}?\.\s*"
    r"Effective\s+at\s+the\s+open\s+of\s+(?:[A-Za-z]+\s*,\s*)?"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\s*,?\s*\d{4})"
    r"[^.]{0,80}?(?:added|included)"
)


NARR_DROP = re.compile(
    r"(?i)ticker\s*[-–:]?\s*(5\d{5})\s*\)?[^.]{0,300}?\.\s*Effective\s+at\s+the\s+open\s+of\s+(?:[A-Za-z]+\s*,\s*)?"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}\s*,?\s*\d{4})"
    r"[^.]{0,120}?dropped\s+from[^.]{0,40}?SME\s*IPO"
)


def narrative_drops(t):
    """'… (Exchange Ticker- 536128) will be migrated … Effective at the open of Monday, January 18, 2016 … this stock will be
    dropped from S&P BSE SME IPO index' (20160113-5) — a drop announced only in a sentence."""
    flat = re.sub(r"\s+", " ", body(t))
    return [(m.group(1), to_date(m.group(2))) for m in NARR_DROP.finditer(flat)]


def narrative_adds(t):
    """SME-platform listings announced in the notice's own sentences: (code, eff). A second reader for the table
    (measured: 20241219-20's table extracts as ', 2024' only, while its sentence names Yash Highvoltage 544310 +
    'open of Friday, December 20, 2024')."""
    flat = re.sub(r"\s+", " ", body(t))
    return [(m.group(1), to_date(m.group(2))) for m in NARR.finditer(flat)]


def main():
    L = {r["notice_no"]: r for r in json.load(open(os.path.join(CACHE, "list.json")))["all"]}
    lo = sys.argv[sys.argv.index("--from") + 1] if "--from" in sys.argv else "0000"
    hi = sys.argv[sys.argv.index("--to") + 1] if "--to" in sys.argv else "9999"
    out = {"events": [], "unparsed": [], "count_only": []}
    for f in sorted(os.listdir(CACHE)):
        if not f.endswith(".pdf"):
            continue
        no = f[:-4]
        r = L.get(no) or {}
        nd = (r.get("dt_tm") or "")[:10]
        if not (lo <= nd <= hi):
            continue
        t = text_of(no)
        if not SME_NAME.search(t) and not re.search(r"(?i)SME\s+platform", t):
            continue
        ev, flags = parse(no, t, r.get("Subject") or "")
        tab = {c: e for a, c, e in ev if a == "add"}
        for c, e in narrative_adds(t):
            if c not in tab:
                ev.append(("add", c, e))
                flags.append(f"narrative-only add {c} {e}")
            elif tab[c] != e:
                # the sentence's "effective at the open of" is the index date; a table row can carry the LISTING date
                # (20250716-16 ASSTON: table 16-Jul = listing day, sentence 17-Jul) — the sentence wins, flagged
                ev = [x for x in ev if not (x[0] == "add" and x[1] == c)] + [("add", c, e)]
                flags.append(
                    f"table/narrative date disagree {c} table={tab[c]} sentence={e} (sentence used)"
                )
        tabd = {c for a, c, e in ev if a == "drop"}
        for c, e in narrative_drops(t):
            if c not in tabd:
                ev.append(("drop", c, e))
                flags.append(f"narrative-only drop {c} {e}")
        for a, c, eff in ev:
            out["events"].append(
                {"notice": no, "notice_date": nd, "action": a, "code": c, "eff": eff}
            )
        for fl in flags:
            (out["count_only"] if fl.startswith("count_only") else out["unparsed"]).append(
                {"notice": no, "notice_date": nd, "subject": r.get("Subject"), "why": fl}
            )
        if not ev and not flags and re.search(r"(?i)SME\s*IPO", body(t)) and CODE.search(body(t)):
            out["unparsed"].append(
                {"notice": no, "notice_date": nd, "subject": r.get("Subject"), "why": "no events"}
            )
    dst = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    s = json.dumps(out, indent=1)
    if dst:
        open(dst, "w").write(s)
    print(
        "events %d (add %d, drop %d), unparsed %d, count_only %d"
        % (
            len(out["events"]),
            sum(e["action"] == "add" for e in out["events"]),
            sum(e["action"] == "drop" for e in out["events"]),
            len(out["unparsed"]),
            len(out["count_only"]),
        )
    )


if __name__ == "__main__":
    main()
