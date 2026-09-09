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


"""Era-dated register-name -> symbol map from NSE's own name/symbol bindings (v2: strict keys).
Evidence: archived official CNX 500 lists 2002-2015 (csv/xls/htm), wayback EQUITY_L 2006/2010/2013/2014, symchg.csv,
optional press-release tables (prs_pairs_strict.json). A register name is matched by STRICT normalised name
(legal suffixes/punctuation only); a LOOSE match is allowed only when it resolves to ONE current-symbol family.
An event gets a symbol only if that symbol's tape (or rename-chain successor) has bars within ±60d of the event;
ties -> nearest evidence date. Scope: events BEFORE the changelog era (2015-03-23) — later events keep the
existing name_map behaviour. MANUAL names in gen_inclexcl_events.py are never touched."""
import collections
import datetime
import json
import os
import re
import sys

S = sys.argv[1]
SCRIPTS = sys.argv[2]
CUTOFF = "2015-03-23"
sys.path.insert(0, SCRIPTS)
import build_membership_v2 as B

RENAME = json.load(open(os.path.join(SCRIPTS, "_rename_map.json")))


def cur(s):
    s = B.canon(s)
    seen = set()
    while s in RENAME and s not in seen:
        seen.add(s)
        s = RENAME[s]
    return s


def strict(x):
    x = (x or "").lower().replace("&", "and")
    x = re.sub(r"\s*-\s*(old|delisted|merged|sus|new|suspended|merge|arrangement|erstwhile)\s*$", "", x)
    x = re.sub(r"[\(\)]", " ", x)
    x = re.sub(r"[^a-z0-9 ]", " ", x)
    x = re.sub(r"\b(ltd|limited|pvt|private|co|company|inc)\b", " ", x)
    return re.sub(r"\s+", " ", x).strip()


def loose(x):
    x = (x or "").lower()
    x = re.sub(r"\(.*?\)", " ", x)
    x = x.replace("pharmaceuticals", "pharma").replace("laboratories", "lab")
    x = re.sub(r"\s*-\s*(old|delisted|merged|sus|new|suspended|merge|arrangement|erstwhile)\s*$", "", x)
    x = re.sub(r"\b(ltd|limited|india|indian|the|company|co|corp|corporation|pvt|private|and|&|of)\b", " ", x)
    return re.sub(r"[^a-z0-9]", "", x)


ES = json.load(open(f"{S}/era_dict_strict.json"))
if os.path.exists(f"{S}/prs_pairs_strict.json"):
    for k, v in json.load(open(f"{S}/prs_pairs_strict.json")).items():
        for s, ds in v.items():
            ES.setdefault(k, {}).setdefault(s, [])
            ES[k][s] = sorted(set(ES[k][s]) | set(ds))
LO = collections.defaultdict(lambda: collections.defaultdict(set))
for k, v in ES.items():
    for s, ds in v.items():
        LO[loose(k)][s] |= set(ds)
span = json.load(open(f"{S}/sf_span.json"))
seq = json.load(open(f"{S}/register_raw.json"))["seq"]
src = open(os.path.join(SCRIPTS, "_staleness_fix", "gen_inclexcl_events.py")).read()
MANUAL = set(re.findall(r"^\s*'([^']+)':\s*'[A-Z0-9&\-]+'", src, flags=re.MULTILINE))
# names whose current mapping is a build_membership_v2.ERA_OVERRIDES target are date-handled there by hand
# (FRETAIL->PANTALOONR, KPITTECH->KPIT, TIINDIA->TUBEINVEST, JSWISPL->JSWISPAT, DALBHARAT->DALMIACEM,
# SHPRE->SPSL, SUMMITSEC->SUMMIT); the era map must not bypass them.
_bsrc = open(os.path.join(SCRIPTS, "build_membership_v2.py")).read()
_ov = set(re.findall(r'^\s*"([A-Z0-9&\-]+)":\s*\("[A-Z0-9&\-]+",\s*"\d{4}-\d{2}-\d{2}"\)', _bsrc, flags=re.MULTILINE))
_prev = (
    json.load(open(os.path.join(SCRIPTS, "_n500_inclexcl_events.json"))).get("name_map", {})
    if os.path.exists(os.path.join(SCRIPTS, "_n500_inclexcl_events.json"))
    else {}
)
OVERRIDE_NAMES = {n for n, sym in _prev.items() if sym in _ov}
print("ERA_OVERRIDES targets", sorted(_ov), "-> names left to the builder:", sorted(OVERRIDE_NAMES))
rev = collections.defaultdict(list)
for o, n in RENAME.items():
    rev[n].append(o)


def tape_keys(sym):
    ks = {sym, cur(sym)}
    stack = list(ks)
    while stack:
        x = stack.pop()
        for o in rev.get(x, []):
            if o not in ks:
                ks.add(o)
                stack.append(o)
    return ks


