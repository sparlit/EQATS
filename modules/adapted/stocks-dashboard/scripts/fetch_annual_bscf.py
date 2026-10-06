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
"""ANNUAL BALANCE-SHEET / CASH-FLOW fill from the company's own BSE audited-result PDF.

WHY. ~45% of FY-end balance sheets and ~19% of full-year cash flows are absent from the
quarterly-result XBRL we parse (build_xbrl_extra) — SEBI lets a filer put the full BS/CF
only in the audited annual result's PDF, not the machine-readable XBRL. This grinds those
PDFs: for each (symbol, FY) where the slice has NO balance sheet from XBRL, fetch the FY-end
'Audited Financial Results' filing, locate the CONSOLIDATED balance-sheet + cash-flow pages,
read the line items from the PDF's text layer, and land them in scripts/annual_bscf.json.

SAFETY — the holdout gate (the whole reason this is trustworthy):
  For every symbol we ALSO parse a year we DO hold from XBRL and compare Total Assets +
  a few anchors. A filer's parse is trusted ONLY if that overlap matches to <=1%. A filer
  whose format defeats the parser fails the gate and lands NOTHING (its cells stay '—'),
  rather than writing a wrong number. So a landed cell is either XBRL-confirmed-format or
  not landed at all.

Basis: the audited result carries BOTH a standalone and a consolidated BS; we take the
CONSOLIDATED page (matching the slice's con-preferred convention), falling back to standalone
only for companies that file standalone-only, and record which.

Text-first: these filings are overwhelmingly digital PDFs (a clean text layer), so the read
is exact and free. `--vision` marks the residue (scanned PDFs / gate failures) for a later
Claude-vision pass; this pass never guesses.

Ledger scripts/annual_bscf.json = { SYM: { "QE": { "b":"c|s", <field>:val, ..., "src":"bse:<att>" } } }
fields: assets, sc, oeq, borr, blt, bst, ppe, cwip, iuad, gw, intg, invst, invprop, rec, pay, invnt,
        cfo, cfi, cff, capex, cf_tax.  v=1 marks a validate-year CASH-FLOW-ONLY cell (BS held by XBRL);
        sup=[fields] lists fields a later re-read of the SAME document added (merge 'supplement').
Resumable: one symbol at a time, checkpoints after each; --only / --limit / --redo.
Run: python -X utf8 scripts/fetch_annual_bscf.py [--only SYM,SYM] [--limit N] [--redo]
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import base64
import datetime
import gzip
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.request

import bse_headers as BH  # §181 BSE headers
import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import contextlib

from merge_annual_bscf import (  # one definition each (fetch + merge)
    cf_identity,
    slice_x,
    validate_cf_cell,
)
from merge_annual_bscf import (
    gate_ok as merge_gate,  # (ok, add_rou) — the landing gate, one definition
)

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
LEDGER = os.path.join(HERE, "annual_bscf.json")
GATE_REPORT = os.path.join(
    HERE, "annual_bscf_gate.json"
)  # TRACKED (not scripts/_*, which is gitignored) so resume persists in CI
FYS = [2025, 2024, 2023, 2022, 2021, 2020]  # FY-ends to fill, newest first
UA = BH.UA  # honest BSE identity (§181) -- no browser impersonation

# ---- queue-advance cooldowns (so the --limit walk moves past attempted-but-unfilled symbols) --
TTRY_COOLDOWN_DAYS = 7  # a token-free text gate-fail is not re-attempted by main() for this long
VNIL_COOLDOWN_DAYS = (
    30  # a prep that can't even RENDER a symbol's pages waits this long (x n) before retry
)


def _today():
    return datetime.date.today().isoformat()


def _fresh(datestr, days):
    """True if datestr (YYYY-MM-DD...) is within `days` of today — i.e. still under cooldown."""
    if not datestr:
        return False
    try:
        d = datetime.date.fromisoformat(str(datestr)[:10])
    except Exception:
        return False
    return (datetime.date.today() - d).days < days


# ---- BSE fetch (narrow window + strCat=Result — BSE now rejects wide ranges) ------------------
def session():
    o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with contextlib.suppress(Exception):
        o.open(
            urllib.request.Request("https://www.bseindia.com/", headers=BH.HEADERS), timeout=30
        ).read()
    return o


_LAST_CALL = [0.0]
MIN_GAP = float(
    os.environ.get("BSE_MIN_GAP", "2.0")
)  # seconds between ANY two BSE requests (<=0.5/s, agreed


# with the parallel BSE session after the 2026-09-23 block)
def get(o, u, b=False):
    w = MIN_GAP - (time.time() - _LAST_CALL[0])
    if w > 0:
        time.sleep(w)
    _LAST_CALL[0] = time.time()
    r = o.open(urllib.request.Request(u, headers=BH.HEADERS), timeout=60)
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw if b else raw.decode("utf-8", "replace")


class BseBlocked(RuntimeError):
    pass


# ---- browser-discovery override -------------------------------------------------------------------
# The BSE announcements API (api.bseindia.com/AnnSubCategoryGetData) 403s scripted clients since
# 2026-09-23, but a real browser reaches it (200) and the PDF host (www.bseindia.com/xml-data) still
# serves scripts (200). So discovery is done in a browser and dropped to a JSON; set BSE_FILINGS_JSON
# to a {scripcode: [[annYYYYMMDD, attachmentname], ...]} map and result_filings() reads that instead
# of calling the blocked API. download()/render()/parse/vision/gate are unchanged — no IP rotation,
# no impersonation. When the block lifts, unset the env var and the live API path runs as before.
_FILINGS = None
_FILINGS_LOADED = False


def _filings_override():
    global _FILINGS, _FILINGS_LOADED
    if not _FILINGS_LOADED:
        _FILINGS_LOADED = True
        p = os.environ.get("BSE_FILINGS_JSON")
        if p and os.path.exists(p):
            raw = json.load(open(p))
            _FILINGS = {int(k): [(int(a), b) for a, b in v] for k, v in raw.items()}
            print("filings-override: %d scrips loaded from %s" % (len(_FILINGS), p))
    return _FILINGS


# Some filers put the audited ANNUAL result under "Board Meeting" / "Outcome of Board Meeting", not
# "Result" — measured 2026-09-26: a Result-only list lacked AUROPHARMA 2025-05, BALKRISIND 2023-05 +
# 2025-05 and PFIZER 2020-04 + 2024-05 + 2025-05 (PFIZER's Result list for FY25 held only the Q1).
# Both are asked; Result rows come first, so a filer that uses Result sees the same order as before.
RESULT_CATS = (("Result", ""), ("Board%20Meeting", "&subcategory=Outcome%20of%20Board%20Meeting"))


def result_filings(o, code, frm, to, pages=6):
    ov = _filings_override()
    if ov is not None:
        fi, ti = int(frm), int(to)
        return sorted({(a, b) for (a, b) in ov.get(int(code), []) if fi <= a <= ti})
    out = []
    seen = set()
    for cat, sub in RESULT_CATS:
        got = []
        for pg in range(1, pages + 1):
            u = (
                "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=%s"
                "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C%s"
                % (pg, cat, frm, code, to, sub)
            )
            try:
                rows = json.loads(get(o, u)).get("Table", [])
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    # BSE BLOCKED this client (measured 2026-09-23 after ~2k symbols: every call 403).
                    # Never let it read as "no filings" — that silently gate-failed ~310 symbols (§148).
                    raise BseBlocked(
                        "BSE HTTP %d on AnnSubCategoryGetData (%s)"
                        % (e.code, cat.replace("%20", " "))
                    )
                break
            except Exception:
                break
            for r in rows:
                if r.get("ATTACHMENTNAME"):
                    ann = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
                    got.append((int(ann) if ann else 0, r["ATTACHMENTNAME"]))
            if len(rows) < 50:
                break
            time.sleep(0.5)
        for f in sorted(set(got)):
            if f[1] not in seen:
                seen.add(f[1])
                out.append(f)
    return out


def download(o, att):
    """The attachment's bytes (a %PDF), or None. BSE_PDF_CACHE=<dir> serves and keeps copies there, so a
    re-run (text pass -> vision prep -> second read) never downloads a filing twice. Keep that dir under
    ~/stocks-cache: session scratch dirs are cleared after a few days."""
    cache = os.environ.get("BSE_PDF_CACHE")
    cp = os.path.join(cache, os.path.basename(att)) if cache else None
    if cp and os.path.exists(cp):
        d = open(cp, "rb").read()
        if d[:4] == b"%PDF":
            return d
    for base in ("AttachHis", "AttachLive"):
        try:
            d = get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                if cp:
                    os.makedirs(cache, exist_ok=True)
                    open(cp, "wb").write(d)
                return d
        except Exception:
            continue
    return None


# ---- number + line parsing -------------------------------------------------------------------
def to_num(tok):
    t = tok.strip()
    neg = t.startswith("(") or t.startswith("-")
    m = re.search(r"\d[\d,]*(?:\.\d+)?", t)  # numeric core, tolerating trailing junk (606,084.)
    if not m:
        return None
    core = m.group(0).rstrip(".")
    # a digit group after the LAST comma is always 3 wide (1,21,200 / 4,110.45). Anything else is an
    # OCR'd decimal point or a garbled figure — APLAPOLLO FY21 "977,11" (= 977.11, read 97,711),
    # KRBL FY21 "(20,0601" — so it is unreadable, never a number (2026-09-26).
    if "," in core and len(core.split(".")[0].rsplit(",", 1)[1]) != 3:
        return None
    core = core.replace(",", "")
    if not core:
        return None
    try:
        v = float(core)
    except ValueError:
        return None
    return -v if neg else v


ISNUM = re.compile(
    r"^[\(\-]?\d[\d,]*(?:\.\d+)?[\).,;:!]*%?$"
)  # numeric with tolerated trailing junk


def rows_of(page):
    """[(label, nums)] — rows_tok() without the printed tokens."""
    return [(label, [v for _, v in toks]) for label, toks in rows_tok(page)]


_GARBLED = re.compile(
    r"^[^A-Za-z]*\d[^A-Za-z]*\d[^A-Za-z]*$"
)  # 2+ digits, no letters: a figure the OCR mangled


def rows_tok(page, garbled_as_none=False):
    """Reconstruct table rows from word boxes: group words by y, split each row into its
    label text (left) and its numeric columns (right, by x). The PDF text layer returns a
    table's labels and numbers on different lines, so line-based reading fails — this doesn't.
    A dash cell ('-', '–') is kept as 0 IN POSITION, so a nil current year can no longer shift
    the prior-year number into nums[0] (§148; a column-clustering rewrite regressed 261/461 fields
    on the landed text cells and was reverted). Each value comes with its printed token, which
    the cash-flow guard (_cf_parse) inspects: [(label, [(token, value), ...])].
    garbled_as_none (the cash-flow reader): a digit-bearing token that is not a number and sits
    right of the row's last word is a MANGLED figure — kept as None in position, so the prior year
    cannot slide into its slot (APLAPOLLO FY22 printed its net change as "147:<61")."""
    words = page.get_text("words")  # (x0,y0,x1,y1,text,block,line,word)
    buckets = {}
    for w in words:
        buckets.setdefault(round(w[1]), []).append((w[0], w[4]))
    merged = []
    for y in sorted(buckets):
        if merged and y - merged[-1][0] <= 3:
            merged[-1][1].extend(buckets[y])
            merged[-1][0] = y
        else:
            merged.append([y, list(buckets[y])])
    # a "Note(s)" column: its short references (8, 8.1, 3a) sit where the values start and were
    # read AS the value (INDOWIND FY25 PP&E 8.1 for 16,134 lakh). Drop note-shaped numbers under it.
    note_x = [x for _, ts in merged for x, t in ts if NOTE_HDR.match(t.strip())]
    rows = []
    for _, toks in merged:
        toks.sort()
        toks = _join_split_figures(toks)
        label = " ".join(t for _, t in toks)
        nums = []
        seen_num = False
        last_word_x = max([x for x, t in toks if re.search(r"[A-Za-z]", t)] or [-1.0])
        prev = ""
        for x, t in toks:
            t = t.strip()
            before, prev = prev, t
            if DASH.match(t):
                if seen_num or nums or _right_of_label(x, toks):
                    nums.append((t, 0.0))
                continue
            if not ISNUM.match(t):
                if garbled_as_none and x > last_word_x and _GARBLED.match(t):
                    nums.append((t, None))
                    seen_num = True
                continue
            if note_x and NOTE_REF.match(t) and any(abs(x - nx) <= 30 for nx in note_x):
                continue
            # a note reference INSIDE the label: "(Refer Note 2)" / "(Note 6 and 7)" / "Note 12" — BPCL FY20-22
            # stored share capital 2.0 / 2.0 / 3.0 from "(Refer Note 2)" (2026-09-26, runbook §168k)
            if (NOTE_INLINE.match(t) and any(NOTE_WORD.search(w) for xw, w in toks if xw < x)) or (
                NOTE_REF.match(t) and NOTE_HDR.match(before)
            ):
                continue
            # an unreadable figure keeps its column as None — dropping it would shift the prior-year
            # number into the current-year slot (the same reason a dash is kept as 0)
            nums.append((t, to_num(t.rstrip("%"))))
            seen_num = True
        rows.append((label, nums))
    return rows


def _right_of_label(x, toks):
    """A dash counts as a value cell only when it sits right of the row's last word (the label),
    so hyphens inside labels ('Work - in - Progress') are never read as a nil value."""
    words = [tx for tx, t in toks if not (ISNUM.match(t.strip()) or DASH.match(t.strip()))]
    return bool(words) and x > max(words)


DASH = re.compile(r"^[-\u2013\u2014]{1,3}$|^nil$", re.I)
NOTE_HDR = re.compile(r"^notes?\.?$|^note\s*no\.?$", re.I)
NOTE_REF = re.compile(r"^\d{1,2}(?:\.\d{1,2})?[a-z]?$", re.I)
NOTE_INLINE = re.compile(r"^\d{1,2}(?:\.\d{1,2})?[a-z]?\)$", re.I)  # "2)" closing "(Refer Note 2)"
NOTE_WORD = re.compile(r"\bnotes?\b", re.I)

# An OCR'd figure split after a comma: "1,37, 101.38" / "2,32, 786.59" / "2, 12,366.62" (BALMLAWRIE FY21 other
# equity stored 1.37, LMW FY23 2.32, EPIGRAL FY23 1.02 \u2014 the first piece). Rejoined only when the result is a
# properly grouped number (Indian 1,37,101.38 or Western 1,371,013.8), so two real columns never merge.
_SPLIT_HEAD = re.compile(r"^\(?\d{1,3}(?:,\d{2,3})*,$")
_SPLIT_REST = re.compile(r"^\d[\d,]*(?:\.\d+)?\)?$")
_GROUPED = re.compile(r"^\(?(?:\d{1,3}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+)(?:\.\d+)?\)?$")


def _join_split_figures(toks):
    out = []
    for x, t in toks:
        s = t.strip()
        if (
            out
            and _SPLIT_HEAD.match(out[-1][1].strip())
            and _SPLIT_REST.match(s)
            and _GROUPED.match(out[-1][1].strip() + s)
        ):
            out[-1] = (out[-1][0], out[-1][1].strip() + s)
            continue
        out.append((x, t))
    return out


def parse_rows(rows, specs_one, specs_sum):
    out = {}
    for field, rx, sign in specs_one:
        for label, nums in rows:
            if re.search(rx, label, re.I) and nums:
                if (
                    nums[0] is not None
                ):  # blank current-year cell = not stated (never the prior year)
                    out[field] = round(sign * nums[0], 2)
                break
    for field, rx in specs_sum:
        tot = 0.0
        seen = False
        for label, nums in rows:
            if re.search(rx, label, re.I) and nums and nums[0] is not None:
                tot += abs(nums[0])
                seen = True
        if seen:
            out[field] = round(tot, 2)
    # Total Assets = Total Equity and Liabilities (accounting identity) when the assets total
    # has no line of its own (ALEMBICLTD FY25 prints only 'TOTAL - EQUITY AND LIABILITIES')
    if "assets" in {f: 1 for f, _, _ in specs_one} and out.get("assets") is None:
        for label, nums in rows:
            if (
                re.search(r"total[\s\-\u2013:.]{0,6}equity\s+and\s+liabilit", label, re.I)
                and nums
                and nums[0] is not None
            ):
                out["assets"] = round(nums[0], 2)
                break
    return out


# label -> field. Order matters: more specific first. Some fields SUM multiple matching lines.
BS_ONE = [  # (field, label regex, sign) — first matching line wins
    ("assets", r"^\s*total\s+assets\b", 1),
    ("sc", r"^\s*(?:\([a-z]\)\s*)?equity\s+share\s+capital\b", 1),
    ("oeq", r"^\s*(?:\([a-z]\)\s*)?other\s+equity\b", 1),
    ("ppe", r"property,?\s*plant\s*(?:and|&)\s*equipments?\b(?!.*expenditure)", 1),
    ("cwip", r"capital\s+work[\-\s]*in[\-\s]*progress\b", 1),
    ("gw", r"^\s*(?:\([a-z]\)\s*)?goodwill\b", 1),
    # right-of-use: its own line in most layouts; the XBRL PropertyPlantAndEquipment key includes it
    # for some filers and not others (merge_annual_bscf.gate_ok accepts either and says which, §148)
    ("rou", r"right[\s\-]*of[\s\-]*use\s+assets?\b", 1),
    # its OWN line — the page adds it to CWIP (Screener's convention); never folded into intg / cwip
    ("iuad", r"intangible\s+assets?\s+under\s+development\b", 1),
    # Screener's Fixed Assets includes investment property (§148c); 'under construction/development' is CWIP-like
    (
        "invprop",
        r"^\s*(?:\([a-z]+\)\s*)?investment\s+propert(?:y|ies)\b(?!.*(?:under|construction|development))",
        1,
    ),
    ("invnt", r"^\s*(?:\([a-z]\)\s*)?inventories\b", 1),
]
BS_SUM = [  # (field, label regex) — SUM the first-col of every matching line (non-current + current)
    ("borr", r"^\s*(?:\([a-z]+\)\s*|\(i+\)\s*)?borrowings\b"),
    (
        "invst",
        r"^\s*(?:\([a-z]+\)\s*|\(i+\)\s*)?investments?\b(?!\s+propert)",
    ),  # 'Investment property' is a fixed asset (§148c)
    ("intg", r"other\s+intangible\s+assets\b(?!\s+under)"),
    ("rec", r"trade\s+receivables\b"),
    ("pay", r"trade\s+payables\b|dues\s+of\s+(?:micro|creditors)"),
]
# "net cash <anything> <section> activities": the old labels required "net cash flow|generated|used"
# and so missed "NET CASH FROM OPERATING ACTIVITIES" (NFL), "Net cash inflow from operating" (DIVISLAB)
# and "Net cash (used in)/from ...". '_'-keys are helpers for the cash identity, never landed.
CF_ONE = [
    # not the "... operating activities BEFORE income-tax" sub-total (BAJAJHLDNG FY22 read 1,804 for 1,610)
    (
        "cfo",
        r"net\s+cash[^\n]{0,50}?operating\s+activit(?![^\n]*before\s+(?:income[\s\-]*)?tax|[^\n]*before\s+exceptional)",
        1,
    ),
    ("cfi", r"net\s+cash[^\n]{0,50}?investing\s+activit", 1),
    ("cff", r"net\s+cash[^\n]{0,50}?financing\s+activit", 1),
    (
        "cf_tax",
        r"(?:income\s+)?tax(?:es)?\s+paid\b|direct\s+taxes\s+paid",
        1,
    ),  # signed by _tax_direction (§168j)
    (
        "capex",
        r"(?:purchases?|acquisitions?|payments?\s+(?:for|towards)|additions?\s+to|(?:capital\s+)?expenditure\s+on)\b"
        r"[^\n]{0,30}?(?:property,?\s*plant|fixed\s+assets|\btangible\s+assets|\bppe\b)",
        1,
    ),  # abs() in _cf_parse
    # the net change in cash — "Net increase/(decrease) in cash ..." or a bare "D. DECREASE IN CASH ..."
    # (HEROMOTOCO FY22); never the investing line for bank balances "not considered as cash"
    (
        "_cf_net",
        r"^\s*(?:[a-z]\.?\s+|\([a-z]\)\s*)?(?:net\s+)?[()/\sa-z]{0,30}?(?:increase|decrease|change)\)?"
        r"[()/\sa-z]{0,20}?\bin\s+cash\s+(?:and|&)\s+cash\s+equivalents?"
        r"(?![^\n]*(?:not\s+considered|other\s+than|bank\s+balance))",
        1,
    ),
]
# the FX effect on cash: the LAST such line is the statement's own (RITES FY21 also prints one among
# the operating adjustments), so every candidate is tried against the identity
CF_FX = re.compile(
    r"(?:effects?|impact)\s+of\b[^\n]{0,60}?(?:exchange|currenc)[^\n]{0,60}?cash"
    r"|(?:exchange|currency)\s+(?:rate\s+)?(?:differences?|fluctuations?|translation)[^\n]{0,60}?cash\s+(?:and|&)\s+cash",
    re.I,
)

_BARE_INT = re.compile(r"^\(?-?\d{1,3}\)?[.,;:]?$")  # "2", "(8)", "103" — no grouping, no decimals
_SPLIT_TAIL = re.compile(
    r"^\(?-?\d{3}(?:\.\d+)?\)?[.,;:]?$"
)  # "103", "403.70": the rest of a split figure

# Income tax in the cash flow is stored SIGNED in the exchange-data (XBRL) convention: + paid, - net refund.
# The direction comes from the statement's own arithmetic, never its label or brackets (runbook §168j):
# GESHIP FY22 "Direct taxes paid/ (refund) 9.47" is ADDED (1,313.09 + 9.47 = 1,322.56: a refund), ATUL FY20
# "Income tax paid (net of refund) 216.77" is SUBTRACTED (1,098.15 - 216.77 = 881.38: a payment).
CF_GEN = re.compile(
    r"cash\s+(?:flows?\s+)?(?:generated|used|\(used\s+in\)|inflow|outflow|from)[^\n]{0,60}?(?:operations?\b|operating\s+activit)"
    r"|(?:post|after)\s+working\s+capital|operating\s+(?:profit|cash\s*flow)[^\n]{0,40}?(?:after|post)\s+(?:working|changes)"
    r"|operating\s+activit[^\n]{0,20}?before\s+(?:income[\s\-]*)?tax",
    re.I,
)
CF_TAXLINE = re.compile(
    r"tax(?:es)?\b[^\n]{0,30}?(?:paid|refund|received)|(?:paid|refund(?:ed)?|received)[^\n]{0,20}?\btax"
    r"|direct\s+tax(?:es)?|income[\s\-]*tax(?:es)?\s*(?:\(net\)|,?\s*net\b)|tax(?:es)?\s*\(net\)",
    re.I,
)
CF_TAXNOT = re.compile(
    r"before\s+(?:income[\s\-]*)?tax|tax\s+expense|deferred|provision\s+for\s+tax|tax\s+deducted|dividend",
    re.I,
)
_NETLINE = re.compile(
    r"^\s*(?:\(?[a-e]\)?[.:]?\s+)?net\b(?![^\n]*before\s+(?:income[\s\-]*)?tax)", re.I
)


def _tax_direction(fixed, rows, cfo):
    """The operating section's net income-tax cash flow, signed + paid / - net refund, or None.
    C = the net-operating-cash line that carries `cfo`; O = the 'cash generated from operations' line
    above it; S = C - O - (every other line between them, as printed) is what the tax line(s) did to cash.
    Accepted only when |S| equals the printed tax amount (several tax lines — BHEL FY22 prints the payment
    and the refund apart — are summed as printed) and the amount is large enough that the two directions
    cannot be confused at the statement's printed precision. Anything else: None, never a guess."""
    if cfo is None:
        return None
    rx_cfo = re.compile(CF_ONE[0][1], re.I)
    for ic, (lab, n) in enumerate(fixed):
        if not (rx_cfo.search(lab) and n and n[0] is not None and abs(n[0] - cfo) < 0.005):
            continue
        io = next(
            (
                i
                for i in range(ic - 1, max(-1, ic - 9), -1)
                if fixed[i][1] and CF_GEN.search(fixed[i][0]) and not _NETLINE.search(fixed[i][0])
            ),
            None,
        )
        if io is None or fixed[io][1][0] is None:
            return None
        taxes = [
            i
            for i in range(io + 1, ic)
            if fixed[i][1] and CF_TAXLINE.search(fixed[i][0]) and not CF_TAXNOT.search(fixed[i][0])
        ]
        others = [i for i in range(io + 1, ic) if fixed[i][1] and i not in taxes]
        if not taxes or any(fixed[i][1][0] is None for i in taxes + others):
            return None
        T = sum(fixed[i][1][0] for i in taxes)
        S = cfo - fixed[io][1][0] - sum(fixed[i][1][0] for i in others)
        toks = [toks[0][0] for i in [io, ic] + taxes + others for toks in [rows[i][1]] if toks]
        res = 1.0 if all("." not in t for t in toks) else 0.01
        tol = res * 0.5 * (2 + len(taxes) + len(others)) + 1e-9  # half a printed unit per term
        if abs(T) <= 2 * tol or abs(abs(S) - abs(T)) > tol:
            return None
        return round(-S, 2)
    return None


