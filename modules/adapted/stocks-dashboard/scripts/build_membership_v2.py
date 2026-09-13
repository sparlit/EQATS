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
FINAL point-in-time index membership builder (all 7 backtest indexes).

Sources, in order of authority:
  1. Parsed NSE reconstitution press releases (_changelog.json) — exact effective
     dates for every captured add/drop, 2015-2026.
  2. Archived official full lists (_wb_n500_snaps.json, Nifty 500 only) — pinned
     as hard checkpoints; reconstruction is forced exact at those dates.
  3. Today's official NSE constituent CSVs — the anchor each walk starts from.
  4. Old scrapbook (indices_history.json) — kept ONLY for dates before the
     earliest accurate event (deep history fallback).

Symbols are converted to the ERA-CORRECT ticker (the symbol that actually traded
on that date) using symchg.csv + a supplement, so membership matches the
survivorship-free bhavcopy price series keys of that period.

Writes: scripts/indices_history.json  +  docs/stock_data.bin (indicesHistory).
Run: python -X utf8 build_membership_v2.py
"""
import csv
import datetime
import gzip
import itertools
import json
import os
import re
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

SLUGS = {  # index display name -> NSE current-list slug — ALL 27 tracked indexes
    "Nifty 50": "nifty50",
    "Nifty Next 50": "niftynext50",
    "Nifty 100": "nifty100",
    "Nifty 200": "nifty200",
    "Nifty 500": "nifty500",
    "Nifty Midcap 50": "niftymidcap50",
    "Nifty Midcap 100": "niftymidcap100",
    "Nifty Midcap 150": "niftymidcap150",
    "Nifty Smallcap 50": "niftysmallcap50",
    "Nifty Smallcap 100": "niftysmallcap100",
    "Nifty Smallcap 250": "niftysmallcap250",
    "Nifty LargeMidcap 250": "niftylargemidcap250",
    "Nifty MidSmallcap 400": "niftymidsmallcap400",
    "Nifty Bank": "niftybank",
    "Nifty IT": "niftyit",
    "Nifty Pharma": "niftypharma",
    "Nifty Auto": "niftyauto",
    "Nifty FMCG": "niftyfmcg",
    "Nifty Metal": "niftymetal",
    "Nifty Energy": "niftyenergy",
    "Nifty Realty": "niftyrealty",
    "Nifty Media": "niftymedia",
    "Nifty Healthcare": "niftyhealthcare",
    "Nifty Consumer Durables": "niftyconsumerdurables",
    "Nifty Oil & Gas": "niftyoilgas",
    "Nifty PSU Bank": "niftypsubank",
    "Nifty MNC": "niftymnc",
}

# ---------- renames (old -> new, with the date the NEW symbol started) ----------
MON = {
    m: i for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)
}


def dmy_iso(s):
    m = re.match(r"(\d{1,2})-([A-Z]{3})-(\d{4})", s.strip().upper())
    return f"{int(m.group(3)):04d}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}" if m and m.group(2) in MON else None


def load_renames():
    ren = {}  # old -> (new, date)
    try:
        sc = os.path.join(HERE, "symchg.csv")  # repo copy first (works in CI)
        if not os.path.exists(sc):
            sc = os.path.join(os.path.dirname(ROOT), "symchg.csv")
        for r in csv.reader(open(sc, encoding="utf-8", errors="replace")):
            if len(r) >= 4 and r[1].strip() and r[2].strip():
                d = dmy_iso(r[3]) if r[3].strip() else None
                ren[r[1].strip().upper()] = (r[2].strip().upper(), d or "1900-01-01")
    except Exception as e:
        print("(symchg.csv not loaded:", e, ")")
    # supplement: recent renames missing from symchg.csv; date resolved from SF price data below
    for old, new in [
        ("GMRINFRA", "GMRAIRPORT"),
        ("GET&D", "GVT&D"),
        ("HBLPOWER", "HBLENGINE"),
        ("AKZOINDIA", "JSWDULUX"),
        ("SWANENERGY", "SWANCORP"),
        ("MFL", "EPIGRAL"),
        ("GLS", "ALIVUS"),
        ("ADANITRANS", "ADANIENSOL"),
        ("MOTHERSUMI", "MOTHERSON"),
        ("MAHINDCIE", "CIEINDIA"),
    ]:  # MAHINDCIE 2026-08-11: in LargeMidcap250 history; bin key merged into CIEINDIA (orphan-series batch)
        ren.setdefault(old, (new, None))
    return ren


def resolve_supplement_dates(ren):
    """date of a rename ~= first trading day of the NEW symbol in the SF data."""
    try:
        D = json.loads(gzip.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read()))
        first = {sym: str(o["d"][0]) for sym, o in D["data"].items() if o["d"]}
        for old, (new, d) in list(ren.items()):
            if d is None:
                f = first.get(new)
                ren[old] = (new, f"{f[:4]}-{f[4:6]}-{f[6:]}" if f else "2099-01-01")
    except Exception as e:
        print("(SF data not loaded for rename dates:", e, ")")
        for old, (new, d) in list(ren.items()):
            if d is None:
                ren[old] = (new, "2099-01-01")
    return ren


REN = resolve_supplement_dates(load_renames())  # old -> (new, date)
FWD = {}  # canonical resolution old->latest


def canon(s):
    seen = set()
    while s in REN and s not in seen:
        seen.add(s)
        s = REN[s][0]
    return s


BACK = {}  # new -> (old, date)
for o, (n, d) in REN.items():
    BACK.setdefault(n, (o, d))


def era_symbol(c, date):
    """era-correct ticker for canonical symbol c at `date` (walk rename chain backward)."""
    seen = set()
    while c in BACK and c not in seen:
        old, d = BACK[c]
        if date < d:
            seen.add(c)
            c = old
        else:
            break
    return c


# ---------- fetch today's official lists ----------
def get(url, tries=5):
    last = None
    for _ in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception as e:
            last = e
            time.sleep(3)
    raise last


def today_list(slug):
    raw = get(f"https://archives.nseindia.com/content/indices/ind_{slug}list.csv")
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    rows = list(csv.reader(raw.decode("utf-8", "ignore").splitlines()))
    si = rows[0].index("Symbol") if "Symbol" in rows[0] else 2
    return sorted({r[si].strip() for r in rows[1:] if len(r) > si and r[si].strip()})


# ---------- reconstruction ----------
def merge_same_eff(events):
    """combine events sharing an effective date (fixes the overwrite bug)."""
    by = {}
    for c in events:
        e = by.setdefault(c["eff"], {"eff": c["eff"], "excluded": [], "included": []})
        e["excluded"] += c["excluded"]
        e["included"] += c["included"]
    return [by[k] for k in sorted(by)]


def reconstruct(anchor_today, events, checkpoints=None):
    """Backward walk from today's anchor; returns {eff: set(canonical members)}.
    checkpoints {date: set} are pinned exact afterwards."""
    ev = merge_same_eff(events)
    snaps = {}
    m = {canon(s) for s in anchor_today}
    for c in reversed(ev):
        inc = {canon(x) for x in c["included"]}
        exc = {canon(x) for x in c["excluded"]}
        snaps[c["eff"]] = set(m)  # membership in force FROM c.eff
        m = (m - inc) | exc  # roll back to before this event
    snaps["1900-01-01"] = set(m)  # pre-changelog baseline
    if checkpoints:
        for d, S in checkpoints.items():
            snaps[d] = {canon(x) for x in S}
    return snaps


def reanchor_segments(snaps, checkpoints, events):
    """Re-derive every between-pin event-date snapshot from the LATER pin, walking only that
    window's events (2026-08-23, finding-1 fix, second pass).

    WHY: reconstruct()'s single global walk runs today -> 1998 through every event without ever
    resetting at a checkpoint, so any event whose counterpart leg is missing (the IndexInclExcl
    register maps 919 of 1,280 names — the rest are dead companies outside our universe, so
    ~30%% of old reconstitutions are one-legged here) leaves a permanent residue that COMPOUNDS
    with depth: measured +60 members at 2006-06-30 (560 vs NSE's 500), +48 at 2009, −28 at 2010.
    Checkpoints pin their own dates exact but nothing in between. Walking each window from its
    later pin bounds the error to that window's own unmapped legs (±ones, not ±tens).
    Runs BEFORE checkpoint_continuity (which only ADDs and remains the changelog-hole healer).
    Returns the count of event-date snapshots rewritten."""
    if not checkpoints:
        return 0
    cps = sorted(d for d in checkpoints if d in snaps)
    ev = merge_same_eff(events)
    rewritten = 0
    for a, b in itertools.pairwise(cps):
        window = [c for c in ev if a < c["eff"] <= b]
        if not window:
            continue
        m = set(snaps[b])
        for c in reversed(window):
            inc = {canon(x) for x in c["included"]}
            exc = {canon(x) for x in c["excluded"]}
            if c["eff"] != b:  # b's own value is the pin — never overwrite it
                snaps[c["eff"]] = set(m)
                rewritten += 1
            m = (m - inc) | exc
    return rewritten


def checkpoint_continuity(snaps, checkpoints, events):
    """Close the holes the BACKWARD walk cannot.

    reconstruct() only restores a past member when the changelog records the exclusion that
    removed them, so every exclusion the press-release parser missed makes the reconstruction
    decay monotonically into the past: 501 members at 2018-10-04 down to 485 at 2015-03-27,
    with no archived full list anywhere between 2015-03-25 and 2018-10-04 to pin it back.
    Symptom to look for: adds/removes balanced at every transition except a few where removes
    exceed adds, after which the deficit never recovers (YESBANK, in the Nifty 50 at the time,
    sat outside the reconstructed Nifty 500 for three years).

    Invariant applied: a symbol present at BOTH surrounding pinned checkpoints and never named
    in an exclusion between them was a member for the whole interval. A genuine leave-and-rejoin
    IS recorded as an exclusion, so requiring "never excluded" preserves those real gaps — this
    fills only the holes the changelog itself cannot account for.
    """
    if not checkpoints:
        return 0
    cps = sorted(d for d in checkpoints if d in snaps)
    dates = sorted(snaps)
    ev = merge_same_eff(events)
    added = 0
    for a, b in itertools.pairwise(cps):
        both = snaps[a] & snaps[b]
        gone = set()
        for c in ev:
            if a < c["eff"] <= b:
                gone |= {canon(x) for x in c["excluded"]}
        stayed = both - gone
        for d in dates:
            if a < d < b:
                miss = stayed - snaps[d]
                if miss:
                    snaps[d] |= miss
                    added += len(miss)
    return added


def validate_n500(snaps, wb):
    def asof(d):
        best = None
        for k in sorted(snaps):
            if k <= d:
                best = k
        return snaps[best]

    print("  validation vs archived official lists (canonical symbols):")
    worst = 100.0
    for d in sorted(wb):
        off = {canon(x) for x in wb[d]}
        rec = asof(d)
        pct = 100 * len(off & rec) / len(off)
        print("    %s  match %.1f%%  off-by %d" % (d, pct, len(off ^ rec)))
        worst = min(worst, pct)
    return worst


def load_inclexcl_register():
    """NSE's own dated inclusion/exclusion register (IndexInclExcl.xls -> Nifty 500 sheet,
    parsed by scripts/_staleness_fix/gen_inclexcl_events.py). 1,765 mapped events, 1998-2020.
    Added 2026-08-23 (DATA_RUNBOOK §102 finding 1): _changelog.json starts 2015-03-23, so the
    backward walk never rolled pre-2015 joiners out of the past — 24 externally-flagged trades
    entered stocks NSE had excluded years earlier (PCBL excluded 2002-01-17 was screenable in
    2017). Returns ({sym: [(iso_date, 'inc'|'exc'), ...] sorted}, [event dicts]) or ({}, [])."""
    try:
        reg = json.load(open(os.path.join(HERE, "_n500_inclexcl_events.json")))
    except Exception as e:
        print(f"(_n500_inclexcl_events.json not loaded: {e} — membership keeps changelog-only events)")
        return {}, []
    by_sym = {}
    by_date = {}
    # Keys live in canon() space (2026-09-05, DATA_RUNBOOK §132): every lookup below compares against
    # canon()-ed checkpoint symbols (register_state(canon(_s)), _wb_canon), but the register file carries
    # the ERA symbol NSE printed (MIRCELECTR, GATI, WABCOINDIA …). A raw key never matched its canon twin,
    # so an exclusion recorded on MIRCELECTR could not scrub ONIDA off a stale Moneycontrol page (measured
    # 2026-09-05: ONIDA still a member at 2012-12-31 after NSE excluded Mirc on 2012-09-28).
    for d, s, k in reg["events"]:
        s = canon(s)
        by_sym.setdefault(s, []).append((d, k))
        e = by_date.setdefault(d, {"eff": d, "included": [], "excluded": [], "src": "IndexInclExcl"})
        e["included" if k == "inc" else "excluded"].append(s)
    for s in by_sym:
        by_sym[s].sort()
    return by_sym, [by_date[d] for d in sorted(by_date)]


def register_inc_is_live(reg_by_sym, sym, iso_date, official):
    """True when the register's 'inc' for sym at iso_date is still credible — i.e. NO official
    archived full list dated after that inclusion and on-or-before iso_date omits the stock.

    WHY (2026-08-24, the 2009-2011 over-count): the register is one-legged for ~30% of names, so a
    stock whose EXCLUSION it lost keeps reading 'inc' forever — HINDMOTORS/CHEMPLASTS/NAGAFERT/
    PATANJALI (Ruchi Soya)/MAXIND carry an 'inc' from 1998-08-01 and nothing after, yet NSE's own
    full list of 2010-01-02 does not contain them. The symmetric join below trusted that stale 'inc'
    and force-added them to every MC checkpoint: measured 776 joins, 285 of them contradicted by an
    official list (17-20 per pin 2008-2011), rosters pinned at 517-528 and 510-513 after the later
    trims vs NSE's 500. The official list is the higher authority: if it post-dates the inclusion
    and omits the stock, the stock left — the register just never recorded it. A register 'inc'
    dated AFTER the latest official list (a real short-arc joiner MC's stale page never showed,
    e.g. BANCOINDIA inc 2010-04-08) is untouched: no list can contradict it yet.
    Self-test: applied at each of the 22 official dates the rule accepts nothing that list omits."""
    last_inc = None
    for d, k in reg_by_sym.get(sym, []):
        if d <= iso_date and k == "inc":
            last_inc = d
    if last_inc is None:
        return False
    return all(not (last_inc < od <= iso_date and sym not in members) for od, members in official.items())


def register_state(reg_by_sym, sym, iso_date):
    """'inc' | 'exc' | None — the register's view of sym's membership as of iso_date."""
    st = None
    for d, k in reg_by_sym.get(sym, []):
        if d <= iso_date:
            st = k
        else:
            break
    return st


def main():
    changelog = json.load(open(os.path.join(HERE, "_changelog.json")))
    wb = json.load(open(os.path.join(HERE, "_wb_n500_snaps.json")))
    REG_BY_SYM, REG_EVENTS = load_inclexcl_register()
    # Official archived sub-index constituent CSVs (ground truth) pinned as hard
    # checkpoints for the 8 broad tiers, exactly like wb does for Nifty 500. Keys
    # are Wayback YYYYMMDD (or "LIVE") -> convert to ISO; LIVE == today's anchor, skip.
    try:
        _off = json.load(open(os.path.join(HERE, "_idx_official_snaps.json")))
    except Exception:
        _off = {}
    OFFICIAL = {}
    for _tier, _snaps in _off.items():
        OFFICIAL[_tier] = {(f"{d[:4]}-{d[4:6]}-{d[6:8]}"): set(v) for d, v in _snaps.items() if d != "LIVE"}
    hist_path = os.path.join(HERE, "indices_history.json")
    H = json.load(open(hist_path, encoding="utf-8"))
    # old->current map from the PRICE build (build_sf_data merges renamed series by ISIN). Membership
    # must key on the SAME current tickers the merged price series uses, else renamed stocks vanish
    # from historical backtests. This supersedes the old era_symbol() (which deliberately used the OLD
    # ticker to match the previously-split price series — no longer how the price data is keyed).
    try:
        RENAME = json.load(open(os.path.join(HERE, "_rename_map.json")))
    except Exception:
        RENAME = {}
        print("(_rename_map.json not found — membership keeps era symbols)")

    def to_current(s):
        seen = set()
        while s in RENAME and s not in seen:
            seen.add(s)
            s = RENAME[s]
        return s

    # --- ERA-AWARE KEY EMISSION (2026-08-23, DATA_RUNBOOK §105) ---------------------------------------
    # to_current() keys every snapshot to the CURRENT ticker on the premise that the price build has
    # folded the old tape into that key. For 71 ISIN-seam pairs it has not (relistings / IBC capital
    # reductions / unexplained steps — joining them would fabricate a return), so the current key has
    # NO bars on the snapshot date, the PHANTOM FLOOR below then deletes the row (>= 2011) and the
    # company is invisible for years: Hexaware 2011-2020, Chemplast 2011-2012, Tube Investments
    # 2011-2017, Ruchi Soya 2011-2019 … (measured 2026-08-23: 30/17/25 invisible members at the
    # 2008/09/10 year-ends, 7 of quantmac's 15 "membership disputes" were this). Rule: if the current
    # key has no bar on or before the snapshot date but an OLD key in its rename chain was trading
    # then (first bar <= date <= last bar + 45d), emit the old key — the engine screens SERIES by
    # symbol, and FUND_ALIAS already bridges old keys to their fundamentals (§95f). A key the bin
    # holds is never redirected, so merged pairs are unaffected.
    # ERA_OVERRIDES repair three name-mapped targets that point at the WRONG successor for the era:
    # the register/checkpoint mapper resolved "KPIT Cummins" to KPITTECH (the 2019 DEMERGED entity;
    # the listed company became BSOFT), "Tube Investments" to TIINDIA (the 2017 spin-off; the old
    # listing continued as CHOLAHLDNG) and "Ispat Industries" to JSWISPL (Monnet's successor — a
    # different company, whose only reverse chain is MONNETISPA, so the generic fallback would land on
    # the wrong tape). Each applies only before the date the true successor's own tape begins.
    ERA_OVERRIDES = {
        "KPITTECH": ("KPIT", "2019-02-26"),
        "TIINDIA": ("TUBEINVEST", "2017-11-02"),
        "JSWISPL": ("JSWISPAT", "2018-09-14"),
        # Three more of the same class, measured 2026-08-24 (evidence in
        # scripts/_n500_norow_handoff.json; each boundary = the wrong successor's own
        # first bar / the true era's end):
        # "Dalmia Bharat" pre-demerger (2010 slots): the listed company then was
        # Dalmia Cement (Bharat) -> renamed Dalmia Bharat SUGAR; DALBHARAT's own tape
        # (the 2019 re-listed entity) begins 2019-01-22, and the 2011-18 leg traded as
        # DALMIABHA. Boundary = DALMIABHA's first bar so only pre-demerger slots move.
        "DALBHARAT": ("DALMIACEM", "2011-01-27"),
        # "Shree Precoated Steels" 2008-09 slots: SPSL's own tape 2006-09-26..2009-05-08
        # covers them; SHPRE's tape only begins 2009-10-15. (SPSL fundamentals were
        # backfilled 2026-08-24: 2008-09/2008-12, EPS/chain-gated.)
        "SHPRE": ("SPSL", "2009-10-15"),
        # "Pantaloon/Future Retail" 2010 slots: FRETAIL (the 2016 demerged listing,
        # first bar 2016-08-29) cannot be the 2010 member; the undivided company is the
        # PANTALOONR -> FEL lineage (FEL tape 2001-11-05..).
        "FRETAIL": ("PANTALOONR", "2016-08-29"),
        # Summit Securities (2026-08-24, PLAN_FAV14 P1): SUMMITSEC is a 2011-01-28 relisting
        # across an unjoined ISIN seam (SUMMIT closed 2010-02-02 at Rs 16.6, SUMMITSEC opened
        # at Rs 192). The register's one arc is mirrored onto both keys (gen_inclexcl_events
        # SEAM_TWINS); before SUMMITSEC's own first bar the member is the SUMMIT tape.
        "SUMMITSEC": ("SUMMIT", "2011-01-28"),
    }
    import gzip as _gz2

    try:
        _sfd = json.loads(_gz2.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read()))["data"]
        _first = {k: str(o["d"][0]) for k, o in _sfd.items() if o.get("d")}
        _last = {k: str(o["d"][-1]) for k, o in _sfd.items() if o.get("d")}
        del _sfd
    except Exception as _e:
        _first = {}
        _last = {}
        print("  era-aware emission disabled (no sf_stock_data.bin):", _e)
    _REV = {}
    for _o in RENAME:
        _c = to_current(_o)
        if _c != _o:
            _REV.setdefault(_c, []).append(_o)
    import datetime as _dt

    def _plus_days(ymd, n):
        return (_dt.date(int(ymd[:4]), int(ymd[4:6]), int(ymd[6:8])) + _dt.timedelta(days=n)).strftime("%Y%m%d")

    _era_hits = {}

    def era_key(cur, iso_date):
        if not _first:
            return cur
        dint = iso_date.replace("-", "")
        if cur in _first and _first[cur] <= dint:
            return cur  # current key trades on/before date
        cands = [o for o in _REV.get(cur, []) if o in _first and _first[o] <= dint <= _plus_days(_last[o], 45)]
        if not cands:
            return cur
        best = max(cands, key=lambda o: _last[o])  # the tape alive closest to the date
        _era_hits.setdefault(f"{cur}->{best}", [0, iso_date, iso_date])
        h = _era_hits[f"{cur}->{best}"]
        h[0] += 1
        h[2] = iso_date
        return best

    def era_fix(s, iso_date):
        ov = ERA_OVERRIDES.get(s)
        return ov[0] if ov and iso_date < ov[1] else s

    def emit(s, iso_date):
        return era_key(to_current(canon(era_fix(s, iso_date))), iso_date)

    for idx, slug in SLUGS.items():
        events = changelog.get(idx, [])
        if not events:
            print(f"{idx}: no change events — left as-is")
            continue
        anchor = today_list(slug)
        if idx == "Nifty 500":
            # Merge the IndexInclExcl register (2026-08-23, finding-1 fix). Pre-changelog events
            # (< first changelog eff) go in wholesale — the changelog simply has nothing there.
            # In-window register events are added ONLY when the changelog has no same-symbol
            # same-direction event within ±10 days (its eff conventions differ by a day or two);
            # each such addition is a hole in the changelog and is printed (PCBL's 2018-09-28
            # re-inclusion is the proven case — present in NSE's register, absent from the
            # changelog, and the reason PCBL read as a member back to 2002).
            if REG_EVENTS:
                first_cl = min(c["eff"] for c in events)
                cl_keys = set()
                for c in events:
                    for s in c["included"]:
                        cl_keys.add((canon(s), "inc", c["eff"]))
                    for s in c["excluded"]:
                        cl_keys.add((canon(s), "exc", c["eff"]))

                def _cl_has(sym, kind, eff):
                    lo = (datetime.date.fromisoformat(eff) - datetime.timedelta(days=10)).isoformat()
                    hi = (datetime.date.fromisoformat(eff) + datetime.timedelta(days=10)).isoformat()
                    return any(k[0] == canon(sym) and k[1] == kind and lo <= k[2] <= hi for k in cl_keys)

                added_pre = added_gap = 0
                for ev in REG_EVENTS:
                    if ev["eff"] < first_cl:
                        events = [*events, ev]
                        added_pre += 1
                    else:
                        inc = [s for s in ev["included"] if not _cl_has(s, "inc", ev["eff"])]
                        exc = [s for s in ev["excluded"] if not _cl_has(s, "exc", ev["eff"])]
                        if inc or exc:
                            events = [
                                *events,
                                {"eff": ev["eff"], "included": inc, "excluded": exc, "src": "IndexInclExcl-gap"},
                            ]
                            added_gap += 1
                            for s in inc:
                                print(f"  register fills changelog HOLE: +{s} eff {ev['eff']}")
                            for s in exc:
                                print(f"  register fills changelog HOLE: -{s} eff {ev['eff']}")
                print(
                    f"  IndexInclExcl register merged: {added_pre} pre-changelog event-days, "
                    f"{added_gap} in-window gap event-days"
                )
            cps = {d: set(v) for d, v in wb.items()}
            # Moneycontrol-derived soft checkpoints for the 2007-13 dark windows (15 dates;
            # code-resolved + evidence-adjudicated, see PRE2015_CAMPAIGN.md STEP M2 and
            # _mc_code_supplement.json). Official wb lists win on any same-date collision.
            # ⚠️ Register outranks MC (2026-08-23): MC's page served STALE rosters for years —
            # measured 59 member-slots across its 18 checkpoints naming stocks NSE had already
            # excluded (SANDESH, excluded 2009-03-27, still listed mid-2011). A checkpoint pins
            # EXACT, so a stale member would survive the event merge above; scrub each MC set
            # against the register's state on that date. wb needed no scrub (0 conflicts).
            try:
                _scrubbed = _added = _stale_joins = 0
                _wb_canon = {d: {canon(x) for x in v} for d, v in wb.items()}
                for _d, _v in json.load(open(os.path.join(HERE, "_mc_n500_snaps.json"))).items():
                    _keep, _drop = set(), []
                    for _s in _v:
                        if register_state(REG_BY_SYM, canon(_s), _d) == "exc":
                            _drop.append(_s)
                        else:
                            _keep.add(_s)
                    # symmetric leg: MC's staleness cuts BOTH ways — it kept showing leavers AND
                    # kept not-showing joiners. Add every register-member the MC page missed
                    # (measured cost of scrub-only: mid-2011 rosters fell to 434 vs NSE's 500).
                    # ... but only joins the OFFICIAL lists do not contradict (register_inc_is_live):
                    # a stale 'inc' whose exclusion the register lost is not a member (2026-08-24).
                    _cands = {
                        s
                        for s in REG_BY_SYM
                        if register_state(REG_BY_SYM, s, _d) == "inc" and s not in {canon(x) for x in _keep}
                    }
                    _joins = {s for s in _cands if register_inc_is_live(REG_BY_SYM, s, _d, _wb_canon)}
                    _stale_joins += len(_cands - _joins)
                    if _joins:
                        _added += len(_joins)
                        _keep |= _joins
                    if _drop:
                        _scrubbed += len(_drop)
                        print(
                            f"  MC checkpoint {_d}: scrubbed {len(_drop)} register-excluded, "
                            f"added {len(_joins)} register-members MC missed"
                        )
                    cps.setdefault(_d, _keep)
                if _scrubbed or _added or _stale_joins:
                    print(
                        f"  MC reconcile total: -{_scrubbed} stale, +{_added} missed member-slots, "
                        f"{_stale_joins} stale register-inc joins refused (official list omits them)"
                    )
            except FileNotFoundError:
                pass
        else:
            cps = OFFICIAL.get(idx) or None  # official archived CSVs pinned exact
        snaps = reconstruct(anchor, events, cps)
        # Nifty 500 only: its checkpoints are dense enough for the invariant to be safe, and it
        # is the index whose backward walk provably decays (see checkpoint_continuity). The
        # fixed-size sub-indexes are already pinned to official CSVs at J=0.997 and adding to
        # them risks pushing a 50-name tier over its size check.
        if idx == "Nifty 500":
            nr = reanchor_segments(snaps, cps, events)
            print(f"  segment re-anchor: {nr} between-pin snapshots re-derived from their later pin")
            n = checkpoint_continuity(snaps, cps, events)
            print(f"  continuity repair: restored {n} member-slots between pinned checkpoints")
        if idx == "Nifty 500":
            worst = validate_n500(snaps, wb)
            if worst < 99.0:  # SAFETY GATE: never overwrite good membership with a degraded rebuild
                msg = (
                    f"ABORT: Nifty500 validation {worst:.1f}% < 99% — refusing to write "
                    "(likely a missing input or NSE fetch issue); keeping committed data."
                )
                raise SystemExit(msg)
        # era-correct symbols per snapshot date so they match that period's bhavcopy series
        new_snaps = [
            {"effectiveDate": d, "symbols": sorted({emit(s, d) for s in S})}
            for d, S in snaps.items()
            if d != "1900-01-01"
        ]
        if idx == "Nifty 500" and _era_hits:
            print(
                f"  era-aware emission: {len(_era_hits)} current->old key redirects on Nifty 500 "
                f"({sum(v[0] for v in _era_hits.values())} member-slots); e.g. "
                + "; ".join(f"{k} {v[1][:7]}..{v[2][:7]}" for k, v in sorted(_era_hits.items())[:12])
            )
        new_snaps.sort(key=lambda x: x["effectiveDate"])
        earliest = new_snaps[0]["effectiveDate"]
        kept_old = [s for s in H.get(idx, []) if s["effectiveDate"] < earliest]
        H[idx] = sorted(kept_old + new_snaps, key=lambda s: s["effectiveDate"])
        print(
            f"{idx}: {len(kept_old)} scrapbook (pre-{earliest}) + {len(new_snaps)} accurate = {len(H[idx])} snapshots"
        )

    # --- PHANTOM FLOOR (listing-date, 2026-07-09) ---------------------------------------------------
    # The backward-walk over-extends a stock into snapshots BEFORE it actually joined Nifty 500 whenever
    # its ENTRY event is missing from the changelog (entered via a sub-index add the N500 list didn't
    # restate, or a COVID-deferred / unparsed reconstitution). The UNAMBIGUOUS, symbol-safe correction:
    # a stock cannot be an index constituent before it started trading. Drop any N500 snapshot entry whose
    # stock has NO price history on-or-before that snapshot's date (catches pre-listing phantoms like
    # SUMICHEM shown in 2017 / RBA / POLYCAB / HDFCAMC pre-IPO). We do NOT floor already-listed names
    # (NESTLEIND, ALKYLAMINE) — that needs true membership dates we don't reliably have, so it's left as-is
    # rather than risk false drops off the incomplete pre-2020 archived lists. sf series merge pre-rename
    # history by ISIN, so first-trade-date == the company's real listing (ETERNAL == Zomato 2021, etc.).
    import gzip as _gz

    try:
        _sf = json.loads(_gz.decompress(open(os.path.join(ROOT, "docs", "sf_stock_data.bin"), "rb").read()))["data"]
    except Exception as _e:
        _sf = None
        print("  PHANTOM FLOOR skipped (no sf_stock_data.bin):", _e)
    if _sf is not None and "Nifty 500" in H:
        first_trade = {s: str(o["d"][0]) for s, o in _sf.items() if o.get("d")}  # YYYYMMDD
        dropped = {}
        for snap in H["Nifty 500"]:
            if snap["effectiveDate"] < "2011-01-01":
                continue  # pre-dataset — data coverage incomplete
            dint = snap["effectiveDate"].replace("-", "")
            keep = []
            for sym in snap["symbols"]:
                ft = first_trade.get(sym)
                if ft is not None and ft > dint:  # not yet trading => impossible => phantom
                    dropped.setdefault(sym, []).append(snap["effectiveDate"])
                else:
                    keep.append(sym)
            snap["symbols"] = keep
        json.dump(dict(sorted(dropped.items())), open(os.path.join(HERE, "_phantom_dropped.json"), "w"), indent=0)
        print(
            "  PHANTOM FLOOR (listing): dropped %d pre-listing rows across %d stocks (see _phantom_dropped.json)"
            % (sum(len(v) for v in dropped.values()), len(dropped))
        )

    # --- DERIVE the cleanly-partitionable sub-indices from the VALIDATED Nifty 500 -----------------
    # NSE methodology: Nifty 500 = Nifty 100 (+) Midcap 150 (+) Smallcap 250 (disjoint by mcap rank),
    # and MidSmallcap 400 = Nifty 500 - Nifty 100. Nifty 500 is validated 100% vs archived lists and
    # Nifty 100 is exact, so deriving these two RECOVERS members the sparse per-index press-release
    # reconstruction missed (mainly 2020-21 delisted small-caps that archive.org — blocked here —
    # would otherwise be needed to pin). Smallcap 250 goes from ~233 (missing 19) to ~250.
    def _asof(idx, d):
        best = None
        for s in H.get(idx, []):
            if s["effectiveDate"] <= d:
                best = s
        return set(best["symbols"]) if best else set()

    def _derive(name, fn, basis):
        # Official archived CSVs are ground truth — pin them exact; derive only between.
        offd = {d: sorted({canon(x) for x in v}) for d, v in OFFICIAL.get(name, {}).items()}
        dates = sorted({s["effectiveDate"] for bi in basis for s in H.get(bi, [])} | set(offd))
        out = []
        for d in dates:
            syms = offd.get(d)  # official wins where present
            if not syms:
                # A set-difference is only meaningful once every subtrahend index has
                # history: with e.g. Nifty 100 still empty, N500 - {} would emit a
                # full-N500 placeholder row for a tier that didn't exist yet (these
                # launched Apr-2016). No snapshot at all => _asof correctly returns
                # empty there.
                if any(not _asof(bi, d) for bi in basis[1:]):
                    continue
                syms = sorted(fn(d))
            if not syms or (out and out[-1]["symbols"] == syms):
                continue
            out.append({"effectiveDate": d, "symbols": syms})
        if out:
            H[name] = out
            print(
                f"  derived {name}: {len(out)} snapshots ({len(offd)} official-pinned, rest from {' - '.join(basis)})"
            )

    _derive(
        "Nifty MidSmallcap 400", lambda d: _asof("Nifty 500", d) - _asof("Nifty 100", d), ["Nifty 500", "Nifty 100"]
    )
    _derive(
        "Nifty Smallcap 250",
        lambda d: _asof("Nifty 500", d) - _asof("Nifty 100", d) - _asof("Nifty Midcap 150", d),
        ["Nifty 500", "Nifty 100", "Nifty Midcap 150"],
    )

    # --- MANUAL MEMBERSHIP ADDS (survive every rebuild) -------------------------------------------
    # Verified members the press-release/checkpoint reconstruction can't carry. Applied AFTER the
    # derives so they land ONLY in the listed index. Each: (index, symbol, from_date, to_date).
    #   TATAMTRDVR — Tata Motors DVR. StockView counts the DVR as a Nifty-500 constituent; NSE's
    #   constituent CSVs list only the ordinary share, so the reconstruction shows it in just ~8
    #   semi-annual snapshots and it flickers in/out. It traded continuously until its merger
    #   record date (last trade 2024-08-29) -> hold it in every Nifty 500 snapshot in range.
    #   First added in cf46cc9 as a direct data patch; that was WIPED by the next rebuild (this
    #   script regenerates indicesHistory wholesale), so it now lives here. 2026-07-04.
    MANUAL_ADDS = [("Nifty 500", "TATAMTRDVR", "2018-10-04", "2024-08-29")]
    for m_idx, m_sym, m_from, m_to in MANUAL_ADDS:
        n = 0
        for s in H.get(m_idx, []):
            if m_from <= s["effectiveDate"] <= m_to and m_sym not in s["symbols"]:
                s["symbols"] = sorted(s["symbols"] + [m_sym])
                n += 1
        print(f"  MANUAL ADD {m_sym} -> {m_idx} [{m_from}..{m_to}]: patched {n} snapshots")

    json.dump(H, open(hist_path, "w", encoding="utf-8"), separators=(",", ":"))
    print(f"\nWrote {hist_path}")
    binp = os.path.join(ROOT, "docs", "stock_data.bin")
    D = json.loads(gzip.decompress(open(binp, "rb").read()))
    D["indicesHistory"] = {**D.get("indicesHistory", {}), **{k: H[k] for k in SLUGS if k in H}}
    open(binp, "wb").write(gzip.compress(json.dumps(D, separators=(",", ":")).encode(), 6))
    print(f"Wrote {binp} ({os.path.getsize(binp) / 1048576:.1f} MB)")

    # spot checks
    n5 = H["Nifty 500"]

    def asof(d):
        best = None
        for s in n5:
            if s["effectiveDate"] <= d and (not best or s["effectiveDate"] > best["effectiveDate"]):
                best = s
        return set(best["symbols"])

    print("\nSpot checks (Nifty 500):")
    print("  2023-03-30 SCI (should be True - pre-reshuffle):", "SCI" in asof("2023-03-30"))
    print("  2023-03-31 SCI (should be False - new list live):", "SCI" in asof("2023-03-31"))
    print("  2022-10-09 AWL (Sept-22 add, was broken before):", "AWL" in asof("2022-10-09"))
    print(
        "  2022-06-01 GMRINFRA era-symbol (not GMRAIRPORT):",
        "GMRINFRA" in asof("2022-06-01"),
        "/",
        "GMRAIRPORT" in asof("2022-06-01"),
    )


if __name__ == "__main__":
    main()
