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


DATE_RE = re.compile(r"effective\s+from\s+([A-Z][a-z]+\s+\d{1,2},\s+\d{4})", re.IGNORECASE)
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
    m = re.match(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", d.strip())
    if not m:
        return None
    mo = MONTHS.get(m.group(1).capitalize())
    return f"{int(m.group(3)):04d}-{mo:02d}-{int(m.group(2)):02d}" if mo else None


# index heading on its own line, numbered OR lettered: "1) Nifty Alpha 50", "c) Nifty 500"
HEAD_RE = re.compile(r"^\s*(?:\d+|[a-zA-Z])[\)\.]\s*((?:nifty|cnx)[\w &\-]*?)\s*$", re.IGNORECASE)
# A data row = serial number, company name, then the ticker as the LAST whitespace token.
# The ticker is extracted by taking the last token and VALIDATING it (O(n), no regex backtracking):
#   - 2-15 chars of [A-Z0-9&-], MUST contain >=1 letter  => allows digit-leading symbols like
#     360ONE / 8KMILES / 3MINDIA / 5PAISA / 63MOONS (the old `[A-Z]`-first regex silently dropped
#     these), and & / - (M&MFIN, BAJAJ-AUTO, L&TFH); rejects pure numbers ("501 securities.").
# Plus a WRAPPED-ROW fallback: long company names wrap so the ticker lands on the next line
#   ("16 Johnson Controls - Hitachi Air Conditioning India" / "Ltd. JCHAC"). When a serial-line has
#   no valid last-token ticker, merge following non-serial continuation lines (<=3) until one appears.
# (Both fixes validated over all cached PDFs: 0 regressions, recovers JCHAC/8KMILES/360ONE. 2026-07-09)
SERIAL_RE = re.compile(r"^\s*\d{1,3}\s+\S")
ROWSER_RE = re.compile(r"^\s*(\d{1,3})\s+(.+)$")
TICK_RE = re.compile(r"[A-Z0-9&\-]{2,15}")
STOP = ("NSE", "EQ", "BE", "NIFTY", "CNX")


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


def parse_pdf(fp):
    try:
        txt = "\n".join(p.extract_text() or "" for p in PdfReader(fp).pages)
    except Exception:
        return []
    md = DATE_RE.search(txt)
    eff_default = to_iso(md.group(1)) if md else None
    cur = None
    mode = None
    blocks = []
    lines = txt.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        h = HEAD_RE.match(ln)
        if h:
            ci = canon_index(h.group(1))
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
            if SERIAL_RE.match(ln):  # wrapped-row fallback
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
]


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
        print(f"  MANUAL FIX {idx} {eff}: -excl{sorted(rmx)} +excl{sorted(adx)}")


def main():
    known = set(FILES)
    stems = list(dict.fromkeys(FILES + recent_stems()))  # hand-maintained history + auto-probed recent
    print(f"Parsing {len(FILES)} known + {len(stems) - len(FILES)} auto-probed recent press releases...")
    ok = miss = 0
    changelog = {}
    for stem in stems:
        fp = download(stem, tries=(5 if stem in known else 1))  # don't retry the speculative probes
        if not fp:
            miss += 1
            continue
        ok += 1
        for b in parse_pdf(fp):
            changelog.setdefault(b["index"], []).append(
                {"eff": b["eff"], "excluded": b["excluded"], "included": b["included"], "src": stem}
            )
    print(f"Have {ok}/{len(FILES)} PDFs (missing {miss})")
    # --- COVID-2020 NULLED RECONSTITUTION (verified from primary sources 2026-07-10) ---------------
    # The Feb-18 + Mar-12 (+Mar-19) reshuffle (eff 2020-03-27) was DEFERRED on Mar-23 (ind_prs23032020)
    # and declared "shall stand null" by ind_prs13052020 — EXCEPT Nifty 50 & Nifty Bank, which were
    # rebalanced EARLY effective 2020-03-19 (Yes Bank Reconstruction Scheme). The reconstitution was
    # re-announced FRESH with UPDATED lists via ind_prs10062020, effective 2020-06-26 (stem in FILES).
    # So: DROP every parsed event from srcs 18022020/12032020 except Nifty 50/Nifty Bank from 18022020,
    # which are redated to 2020-03-19. (Without this, ALKYLAMINE/DHANUKA/GMMPFAUDLR/SUMICHEM etc. appear
    # in Nifty 500 from 2020-03-27 though they only entered 2020-06-26 — caught by a StockView cross-check.)
    nulled = 0
    for idx in list(changelog):
        kept = []
        for c in changelog[idx]:
            if c["src"] in ("18022020", "12032020"):
                if idx in ("Nifty 50", "Nifty Bank") and c["src"] == "18022020":
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
    apply_manual_fixes(changelog)
    for idx in sorted(changelog):
        ch = changelog[idx]
        ch.sort(key=lambda x: x["eff"])
        nx = sum(len(c["excluded"]) for c in ch)
        ni = sum(len(c["included"]) for c in ch)
        print(f"  {idx:22s}: {len(ch):3d} events, {nx:3d} out / {ni:3d} in   {ch[0]['eff']}..{ch[-1]['eff']}")
    json.dump(changelog, open(os.path.join(HERE, "_changelog.json"), "w"), indent=0)
    print("Wrote _changelog.json")


if __name__ == "__main__":
    main()