def _cf_parse(rows):
    """CF_ONE over a cash-flow statement's token rows (rows_tok), with guards measured on real filings
    (2026-09-26). Returns the fields plus '_cf_ok' (the identity verdict) and '_cf_layout'.
      * a statement whose rows usually carry 3+ figures prints several bases/periods side by side (NFL
        FY22: standalone and consolidated, 4 columns) — which column is the wanted one is not knowable
        from the text, so its cash flow is NOT read here ('_cf_layout': 'multi'; the vision reader gets it);
      * a row with MORE figures than usual: when its first figure is a complete number the extra ones
        sit in the prior-year part and the current-year value stands (NATIONALUM FY22 prior year
        "1 403.70"); a bare small integer followed by a 3-digit fragment is a split figure and the field
        is left unread (HEROMOTOCO FY22 printed 2,103.70 as "2 103 70" -> stored CFO 2.0); one extra bare
        integer <= 50 before a complete figure is a note / section marker and is dropped (KRBL FY21 capex
        "1 (4,142)", VINDHYATEL FY20 "(B)" OCR'd as "(8)");
      * capex is an outflow by definition: abs(), whatever sign convention the filer uses. Income tax is
        NOT: a net refund is an inflow, so cf_tax is signed by the statement's own arithmetic
        (_tax_direction: + paid, - refund) and left unread when that cannot be proven (§168j);
      * cfo/cfi/cff are dropped when the statement's own identity cfo + cfi + cff (+ any FX-effect line)
        = net change in cash is checkable and fails (APLAPOLLO FY21 "977,11"; IPCALAB FY20's text layer
        says 554.27 where the page prints 564.27)."""
    cnt = {}
    for _, toks in rows:
        if toks:
            cnt[len(toks)] = cnt.get(len(toks), 0) + 1
    mode = max(cnt, key=lambda k: (cnt[k], -k)) if cnt else None
    if mode is not None and mode >= 3:
        return {"_cf_ok": None, "_cf_layout": "multi"}
    fixed = []
    for lab, toks in rows:
        nums = [v for _, v in toks]
        if mode and len(toks) > mode and nums[0] is not None:
            t0, t1 = toks[0][0], toks[1][0]
            if _BARE_INT.match(t0):
                if _SPLIT_TAIL.match(t1) and not t1.startswith("("):
                    # a split figure: unreadable, never a fragment of it. (A BRACKETED next token is a
                    # complete figure, so t0 is a marker: ATUL FY22 cfi "8 (167.65)".)
                    nums = [None]
                elif len(toks) == mode + 1 and 0 < abs(nums[0]) <= 50:
                    nums = nums[1:]  # a note / section marker before the figures
                else:
                    nums = [None]
        fixed.append((lab, nums))
    cf = parse_rows(fixed, CF_ONE, [])
    if cf.get("capex") is not None:
        cf["capex"] = abs(cf["capex"])
    cf.pop("cf_tax", None)  # re-derived, signed, below
    a, b, c, net = cf.get("cfo"), cf.get("cfi"), cf.get("cff"), cf.get("_cf_net")
    chk = cf_identity(a, b, c, net)
    fxs = [n[0] for lab, n in fixed if n and n[0] is not None and CF_FX.search(lab)]
    if chk is False:
        for f in fxs:
            if cf_identity(a, b, c, net, f):
                chk = True
                cf["_cf_fx"] = f
                break
    if chk is False:
        # the first matching line is not always the statement's own total: HGS FY22 prints TWO lines both
        # called "Net cash generated from operating activities" (the first is before tax). Try every
        # candidate line per total; accept only a UNIQUE triple that closes the identity.
        rx = {k: rxx for k, rxx, _ in CF_ONE if k in ("cfo", "cfi", "cff")}
        cand = {
            k: [n[0] for lab, n in fixed if n and n[0] is not None and re.search(rx[k], lab, re.I)][
                :3
            ]
            for k in rx
        }
        sols = {
            (x, y, z): f
            for x in cand["cfo"]
            for y in cand["cfi"]
            for z in cand["cff"]
            for f in [None] + fxs
            if cf_identity(x, y, z, net, f)
        }
        if len(sols) == 1:
            (a, b, c), f = next(iter(sols.items()))
            cf.update({"cfo": a, "cfi": b, "cff": c})
            chk = True
            if f is not None:
                cf["_cf_fx"] = f
    # before a failed identity drops cfo: the tax arithmetic checks the operating line on its own terms
    tax = _tax_direction(fixed, rows, cf.get("cfo"))
    if tax is not None:
        cf["cf_tax"] = tax
    if chk is False:
        for k in ("cfo", "cfi", "cff"):
            cf.pop(k, None)
    cf["_cf_ok"] = chk
    cf["_cf_layout"] = "single"
    return cf


