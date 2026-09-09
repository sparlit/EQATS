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


#!/usr/bin/env python3
"""Parse NSE's IndexInclExcl.xls (Nifty 500 sheet) into scripts/_n500_inclexcl_events.json —
the authoritative dated inclusion/exclusion register build_membership_v2.py merges in.

WHY (PLAN_QUANTMAC_FIXES.md finding 1, DATA_RUNBOOK §102): scripts/_changelog.json holds only
74 events starting 2015-03-23, so the backward membership walk never rolls pre-2015 joiners out
of the past — 24 quantmac-flagged trades entered stocks that NSE had excluded years earlier
(SANDESH excluded 2009-03-27 still screenable in 2010; PCBL excluded 2002-01-17 screenable in
2017). This file is NSE's own register: 2,495 dated events, 1998-08-01 .. 2020-09-14, one sheet
per index; we parse Nifty 500.

Name→symbol mapping: exact normalized-name match against search_index / NSE EQUITY_L / BSE
master (fed only with names whose scrip_id exists in our fundamentals), then difflib fuzzy at
0.90 MINUS an explicit blacklist (fuzzy produced provably-wrong pairs: "Indian Petrochemicals
Corporation"→IGPL and "BPL Engineering"→HBLENGINE are DIFFERENT companies — a wrong mapping
injects a dead company's exclusion onto a live symbol, worse than no mapping), plus manual
entries for names whose current ticker drifted (PCBL, CRESTANI, STYRENIX, SMLMAH).

Unmapped names are RECORDED, not guessed: mostly 1998-2005 era companies outside our tracked
universe. Their missing exclusions can leave ghosts only for symbols we don't track.

Output: {"events": [[iso_date, symbol, "inc"|"exc"], ...] (mapped only, current-name space),
         "name_map": {xls_name: symbol}, "unmapped": [names...], "source": "..."}
"""
import collections
import csv
import datetime
import difflib
import json
import os
import re

import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
OUT = os.path.join(SCRIPTS, "_n500_inclexcl_events.json")

