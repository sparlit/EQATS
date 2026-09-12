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
fields: assets, sc, oeq, borr, ppe, cwip, gw, intg, invst, rec, pay, invnt, cfo, cfi, cff, capex, cf_tax
Resumable: one symbol at a time, checkpoints after each; --only / --limit / --redo.
Run: python -X utf8 scripts/fetch_annual_bscf.py [--only SYM,SYM] [--limit N] [--redo]
"""
import base64
import contextlib
import gzip
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.request

import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.join(HERE, "..", "docs")
LEDGER = os.path.join(HERE, "annual_bscf.json")
GATE_REPORT = os.path.join(
    HERE, "annual_bscf_gate.json"
)  # TRACKED (not scripts/_*, which is gitignored) so resume persists in CI
FYS = [2025, 2024, 2023, 2022, 2021, 2020]  # FY-ends to fill, newest first
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"


# ---- BSE fetch (narrow window + strCat=Result — BSE now rejects wide ranges) ------------------
def session():
    o = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    with contextlib.suppress(Exception):
        o.open(urllib.request.Request("https://www.bseindia.com/", headers={"User-Agent": UA}), timeout=30).read()
    return o


def get(o, u, b=False):
    r = o.open(
        urllib.request.Request(u, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}), timeout=60
    )
    raw = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return raw if b else raw.decode("utf-8", "replace")


def result_filings(o, code, frm, to, pages=6):
    out = []
    for pg in range(1, pages + 1):
        u = (
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=%d&strCat=Result"
            "&strPrevDate=%s&strScrip=%d&strSearch=P&strToDate=%s&strType=C" % (pg, frm, code, to)
        )
        try:
            rows = json.loads(get(o, u)).get("Table", [])
        except Exception:
            break
        for r in rows:
            if r.get("ATTACHMENTNAME"):
                ann = re.sub(r"[^0-9]", "", (r.get("NEWS_DT") or ""))[:8]
                out.append((int(ann) if ann else 0, r["ATTACHMENTNAME"]))
        if len(rows) < 50:
            break
        time.sleep(0.5)
    return sorted(set(out))


def download(o, att):
    for base in ("AttachHis", "AttachLive"):
        try:
            d = get(o, f"https://www.bseindia.com/xml-data/corpfiling/{base}/{att}", b=True)
            if d[:4] == b"%PDF":
                return d
        except Exception:
            continue
    return None


# ---- number + line parsing -------------------------------------------------------------------
def to_num(tok):
    t = tok.strip()
    neg = t.startswith(("(", "-"))
    m = re.search(r"\d[\d,]*(?:\.\d+)?", t)  # numeric core, tolerating trailing junk (606,084.)
    if not m:
        return None
    core = m.group(0).rstrip(".").replace(",", "")
    if not core:
        return None
    try:
        v = float(core)
    except ValueError:
        return None
    return -v if neg else v


ISNUM = re.compile(r"^[\(\-]?\d[\d,]*(?:\.\d+)?[\).,;:!]*%?$")  # numeric with tolerated trailing junk


def rows_of(page):
    """Reconstruct table rows from word boxes: group words by y, split each row into its
    label text (left) and its numeric columns (right, by x). The PDF text layer returns a
    table's labels and numbers on different lines, so line-based reading fails — this doesn't."""
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
    rows = []
    for _, toks in merged:
        toks.sort()
        label = " ".join(t for _, t in toks)
        nums = [to_num(t.rstrip("%")) for _, t in toks if ISNUM.match(t.strip())]
        nums = [n for n in nums if n is not None]
        rows.append((label, nums))
    return rows


def parse_rows(rows, specs_one, specs_sum):
    out = {}
    for field, rx, sign in specs_one:
        for label, nums in rows:
            if re.search(rx, label, re.IGNORECASE) and nums:
                out[field] = round(sign * nums[0], 2)
                break
    for field, rx in specs_sum:
        tot = 0.0
        seen = False
        for label, nums in rows:
            if re.search(rx, label, re.IGNORECASE) and nums:
                tot += abs(nums[0])
                seen = True
        if seen:
            out[field] = round(tot, 2)
    return out


# label -> field. Order matters: more specific first. Some fields SUM multiple matching lines.
BS_ONE = [  # (field, label regex, sign) — first matching line wins
    ("assets", r"^\s*total\s+assets\b", 1),
    ("sc", r"^\s*(?:\([a-z]\)\s*)?equity\s+share\s+capital\b", 1),
    ("oeq", r"^\s*(?:\([a-z]\)\s*)?other\s+equity\b", 1),
    ("ppe", r"property,?\s*plant\s+and\s+equipment\b(?!.*expenditure)", 1),
    ("cwip", r"capital\s+work[\-\s]*in[\-\s]*progress\b", 1),
    ("gw", r"^\s*(?:\([a-z]\)\s*)?goodwill\b", 1),
    ("invnt", r"^\s*(?:\([a-z]\)\s*)?inventories\b", 1),
]
BS_SUM = [  # (field, label regex) — SUM the first-col of every matching line (non-current + current)
    ("borr", r"^\s*(?:\([a-z]+\)\s*|\(i+\)\s*)?borrowings\b"),
    ("invst", r"^\s*(?:\([a-z]+\)\s*|\(i+\)\s*)?investments?\b"),
    ("intg", r"other\s+intangible\s+assets\b(?!\s+under)"),
    ("rec", r"trade\s+receivables\b"),
    ("pay", r"trade\s+payables\b|dues\s+of\s+(?:micro|creditors)"),
]
CF_ONE = [
    ("cfo", r"net\s+cash\s+(?:flow|generated|used).{0,30}operating", 1),
    ("cfi", r"net\s+cash\s+(?:flow|used|from).{0,30}investing", 1),
    ("cff", r"net\s+cash\s+(?:flow|used|from).{0,30}financing", 1),
    ("cf_tax", r"(?:income\s+)?tax(?:es)?\s+paid\b|direct\s+taxes\s+paid", -1),
]

BS_PAGE = re.compile(r"(balance sheet|assets and liabilities|statement of assets)", re.IGNORECASE)
BS_REAL = re.compile(r"(total\s+equity|equity\s+share\s+capital|other\s+equity)", re.IGNORECASE)  # equity marker
BS_ASSET = re.compile(
    r"total[\s\-–—:.]{0,4}assets", re.IGNORECASE
)  # the real BS foots to a Total Assets line; a P&L results page / notes page does not
BS_LIAB = re.compile(
    r"trade\s+payables|total[\s\-–—:.]{0,4}equity\s+and\s+liabilit", re.IGNORECASE
)  # POSITIVE liabilities-side marker: a real BS/statement-of-assets-and-liabilities always has it; a P&L results page, a notes page, or a per-segment "assets & liabilities" schedule does NOT (so this excludes the decoys without over-excluding a real BS page that merely shares a page with segment text)
CF_PAGE = re.compile(r"cash\s*flow", re.IGNORECASE)
CF_REAL = re.compile(r"operating\s+activit|investing\s+activit|financing\s+activit", re.IGNORECASE)
CONSOL = re.compile(r"consolidated", re.IGNORECASE)
STANDAL = re.compile(r"standalone", re.IGNORECASE)


def locate(pdf, want_year):
    """Confirm this PDF is the FY-end audited result and return (basis, bs_pi, cf_pi) — the
    consolidated BS + CF page indices (standalone fallback). None otherwise."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    texts = [doc[i].get_text() for i in range(len(doc))]
    doc.close()
    yr = str(want_year)
    if not any(
        re.search(r"(year ended|ended)\s+(31st?\s+)?march[,\s]+" + yr, t, re.IGNORECASE)
        or (f"31.03.{yr[-2:]}") in t.replace(" ", "")
        for t in texts
    ):
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

    if bs_con is not None:
        return "c", bs_pages(bs_con), (cf_con if cf_con is not None else cf_std)
    if bs_std is not None:
        return "s", bs_pages(bs_std), (cf_std if cf_std is not None else cf_con)
    return None