BS_PAGE = re.compile(r"(balance sheet|assets and liabilities|statement of assets)", re.I)
BS_REAL = re.compile(
    r"(total\s+equity|equity\s+share\s+capital|other\s+equity)", re.I
)  # equity marker
BS_ASSET = re.compile(
    r"total[\s\-–—:.]{0,4}assets", re.I
)  # the real BS foots to a Total Assets line; a P&L results page / notes page does not
BS_LIAB = re.compile(
    r"trade\s+payables|total[\s\-–—:.]{0,4}equity\s+and\s+liabilit", re.I
)  # POSITIVE liabilities-side marker: a real BS/statement-of-assets-and-liabilities always has it; a P&L results page, a notes page, or a per-segment "assets & liabilities" schedule does NOT (so this excludes the decoys without over-excluding a real BS page that merely shares a page with segment text)
CF_PAGE = re.compile(r"cash\s*flow", re.I)
CF_REAL = re.compile(r"operating\s+activit|investing\s+activit|financing\s+activit", re.I)
CONSOL = re.compile(r"consolidated", re.I)
STANDAL = re.compile(r"standalone", re.I)
# RELAXED markers — used ONLY by locate()'s second pass, after the strict rules above found no
# consolidated BS. Measured misses of the strict ones (2026-09-26, 40 failing filings): BEL prints
# "Assets & Liabilities"; ANANTRAJ "Total of equity and liabilities"; ASTRAL/BEL put the title +
# Total Assets on one page and "Trade payables" + the "Total equity and liabilities" footing on the
# NEXT, untitled page, so no single page carries all three strict markers.
BS_PAGE2 = re.compile(
    r"balance\s*sheet|assets\s*(?:and|&)\s*liabilities|statement\s+of\s+assets", re.I
)
BS_FOOT = re.compile(
    r"total[\s\-–—:.]{0,4}(?:of\s+)?equity\s*(?:and|&)\s*liabilit", re.I
)  # the liabilities-side FOOTING line
BS_LIAB2 = re.compile(r"trade\s*payables?|" + BS_FOOT.pattern, re.I)