# fuzzy pairs verified WRONG by hand (different companies) — never map these
FUZZY_BLACKLIST = {
    "Indian Petrochemicals Corporation Ltd.",  # IPCL (merged into RIL) != IGPL (I G Petrochemicals)
    "BPL Engineering Ltd.",  # != HBL Engineering
    "BIL Industries Ltd.",  # != ITL Industries
}
# current-ticker drift the automatic passes cannot see (each verified against the xls rows +
# our rename map by hand, 2026-08-23)
MANUAL = {
    "Phillips Carbon Black Ltd.": "PCBL",
    "Crest Animation Studios Ltd.": "CRESTANI",
    "INEOS Styrolution India Ltd.": "STYRENIX",
    "Styrolution ABS (India) Ltd.": "STYRENIX",
    "SML Isuzu Ltd.": "SMLMAH",
    # 2026-08-23 (DATA_RUNBOOK §106e): names the automatic passes cannot see because our old-era bin
    # keys carry name == symbol, plus the collisions norm() produced (it strips india/corporation/of,
    # so "Bank of India", "Corporation Bank" and "Indian Bank" all became "bank" and landed on INDIANB;
    # "Indian Oil" and "Oil India" on IOC; "Welspun India" on WELCORP). Each target verified in the
    # live bin with a tape covering the event dates; quantmac parity flipped on UTVSOF/LTF/WELSPUNLIV/
    # SECURKLOUD (we held non-members, missed members) before these landed.
    "UTV Software Communication Ltd.": "UTVSOF",  # member 2009-03-27 .. 2012-03-09 (delisted 2012)
    "L&T Finance Holdings Ltd.": "LTF",  # included 2012-03-09 (listed 2011-08-12)
    "AGC Networks Ltd.": "BBOX",  # excluded 2011-03-25 (Tata Telecom/Avaya era key)
    "8K Miles Soft Services Ltd.": "SECURKLOUD",  # included 2016-04-01, excluded 2019-03-29
    "Oswal Chemicals & Fertilizers Ltd.": "OSWALGREEN",  # (Oswal Agro Mills is a different register name)
    "Ruchi Soya Industries Ltd.": "PATANJALI",  # excluded 2017-09-29; era key RUCHISOYA via build_membership_v2
    "Motherson Sumi Systems Ltd.": "MOTHERSON",  # included 2001-12-07
    "Welspun India Ltd.": "WELSPUNLIV",  # textiles — NOT Welspun Corp (pipes)
    "Welspun Corp Ltd.": "WELCORP",
    "Bank of India": "BANKINDIA",
    "Corporation Bank": "CORPBANK",  # tape 1997-12 .. 2020-03 (merged into Union Bank)
    "Indian Bank": "INDIANB",
    "Indian Oil Corporation Ltd.": "IOC",
    "Oil India Ltd.": "OIL",
    # overlapping-tape collisions the guard rightly refuses — resolved by hand (§106e):
    "SKF India Ltd.": "SKFINDIA",  # not SKFINDUS (2025 demerged industrial arm)
    "Tata Motors Ltd.": "TMPV",  # the register (to 2020) = the old listing, now TMPV; TMCV is the 2025 CV spin-off that took the name
    "Jain Irrigation Systems Ltd.": "JISLJALEQS",  # ordinary share, not the DVR
    "Jain Irrigation Systems Ltd. (Old)": "JISLJALEQS",
    "Jindal Stainless Ltd.": "JSL",
    "Jindal Stainless (Hisar) Ltd.": "JSLHISAR",  # separate listing 2016-2023
    "Asian Hotels (North) Ltd.": "ASIANHOTNR",  # West/East are different companies
    # 2026-08-24 (DATA_RUNBOOK §106g) — the 2012-09..2013-07 UNDER-count: the 2012-04-27 / 2012-09-28 /
    # 2013-04-01 reviews were replayed one-legged because these joiners have no CURRENT-name row (renamed,
    # merged or delisted since), so the walk dropped 3-4 members per review. Each key verified three ways:
    # the bin tape covers the event date(s), the ISIN is on the bin meta, and symchg.csv / NSE EQUITY_L
    # carries the name->symbol row (quoted). Keys are the ERA symbol where a rename chain exists
    # (to_current() folds them) and the era symbol ALONE where today's listing is a DIFFERENT ISIN.
    "WABCO India Ltd.": "WABCOINDIA",  # symchg WABCO-TVS->WABCOINDIA 2011-09-06; INE342J01019; tape 2011-2022 (-> ZFCVINDIA)
    "Gati Ltd.": "GATI",  # symchg GATI->ACLGATI 2023-11-30; INE152B01027; tape 2006-2023
    "Vakrangee Software Ltd.": "VAKRANSOFT",  # symchg VAKRANSOFT->VAKRANGEE 2013-11-27; INE051B01021
    "NIIT Technologies Ltd.": "NIITTECH",  # symchg NIITTECH->COFORGE 2020-08-20; INE591G01017 (NOT NIITLTD, the parent)
    "Bharti Infratel Ltd.": "INFRATEL",  # symchg INFRATEL->INDUSTOWER 2020-12-18; INE121J01017; tape 2012-12+
    "PVR Ltd.": "PVR",  # symchg PVR->PVRINOX 2023-05-12; INE191H01014
    "Eros Intl Media Ltd.": "EROSMEDIA",  # INE416L01017; tape 2010-2024; sole Eros key in the bin
    "Swan Energy Ltd.": "SWANENERGY",  # symchg SWANENERGY->SWANCORP 2025-09-04; INE665A01038
    "Alstom T&D India Ltd.": "ALSTOMT&D",  # symchg AREVAT&D->ALSTOMT&D 2012-03-12, ->GET&D 2016-09-14; INE200A01026 (chain -> GVT&D; era emission back-maps pre-2012 events to AREVAT&D)
    "Techno Elt & Eng Co. Ltd.": "TECHNO",  # INE286K01024, tape 2010-11..2018-08 — NOT TECHNOE (INE285K01026, a 2018 relisting with no rename chain)
    "Magma Fincorp Ltd.": "MAGMA",  # symchg MAGMA->POONAWALLA 2021-08-05; INE511C01022
    "Arshiya International Ltd.": "ARSHIYA",  # EQUITY_L ARSHIYA "Arshiya Limited" INE968D01022; tape 2009-2025
    "Ramky Infra Ltd.": "RAMKY",  # EQUITY_L RAMKY "Ramky Infrastructure Limited" INE874I01013
    "Flexituff International Ltd.": "FLEXITUFF",  # EQUITY_L FLEXITUFF "Flexituff Ventures International" INE060J01017
    "Dr. Datsons Labs Ltd.": "DRDATSONS",  # INE928K01013; tape 2011-2015; sole DRDATSONS key
    "S.E. Investments Ltd.": "SEINV",  # symchg SEINV->PAISALO 2018-01-24; INE420C01042
    "Indiabulls Real Estate Ltd.": "IBREALEST",  # INE069I01010; tape 2007-2024 (INDIABULLS = Indiabulls FINANCIAL, below)
    "Indiabulls Financial Services Ltd.": "INDIABULLS",  # INE894F01025; tape 2004-2013 (merged into IBHFL 2013)
    "NDTV Ltd.": "NDTV",  # INE155G01029; tape 2004-2026
    "Lakshmi Energy & Foods Ltd.": "LAKSHMIEFL",  # INE992B01026; tape 2007-2018
    "Paper Products Ltd.": "PAPERPROD",  # symchg PAPERPROD->HUHTAMAKI 2020-11-26; INE275B01026
    "Patni Computer Systems Ltd.": "PATNI",  # INE660F01012; tape 2004-2012 (delisted 2012 after iGATE buyout; exc 2012-05-21 lands on the last tape months)
    "First Leasing Co. of India Ltd.": "FIRSTLEASE",  # INE492B01019; tape 1996-2013
    "Reliance MediaWorks Ltd.": "RELMEDIA",  # symchg ADLABSFILM->RELMEDIA 2009-10-20; INE540B01015
    "Sterlite Industries (India) Ltd.": "STER",  # INE268A01049; tape 2004-2013 (merged into Sesa Sterlite 2013) — NOT Sterlite Technologies
    "Deccan Chronicle Holdings Ltd.": "DCHL",  # INE137G01027; tape 2004-2013
    "Sona Koyo Steering Systems Ltd.": "SONASTEER",  # INE643A01035; tape 1996-2018 — NOT SONACOMS (Sona BLW, 2021 IPO)
    "Future Consumer Enterprise Ltd.": "FUTUREVENT",  # symchg FVIL->FCEL 2013-10-17, FCEL->FCONSUMER 2016-10-25; INE220J01017 (chain -> FCONSUMER)
    "JSW ISPAT Steel Ltd.": "JSWISPAT",  # symchg ISPATIND->JSWISPAT 2011-08-16; INE136A01022; tape 2006-2013
    "Sujana Towers Ltd.-old": "SUJANATOW",  # INE333I01028; tape 2008-10..2013-08 (the "-old" listing; SUJANATWR INE333I01036 is the post-2013 one)
    "Kemrock Industries and Exports Ltd.": "KEMROCK",  # INE990B01012; tape 2009-2016
    "Varun Shipping Co. Ltd.": "VARUNSHIP",  # INE702A01013; tape 1996-2015
    "Fresenius Kabi Oncology Ltd.": "FKONCO",  # symchg DABURPHARM->FKONCO 2009-02-19; INE575G01010; tape 2004-2013
    "Carol Info Services Ltd.": "CAROLINFO",  # symchg WOCKLIFE->CAROLINFO 2004-09-27; INE198A01014; tape 2000-2012
    "Zuari Global Ltd.": "ZUARIGLOB",  # symchg ZUARIAGRO->ZUARIGLOB 2012-09-25, ->ZUARIIND 2022-07-04; INE217A01012 (chain -> ZUARIIND)
    "Mandhana Industries Ltd.": "GBGLOBAL",  # 2026-08-24 (PLAN_FAV14 P1): textiles, N500 2012-09-28..2015-12-14; symchg MIL->GBGLOBAL 2019-09-09, _rename_map MANDHANA->GBGLOBAL; tape GBGLOBAL 2010-05-19..2021-05-31 INE087J01028. The 0.90 fuzzy pass had sent it to TANDHANIN (Tandhan Industries, Rs 7 lakh mcap, never an N500 member) = 25 phantom member-months with no price row. MANUAL is checked before fuzzy, so this overrides it.
    # 2026-08-24 (PLAN_FAV14 P1) — four DEAD companies whose EXCLUSION the register records but the
    # current-name tables cannot map, so the roster carried them for months after NSE dropped them
    # (PUNJABTRAC 7 / BONGAIREFN 5 / MICRO 3 / VISHALEXPO 1 member-months with no price row). Each
    # tape ends within a day of NSE's exclusion date — the exclusion IS the delisting/merger.
    "Punjab Tractors Ltd.": "PUNJABTRAC",  # exc 2009-02-25; tape 1996..2009-02-24 (merged into Mahindra)
    "Bongaigaon Refinery & Petrochemicals Ltd.": "BONGAIREFN",  # exc 2009-04-21; tape 1996..2009-04-20 (merged into IOC)
    "Micro Inks Ltd.": "MICRO",  # exc 2010-04-06; tape 1996..2010-04-05 (symchg HINDINKS->MICRO 2004-03-26; delisted)
    "Vishal Exports Overseas Ltd.": "VISHALEXPO",  # exc 2009-03-27; tape 2004-05..2009-11-13
    # Summit Securities: the register row is the "- Old" entity, i.e. the 2008-era SUMMIT listing
    # (symchg KECINFRA->SUMMIT 2008-04-21, tape 1996..2010-02-02), NOT SUMMITSEC (a 2011-01-28 relisting,
    # INE519C01017). The automatic pass mapped it to SUMMITSEC, which has no bars in 2009.
    "Summit Securities Ltd.- Old": "SUMMIT",
    # NOT mapped, on purpose: 'Innoventive Industries Ltd.' (inc 2012-09-28 / exc 2013-09-27) — no tape under any key
    # in our universe, so there is nothing to screen; recorded in `unmapped` as before.
}


