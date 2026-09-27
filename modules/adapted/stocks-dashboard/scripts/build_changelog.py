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
"""
Download NSE/niftyindices reconstitution press-release PDFs and parse them into a
per-index change log: {index: [{eff, excluded:[...], included:[...], src}]}.

Output: scripts/_changelog.json  (then reconstruct_validate.py checks it).
Run: python -X utf8 build_changelog.py
"""
import json
import os
import re
import time
import urllib.request

from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_pr_cache")
os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
BASE = "https://www.niftyindices.com/Press_Release/"

FILES = [
    "16032020",
    "28082019",
    "13062019",
    "08042019",
    "20032019",
    "25022019",
    "20022019",
    "10062026",
    "21052026_1",
    "20052026_1",
    "15052026",
    "08052026",
    "04052026",
    "23042026",
    "12032026",
    "23022026",
    "20022026_2",
    "20012026_2",
    "26122025",
    "23122025",
    "11122025",
    "01122025",
    "17112025_1",
    "20102025",
    "17102025",
    "25092025_1",
    "15092025",
    "15092025_1",
    "22082025",
    "22082025_1",
    "24072025",
    "10072025",
    "04072025",
    "03072025",
    "02072025",
    "26062025_1",
    "25062025_1",
    "23062025_1",
    "06062025",
    "05062025",
    "04062025",
    "03062025_1",
    "29052025",
    "07052025",
    "21042025_1",
    "04042025_2",
    "25032025",
    "17032025",
    "13032025",
    "06032025",
    "25022025_1",
    "21022025",
    "20022025",
    "18022025",
    "31122024",
    "30122024_1",
    "11122024",
    "22112024",
    "10102024",
    "10102024_1",
    "04102024",
    "25092024",
    "23092024",
    "27082024",
    "23082024",
    "23082024_1",
    "24072024",
    "21062024_1",
    "07062024",
    "22052024",
    "24042024",
    "24042024_1",
    "19032024",
    "14032024",
    "28022024",
    "30012024",
    "19012024",
    "10012024",
    "07122023",
    "09112023",
    "17102023",
    "15092023",
    "23082023",
    "17082023",
    "24072023",
    "04072023",
    "27062023",
    "09062023",
    "19042023_1",
    "06032023",
    "21022023",
    "17022023_1",
    "09022023_1",
    "22122022",
    "06122022",
    "20102022",
    "20102022_1",
    "16092022",
    "01092022",
    "23082022",
    "26072022",
    "11072022",
    "15062022",
    "24052022",
    "06042022",
    "05042022",
    "05042022_1",
    "08032022",
    "24022022_1",
    "08122021",
    "22102021",
    "08102021",
    "20092021",
    "15092021",
    "23082021",
    "15062021",
    "22042021",
    "10032021",
    "23022021",
    "11122020",
    "18112020",
    "26102020",
    "30092020",
    "07092020",
    "20082020",
    "02072020_1",
    "10062020",
    "12032020",
    "18022020",
    "09012020",
    "19122019",
    "18122019",
    "16122019",
    "28112019",
    "17092019",
    "17092019_1",
    "13032019",
    "24092018",
    "31082018",
    "01082018",
    "15062018",
    "15062018_1",
    "06032018",
    "29082017",
    "27042017",
    "07032017",
    "17102016",
    "12082016",
    "18072016",
    "28042016",
    "22042016",
    "22022016_2",
    "11012016",
    "07122015",
    "18092015",
    "24082015",
    "12082015",
    "05062015",
    "29042015",
    "20042015",
    "18032015_2",
    "20022015",
    "23012015",
    "21012015",
]

_CANON_LIST = [  # (display name, [normalised heading aliases]) — ALL 27 tracked indexes
    ("Nifty 50", ["nifty50", "cnxnifty"]),
    ("Nifty Next 50", ["niftynext50", "cnxnifty50junior", "niftyjunior"]),
    ("Nifty 100", ["nifty100", "cnx100"]),
    ("Nifty 200", ["nifty200", "cnx200"]),
    ("Nifty 500", ["nifty500", "cnx500"]),
    ("Nifty Midcap 50", ["niftymidcap50", "cnxmidcap50"]),
    ("Nifty Midcap 100", ["niftymidcap100", "cnxmidcap"]),
    ("Nifty Midcap 150", ["niftymidcap150"]),
    ("Nifty Smallcap 50", ["niftysmallcap50"]),
    ("Nifty Smallcap 100", ["niftysmallcap100", "cnxsmallcap"]),
    ("Nifty Smallcap 250", ["niftysmallcap250"]),
    ("Nifty LargeMidcap 250", ["niftylargemidcap250"]),
    ("Nifty MidSmallcap 400", ["niftymidsmallcap400"]),
    ("Nifty Bank", ["niftybank", "cnxbank", "banknifty"]),
    ("Nifty IT", ["niftyit", "cnxit"]),
    ("Nifty Pharma", ["niftypharma", "cnxpharma"]),
    ("Nifty Auto", ["niftyauto", "cnxauto"]),
    ("Nifty FMCG", ["niftyfmcg", "cnxfmcg"]),
    ("Nifty Metal", ["niftymetal", "cnxmetal"]),
    ("Nifty Energy", ["niftyenergy", "cnxenergy"]),
    ("Nifty Realty", ["niftyrealty", "cnxrealty"]),
    ("Nifty Media", ["niftymedia", "cnxmedia"]),
    ("Nifty Healthcare", ["niftyhealthcare"]),
    ("Nifty Consumer Durables", ["niftyconsumerdurables"]),
    ("Nifty Oil & Gas", ["niftyoilgas"]),
    ("Nifty PSU Bank", ["niftypsubank", "cnxpsubank"]),
    ("Nifty MNC", ["niftymnc", "cnxmnc"]),
]
CANON = {}
for _disp, _keys in _CANON_LIST:
    for _k in _keys:
        CANON[_k] = _disp