def _relaxed_bs(texts):
    """Second-pass BS/CF page finder: {'bs_con','bs_std': [pages] | None, 'cf_con','cf_std': i | None}.
    Three shapes: (1) one page with title + liabilities marker + a total; (2) title + totals on page
    i with the FOOTING on page i+1; (3) title + footing on page i with Total Assets on page i-1.
    Shapes 2/3 require the "total equity and liabilities" FOOTING, which a cash-flow page ("trade
    payables" as a working-capital line) and a per-segment assets & liabilities schedule never
    carry — so a segment page followed by a cash-flow page (BHARTIARTL p3->p4) cannot pair up."""
    n = len(texts)
    title = [bool(BS_PAGE2.search(t)) for t in texts]
    liab = [bool(BS_LIAB2.search(t)) for t in texts]
    foot = [bool(BS_FOOT.search(t)) for t in texts]
    asset = [bool(BS_ASSET.search(t)) for t in texts]
    tot = [bool(BS_REAL.search(t)) or asset[i] for i, t in enumerate(texts)]
    con = [bool(CONSOL.search(t)) for t in texts]
    R = {"bs_con": None, "bs_std": None, "cf_con": None, "cf_std": None}
    for i in range(n):
        pages = None
        if title[i] and liab[i] and tot[i]:
            pages = (
                [i - 1, i] if (not asset[i] and i > 0 and asset[i - 1] and not liab[i - 1]) else [i]
            )
        elif title[i] and tot[i] and not liab[i] and i + 1 < n and foot[i + 1]:
            pages = [i, i + 1]
        elif title[i] and foot[i] and not tot[i] and i > 0 and asset[i - 1]:
            pages = [i - 1, i]
        if pages:
            k = "bs_con" if any(con[p] for p in pages) else "bs_std"
            if R[k] is None:
                R[k] = pages
        if CF_PAGE.search(texts[i]) and CF_REAL.search(texts[i]):
            k = "cf_con" if con[i] else "cf_std"
            if R[k] is None:
                R[k] = i
    return R


# ---- a cash-flow statement that runs onto the next page ----------------------------------------
# Measured 2026-09-26 on 36 located statements: 7 continue (BEL FY20/21/22/25, DIVISLAB FY22, NFL FY22,
# SUNPHARMA FY25) — operating section on page i, investing + financing on page i+1. Reading page i
# alone lost cfi/cff/capex (BEL's landed FY20-22 cells; DIVISLAB/NFL FY22 even lost cfo to the labels).
CF_DONE = re.compile(
    r"net\s+cash[^\n]{0,60}financing\s+activit|net\s+(?:increase|decrease|\(decrease\)|change)[^\n]{0,50}cash"
    r"|cash\s+and\s+cash\s+equivalents?\s+at\s+(?:the\s+)?(?:end|close)",
    re.I,
)
CF_SECT = re.compile(r"(?:financing|investing)\s+activit", re.I)
CF_TITLE = re.compile(r"cash\s*flow\s+statement|statement\s+of\s+cash\s*flows?", re.I)
CF_OPS = re.compile(r"operating\s+activit", re.I)


def cf_span(texts, i):
    """Cash-flow page list: [i], or [i, i+1] when the statement on page i stops before its financing
    section and page i+1 carries investing/financing WITHOUT starting a new statement (a title plus
    an operating section = the other basis's cash flow, never a continuation). [] for no page."""
    if i is None:
        return []
    if CF_DONE.search(texts[i]) or i + 1 >= len(texts):
        return [i]
    nxt = texts[i + 1]
    if CF_SECT.search(nxt) and not (CF_TITLE.search(nxt) and CF_OPS.search(nxt)):
        return [i, i + 1]
    return [i]


def fy_end_hit(text, want_year):
    r"""True if `text` names the fiscal-year-end 31 March <want_year>, in ANY of the printed
    forms these audited results use. STRICT SUPERSET of the old matcher, which had two bugs that
    silently zeroed out most filers:
      * r'(31st?\s+)?march' parsed as the literal '31s'+optional 't', so 'YEAR ENDED 31 MARCH 2024'
        (a bare '31', no 'st') never matched — the '(31st?\s+)?' group failed and 'march' could
        not follow 'ended '. Filers who wrote '31st March,' matched; '31 March' did not.
      * "'31.03.%s' % yr[-2:] in text" tested the 2-digit '31.03.24', which is NOT a substring of
        the 4-digit '31.03.2024' — so the numeric form was missed too.
    Forms accepted: '[31[st]] March[,] 2024', 'March 31[st], 2024', 'ended March 2024',
    '31.03.2024' / '31/03/2024' / '31-03-2024' (2- or 4-digit year, any of . / - separators)."""
    yr = str(want_year)
    yy = yr[-2:]
    if re.search(r"\b31\s*(?:st|nd|rd|th)?\s+march[,\s]+" + yr + r"\b", text, re.I):
        return True
    if re.search(r"\bmarch\s+31\s*(?:st|nd|rd|th)?\s*,?\s*" + yr + r"\b", text, re.I):
        return True
    if re.search(r"\bended\s+march[,\s]+" + yr + r"\b", text, re.I):
        return True
    ns = re.sub(r"\s+", "", text)
    # numeric dd?mm?yyyy — 4-digit first (word-boundary via negative-lookahead so 2020 != 2024),
    # then 2-digit '31.03.24' (also guarded so it can't match inside '31.03.2024').
    if re.search(r"31[./-]0?3[./-]" + yr + r"(?!\d)", ns):
        return True
    return bool(re.search(r"31[./-]0?3[./-]" + yy + r"(?!\d)", ns))