def _as_list(x):
    return list(x) if isinstance(x, (list, tuple)) else [x]


def text_read(pdf, bs_pi, cf_pi):
    """Word-grid text parse (free, exact — but fails on filers who shade the current-year column).
    bs_pi may be one page or a two-page [assets, liabilities] split."""
    doc = fitz.open(stream=pdf, filetype="pdf")
    fields = {}
    for pi in _as_list(bs_pi):
        for k, v in parse_rows(rows_of(doc[pi]), BS_ONE, BS_SUM).items():
            fields.setdefault(k, v)  # first page (assets side) wins any shared key
    if cf_pi is not None:
        fields.update(parse_rows(rows_of(doc[cf_pi]), CF_ONE, []))
    doc.close()
    return fields


def render(pdf, pi, dpi=200):
    doc = fitz.open(stream=pdf, filetype="pdf")
    png = doc[pi].get_pixmap(dpi=dpi).tobytes("png")
    doc.close()
    return png


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
]


def _schema():
    props = {f: {"type": ["number", "null"]} for f in _FIELDS}
    props["ok"] = {"type": "boolean"}
    props["basis"] = {"type": "string", "enum": ["C", "S"]}
    return {"type": "object", "additionalProperties": False, "properties": props, "required": ["ok", "basis", *_FIELDS]}