def canon_index(name):
    n = re.sub(r"[^a-z0-9]", "", name.lower())
    n = re.sub(r"index$", "", n)  # "Nifty Bank Index" -> "niftybank"
    n = re.sub(r"^spcnx", "cnx", n)  # IISL-era "S&P CNX 500" / "S&P CNX Nifty" (2026-09-23, §141e)
    return CANON.get(n)


def get(url, tries=5):
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception as e:
            last = e
            time.sleep(3)
    raise last


def download(stem, tries=5):
    fp = os.path.join(CACHE, stem + ".pdf")
    if os.path.exists(fp) and os.path.getsize(fp) > 1000:
        return fp
    try:
        raw = get(BASE + "ind_prs" + stem + ".pdf", tries=tries)
        if raw[:4] != b"%PDF":
            return None
        open(fp, "wb").write(raw)
        return fp
    except Exception:
        return None


def recent_stems(days=80):
    """FRESHNESS SAFEGUARD: auto-discover press releases published since the hand-maintained
    FILES list. Probe each recent weekday's PDF name (ind_prsDDMMYYYY.pdf, + _1/_2 variants),
    single attempt so 404s are fast. This is what makes a new reshuffle get captured WITHOUT a
    manual edit — the failure mode that mis-dated the 2026 March reshuffle."""
    import datetime

    out = []
    today = datetime.date.today()
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5:
            continue  # press releases come out on weekdays
        s = d.strftime("%d%m%Y")
        out += [s, s + "_1", s + "_2"]
    return out


DATE_RE = re.compile(
    r"effective\s+from\s+([A-Z][a-z]+\s+\d{1,2}\s*,\s*\d{4})", re.IGNORECASE
)  # "December 7 , 2011" (§141e)
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        1,
    )
}


def to_iso(d):
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s*,\s*(\d{4})", d.strip())
    if not m:
        return None
    mo = MONTHS.get(m.group(1).capitalize())
    return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}" if mo else None


# index heading on its own line, numbered OR lettered: "1) Nifty Alpha 50", "c) Nifty 500"
# 2026-09-23 (runbook §141d): tolerate a footnote marker ("5) NIFTY Smallcap 100**", "4) NIFTY Smallcap 50*")
# and a trailing parenthetical ("2) Nifty Midcap 150 (a parent index for Nifty Midcap 50)") after the
# name — the strict form dropped those WHOLE sections (15092021 lost its Smallcap 50/100 blocks).
HEAD_RE = re.compile(
    r"^\s*(?:\d+|[a-zA-Z])[\)\.]\s*((?:s&p\s*)?(?:nifty|cnx)[\w &\-]*?)\s*[\*#@\u2020]*\s*(?:\([^)]*\)?)?\s*[\*#@\u2020]*\s*$",
    re.IGNORECASE,
)
# 2026-09-23 (§141d): a lettered PROSE heading that names one index — how NSE words one-off revisions:
# "B. Revision in criteria and replacements in Nifty Energy index:" (ind_prs11122024, Energy 10 -> 40).
# LETTERED only ("B. …"): numbered lines in these notices are footnotes — "1. Bharat Electronics … removed
# from Nifty Next 50 on account of its inclusion in Nifty 50 index" — and matching them hijacked the
# section mid-list (23082024 / 22082025 lost their Next 50 inclusions in the first cut).
HEAD2_RE = re.compile(
    r"^\s*[A-Z][\)\.]\s*(?![^\n]*\b(?:has been|have been|pursuant|on account of its)\b)[^\n]*?\b(?:replacements?|changes?|inclusions?|exclusions?)\s+(?:in|to|from)\s+"
    r"((?:nifty|cnx)[\w &\-]*?)\s*(?:index|indices)?\s*[:\.]?\s*$",
    re.IGNORECASE,
)
# A data row = serial number, company name, then the ticker as the LAST whitespace token.
# The ticker is extracted by taking the last token and VALIDATING it (O(n), no regex backtracking):
#   - 2-15 chars of [A-Z0-9&-], MUST contain >=1 letter  => allows digit-leading symbols like
#     360ONE / 8KMILES / 3MINDIA / 5PAISA / 63MOONS (the old `[A-Z]`-first regex silently dropped
#     these), and & / - (M&MFIN, BAJAJ-AUTO, L&TFH); rejects pure numbers ("501 securities.").
# Plus a WRAPPED-ROW fallback: long company names wrap so the ticker lands on the next line
#   ("16 Johnson Controls - Hitachi Air Conditioning India" / "Ltd. JCHAC"). When a serial-line has
#   no valid last-token ticker, merge following non-serial continuation lines (<=3) until one appears.
# (Both fixes validated over all cached PDFs: 0 regressions, recovers JCHAC/8KMILES/360ONE. 2026-07-09)
# 2026-09-23 (runbook §141e): a LETTERED section heading that names no tracked index still ENDS the
# current section — "B. Exclusion of a security from NIFTY SME EMERGE Index:" (ind_prs17092019_1) left the
# Smallcap 100 block open, so SME-platform AKASH was read as a Smallcap 100 exclusion (and walked in to
# 2018). Heading-shaped only: capital letter + ")"/"." + a capitalised word, and the line names an index or
# a change, or ends in ":"; row lines start with a serial number, so they never match.
SECT_RE = re.compile(
    r"^\s*[A-Z][\)\.]\s+[A-Z][a-z]+[^\n]*(?:(?i:\b(?:index|indices|replacements?|exclusions?|inclusions?|revisions?|changes?)\b)|:\s*$)"
)
# IISL-era single-index notices name the index only in prose: "It has been decided to make the following
# change in Nifty Midcap 50 Index which will become effective from July 25, 2011" (ind_prs07062011 —
# CHENNPETRO out / ADANIPOWER in, the Midcap 50 swap the 2010 and 2012 archived lists bracket). §141e.
PROSE_RE = re.compile(
    r"\b(?:decided|effective)\b[^\n]*?\bchanges?\s+in\s+((?:s&p\s*)?(?:nifty|cnx)[\w &\-]*?)\s+index\b", re.IGNORECASE
)
SERIAL_RE = re.compile(r"^\s*\d{1,3}\s+\S")
ROWSER_RE = re.compile(r"^\s*(\d{1,3})\s+(.+)$")
TICK_RE = re.compile(r"[A-Z0-9&\-]{2,15}")
STOP = (
    "NSE",
    "EQ",
    "BE",
    "NIFTY",
    "CNX",
    "LIMITED",
    "LTD",
    "IISL",
)  # "IISL" = the old page header   # "LIMITED" = a wrapped name, not a ticker (§141e)