def locate(pdf, want_year, want_basis=None):
    """Confirm this PDF is the FY-end audited result and return (basis, bs_pi, cf_pi) — the
    consolidated BS + CF page indices (standalone fallback). None otherwise."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    texts = [doc[i].get_text() for i in range(len(doc))]
    doc.close()
    if not any(fy_end_hit(t, want_year) for t in texts):
        return None
    bs_con = bs_std = cf_con = cf_std = None
    for i, t in enumerate(texts):
        con = bool(CONSOL.search(t))
        # real BS = the A&L/balance-sheet TITLE + the robust "trade payables" liabilities marker
        # + at least ONE of the equity/assets total markers. Consolidated pages often have a
        # CORRUPTED text layer ("TOT AL ASSETS", "EQUITY A~D LIABILITIES"), so we anchor on
        # trade-payables (survives) and tolerate corruption in either total line, but not both.
        if BS_PAGE.search(t) and BS_LIAB.search(t) and (BS_REAL.search(t) or BS_ASSET.search(t)):
            if con and bs_con is None:
                bs_con = i
            elif not con and bs_std is None:
                bs_std = i
        if CF_PAGE.search(t) and CF_REAL.search(t):
            if con and cf_con is None:
                cf_con = i
            elif not con and cf_std is None:
                cf_std = i

    def bs_pages(i):
        # A balance sheet can span TWO pages: the matched page (found via the trade-payables
        # marker) is the equity-&-liabilities half and carries NO "Total Assets" line, while the
        # assets side sits on the PREVIOUS page. Return both so PP&E/Total-Assets aren't lost
        # (HAL, GLAXO, TATACOMM, TIINDIA). Otherwise a single page. bs_pi is always a LIST.
        if i is None:
            return None
        if (
            not BS_ASSET.search(texts[i])
            and i > 0
            and BS_ASSET.search(texts[i - 1])
            and not BS_LIAB.search(texts[i - 1])
        ):
            return [i - 1, i]
        return [i]

    # a FILL year must come from the basis the gate validated — prefer that page when the filing
    # carries both (PROZONER FY22: con page read fine but the validated basis is std, §148)
    # the cash flow must be the SAME basis as the balance sheet. When no page is labelled with that basis,
    # take an unlabelled cash-flow page only if it sits right AFTER that balance sheet (within 3 pages) —
    # BIRLACORPN FY20 BS p8 -> CF p9, CIPLA, PNBHOUSING: all match Screener's consolidated cash flow — or,
    # in a SINGLE-basis filing, any cash-flow page. The old fallback took the first cash-flow page of the
    # filing, i.e. the STANDALONE one ahead of the consolidated section: AUROPHARMA FY21 (BS p27, CF p3),
    # ALLCARGO FY20 (p21 / p10), JBCHEPHARM FY22 (p15 / p7) landed standalone cash flows in consolidated
    # cells (2026-09-26, Screener FAR).
    def _after(bs_i, other):
        if bs_i is None:
            return None
        last = bs_pages(bs_i)[-1]
        for j in range(last + 1, min(len(texts), last + 4)):
            if CF_PAGE.search(texts[j]) and CF_REAL.search(texts[j]) and not other.search(texts[j]):
                return j
        return None

    cf_c = (
        cf_con
        if cf_con is not None
        else (_after(bs_con, STANDAL) if bs_std is not None else cf_std)
    )
    cf_s = (
        cf_std if cf_std is not None else (_after(bs_std, CONSOL) if bs_con is not None else cf_con)
    )
    strict = None
    if want_basis == "s" and bs_std is not None:
        strict = ("s", bs_pages(bs_std), cf_s)
    elif bs_con is not None:
        strict = ("c", bs_pages(bs_con), cf_c)
    elif bs_std is not None:
        strict = ("s", bs_pages(bs_std), cf_s)
    if strict is not None and strict[0] == "c":
        return strict  # strict rules found the consolidated BS: unchanged
    # RELAXED second pass — only when the strict markers found nothing, or found only a standalone
    # BS while a consolidated one exists (consolidated-first is the intended precedence; the strict
    # markers just missed it). Regression-tested 2026-09-26 on 24 filings that already landed: 23
    # identical, 1 now auto-located on exactly the pages its hand-read values came from (ASTRAL FY22).
    R = _relaxed_bs(texts)
    if strict is not None:
        if want_basis != "s" and R["bs_con"] is not None:
            return (
                "c",
                R["bs_con"],
                R["cf_con"],
            )  # CF on the SAME basis or none — never mix bases in a cell
        return strict
    if want_basis == "s" and R["bs_std"] is not None:
        return "s", R["bs_std"], R["cf_std"]
    if R["bs_con"] is not None:
        return "c", R["bs_con"], R["cf_con"]
    if R["bs_std"] is not None:
        return "s", R["bs_std"], R["cf_std"]
    return None


def _as_list(x):
    return list(x) if isinstance(x, (list, tuple)) else [x]


# ---- statement unit (runbook §0 "FILINGS COME IN THREE UNITS", §148) -------------------------
# The text path used to land the printed number as crore, so every lakh / million filer read
# 10x-100x off and gate-failed (CMSINFO FY25: read 31,199.24 = Rs mn vs key 3,119.92 cr).
UNIT_PATS = [
    (
        100.0,
        re.compile(r"\b(?:in\s+)?(?:rs\.?|inr|₹|rupees)?\s*(?:in\s+)?(?:lakhs?|lacs?)\b", re.I),
    ),
    (10.0, re.compile(r"\b(?:in\s+)?(?:rs\.?|inr|₹|rupees)?\s*(?:in\s+)?(?:millions?|mn)\b", re.I)),
    (1e4, re.compile(r"\b(?:rs\.?|inr|₹|rupees)?\s*in\s+(?:thousands?|\'?000s?)\b", re.I)),
    (
        1.0,
        re.compile(
            r"\b(?:in\s+)?(?:rs\.?|inr|₹|rupees)?\s*(?:in\s+)?(?:crores?|crs?\.?)\b(?!\s*(?:shares|equity))",
            re.I,
        ),
    ),
]
UNIT_CTX = re.compile(
    r"(?:amount|figures|rs\.?|inr|₹|rupees)[^\n]{0,25}\bin\b|\(\s*(?:rs\.?|inr|₹|rupees)?\s*in\b",
    re.I,
)


def detect_unit(text):
    """Divisor to crore from the statement's own unit note, or None when absent/ambiguous.
    Only lines that LOOK like a unit note count ('(Rs. in Lakhs)', 'Amount in ₹ million',
    '₹ in crore') — a bare 'crore' in a footnote is not a unit declaration."""
    found = set()
    for ln in text.splitlines():
        if not UNIT_CTX.search(ln) or len(ln) > 160:
            continue
        for f, pat in UNIT_PATS:
            if pat.search(ln):
                found.add(f)
                break
    return found.pop() if len(found) == 1 else None


MONEY_KEYS = (
    "assets",
    "sc",
    "oeq",
    "borr",
    "blt",
    "bst",
    "ppe",
    "cwip",
    "iuad",
    "gw",
    "intg",
    "invst",
    "invprop",
    "rec",
    "pay",
    "invnt",
    "rou",
    "cfo",
    "cfi",
    "cff",
    "capex",
    "cf_tax",
    "eq",
    "cash",
)
CF_KEYS = ("cfo", "cfi", "cff", "capex", "cf_tax")


def scale_read(p, k):
    return {
        kk: (round(v / k, 2) if (kk in MONEY_KEYS and isinstance(v, (int, float))) else v)
        for kk, v in p.items()
    }


def scale_text(p, k):
    """A text read in crore: BS fields by the BS unit k, cash-flow fields by the cash-flow page's own
    stated unit (else k); '_' helper keys dropped."""
    cfk = p.get("_cf_unit") or k
    return {
        kk: (
            round(v / (cfk if kk in CF_KEYS else k), 2)
            if (kk in MONEY_KEYS and isinstance(v, (int, float)))
            else v
        )
        for kk, v in p.items()
        if not kk.startswith("_")
    }


def page_is_ocr(page):
    """True when the page's text is an OCR layer over a SCANNED image, not the filer's own digital text:
    most text is invisible (render mode 3 — 'ignore-text' in MuPDF's bbox log) or an image covers >= 90%
    of the page under the text (ABBYY-style visible OCR). Measured 2026-09-26 on the 115 N500 text cells:
    78 sat on such pages (66 invisible layer; 10 image-backed, producers ABBYY / HP Scan / Konica Minolta /
    Acrobat Paper Capture) — the source of the split / mangled / decimal-comma figures in §168c. Digital
    filings (TCS FY21, GRASIM FY20, POLYCAB FY20) show neither. (get_bboxlog, not get_texttrace: the latter
    crashes PyMuPDF 1.28 with a refcount error after a few hundred pages.)"""
    try:
        log = page.get_bboxlog()
    except Exception:
        return False
    txt = [k for k, _ in log if k.endswith("-text")]
    if not txt:
        return False
    inv = sum(1 for k in txt if k == "ignore-text")
    pa = (page.rect.width * page.rect.height) or 1.0
    img = (
        sum((b[2] - b[0]) * (b[3] - b[1]) for k, b in log if k in ("fill-image", "fill-imgmask"))
        / pa
    )
    return inv / len(txt) > 0.5 or img >= 0.9


def _mode_cols(rows):
    cnt = {}
    for _, toks in rows:
        if toks:
            cnt[len(toks)] = cnt.get(len(toks), 0) + 1
    return max(cnt, key=lambda k: (cnt[k], -k)) if cnt else 0


def text_read(pdf, bs_pi, cf_pi, allow_ocr=False):
    """Word-grid text parse (free, exact — but fails on filers who shade the current-year column).
    bs_pi may be one page or a two-page [assets, liabilities] split; the cash flow may run onto the
    next page (cf_span). Returns the RAW printed numbers plus '_unit' / '_cf_unit' = divisor to crore
    stated on the BS / CF page(s) (None if not stated). cfo/cfi/cff are dropped when the statement's
    own cash identity is checkable and fails — a label matched the wrong line.
    Withheld (never read from text, runbook §168h): a balance sheet printing several column blocks
    side by side (usually 3+ figures per row: standalone + consolidated — TRENT FY21 landed its
    STANDALONE block as consolidated), and — unless allow_ocr — a balance sheet on an OCR'd scan
    (page_is_ocr). On an OCR'd cash-flow page only cfo/cfi/cff that CLOSE the cash identity are kept
    (a mangled digit cannot close it); capex / cf_tax are withheld. Flags: _bs_ocr, _bs_layout, _cf_ocr."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    fields = {}
    bs_text = ""
    bs_rows = []
    bs_ocr = False
    for pi in _as_list(bs_pi):
        bs_text += doc[pi].get_text() + "\n"
        toks = rows_tok(doc[pi])
        bs_rows += toks
        bs_ocr = bs_ocr or page_is_ocr(doc[pi])
        for k, v in parse_rows(
            [(lab, [v for _, v in t]) for lab, t in toks], BS_ONE, BS_SUM
        ).items():
            fields.setdefault(k, v)  # first page (assets side) wins any shared key
    bs_layout = "multi" if _mode_cols(bs_rows) >= 3 else "single"
    if bs_layout == "multi" or (bs_ocr and not allow_ocr):
        fields = {}
    fields["_bs_ocr"] = bs_ocr
    fields["_bs_layout"] = bs_layout
    cf_unit = None
    if cf_pi is not None:
        span = cf_span([doc[k].get_text() for k in range(len(doc))], cf_pi)
        cf_rows = []
        for pi in span:
            cf_rows += rows_tok(doc[pi], garbled_as_none=True)
        cf = _cf_parse(cf_rows)
        cf_ocr = any(page_is_ocr(doc[pi]) for pi in span)
        if cf_ocr:
            cf.pop("capex", None)
            cf.pop("cf_tax", None)
            if cf.get("_cf_ok") is not True:
                for k in ("cfo", "cfi", "cff"):
                    cf.pop(k, None)
        fields["_cf_ocr"] = cf_ocr
        fields.update({k: v for k, v in cf.items() if not k.startswith("_")})
        fields["_cf_ok"] = cf.get("_cf_ok")  # True / False / None: the cash identity's verdict
        fields["_cf_layout"] = cf.get(
            "_cf_layout"
        )  # 'single' / 'multi' (side-by-side bases: not read)
        fields["_cf_net"] = cf.get("_cf_net")  # the printed net change in cash (raw) ...
        fields["_cf_fx"] = cf.get("_cf_fx")  # ... and the FX-effect line that closed the identity
        cf_unit = detect_unit("\n".join(doc[pi].get_text() for pi in span))
    doc.close()
    fields["_unit"] = detect_unit(bs_text)
    fields["_cf_unit"] = cf_unit
    return fields


def unit_candidates(p):
    """Divisors to try: the stated unit alone when the page states one, else crore/million/lakh —
    the holdout gate (<=1% on Total Assets AND PP&E) can accept at most one of them."""
    return (
        [p["_unit"]] if p.get("_unit") else [1.0, 10.0, 100.0, 1e4, 1e7]
    )  # crore, mn, lakh, '000, Rs


def render(pdf, pi, dpi=200):
    doc = fitz.open(stream=pdf, filetype="pdf")
    png = doc[pi].get_pixmap(dpi=dpi).tobytes("png")
    doc.close()
    return png


def _page_texts(pdf):
    doc = fitz.open(stream=pdf, filetype="pdf")
    texts = [doc[k].get_text() for k in range(len(doc))]
    doc.close()
    return texts


# ---- vision read (Claude Haiku via the Anthropic API — CI only; needs ANTHROPIC_API_KEY) -----
_FIELDS = [
    "assets",
    "sc",
    "oeq",
    "borr",
    "blt",
    "bst",
    "ppe",
    "cwip",
    "iuad",
    "gw",
    "intg",
    "invst",
    "rec",
    "pay",
    "invnt",
    "cfo",
    "cfi",
    "cff",
    "capex",
    "cf_tax",
    "cf_net",
    "cf_fx",
]


def _schema():
    props = {f: {"type": ["number", "null"]} for f in _FIELDS}
    props["ok"] = {"type": "boolean"}
    props["basis"] = {"type": "string", "enum": ["C", "S"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": props,
        "required": ["ok", "basis"] + _FIELDS,
    }


_VPROMPT = (
    "These images are pages from %s's audited annual results for the year ended 31 March %d: a BALANCE "
    "SHEET and a CASH FLOW STATEMENT. Read the numbers as printed (the current-year column — the LEFT "
    "data column, 'As at/Year ended 31 March %d'), in the statement's own unit (almost always ₹ crore; "
    "if the header says lakh/lakhs divide by 100, if absolute rupees divide by 1e7). Prefer the "
    "CONSOLIDATED statement if both consolidated and standalone are shown; set basis 'C' or 'S' for which "
    "you used. Extract, all ₹ crore, null if a line is genuinely absent:\n"
    "assets=Total Assets; sc=Equity Share Capital; oeq=Other Equity (reserves); blt=non-current "
    "Borrowings; bst=current Borrowings; borr=blt+bst (interest-bearing borrowings only, EXCLUDE lease "
    "liabilities); ppe=Property Plant & Equipment (net block); cwip=the Capital Work-in-Progress line ONLY; "
    "iuad=Intangible Assets Under Development (its own line; never add it to cwip or intg); gw=Goodwill; "
    "intg=Other Intangible Assets; invst=total Investments (non-current + current); rec=total Trade "
    "Receivables; pay=total Trade Payables; invnt=Inventories; cfo=Net Cash Flow FROM OPERATING "
    "activities; cfi=Net Cash Flow FROM INVESTING activities; cff=Net Cash Flow FROM FINANCING "
    "activities; capex=cash spent on purchase of PP&E/intangibles (investing outflow, as a positive "
    "number); cf_tax=net income tax in the operating section, POSITIVE if tax was paid, NEGATIVE if a net refund "
    "came in — decide by the statement's arithmetic (cash generated from operations +/- this line = net cash from "
    "operating activities), never by its label or brackets; null if that cannot be seen; cf_net=Net increase/(decrease) in "
    "cash and cash equivalents; cf_fx=effect of exchange-rate changes on cash (null if not printed). The "
    "cash-flow statement may continue onto a second image — read both. If these are the wrong company or "
    "you cannot find a balance sheet, set ok=false. Return ONLY the JSON object."
)


def vision_read(pdf, bs_pi, cf_pi, name, want_year):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        cli = anthropic.Anthropic()
    except Exception:
        return None
    pngs = [render(pdf, pi) for pi in _as_list(bs_pi)]
    for pi in cf_span(_page_texts(pdf), cf_pi):
        pngs.append(render(pdf, pi))
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": base64.standard_b64encode(p).decode(),
            },
        }
        for p in pngs
    ]
    content.append({"type": "text", "text": _VPROMPT % (name, want_year, want_year)})
    try:
        resp = cli.messages.create(
            model=os.environ.get("BSE_VISION_MODEL", "claude-haiku-4-5"),
            max_tokens=1024,
            output_config={"format": {"type": "json_schema", "schema": _schema()}},
            messages=[{"role": "user", "content": content}],
        )
        txt = next((b.text for b in resp.content if b.type == "text"), None)
        d = json.loads(txt) if txt else None
    except Exception as ex:
        print("    vision-api err:", str(ex)[:80])
        return None
    if not d or not d.get("ok"):
        return None
    b = "c" if d.get("basis") == "C" else "s"
    got = {f: d[f] for f in _FIELDS if d.get(f) is not None}
    if (
        cf_identity(
            got.get("cfo"), got.get("cfi"), got.get("cff"), got.get("cf_net"), got.get("cf_fx")
        )
        is False
    ):
        for k in ("cfo", "cfi", "cff"):
            got.pop(k, None)  # the statement's own cash identity failed: a misread
    got.pop("cf_net", None)
    got.pop("cf_fx", None)  # identity helpers, never landed
    return b, got