_VPROMPT = (
    "These images are pages from %s's audited annual results for the year ended 31 March %d: a BALANCE "
    "SHEET and a CASH FLOW STATEMENT. Read the numbers as printed (the current-year column — the LEFT "
    "data column, 'As at/Year ended 31 March %d'), in the statement's own unit (almost always ₹ crore; "
    "if the header says lakh/lakhs divide by 100, if absolute rupees divide by 1e7). Prefer the "
    "CONSOLIDATED statement if both consolidated and standalone are shown; set basis 'C' or 'S' for which "
    "you used. Extract, all ₹ crore, null if a line is genuinely absent:\n"
    "assets=Total Assets; sc=Equity Share Capital; oeq=Other Equity (reserves); blt=non-current "
    "Borrowings; bst=current Borrowings; borr=blt+bst (interest-bearing borrowings only, EXCLUDE lease "
    "liabilities); ppe=Property Plant & Equipment (net block); cwip=Capital Work-in-Progress; gw=Goodwill; "
    "intg=Other Intangible Assets; invst=total Investments (non-current + current); rec=total Trade "
    "Receivables; pay=total Trade Payables; invnt=Inventories; cfo=Net Cash Flow FROM OPERATING "
    "activities; cfi=Net Cash Flow FROM INVESTING activities; cff=Net Cash Flow FROM FINANCING "
    "activities; capex=cash spent on purchase of PP&E/intangibles (investing outflow, as a positive "
    "number); cf_tax=income taxes paid (operating, positive number). If these are the wrong company or "
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
    if cf_pi is not None:
        pngs.append(render(pdf, cf_pi))
    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": base64.standard_b64encode(p).decode()},
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
    return b, {f: d[f] for f in _FIELDS if d.get(f) is not None}


# ---- slice answer key (what we already hold from XBRL) ----------------------------------------
def slice_x(sym):
    p = os.path.join(DOCS, "fin", "{}.json".format(re.sub(r"[^A-Za-z0-9._-]", "_", sym)))
    if not os.path.exists(p):
        return {}
    try:
        return json.load(open(p)).get("x") or {}
    except Exception:
        return {}


def held_bs(x, qe):
    cell = x.get(qe) or {}
    c = cell.get("c") or cell.get("s") or {}
    return c if c.get("assets") is not None else None


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
        entries = []
        for role, fy in [("validate", val_fy)] + [("fill", f) for f in miss]:
            try:
                fl = result_filings(o, code, "%d0401" % fy, "%d0901" % fy)
            except Exception:
                continue
            for _ann, att in fl[:8]:
                pdf = download(o, att)
                if not pdf:
                    continue
                loc = locate(pdf, fy)
                if not loc:
                    continue
                b, bs_pi, cf_pi = loc
                pngs = []
                for j, pi in enumerate(_as_list(bs_pi)):  # 1 page, or a 2-page [assets, liabilities] split
                    fn = "%s_%d_bs%s.png" % (sym, fy, "" if j == 0 else str(j + 1))
                    open(os.path.join(outdir, fn), "wb").write(render(pdf, pi))
                    pngs.append(fn)
                if cf_pi is not None:
                    cf_fn = "%s_%d_cf.png" % (sym, fy)
                    open(os.path.join(outdir, cf_fn), "wb").write(render(pdf, cf_pi))
                    pngs.append(cf_fn)
                e = {"sym": sym, "fy": fy, "role": role, "basis": b, "pngs": pngs, "src": "bse:" + att}
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
    print("PREP DONE: %d symbols, %d manifest entries -> %s" % (n, len(manifest), mp))


def main():
    args = sys.argv[1:]
    if "--prep" in args:
        outdir = args[args.index("--prep") + 1]
        limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
        only = {s.strip().upper() for s in args[args.index("--only") + 1].split(",")} if "--only" in args else None
        prep(outdir, limit, only)
        return
    only = None
    limit = None
    redo = "--redo" in args
    if "--only" in args:
        only = {s.strip().upper() for s in args[args.index("--only") + 1].split(",")}
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
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
    todo = [s for s in n500 if (only is None or s in only)]
    o = session()
    processed = 0
    for sym in todo:
        if limit and processed >= limit:
            break
        code = byid.get(sym)
        if not code:
            continue
        if not redo and only is None:
            gv = gate.get(sym)
            if gv and (gv.get("verdict") in ("trusted", "no-xbrl-year-to-validate") or gv.get("vtry")):
                continue  # settled; a text-only gate-fail is retried once a vision key exists
        x = slice_x(sym)
        # which FYs do we already hold (validation) vs miss (fill)?
        held = {fy: held_bs(x, "%d0331" % fy) for fy in FYS}
        held = {fy: k for fy, k in held.items() if k}
        miss = [fy for fy in FYS if "%d0331" % fy not in [q for q in x if held_bs(x, q)] and fy not in held]
        if not held:
            gate[sym] = {"verdict": "no-xbrl-year-to-validate"}
            continue
        val_fy = max(held)  # newest held year = the gate
        got = {}
        basis = None
        trusted = False
        method = None
        note = None
        # 1) validate on the newest held year — text first (free), vision fallback (CI, needs key)
        frm, to = "%d0401" % val_fy, "%d0901" % val_fy
        try:
            fl = result_filings(o, code, frm, to)
        except Exception as e:
            note = f"filings-err:{str(e)[:30]}"
            fl = []
        for _ann, att in fl[:8]:
            pdf = download(o, att)
            if not pdf:
                continue
            loc = locate(pdf, val_fy)
            if not loc:
                continue
            b, bs_pi, cf_pi = loc
            p = text_read(pdf, bs_pi, cf_pi)
            if gate_ok(p, held[val_fy]):
                trusted, basis, method = True, b, "text"
                break
            v = vision_read(pdf, bs_pi, cf_pi, sym, val_fy)  # None locally (no key) / on CI reads
            if v and gate_ok(v[1], held[val_fy]):
                trusted, basis, method = True, v[0], "vision"
                break
        gate[sym] = {
            "verdict": "trusted" if trusted else "gate-failed",
            "val_fy": val_fy,
            "basis": basis,
            "method": method,
            "note": note,
            "vtry": bool(os.environ.get("ANTHROPIC_API_KEY")),
        }
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
            except Exception:
                continue
            for _ann, att in fl[:8]:
                pdf = download(o, att)
                if not pdf:
                    continue
                loc = locate(pdf, fy)
                if not loc:
                    continue
                b, bs_pi, cf_pi = loc
                if method == "text":
                    p = text_read(pdf, bs_pi, cf_pi)
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
        if got:
            ledger.setdefault(sym, {}).update(got)
            json.dump(ledger, open(LEDGER, "w"), separators=(",", ":"), sort_keys=True)
        processed += 1
        print("%-11s trusted(%s,%s) basis=%s  filled %d FYs: %s" % (sym, val_fy, method, basis, len(got), sorted(got)))
    n = sum(len(v) for k, v in ledger.items())
    print(
        "DONE. ledger: %d symbols, %d symbol-years. gate report: %s" % (len(ledger), n, os.path.basename(GATE_REPORT))
    )


if __name__ == "__main__":
    main()