def _ticker(tok):
    if not tok or not TICK_RE.fullmatch(tok):
        return None
    if not any(c.isalpha() for c in tok):
        return None
    if tok in STOP or tok.startswith("DUMMY"):
        return None
    return tok


def _row_ticker(line):
    m = ROWSER_RE.match(line.strip())
    if not m:
        return None
    toks = m.group(2).split()
    return _ticker(toks[-1]) if toks else None


OCR_DIR = os.path.join(HERE, "_pr_ocr")


def _bare_head(lines, i):
    """OCR text only: a line that is exactly a tracked index name, followed within 3 lines by
    'being excluded/included', is a section heading whose '4)' numbering the OCR split off
    ("NIFTY Midcap 50" in ind_prs23082021)."""
    ci = canon_index(lines[i].strip())
    if not ci:
        return None
    for j in range(i + 1, min(i + 4, len(lines))):
        low = lines[j].lower()
        if "being excluded" in low or "being included" in low:
            return ci
    return None


# fallback ONLY when no "effective from <date>" parses: IISL notices whose text layer splits that phrase
# carry the date once as "with effect from December 7 , 2011" (ind_prs01122011, Indiabulls demerger). §141e
DATE2_RE = re.compile(r"(?:with\s+)?effect\s+from\s+([A-Z][a-z]+\s+\d{1,2}\s*,\s*\d{4})", re.IGNORECASE)
# RESCHEDULING NOTICES (2026-09-23, runbook §141f): the preamble first QUOTES the review being amended
# ("On August 28, 2017 IISL announced replacement of Reliance Capital Ltd. … effective from September
# 29, 2017"), then gives the new date ("decided to reschedule replacement of Reliance Capital Ltd. …
# effective from September 05, 2017"). The first "effective from" is the OLD date, so every block of
# ind_prs29082017 (RELCAPITAL) and ind_prs07032017 (SBBJ / MYSOREBANK / SBT: 16-Mar, not 31-Mar 2017)
# was dated 15-24 days late. Returns (announced, rescheduled) or None.
RESCHED_RE = re.compile(r"reschedul", re.IGNORECASE)


def resched_dates(txt):
    m = RESCHED_RE.search(txt)
    if not m:
        return None
    old = DATE_RE.search(txt[: m.start()])
    new = DATE_RE.search(txt, m.start())
    if not (old and new):
        return None
    return to_iso(old.group(1)), to_iso(new.group(1))