# ---- slice answer key (what we already hold from XBRL; slice_x lives in merge_annual_bscf) -----
def held_bs(x, qe):
    cell = x.get(qe) or {}
    c = cell.get("c") or cell.get("s") or {}
    return c if c.get("assets") is not None else None


def key_basis(x, qe):
    """Which basis does the XBRL key we validate against actually hold — 'c' or 's'? held_bs
    prefers consolidated, so this says which one it returned."""
    cell = x.get(qe) or {}
    if (cell.get("c") or {}).get("assets") is not None:
        return "c"
    if (cell.get("s") or {}).get("assets") is not None:
        return "s"
    return None


# ---- consolidated-BS recovery (prep only) ----------------------------------------------------
# locate() can pick the STANDALONE balance sheet when the CONSOLIDATED one is what the XBRL key
# holds: on many filers the consolidated BS has its assets-side and liabilities-side on separate,
# non-adjacent pages that each fail locate()'s single-page test, while the standalone is one
# compact page (GRASIM: standalone p8 TotAssets 77,980 vs consolidated assets p29 500,535 + liab
# p31). These helpers re-pick the right BS by the ACTUAL answer key (validate) or by Total-Assets
# size (fills: consolidation only ADDS subsidiary assets, so the largest Total Assets IS the
# consolidated one). Used in prep only. (locate() runs its strict markers first; its relaxed second
# pass only fires when those find no consolidated BS — see _relaxed_bs.)
_TA_RX = re.compile(r"^\s*total\s+assets\b", re.I)
_PPE_RX = re.compile(r"property,?\s*plant\s+and\s+equipment\b(?!.*expenditure)", re.I)
_ROU_RX = re.compile(r"right[\-\s]*of[\-\s]*use\s+asset", re.I)


def _page_total_assets(page):
    for label, nums in rows_of(page):
        if _TA_RX.search(label) and nums:
            return nums[0]
    return None


def _page_ppe_rou(page):
    """(PP&E line, separate Right-of-use line) parsed off an assets-side page, current-year col."""
    ppe = rou = None
    for label, nums in rows_of(page):
        if ppe is None and _PPE_RX.search(label) and nums:
            ppe = nums[0]
        if rou is None and _ROU_RX.search(label) and nums:
            rou = nums[0]
    return ppe, rou


def bs_assets_pages(doc, texts):
    """[(page_idx, current-year Total Assets)] for pages that are a real BS ASSETS side — a
    'Total Assets' line plus BS context (a BS title / equity marker / a liabilities marker on the
    page or an adjacent one), which excludes a segment schedule's per-segment 'total assets'."""
    out = []
    n = len(texts)
    for i in range(n):
        ta = _page_total_assets(doc[i])
        if ta is None or ta <= 0:
            continue
        t = texts[i]
        if (
            BS_PAGE.search(t)
            or BS_REAL.search(t)
            or BS_LIAB.search(t)
            or (i + 1 < n and BS_LIAB.search(texts[i + 1]))
            or (i - 1 >= 0 and BS_LIAB.search(texts[i - 1]))
        ):
            out.append((i, ta))
    return out