def norm(x):
    x = (x or "").lower()
    x = re.sub(r"\(.*?\)", " ", x)
    x = x.replace("pharmaceuticals", "pharma").replace("laboratories", "lab")
    x = re.sub(r"\b(ltd|limited|india|indian|the|company|co|corp|corporation|pvt|private|and|&|of)\b", " ", x)
    return re.sub(r"[^a-z0-9]", "", x)


def parse_date(v, datemode):
    if isinstance(v, float):
        return datetime.datetime(*xlrd.xldate_as_tuple(v, datemode)).date().isoformat()
    s = str(v).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    m = re.match(r"^(\d{1,2})-(\d{1,2})-(\d{4})$", s)
    if m:  # NSE prints DD-MM-YYYY (verified: PCBL "17-01-2002" == the known 2002-01-17 exclusion)
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return None


def main():
    wb = xlrd.open_workbook(os.path.join(HERE, "IndexInclExcl.xls"))
    sh = wb.sheet_by_name("Nifty 500")
    raw = []
    for r in range(1, sh.nrows):
        d = parse_date(sh.cell_value(r, 1), wb.datemode)
        name = str(sh.cell_value(r, 2)).strip()
        desc = str(sh.cell_value(r, 3)).strip().lower()
        if d and name:
            raw.append((d, name, "inc" if "inclusion" in desc else "exc"))
    print(f"xls rows parsed: {len(raw)}")

    # old->current ticker chains: two bin keys that are ONE company under two names (3IINFOTECH /
    # 3IINFOLTD, CASTROL / CASTROLIND …) must resolve to the same current symbol, not collide.
    try:
        RENAME = json.load(open(os.path.join(SCRIPTS, "_rename_map.json")))
    except Exception:
        RENAME = {}

    def to_current(x):
        seen = set()
        while x in RENAME and x not in seen:
            seen.add(x)
            x = RENAME[x]
        return x

    # tape spans decide whether two keys sharing a name are ONE company (sequential fragments:
    # NESTLE 1996-2003 then NESTLEIND, CEAT then CEATLTD, NIIT then NIITLTD …) or TWO (overlapping:
    # SKFINDIA vs SKFINDUS, TMPV vs TMCV, ordinary vs DVR). Read from the price bin's d arrays.
    try:
        import gzip as _gz

        _sf = json.loads(_gz.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read()))["data"]
        SPAN = {k: (o["d"][0], o["d"][-1]) for k, o in _sf.items() if o.get("d")}
        del _sf
    except Exception as e:
        SPAN = {}
        print(f"(sf bin not loaded — collision guard refuses every collision: {e})")

    def sequential(a, b):
        sa, sb = SPAN.get(a), SPAN.get(b)
        return bool(sa and sb and (sa[1] < sb[0] or sb[1] < sa[0]))

    cand = {}  # norm-name -> (sym, src); None = AMBIGUOUS — two DIFFERENT companies normalise to it

    def feed(name, sym, src):
        k = norm(name)
        if not k:
            return
        sym = to_current(sym)
        if k in cand:
            # COLLISION GUARD (2026-08-23, §106e): first-feed-wins silently mapped "Bank of India",
            # "Corporation Bank" and "Indian Bank" (all -> "bank") onto INDIANB, "Oil India" onto IOC,
            # "Welspun India" onto WELCORP. Two keys on one key: if their tapes never overlap they are
            # one company under two names -> keep the LATEST tape (the current key); if they overlap
            # they are two companies -> map NOBODY (MANUAL only).
            if cand[k] is None:
                return
            prev = cand[k][0]
            if prev == sym:
                return
            if sequential(prev, sym):
                if SPAN[sym][0] > SPAN[prev][0]:
                    cand[k] = (sym, src)
                return
            cand[k] = None
            return
        cand[k] = (sym, src)

    for row in json.load(open(os.path.join(ROOT, "docs", "search_index.json")))["s"]:
        feed(row[1], row[0], "search_index")
    for r in csv.DictReader(open(os.path.join(HERE, "nse_equity_l.csv"))):
        feed(r["NAME OF COMPANY"], r["SYMBOL"].strip(), "nse")
    fund_syms = set(json.load(open(os.path.join(SCRIPTS, "fundamentals.json"))).keys())
    for r in json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json"))):
        sid = r.get("scrip_id")
        if sid and sid in fund_syms:
            for f in ("Scrip_Name", "Issuer_Name"):
                feed(r.get(f), sid, "bse_master")

    # --- ERA-DATED MAP (2026-09-05, DATA_RUNBOOK §132): NSE's OWN name->symbol bindings for the register's
    # names, read off the archived official CNX 500 constituent lists (2002-2015, csv/xls/htm), wayback
    # EQUITY_L masters (2006/2010/2013/2014) and symchg.csv — evidence in _era_names_evidence.json, map built by
    # scripts/_staleness_fix/build_register_names.py. Fixes the two defects of the current-name passes above:
    # (a) 316 names never mapped because the company no longer lists under that name (Gateway Distriparks
    # = GDL 2005-2022, not the 2022 relisting GATEWAY; Mirc Electronics = MIRCELECTR, not MICEL) — 273 of
    # their 1,108 events 2002-2015 were silently dropped, which is why the official-list diffs were only
    # 82%/59% explained (joins/leaves); (b) auto mappings that landed on a later, different listing.
    # Precedence: MANUAL (hand-verified) > ERA (per-event date) > exact > fuzzy. An ERA symbol is used for an
    # event only if it is the segment in force at that date AND (pre-changelog event OR its tape covers the
    # date ±60d); otherwise the name's ordinary mapping applies. Nothing here guesses: every symbol comes
    # from an NSE document that names both the company and the symbol.
    try:
        ERA = json.load(open(os.path.join(HERE, "register_names_era.json")))
    except Exception as _e:
        ERA = {}
        print(f"(register_names_era.json not loaded: {_e})")
    ERA_CUTOFF = "2015-03-23"
    _rev = {}
    for _o in RENAME:
        _rev.setdefault(to_current(_o), set()).add(_o)

    def _covers(sym, d):
        ks = {sym, to_current(sym)} | _rev.get(to_current(sym), set())
        lo = (datetime.date.fromisoformat(d) - datetime.timedelta(days=60)).strftime("%Y%m%d")
        hi = (datetime.date.fromisoformat(d) + datetime.timedelta(days=60)).strftime("%Y%m%d")
        return any(k in SPAN and str(SPAN[k][0]) <= hi and str(SPAN[k][1]) >= lo for k in ks)

    def era_sym(n, d):
        segs = ERA.get(n)
        if not segs:
            return None
        best = None
        for f, sym in segs:
            if f <= d:
                best = sym
        if best is None:
            best = segs[0][1]
        return best if (d < ERA_CUTOFF or _covers(best, d)) else None

    keys = [k for k, v in cand.items() if v is not None]  # fuzzy never lands on an ambiguous key
    ambiguous_keys = {k for k, v in cand.items() if v is None}
    names = sorted({x[1] for x in raw})
    name_map, unmapped, fuzzy_used, ambiguous = {}, [], [], []
    for n in names:
        if n in MANUAL:
            name_map[n] = MANUAL[n]
            continue
        k = norm(n)
        if k in ambiguous_keys:
            ambiguous.append(n)
            unmapped.append(n)
            continue
        if k in cand and cand[k] is not None:
            name_map[n] = cand[k][0]
            continue
        if n in FUZZY_BLACKLIST:
            unmapped.append(n)
            continue
        hits = difflib.get_close_matches(k, keys, n=1, cutoff=0.90)
        if hits:
            name_map[n] = cand[hits[0]][0]
            fuzzy_used.append((n, cand[hits[0]][0]))
        else:
            unmapped.append(n)
    print(
        f"names: {len(names)}  mapped: {len(name_map)} ({len(fuzzy_used)} fuzzy)  unmapped: {len(unmapped)}  "
        f"(of which ambiguous-key, refused: {len(ambiguous)}: {ambiguous[:12]})"
    )

    def _sym_for(n, d):
        if n in MANUAL:
            return MANUAL[n]
        e = era_sym(n, d)
        return e or name_map.get(n)

    era_used = collections.Counter()
    for d, n, k in raw:
        if n not in MANUAL and era_sym(n, d):
            era_used["events"] += 1
            era_used[n] += 0
    events = sorted([d, _sym_for(n, d), k] for d, n, k in raw if _sym_for(n, d))
    era_names = sorted(n for n in names if n not in MANUAL and n in ERA)
    for n in era_names:
        if n not in name_map:
            name_map[n] = ERA[n][-1][1]
    unmapped = [n for n in unmapped if n not in name_map]
    print(
        f"ERA map: {len(era_names)} names, {era_used['events']} events resolved by era segments; "
        f"now mapped {len(name_map)} names, unmapped {len(unmapped)}"
    )
    # SEAM TWINS (2026-08-24, PLAN_FAV14 P1): two bin keys that are ONE company across an ISIN seam the
    # price build deliberately does not join (SUMMIT 1996..2010-02-02 closed at Rs 16.6; SUMMITSEC relisted
    # 2011-01-28 at Rs 192 — an 11-month gap and a ~12x step, runbook §106). The register's single row
    # names the company once; the Moneycontrol checkpoints carry the CURRENT key for every era. With the
    # events on SUMMIT alone, nothing scrubbed SUMMITSEC from the 2008-2011 MC pins and the walk kept
    # a phantom SUMMITSEC (no bars until 2011) on 30 snapshots. Mirroring the events onto the twin
    # makes both keys follow the one arc; era emission then picks whichever tape was alive.
    SEAM_TWINS = {"SUMMIT": "SUMMITSEC"}
    # + the pairs build_register_names.py derived from NSE's own lists (same company name bound to two
    # symbols whose tapes are sequential and that no rename chain joins: CEAT->CEATLTD, MUKAND->MUKANDLTD …)
    try:
        SEAM_TWINS.update(json.load(open(os.path.join(HERE, "seam_twins.json"))))
    except Exception as _e:
        print(f"(seam_twins.json not loaded: {_e})")
    print(f"seam twins mirrored: {len(SEAM_TWINS)}")
    for a, b in SEAM_TWINS.items():
        events += [[d, b, k] for d, sym, k in list(events) if sym == a]
    events.sort()
    # sanity: no symbol may have two OPPOSITE events on the same date
    bad = [g for g, c in collections.Counter((d, s) for d, s, _ in events).items() if c > 1]
    for d, s in bad:
        ks = {k for dd, ss, k in events if dd == d and ss == s}
        if len(ks) > 1:
            print(f"  ⚠️ CONFLICT same-day inc+exc: {s} {d} — dropping both (ambiguous)")
            events = [e for e in events if not (e[0] == d and e[1] == s)]
    json.dump(
        {
            "events": events,
            "name_map": name_map,
            "era_map": {n: ERA[n] for n in era_names},
            "unmapped": unmapped,
            "ambiguous": ambiguous,
            "source": "NSE IndexInclExcl.xls (saved 2020-09-22), Nifty 500 sheet, parsed 2026-08-23",
        },
        open(OUT, "w"),
        indent=0,
    )
    print(f"wrote {OUT}: {len(events)} mapped events")


if __name__ == "__main__":
    main()