def parse_text(txt, bare_heads=False):
    md = DATE_RE.search(txt) or DATE2_RE.search(txt)
    eff_default = to_iso(md.group(1)) if md else None
    rs = resched_dates(txt)
    if rs:
        eff_default = rs[1]
    cur = None
    mode = None
    blocks = []
    lines = txt.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        h = HEAD_RE.match(ln) or HEAD2_RE.match(ln) or PROSE_RE.search(ln)
        ci = canon_index(h.group(1)) if h else (_bare_head(lines, i) if bare_heads else None)
        if h or ci or SECT_RE.match(ln):
            cur = {"index": ci, "eff": eff_default, "excluded": [], "included": []} if ci else None
            if cur:
                blocks.append(cur)
            mode = None
            i += 1
            continue
        low = ln.lower()
        if "exclud" in low:
            mode = "excluded"
            i += 1
            continue
        if "includ" in low:
            mode = "included"
            i += 1
            continue
        if "no change" in low or "no replacement" in low:
            mode = None
            i += 1
            continue
        if mode and cur is not None:
            t = _row_ticker(ln)  # single-line row
            if t:
                cur[mode].append(t)
                i += 1
                continue
            # wrapped-row fallback; the serial may also stand ALONE on its line with the name and ticker
            # wrapped below it ("8" / "ICICI Prudential Asset Management Company" / "Ltd. ICICIAMC" in
            # ind_prs23022026; GNFC in ind_prs28022024) — 2026-09-23, runbook §141d
            if SERIAL_RE.match(ln) or re.match(r"^\s*\d{1,3}\s*$", ln):
                merged = ln.strip()
                j = i + 1
                while (
                    j < n
                    and j <= i + 3
                    and not SERIAL_RE.match(lines[j])
                    and not HEAD_RE.match(lines[j])
                    and "exclud" not in lines[j].lower()
                    and "includ" not in lines[j].lower()
                ):
                    merged += " " + lines[j].strip()
                    t2 = _row_ticker(merged)
                    if t2:
                        cur[mode].append(t2)
                        break
                    j += 1
        i += 1
    return [b for b in blocks if (b["excluded"] or b["included"]) and b["eff"]]


# REVOCATION TABLES (2026-09-23, runbook §141d): "Sr. No. | Index Name | Security Name | Symbol | Remarks"
# with Remarks = Inclusion / Exclusion / Inclusion revoked / Exclusion revoked — how NSE amends an announced
# review (ind_prs19032024: IREDA's inclusion revoked in 6 indices, BSE included instead; ind_prs25092024:
# IDEA's exclusion revoked in 10). parse_text cannot read this layout, so these amendments were missed
# entirely (BSE read as a Nifty 200 / Midcap 100 / 150 / LargeMidcap member back to 2006).
REV_ROW = re.compile(
    r"(?<![A-Z0-9&\-])([A-Z][A-Z0-9&\-]{1,14})\*?\s+(Inclusion revoked|Exclusion revoked|Inclusion|Exclusion)\s*$"
)


def _lead_index(toks):
    """longest leading run of tokens that names a tracked index -> (index, tokens used)"""
    for k in range(min(len(toks), 5), 1, -1):
        ci = canon_index(re.sub(r"[#*]+$", "", " ".join(toks[:k])))
        if ci:
            return ci, k
    return None, 0


def parse_revocations(txt):
    md = DATE_RE.search(txt)
    eff = to_iso(md.group(1)) if md else None
    lines = txt.splitlines()
    out = []
    active = False
    cur = None
    for i, ln in enumerate(lines):
        low = ln.lower()
        if "index name" in low and "remarks" in low:
            active = True
            cur = None
            continue
        if not active:
            continue
        if low.startswith("about nse indices") or re.match(r"^\s*[A-Z]\.\s", ln) or "the following compan" in low:
            active = False
            cur = None
            continue
        m = re.match(r"^\s*\d{1,2}\s+(.*)$", ln)
        if m and re.match(r"(?i)nifty", m.group(1).strip()):
            toks = m.group(1).split()
            ci, k = _lead_index(toks)
            if (
                not ci and i + 1 < len(lines) and len(lines[i + 1].split()) <= 2
            ):  # name wrapped: "Nifty LargeMidcap" / "250"
                toks = toks + lines[i + 1].split()
                ci, k = _lead_index(toks)
            cur = ci
            ln = " ".join(toks[k:]) if ci else ""
        r = REV_ROW.search(ln)
        if r and cur and eff:
            out.append((cur, eff, r.group(2).lower(), r.group(1)))
    return out


# ONE SYMBOL, MANY INDICES (2026-09-23, §141d): "… (Symbol: TATAMTRDVR) shall be excluded from the following
# indices: Sr. No. Index Name / 1 Nifty 100 / 2 Nifty 200 / …" (ind_prs23082024_1, the DVR cancellation,
# effective 2024-08-30). Returns the same (index, eff, action, symbol) tuples as parse_revocations.
SYM_LIST = re.compile(
    r"\(Symbol:\s*([A-Z0-9&\-]{2,15})\)\s*shall\s+be\s+(excluded\s+from|included\s+in)\s+the\s+following\s+indices",
    re.IGNORECASE | re.DOTALL,
)


def parse_symbol_lists(txt):
    md = DATE_RE.search(txt)
    eff = to_iso(md.group(1)) if md else None
    out = []
    for m in SYM_LIST.finditer(txt):
        act = "exclusion" if m.group(2).lower().startswith("excluded") else "inclusion"
        for ln in txt[m.end() :].splitlines()[1:]:
            s2 = ln.strip()
            if not s2 or s2.lower().startswith("sr. no"):
                continue
            mm = re.match(r"^\d{1,2}\s+(.+)$", s2)
            if not mm:
                break
            ci = canon_index(mm.group(1))
            if ci and eff:
                out.append((ci, eff, act, m.group(1)))
    return out