def covers(sym, d):
    lo = (datetime.date.fromisoformat(d) - datetime.timedelta(days=60)).strftime("%Y%m%d")
    hi = (datetime.date.fromisoformat(d) + datetime.timedelta(days=60)).strftime("%Y%m%d")
    return [k for k in tape_keys(sym) if k in span and span[k][0] <= hi and span[k][1] >= lo]


def evd(x):
    return f"{x[:4]}-{x[4:6]}-{x[6:8]}" if re.fullmatch(r"\d{8}", x) else None


def days(a, b):
    return abs((datetime.date.fromisoformat(a) - datetime.date.fromisoformat(b)).days)


out = {}
rep = collections.Counter()
unm = []
how = {}
for name, events in seq.items():
    if name in MANUAL:
        rep["manual-skipped"] += 1
        continue
    if name in OVERRIDE_NAMES:
        rep["era-override-skipped"] += 1
        continue
    # scope: pre-changelog events unconditionally (the changelog has nothing there); post-cutoff events too
    # (2026-09-05 pass 2, the 33 post-2015-only names) — gen_inclexcl_events.era_sym() applies a post-cutoff
    # segment only when its tape covers the event date, so a wrong-era symbol cannot land there.
    pre = [(d, k) for d, k in events]
    if not pre:
        rep["no-events"] += 1
        continue
    k = strict(name)
    cands = ES.get(k)
    h = "strict"
    if not cands:
        lc = LO.get(loose(name))
        if lc and len({cur(s) for s in lc}) == 1:
            cands = {s: sorted(ds) for s, ds in lc.items()}
            h = "loose-unique"
    if not cands:
        rep["name-not-in-any-list"] += 1
        continue
    segs = []
    for d, kind in pre:
        scored = []
        # symchg validity: an OLD symbol renamed (NSE symchg.csv date) BEFORE the event no longer names the
        # company at that date — skip it when another candidate exists (Bajaj Auto 2008: BAJAJAUTO became
        # BAJAJHLDNG on demerger; the 2008-09-10 inclusion is the NEW listing BAJAJ-AUTO).
        live = [s for s in cands if not (B.REN.get(s) and "1900-01-02" < B.REN[s][1] < d)]
        for s, ev in cands.items():
            if live and s not in live:
                continue
            tk = covers(s, d)
            if not tk:
                continue
            near = min((days(d, e) for e in (evd(x) for x in ev) if e), default=9999)
            scored.append((near, s))
        if not scored:
            unm.append((name, d, kind, sorted(cands)))
            continue
        scored.sort()
        segs.append((d, scored[0][1]))
    if not segs:
        rep["no-event-covered-by-a-tape"] += 1
        continue
    comp = []
    for d, s in segs:
        if not comp or comp[-1][1] != s:
            comp.append([d, s])
    out[name] = comp
    how[name] = h
    rep["mapped"] += 1
    rep[f"mapped-{h}"] += 1
twins = {}
for name, segs in out.items():
    syms = []
    for _, sym in segs:
        if sym not in syms:
            syms.append(sym)
    if len(syms) < 2:
        continue
    for a in syms:
        for b in syms:
            if a >= b or cur(a) == cur(b):
                continue
            sa, sb = span.get(a), span.get(b)
            if sa and sb and (sa[1] < sb[0] or sb[1] < sa[0]):
                old_, new_ = (a, b) if sa[0] < sb[0] else (b, a)
                twins[old_] = new_
json.dump(twins, open(f"{S}/seam_twins.json", "w"), indent=0)
print("seam twins (same company, sequential tapes, no rename chain):", len(twins), twins)
json.dump(out, open(f"{S}/register_names_era.json", "w"), indent=0)
json.dump(unm, open(f"{S}/register_names_unmapped_events.json", "w"), indent=0)
print("report:", dict(rep), "| pre-cutoff events left unmapped:", len(unm))
multi = [(n, c) for n, c in out.items() if len(c) > 1]
print("multi-era names:", len(multi))
for n, c in multi:
    print("   ", n, c)
for q in [
    "Bajaj Auto Ltd.",
    "Max India Ltd.",
    "Gateway Distriparks Ltd.",
    "Mirc Electronics Ltd.",
    "Pricol Ltd.",
    "Sundaram Clayton Ltd.- OLD",
    "Gujarat Fluorochemicals Ltd.",
    "ITC Hotels Ltd.",
    "IDBI Bank Ltd.",
    "IDBI Bank Ltd.-OLD",
    "Agro Dutch Industries Ltd.",
    "Accelya Kale Solutions Ltd.",
    "Koutons Retail India Ltd.",
    "Tulip Telecom Ltd.",
    "Reliance Natural Resources Ltd.",
    "Satyam Computer Services Ltd.",
    "Ceat Ltd.",
    "Corporation Bank",
    "Jindal Stainless (Hisar) Ltd.",
]:
    print(f"   {q:36s} -> {out.get(q)}  [{how.get(q)}]")