def _bs_pages_from_assets(texts, i):
    """Assets page i + its liabilities-side page (itself if single-page, else the nearest of the
    next two pages carrying the liab marker)."""
    n = len(texts)
    for j in (i, i + 1, i + 2):
        if 0 <= j < n and BS_LIAB.search(texts[j]):
            return [i] if j == i else [i, j]
    return [i]


_SCALES = (1.0, 0.1, 0.01, 1e-7)  # crore / million / lakh / absolute-rupees -> crore


def bs_pages_for_key(doc, texts, key):
    """The BS page(s) matching the key on BOTH Total Assets AND PP&E within 1% (ROU-aware), at a
    common unit scale — i.e. a page the holdout gate would accept. Matching both anchors (not
    assets alone) stops a low-consolidation filer's standalone page, whose assets sit ~1-2% from
    the consolidated key, from being mis-picked (MRF: standalone assets 29,096 vs consol key
    29,567). Closest-assets match wins. None if nothing qualifies. Uses only the exact key."""
    ka, kp = (key or {}).get("assets"), (key or {}).get("ppe")
    if not ka:
        return None
    best_i = None
    best_err = 0.01
    for i, ta in bs_assets_pages(doc, texts):
        pp, rr = _page_ppe_rou(doc[i])
        for scale in _SCALES:
            ea = abs(ta * scale - ka) / abs(ka)
            if ea > best_err:
                continue
            if kp:  # confirm PP&E at the SAME scale, ROU-aware
                if pp is None:
                    continue
                p, r = pp * scale, (rr or 0) * scale
                if not (abs(p - kp) / abs(kp) <= 0.01 or abs(p + r - kp) / abs(kp) <= 0.01):
                    continue
            best_err = ea
            best_i = i
    return _bs_pages_from_assets(texts, best_i) if best_i is not None else None


def bs_pages_largest(doc, texts):
    """The BS with the LARGEST Total Assets = the consolidated one. None if no BS assets page."""
    cands = bs_assets_pages(doc, texts)
    if not cands:
        return None
    return _bs_pages_from_assets(texts, max(cands, key=lambda c: c[1])[0])


def gate_ok(parsed, key):
    """parsed BS agrees with the XBRL-held BS for a held year? Compare Total Assets + PP&E."""
    for f in ("assets", "ppe"):
        p, k = parsed.get(f), key.get(f)
        if p is None or k is None or not k:
            return False
        if abs(p - k) / abs(k) > 0.01:
            return False
    return True


def _n500():
    m = json.load(open(os.path.join(DOCS, "nifty500_members_2025.json")))
    out = []
    for k in ("current_504", "union_652"):
        for s in m.get(k) or []:
            s = s[0] if isinstance(s, (list, tuple)) else s
            s = str(s).upper().replace(".NS", "")
            if s not in out:
                out.append(s)
    return out


def prep(outdir, limit, only):
    """NO-API vision prep (the repo's render -> Claude-reads -> merge pattern). For each vision-needed
    filer (gate-failed on text, not yet landed), render its consolidated balance-sheet + cash-flow
    pages for the newest HELD year (the gate) and every MISSING year, and append to a manifest a
    Claude reader consumes. Writes <outdir>/manifest.json = [{sym,fy,role,basis,pngs,src,key?}]."""
    os.makedirs(outdir, exist_ok=True)
    byid = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    gate = json.load(open(GATE_REPORT)) if os.path.exists(GATE_REPORT) else {}
    ledger = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    mp = os.path.join(outdir, "manifest.json")
    manifest = json.load(open(mp)) if os.path.exists(mp) else []
    done = {e["sym"] for e in manifest}
    o = session()
    n = 0
    for sym in _n500():
        if limit and n >= limit:
            break
        if only is not None and sym not in only:
            continue
        if only is None:
            gv = gate.get(sym)
            if not gv or gv.get("verdict") != "gate-failed" or gv.get("vtry"):
                continue  # only vision-needed
            if sym in ledger or sym in done:
                continue
            if isinstance(gv.get("vnil"), dict) and _fresh(
                gv["vnil"].get("d"), VNIL_COOLDOWN_DAYS * gv["vnil"].get("n", 1)
            ):
                continue  # prep already failed to render this recently — don't re-fetch every night
        code = byid.get(sym)
        if not code:
            continue
        x = slice_x(sym)
        held = {fy: k for fy in FYS if (k := held_bs(x, "%d0331" % fy))}
        if not held:
            continue
        val_fy = max(held)
        miss = [fy for fy in FYS if fy not in held]
        if not miss:
            continue  # 0-fill "jammer": every FY-end already held, nothing to fill —
        # skip it BEFORE any BSE fetch/render and WITHOUT counting it against --limit, so each
        # batch spends its whole limit on symbols that can actually land (was ~42% wasted).
        kbasis = key_basis(x, "%d0331" % val_fy)  # 'c' or 's': the basis the answer key holds
        need_recover = False  # set True once the validate re-pick fires
        entries = []
        for role, fy in [("validate", val_fy)] + [("fill", f) for f in miss]:
            try:
                fl = result_filings(o, code, "%d0401" % fy, "%d0901" % fy)
            except BseBlocked:
                raise
            except Exception:
                continue
            for _ann, att in fl[:8]:
                pdf = download(o, att)
                if not pdf:
                    continue
                loc = locate(
                    pdf, fy, kbasis
                )  # the validated basis, as the text pass already does (PROZONER, §148): without it
                if not loc:
                    continue  # a standalone-key filer's fill got the consolidated page -> basis-mix skip at merge
                b, bs_pi, cf_pi = loc
                # CONSOLIDATED-BS recovery: locate() may have picked the standalone BS. For the
                # validate year, ONLY when locate's page does not already satisfy the key, re-pick
                # by the exact key (closest Total-Assets match). If that fires, the filer needs
                # recovery, so also re-pick its fill years to the largest-Total-Assets (=consolidated)
                # BS. locate()'s pick is otherwise kept untouched, so working filers never change.
                try:
                    _d = fitz.open(stream=pdf, filetype="pdf")
                    _tx = [_d[k].get_text() for k in range(len(_d))]
                    if role == "validate":
                        _ka = held[val_fy].get("assets")
                        _lta = _page_total_assets(_d[_as_list(bs_pi)[0]])
                        _loc_ok = (
                            _lta is not None
                            and _ka
                            and any(
                                abs(_lta * s - _ka) / abs(_ka) <= 0.02
                                for s in (1.0, 0.1, 0.01, 1e-7)
                            )
                        )
                        if not _loc_ok:
                            _np = bs_pages_for_key(_d, _tx, held[val_fy])
                            if _np and _np != _as_list(bs_pi):
                                bs_pi = _np
                                b = kbasis or b
                                need_recover = True
                    elif kbasis == "c" and need_recover:
                        _np = bs_pages_largest(_d, _tx)
                        if _np and _np != _as_list(bs_pi):
                            bs_pi = _np
                            b = "c"
                    _d.close()
                except Exception:
                    pass
                pngs = []
                for j, pi in enumerate(
                    _as_list(bs_pi)
                ):  # 1 page, or a 2-page [assets, liabilities] split
                    fn = "%s_%d_bs%s.png" % (sym, fy, "" if j == 0 else str(j + 1))
                    open(os.path.join(outdir, fn), "wb").write(render(pdf, pi))
                    pngs.append(fn)
                for j, pi in enumerate(
                    cf_span(_page_texts(pdf), cf_pi)
                ):  # 1 page, or a statement continued onto the next
                    cf_fn = "%s_%d_cf%s.png" % (sym, fy, "" if j == 0 else str(j + 1))
                    open(os.path.join(outdir, cf_fn), "wb").write(render(pdf, pi))
                    pngs.append(cf_fn)
                e = {
                    "sym": sym,
                    "fy": fy,
                    "role": role,
                    "basis": b,
                    "pngs": pngs,
                    "src": "bse:" + att,
                }
                if role == "validate":
                    e["key"] = {f: held[val_fy].get(f) for f in ("assets", "ppe", "eq", "borr")}
                entries.append(e)
                break
            time.sleep(0.2)
        if any(e["role"] == "validate" for e in entries):
            manifest.extend(entries)
            n += 1
            json.dump(manifest, open(mp, "w"), indent=0)
            print(
                "%-11s prepped: val FY%d + %d fill-years (%d pages)"
                % (sym, val_fy, len(entries) - 1, sum(len(e["pngs"]) for e in entries))
            )
        elif only is None:
            # couldn't render even the validate page (no filings / no locatable BS): mark vnil so
            # the queue ADVANCES — otherwise this symbol is re-fetched from BSE every single night.
            # Not counted against --limit (that budget is for fill-bearing symbols); retried after
            # VNIL_COOLDOWN_DAYS x n. Persist immediately so a mid-run crash doesn't lose it.
            gv = gate.setdefault(sym, {})
            prev = gv.get("vnil") if isinstance(gv.get("vnil"), dict) else {}
            gv["vnil"] = {"d": _today(), "n": prev.get("n", 0) + 1, "why": "no-validate-render"}
            json.dump(gate, open(GATE_REPORT, "w"), separators=(",", ":"), sort_keys=True)
            print("%-11s NOT prepped: no validate render -> vnil (n=%d)" % (sym, gv["vnil"]["n"]))
    print("PREP DONE: %d symbols, %d manifest entries -> %s" % (n, len(manifest), mp))