def parse_pdf(fp):
    """Text layer via pypdf. A notice whose text is drawn as IMAGES (ind_prs23082021 — the Sept-2021
    semi-annual review for 20+ indices, ~90 image draws per page, zero real text) yields nothing, so
    such a notice is read from a committed OCR sidecar scripts/_pr_ocr/<stem>.txt (macOS Vision OCR,
    every ticker checked against the symbol universe, runbook §141d) — CI parses the same text."""
    try:
        txt = "\n".join(p.extract_text() or "" for p in PdfReader(fp).pages)
    except Exception:
        txt = ""
    if len(txt.strip()) < 200:
        stem = os.path.basename(fp).replace("ind_prs", "").replace(".pdf", "")
        side = os.path.join(OCR_DIR, stem + ".txt")
        if os.path.exists(side):
            return parse_text(open(side, encoding="utf-8").read(), bare_heads=True)
        return []
    return parse_text(txt)


# Manual corrections for reconstitution notices whose non-standard layout parse_pdf can't read.
# Each: (index, eff, {remove from excluded}, {add to excluded}, {remove from included}, {add to included}).
#  - ind_prs25092024 (eff 2024-09-30): a "revocation table" (Index|Security|Symbol|Remarks), NOT the
#    standard "being excluded/included:" lists the parser keys on. It REVOKED Vodafone Idea's (IDEA)
#    exclusion from the 2024-09-30 review (ind_prs23082024) and EXCLUDED Prism Johnson (PRSMJOHNSN)
#    in its place. Un-patched, IDEA carries a phantom exclusion (harmless — it's in today's anchor, so
#    the backward walk just re-adds it) but PRSMJOHNSN's REAL removal is missing, so reconstruct()
#    never re-adds it and it vanishes from every pre-2024-09 snapshot despite being a genuine Nifty 500
#    member 2020-2024. Verified from the PR text: net 27 out / 27 in on 2024-09-30. 2026-07-03.
MANUAL_CHANGELOG_FIXES = [
    ("Nifty 500", "2024-09-30", {"IDEA"}, {"PRSMJOHNSN"}, set(), set()),
    #  - ind_prs10062020 (eff 2020-06-26, the COVID re-done reconstitution): IRCTC & SWSOLAR are missing
    #    from the parsed N500 include list (very long company names — rows lost across a page break in the
    #    pypdf text layer). PROOF they entered on 2020-06-26: both are in the 2020-07-25 archived NSE CSV
    #    (Wayback checkpoint) and NO other event exists between 2020-06-26 and 2020-07-25; their only other
    #    add (Feb-18-2020) was nulled. Without this they phantom-extend back to listing (Jan-May 2020). 2026-07-10.
    ("Nifty 500", "2020-06-26", set(), set(), set(), {"IRCTC", "SWSOLAR"}),
    #  - ind_prs12032020 (Nifty Bank, redated 2020-03-19 above): the notice's next section "B. Replacement
    #    in NIFTY50 Value 20 index" is a lettered heading HEAD_RE does not recognise, so its rows (excluded
    #    Yes Bank, included ITC) bleed into the Nifty Bank block — ITC as a pre-2020 Nifty Bank member.
    #    The Nifty Bank swap is exactly YESBANK out / BANDHANBNK in (NSE register, same date). 2026-09-21.
    ("Nifty Bank", "2020-03-19", set(), set(), {"ITC"}, set()),
    #  (the other nine indices in ind_prs25092024's table are applied by parse_revocations(), which reads
    #   that table and ind_prs19032024's generically — runbook §141d)
]

# Whole events parse_pdf cannot see because the notice is not a reconstitution review. Each:
# (index, eff, [excluded], [included], src stem, why). Added only when no event with that index+eff+src
# exists (the parser never produces one for these layouts, so the add is idempotent across runs).
#  - ind_prs01122025 (eff 2025-12-31): "Revision in criteria for Nifty indices and inclusions in Nifty
#    Bank index" — Nifty Bank widened from 12 to 14 names for SEBI's F&O eligibility circular; section B
#    "Inclusions in Nifty Bank index": Union Bank of India UNIONBANK, Yes Bank Ltd. YESBANK, "effective
#    from December 31, 2025 (close of December 30, 2025)". Corroborated by NSE's archived constituent
#    list of 2026-08-27 (14 names, both present) vs 2024-09-28 (12, neither). 2026-09-21, runbook §141a.
MANUAL_CHANGELOG_EVENTS = [
    (
        "Nifty Bank",
        "2025-12-31",
        [],
        ["UNIONBANK", "YESBANK"],
        "01122025",
        "index widened 12->14 (SEBI F&O eligibility), ind_prs01122025 section B",
    ),
]


def apply_revocations(changelog, revs, src):
    for idx, eff, act, sym in revs:
        evs = [c for c in changelog.get(idx, []) if c["eff"] == eff]
        if act == "inclusion revoked":
            for c in evs:
                c["included"] = [x for x in c["included"] if x != sym]
        elif act == "exclusion revoked":
            for c in evs:
                c["excluded"] = [x for x in c["excluded"] if x != sym]
        else:
            if not evs:
                c = {"eff": eff, "excluded": [], "included": [], "src": src}
                changelog.setdefault(idx, []).append(c)
                evs = [c]
            side = "included" if act == "inclusion" else "excluded"
            if sym not in evs[0][side]:
                evs[0][side].append(sym)
        print(f"  REVOCATION TABLE {src}: {idx} {eff} {act} {sym}")


def apply_manual_events(changelog):
    for idx, eff, exc, inc, src, why in MANUAL_CHANGELOG_EVENTS:
        ev = changelog.setdefault(idx, [])
        if any(c["eff"] == eff and c["src"] == src for c in ev):
            continue
        ev.append({"eff": eff, "excluded": list(exc), "included": list(inc), "src": src})
        print(f"  MANUAL EVENT {idx} {eff}: -{exc} +{inc} ({why})")


def apply_manual_fixes(changelog):
    for idx, eff, rmx, adx, rmi, adi in MANUAL_CHANGELOG_FIXES:
        events = [c for c in changelog.get(idx, []) if c["eff"] == eff]
        if not events:
            print(f"  MANUAL FIX skipped: no {idx} event on {eff}")
            continue
        for c in events:  # drop revoked-exclusion tickers everywhere
            c["excluded"] = [s for s in c["excluded"] if s not in rmx]
            c["included"] = [s for s in c["included"] if s not in rmi]
        first = events[0]  # add the real change once
        for s in adx:
            if s not in first["excluded"]:
                first["excluded"].append(s)
        for s in adi:
            if s not in first["included"]:
                first["included"].append(s)
        print(f"  MANUAL FIX {idx} {eff}: -excl{sorted(rmx)} +excl{sorted(adx)} -incl{sorted(rmi)} +incl{sorted(adi)}")


# 2026-09-23 (runbook §141d): an auto-probed notice that yields events is PERSISTED here, because the
# probe only looks back 80 days — ind_prs10082026 (the whole Sept-2026 reshuffle, 21 indices) and
# ind_prs13072026_1 were reachable ONLY through the probe window, so the weekly rebuild would have
# silently dropped them in late October. refresh-membership.yml commits this file with the changelog.
PROBED_FILE = os.path.join(HERE, "_pr_probed_stems.json")


def load_probed():
    try:
        return list(json.load(open(PROBED_FILE)))
    except Exception:
        return []