def main():
    args = sys.argv[1:]
    if "--prep" in args:
        outdir = args[args.index("--prep") + 1]
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
        only = (
            {s.strip().upper() for s in args[args.index("--only") + 1].split(",")}
            if "--only" in args
            else None
        )
        prep(outdir, limit, only)
        return
    only = None
    limit = None
    redo = "--redo" in args
    if "--only" in args:
        only = {s.strip().upper() for s in args[args.index("--only") + 1].split(",")}
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    # wall-clock budget: stop BETWEEN symbols (each is already checkpointed) so CI's commit step runs
    # before the job timeout. 2026-09-27: with BSE answering again, 3 runs hit the 55-min timeout
    # mid-batch and were killed before committing — every symbol they worked was lost.
    max_min = float(args[args.index("--max-minutes") + 1]) if "--max-minutes" in args else None
    t0 = time.time()
    byid = json.load(open(os.path.join(HERE, "bse_scrips.json")))["by_id"]
    m = json.load(open(os.path.join(DOCS, "nifty500_members_2025.json")))
    n500 = []
    for k in ("current_504", "union_652"):
        for s in m.get(k) or []:
            s = s[0] if isinstance(s, (list, tuple)) else s
            s = str(s).upper().replace(".NS", "")
            if s not in n500:
                n500.append(s)
    ledger = json.load(open(LEDGER)) if os.path.exists(LEDGER) else {}
    gate = json.load(open(GATE_REPORT)) if os.path.exists(GATE_REPORT) else {}
    FYS = [2025, 2024, 2023, 2022, 2021, 2020]  # newest first
    # --only is a full target list, not a filter on the N500 queue: the universe backfill (§148)
    # runs it over every listed company >= Rs 100 cr, most of which were never Nifty-500 members
    todo = n500 if only is None else sorted(only)
    o = session()
    processed = 0
    for sym in todo:
        if limit and processed >= limit:
            break
        if max_min and time.time() - t0 > max_min * 60:
            print(
                "time budget %.0f min reached after %d symbols — stopping; progress is saved"
                % (max_min, processed)
            )
            break
        code = byid.get(sym)
        if not code:
            continue
        if not redo and only is None:
            gv = gate.get(sym)
            if gv and (gv.get("verdict") == "trusted" or gv.get("vtry")):
                continue  # settled; a text-only gate-fail is retried once a vision key exists
            if (
                gv
                and gv.get("verdict") == "no-xbrl-year-to-validate"
                and not held_bs(slice_x(sym), "20260331")
            ):
                continue  # still nothing to validate on (FY26 counts — §148e)
            # queue-advance: don't re-chew a symbol the token-free pass just tried, or one prep
            # can't render. Without this the --limit window re-attempts the same head every run
            # and never reaches the tail (the 2026-09 jam). Skips expire (TTRY/VNIL cooldowns).
            if (
                gv
                and not os.environ.get("ANTHROPIC_API_KEY")
                and _fresh(gv.get("ttry"), TTRY_COOLDOWN_DAYS)
            ):
                continue
            if (
                gv
                and isinstance(gv.get("vnil"), dict)
                and _fresh(gv["vnil"].get("d"), VNIL_COOLDOWN_DAYS * gv["vnil"].get("n", 1))
            ):
                continue
        x = slice_x(sym)
        # which FYs do we already hold (validation) vs miss (fill)?
        held = {fy: held_bs(x, "%d0331" % fy) for fy in FYS}
        held = {fy: k for fy, k in held.items() if k}
        miss = [
            fy
            for fy in FYS
            if "%d0331" % fy not in [q for q in x if held_bs(x, q)] and fy not in held
        ]
        if not held and not held_bs(
            x, "20260331"
        ):  # FY2026 is a validation year too (below): a filer whose
            # only XBRL balance sheet is FY26 (130 of the 865 queued, e.g. INA — SME years on BSE only) was refused here
            gate.setdefault(sym, {}).update({"verdict": "no-xbrl-year-to-validate"})
            json.dump(gate, open(GATE_REPORT, "w"), separators=(",", ":"), sort_keys=True)
            continue
        # the gate: try each XBRL-held year newest first (FY2026 included — a validation year, never
        # a fill year) until one passes; one awkward filing no longer sinks the symbol (§148 — in a
        # 40-symbol sample of gate-fails, 10 matched Total Assets exactly on FY2026, never tried)
        got = {}
        basis = None
        trusted = False
        method = None
        note = None
        unit = None
        add_rou = False
        val_assets = None
        val_cf = None
        val_src = None
        vheld = dict(held)
        k26 = held_bs(x, "20260331")
        if k26:
            vheld[2026] = k26
        val_fy = max(vheld)
        for vfy in sorted(vheld, reverse=True)[:3]:
            try:
                fl = result_filings(o, code, "%d0401" % vfy, "%d0901" % vfy)
            except BseBlocked:
                raise  # a block aborts the run — never a gate-fail (§148: 316 cos)
            except Exception as e:
                note = f"filings-err:{str(e)[:30]}"
                fl = []
            for _ann, att in fl[:8]:
                pdf = download(o, att)
                if not pdf:
                    continue
                loc = locate(pdf, vfy)
                if not loc:
                    continue
                b, bs_pi, cf_pi = loc
                p = text_read(pdf, bs_pi, cf_pi)
                for k in unit_candidates(p):
                    ok, add_rou = merge_gate(
                        scale_read(p, k), vheld[vfy]
                    )  # ROU-aware, zero-PP&E aware
                    if ok:
                        trusted, basis, method, unit, val_fy = True, b, "text", k, vfy
                        val_assets = scale_read(p, k).get("assets")
                        val_cf, val_src = scale_text(p, k), att
                        break
                if trusted:
                    break
                v = vision_read(pdf, bs_pi, cf_pi, sym, vfy)  # None locally (no key) / on CI reads
                if v and gate_ok(v[1], vheld[vfy]):
                    trusted, basis, method, val_fy = True, v[0], "vision", vfy
                    val_cf, val_src = v[1], att
                    break
            if trusted:
                break
        entry = gate.setdefault(
            sym, {}
        )  # UPDATE, don't replace: carry over vnil/na marks prep wrote
        entry.update(
            {
                "verdict": "trusted" if trusted else "gate-failed",
                "val_fy": val_fy,
                "basis": basis,
                "method": method,
                "note": note,
                "unit": unit,
                "vtry": bool(os.environ.get("ANTHROPIC_API_KEY")),
            }
        )
        if not trusted and not os.environ.get("ANTHROPIC_API_KEY"):
            entry["ttry"] = _today()  # token-free text attempt -> cooldown so the walk advances
        elif trusted:
            entry.pop("ttry", None)
            entry.pop("vnil", None)  # settled clean
        json.dump(gate, open(GATE_REPORT, "w"), separators=(",", ":"), sort_keys=True)
        if not trusted:
            processed += 1
            print("%-11s GATE-FAILED (val FY%d) %s" % (sym, val_fy, note or ""))
            continue
        # 2) trusted -> fill the missing FYs with the SAME method that passed the gate
        for fy in miss:
            frm, to = "%d0401" % fy, "%d0901" % fy
            try:
                fl = result_filings(o, code, frm, to)
            except BseBlocked:
                raise
            except Exception:
                continue
            for _ann, att in fl[:8]:
                pdf = download(o, att)
                if not pdf:
                    continue
                loc = locate(pdf, fy, basis)
                if not loc:
                    continue
                b, bs_pi, cf_pi = loc
                if method == "text":
                    p = text_read(pdf, bs_pi, cf_pi)
                    k = p.get("_unit") or unit  # the year's own stated unit, else the validated one
                    u_src = "stated" if p.get("_unit") else "inherited"
                    p = scale_text(p, k)
                    p["u"] = u_src
                    if add_rou and p.get("ppe") is not None:
                        p["ppe"] = round(
                            p["ppe"] + (p.get("rou") or 0), 2
                        )  # the convention the gate proved
                    p.pop("rou", None)  # not a ledger field (merge_annual_bscf FIELDS)
                    # an INHERITED unit is only safe when the year sits within 7x of the validated
                    # year's Total Assets — a wrong unit is off by exactly 10x / 100x (§148)
                    # EVERY fill year must sit within 7x of the validated year's Total Assets — a stated
                    # unit is no guarantee (9 first-pass cells read a note number / sub-total as Total
                    # Assets: AARTISURF FY22 0.4 vs 402 cr, GIPCL FY20 0.03 vs 4,487; §148)
                    if (
                        not val_assets
                        or p.get("assets") is None
                        or not (1 / 7 <= p["assets"] / val_assets <= 7)
                    ):
                        continue
                else:
                    v = vision_read(pdf, bs_pi, cf_pi, sym, fy)
                    if not v:
                        continue
                    b, p = v
                if p.get("assets") is None or b != basis:
                    continue  # same basis we validated on
                cell = {"b": b, "m": method, "src": "bse:" + att}
                cell.update({k: val for k, val in p.items() if val is not None})
                got["%d0331" % fy] = cell
                break
            time.sleep(0.3)
        # 3) the validate year's OWN cash flow, when XBRL holds that year's balance sheet but no cash
        #    flow (PFIZER FY25): a CF-only cell (v=1). Never its BS fields — those are XBRL's.
        vq = "%d0331" % val_fy
        if val_cf is not None and vq not in (ledger.get(sym) or {}):
            vc = validate_cf_cell(
                val_cf, (x.get(vq) or {}).get(basis), basis, method, "bse:" + val_src
            )
            if vc:
                got[vq] = vc
        if got:
            ledger.setdefault(sym, {}).update(got)
            json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"), sort_keys=True)
        processed += 1
        print(
            "%-11s trusted(%s,%s) basis=%s  filled %d FYs: %s"
            % (sym, val_fy, method, basis, len(got), sorted(got))
        )
    n = sum(len(v) for k, v in ledger.items())
    print(
        "DONE. ledger: %d symbols, %d symbol-years. gate report: %s"
        % (len(ledger), n, os.path.basename(GATE_REPORT))
    )


if __name__ == "__main__":
    try:
        main()
    except BseBlocked as e:
        # the block stops the run BEFORE the symbol in hand is recorded; every symbol already written stands.
        # 2026-09-25: without this every 6-hourly CI run re-stamped 150 symbols 'gate-failed: 403' (§148)
        print(f"::warning::{e} — run stopped, nothing recorded for the symbol in hand")