def main():
    probed_keep = load_probed()
    files_all = list(dict.fromkeys(FILES + probed_keep))
    known = set(files_all)
    stems = list(dict.fromkeys(files_all + recent_stems()))  # hand-maintained + persisted + auto-probed recent
    print(
        f"Parsing {len(FILES)} known + {len(probed_keep)} persisted + {len(stems) - len(files_all)} auto-probed recent press releases..."
    )
    ok = miss = 0
    changelog = {}
    revocations = []
    rescheduled = []
    for stem in stems:
        fp = download(stem, tries=(5 if stem in known else 1))  # don't retry the speculative probes
        if not fp:
            miss += 1
            continue
        ok += 1
        blocks = parse_pdf(fp)
        try:
            _rtxt = "\n".join(p.extract_text() or "" for p in PdfReader(fp).pages)
            _revs = parse_revocations(_rtxt) + parse_symbol_lists(_rtxt)
            _rs = resched_dates(_rtxt)
        except Exception:
            _revs = []
            _rs = None
        if _revs:
            revocations.append((stem, _revs))
        if _rs and blocks:
            rescheduled.append((stem, _rs[0], blocks))
        if blocks and stem not in known and stem not in probed_keep:
            probed_keep.append(stem)
            print(f"  persisting auto-probed notice {stem} ({len(blocks)} index blocks)")
        for b in blocks:
            changelog.setdefault(b["index"], []).append(
                {"eff": b["eff"], "excluded": b["excluded"], "included": b["included"], "src": stem}
            )
    print(f"Have {ok}/{len(files_all)} PDFs (missing {miss})")
    # HOLE-FILL SUPPLEMENT (2026-09-23, runbook §141e): IISL-era notices (2011-2012), each READ BY HAND,
    # that carry changes NSE's IndexInclExcl register lost — the Midcap 50 CHENNPETRO->ADANIPOWER swap
    # (07062011), CNX Midcap's IBREALEST->DISHTV (01122011) and AREVAT&D->JISLJALEQS (12122011), CNX
    # Smallcap/Media (16062011, 29022012). Tagged hole_fill: the builder adds an event only where neither
    # the changelog nor the register already has that stock moving that way within ±10 days, so the
    # register's pre-changelog history is never re-routed. Blocks with a repeated ticker or unequal in/out
    # counts (a garbled two-copy text layer) are refused. NOT listed: 03092012 — its Midcap 50 "exclusion"
    # of SOUTHBANK cancels an announced inclusion (the register has neither leg) and would fabricate a
    # pre-2012 member.
    # MIDCAP 150 BEFORE 2019 (2026-09-23, runbook §141f): Midcap 150 has no sheet in the register and its
    # first archived list is 2019-02-01, so every 2017-2018 review was missing from its walk — only their
    # Nifty 500 blocks entered, via the hunt overlay — and the 2016-09-30 roster had 138 names. Each notice
    # below was READ BY HAND; only its Midcap 150 block is admitted (the second field names the indices a
    # stem may feed; None = every block). All eleven blocks balance, with no repeated ticker. The
    # RELCAPITAL / MFSL leg of 28082017 is taken out by the rescheduling step below (29082017 moved it to
    # 2017-09-05).
    M150 = {"Nifty Midcap 150"}
    SUPPLEMENT = [
        ("07062011", None),
        ("16062011", None),
        ("01122011", None),
        ("12122011", None),
        ("29022012", None),
        ("16012017", M150),
        ("16022017", M150),
        ("15062017", M150),
        ("28082017", M150),
        ("16102017", M150),
        ("03112017", M150),
        ("08012018", M150),
        ("21022018", M150),
        ("24052018", M150),
        ("28082018", M150),
        ("14122018", M150),
    ]
    for stem, only in SUPPLEMENT:
        fp = download(stem)
        if not fp:
            print(f"  SUPPLEMENT {stem}: PDF unavailable — skipped")
            continue
        for b in parse_pdf(fp):
            if only is not None and b["index"] not in only:
                continue
            if (
                len(set(b["included"])) != len(b["included"])
                or len(set(b["excluded"])) != len(b["excluded"])
                or len(b["included"]) != len(b["excluded"])
            ):
                print(f"  SUPPLEMENT {stem} {b['index']}: refused (+{b['included']} -{b['excluded']})")
                continue
            changelog.setdefault(b["index"], []).append(
                {"eff": b["eff"], "excluded": b["excluded"], "included": b["included"], "src": stem, "hole_fill": True}
            )
            print(f"  SUPPLEMENT {stem} {b['index']} {b['eff']}: -{len(b['excluded'])} +{len(b['included'])}")
    # SUPERSEDED NOTICES (2026-09-23, runbook §141d): a later notice that says its lists REPLACE an
    # earlier notice's lists for named indices. ind_prs15092021 §C: REIT/InvIT inclusion put on hold,
    # so "the earlier list of replacement of these indices published through a press release on August
    # 23, 2021 stands replaced" for Nifty 500, Midcap 150, Smallcap 250/50/100, LargeMidcap 250,
    # MidSmallcap 400 and Realty. The August lists stand for every other index.
    SUPERSEDED = [
        (
            "23082021",
            "15092021",
            {
                "Nifty 500",
                "Nifty Midcap 150",
                "Nifty Smallcap 250",
                "Nifty Smallcap 50",
                "Nifty Smallcap 100",
                "Nifty LargeMidcap 250",
                "Nifty MidSmallcap 400",
                "Nifty Realty",
            },
        )
    ]
    for old_src, new_src, idxs in SUPERSEDED:
        for idx in idxs:
            evs = changelog.get(idx, [])
            if any(c["src"] == new_src for c in evs):
                n0 = len(evs)
                changelog[idx] = [c for c in evs if c["src"] != old_src]
                if len(changelog[idx]) != n0:
                    print(f"  SUPERSEDED {idx}: {old_src} list replaced by {new_src}")
    json.dump(sorted(set(probed_keep), key=lambda x: (x[4:8], x[2:4], x[:2], x)), open(PROBED_FILE, "w"), indent=0)
    # --- COVID-2020 NULLED RECONSTITUTION (verified from primary sources 2026-07-10) ---------------
    # The Feb-18 + Mar-12 (+Mar-19) reshuffle (eff 2020-03-27) was DEFERRED on Mar-23 (ind_prs23032020)
    # and declared "shall stand null" by ind_prs13052020 — EXCEPT Nifty 50 & Nifty Bank, which were
    # rebalanced EARLY effective 2020-03-19 (Yes Bank Reconstruction Scheme). The reconstitution was
    # re-announced FRESH with UPDATED lists via ind_prs10062020, effective 2020-06-26 (stem in FILES).
    # So: DROP every parsed event from srcs 18022020/12032020 except Nifty 50/Nifty Bank from 18022020,
    # which are redated to 2020-03-19. (Without this, ALKYLAMINE/DHANUKA/GMMPFAUDLR/SUMICHEM etc. appear
    # in Nifty 500 from 2020-03-27 though they only entered 2020-06-26 — caught by a StockView cross-check.)
    # 2026-09-21 (runbook §141a): the Nifty BANK leg of that early rebalance is NOT in 18022020 (which
    # says "no changes ... NIFTY Bank") but in ind_prs12032020 ("Replacement on account of
    # non-availability of F&O contracts: NIFTY Bank — excluded Yes Bank YESBANK, included Bandhan Bank
    # BANDHANBNK"), which the rule above nulled wholesale — so the Nifty Bank changelog began in 2021 and
    # YESBANK never left. NSE's own register dates that swap 2020-03-19 (IndexInclExcl.xls, Nifty Bank
    # sheet); keep it, redated like the Nifty 50 leg.
    nulled = 0
    for idx in list(changelog):
        kept = []
        for c in changelog[idx]:
            # 19032020 (found by the 2026-09-23 probe, §141d) re-fills Yes Bank's vacancy in the SAME
            # never-effective 27-Mar reshuffle (its own text: "w.e.f. March 27, 2020") — nulled with it.
            # 16032020 is NOT nulled: the early Yes Bank removal it announces took effect 2020-03-19.
            if c["src"] in ("18022020", "12032020", "19032020"):
                if (idx == "Nifty 50" and c["src"] == "18022020") or (
                    idx == "Nifty Bank" and c["src"] in ("18022020", "12032020")
                ):
                    c = dict(c, eff="2020-03-19")
                else:
                    nulled += 1
                    continue
            kept.append(c)
        changelog[idx] = kept
    print(
        f"  COVID-2020 null: dropped {nulled} never-effective events (Feb/Mar-2020, superseded by 10062020 eff 2020-06-26)"
    )
    # --- 2015-2019 HUNTED REVIEWS OVERLAY (Nifty 500 only) -----------------------------------------
    # The six semi-annual reviews Mar-2017..Sep-2019 (plus Mar-2015 and a few off-cycles) use older
    # PDF layouts parse_pdf can't read ("CNX 500" headings without the numbered prefix, "Nifty 500
    # Index" suffix), so the walk was missing ~145 swaps — Nifty 500 collapsed to 432-489 members
    # across 2015-2018 and carried the Mar-2019 review unapplied. Those PDFs were brute-hunted and
    # parsed with an era-aware parser (2026-07-02) into _n500_hunt_prs.json (force-tracked). Overlay
    # them here: for any stem the hunt covers, the hunt parse WINS (it was validated anchor-to-anchor).
    try:
        hunt = json.load(open(os.path.join(HERE, "_n500_hunt_prs.json")))
    except Exception as e:
        hunt = []
        print(f"  WARNING: _n500_hunt_prs.json not loaded ({e}) — 2015-2019 N500 reviews will be missing")
    if hunt:
        hstems = {h["file"].replace("ind_prs", "").replace(".pdf", "") for h in hunt}
        n5 = [c for c in changelog.get("Nifty 500", []) if c["src"] not in hstems]
        for h in hunt:
            e = str(h["eff"])
            n5.append(
                {
                    "eff": f"{e[:4]}-{e[4:6]}-{e[6:]}",
                    "excluded": h["excluded"],
                    "included": h["included"],
                    "src": h["file"].replace("ind_prs", "").replace(".pdf", ""),
                }
            )
        changelog["Nifty 500"] = n5
        print(f"  HUNT OVERLAY (Nifty 500): {len(hunt)} hunted docs win over {len(hstems)} stems")
    # RESCHEDULED LEGS (2026-09-23, runbook §141f): a rescheduling notice moves the legs it names OFF the
    # date the original review announced. Its own events now carry the new date (resched_dates; for Nifty
    # 500 the hunt ledger's eff, corrected to 20170905 / 20170316), so the same legs are removed from every
    # other event of that index dated on the announced date — else the stock is excluded twice and the walk
    # holds it in the index between the two dates (28082017 vs 29082017 in Midcap 150 and Nifty 500;
    # 16022017 vs 07032017 in Nifty 500). Runs AFTER the hunt overlay so Nifty 500's reviews are covered.
    for stem, old_eff, blocks in rescheduled:
        for b in blocks:
            for c in changelog.get(b["index"], []):
                if c["src"] == stem or c["eff"] != old_eff:
                    continue
                gone = [x for x in c["excluded"] if x in b["excluded"]] + [
                    x for x in c["included"] if x in b["included"]
                ]
                if gone:
                    c["excluded"] = [x for x in c["excluded"] if x not in b["excluded"]]
                    c["included"] = [x for x in c["included"] if x not in b["included"]]
                    print(
                        f"  RESCHEDULED {stem}: {b['index']} {gone} moved {old_eff} -> {b['eff']} (removed from {c['src']})"
                    )
    for _src, _revs in sorted(revocations, key=lambda x: (x[0][4:8], x[0][2:4], x[0][:2])):
        apply_revocations(changelog, _revs, _src)
    apply_manual_fixes(changelog)
    apply_manual_events(changelog)
    for idx in sorted(changelog):
        ch = changelog[idx]
        ch.sort(key=lambda x: x["eff"])
        for c in ch:  # a ticker listed twice in one block is one event
            c["excluded"] = list(dict.fromkeys(c["excluded"]))
            c["included"] = list(dict.fromkeys(c["included"]))
        nx = sum(len(c["excluded"]) for c in ch)
        ni = sum(len(c["included"]) for c in ch)
        print(f"  {idx:22s}: {len(ch):3d} events, {nx:3d} out / {ni:3d} in   {ch[0]['eff']}..{ch[-1]['eff']}")
    json.dump(changelog, open(os.path.join(HERE, "_changelog.json"), "w"), indent=0)
    print("Wrote _changelog.json")


if __name__ == "__main__":
    main()
