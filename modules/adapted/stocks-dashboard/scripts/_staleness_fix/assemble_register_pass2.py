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


"""Register pass 2 (2026-09-05, DATA_RUNBOOK §132h): graded name→symbol candidates for register names the era map left
unmapped. Inputs are the scratch evidence files produced in that session (archived lists, EQUITY_L pages, press tables,
NSE delisted.csv, suspension pages, results.jsp names, Nifty/Junior change-page joins, BSE master). Kept for the record;
re-run needs those scratch inputs rebuilt from the sources listed in register_names_pass2.json["routes_tried"]."""
import collections
import csv
import datetime
import json
import os
import re
import sys

S = sys.argv[1]
SCRIPTS = sys.argv[2]
sys.path.insert(0, SCRIPTS)
import build_membership_v2 as B

RENAME = json.load(open(os.path.join(SCRIPTS, "_rename_map.json")))
span = json.load(open(f"{S}/sf_span.json"))


def cur(s):
    s = B.canon(s)
    seen = set()
    while s in RENAME and s not in seen:
        seen.add(s)
        s = RENAME[s]
    return s


def strict(x):
    x = (x or "").lower().replace("&", "and")
    x = re.sub(r"\s*-\s*(old|delisted|merged|sus|new|suspended|merge|arrangement|erstwhile|merger)\s*$", "", x)
    x = re.sub(r"\(\s*erstwhile\s*\)", "", x)
    x = re.sub(r"[\(\)]", " ", x)
    x = re.sub(r"[^a-z0-9 ]", " ", x)
    x = re.sub(r"\b(ltd|limited|pvt|private|co|company|inc)\b", " ", x)
    return re.sub(r"\s+", " ", x).strip()


ev = collections.defaultdict(lambda: collections.defaultdict(set))  # strict name -> sym -> {source:date}


def add(name, sym, src):
    if name and sym and re.fullmatch(r"[A-Z][A-Z0-9&\-]{1,13}", sym):
        ev[strict(name)][sym].add(src)


for k, v in json.load(open(f"{S}/era_dict_strict.json")).items():
    for s, ds in v.items():
        for d in ds:
            ev[k][s].add("A:list:" + str(d))
for k, v in json.load(open(f"{S}/prs_pairs_strict.json")).items():
    for s, ds in v.items():
        for d in ds:
            ev[k][s].add("A:press:" + str(d))
for d, pp in json.load(open(f"{S}/era_names_wbcsv_2018.json")).items():
    for n, s in pp.items():
        add(n, s, "A:list:" + d)
for pg, pp in json.load(open(f"{S}/era_equity_l_2003.json")).items():
    for n, s in pp.items():
        add(n, s, "A:equity_l:" + pg[:8])
for s, v in json.load(open(f"{S}/results_names.json")).items():
    if v.get("name"):
        add(v["name"], s, "A:results_jsp:" + v.get("ts", "")[:8])
for n, v in json.load(open(f"{S}/bind_nifty_pages.json")).items():
    add(n, v["sym"], "A:nifty_changes:" + v["via"][1])
for n, sym in json.load(open(f"{S}/nse_delisted_pairs.json")).items():
    add(n, sym, "A:nse_delisted_csv")
for pg, pp in json.load(open(f"{S}/nse_suspension_pairs.json")).items():
    for n, sym in pp.items():
        add(n, sym, "A:nse_suspension:" + pg[:8])
for r in json.load(open(os.path.join(SCRIPTS, "_bse_master_all.json"))):
    sid = r.get("scrip_id")
    if sid and sid in span:
        for f in ("Scrip_Name", "Issuer_Name"):
            add(r.get(f), sid, "B:bse_master")
rev = collections.defaultdict(list)
for o, n in RENAME.items():
    rev[n].append(o)


def tape_keys(sym):
    ks = {sym, cur(sym)}
    st = list(ks)
    while st:
        x = st.pop()
        for o in rev.get(x, []):
            if o not in ks:
                ks.add(o)
                st.append(o)
    return ks


def covers(sym, d, kind):
    di = d.replace("-", "")
    dd = datetime.date.fromisoformat(d)
    lo = (dd - datetime.timedelta(days=60)).strftime("%Y%m%d")
    hi = (dd + datetime.timedelta(days=60)).strftime("%Y%m%d")
    for k in tape_keys(sym):
        sp = span.get(k)
        if not sp:
            continue
        if sp[0] <= hi and sp[1] >= lo:
            return k
        if (
            kind == "exc"
            and sp[1] < di
            and (dd - datetime.date(int(sp[1][:4]), int(sp[1][4:6]), int(sp[1][6:]))).days <= 400
            and sp[0] <= di
        ):
            return k
    return None


def lev1(a, b):
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1 :] == b[i + 1 :] or a[i + 1 :] == b[i:] or a[i:] == b[i + 1 :]


def lookup(name):
    k = strict(name)
    c = ev.get(k)
    if c:
        return c, "strict"
    # one-letter register typos only (Sanghi 'Polysters'): long keys, same first word — 'idi' vs 'iti' must never match
    near = (
        [
            kk
            for kk in ev
            if len(k) >= 8 and abs(len(kk) - len(k)) <= 1 and k.split()[0] == kk.split()[0] and lev1(k, kk)
        ]
        if len(k) >= 8
        else []
    )
    if len(near) == 1:
        return ev[near[0]], "edit1:" + near[0]
    # loose fallback (the gen script's norm: drops india/indian/corporation/of/and…) — ONLY when every loose hit folds
    # to one current-symbol family, so 'bank'-class collisions can never bind
    lk = loose(k)
    hits = {kk: v for kk, v in ev.items() if loose(kk) == lk}
    fam = {cur(sym) for v in hits.values() for sym in v}
    if hits and len(fam) == 1:
        merged = {}
        for v in hits.values():
            for sym, src in v.items():
                merged.setdefault(sym, set()).update(src)
        return merged, "loose-unique:" + "|".join(list(hits)[:2])
    return {}, None


def loose(x):
    x = re.sub(r"\b(india|indian|the|corporation|corp|of|and|ltd|limited|company|co|pvt|private|inc)\b", " ", x)
    return re.sub(r"[^a-z0-9]", "", x)


rows = json.load(open(f"{S}/unmapped125.json"))
table = []
segs_out = {}
grade_ct = collections.Counter()
for cls, name, events in rows:
    cands, how = lookup(name)
    per = []
    ok_all = True
    segs = []
    for d, k in events:
        best = None
        for s, srcs in cands.items():
            tk = covers(s, d, k)
            if not tk:
                continue
            g = "A" if any(x.startswith("A:") for x in srcs) else "B"
            near = min(
                (
                    abs(
                        (
                            datetime.date.fromisoformat(
                                x.split(":")[-1][:4] + "-" + x.split(":")[-1][4:6] + "-" + x.split(":")[-1][6:8]
                            )
                            - datetime.date.fromisoformat(d)
                        )
                    ).days
                    for x in srcs
                    if re.search(r":\d{8}$", x)
                ),
                default=9999,
            )
            cand = (0 if g == "A" else 1, near, s, g, tk)
            if best is None or cand < best:
                best = cand
        if best:
            per.append((d, k, best[2], best[3], best[4], sorted(cands[best[2]])[:2]))
            segs.append((d, best[2]))
        else:
            per.append((d, k, None, None, None, []))
            ok_all = False
    mapped = [p for p in per if p[2]]
    if mapped:
        comp = []
        for d, s in segs:
            if not comp or comp[-1][1] != s:
                comp.append([d, s])
        segs_out[name] = comp
    grade = "A" if mapped and all(p[3] == "A" for p in mapped) else ("B" if mapped else "-")
    grade_ct[(cls, grade, "all" if ok_all else "partial")] += 1
    table.append(
        {
            "class": cls,
            "name": name,
            "grade": grade,
            "how": how,
            "events": per,
            "cands": {s: sorted(v)[:3] for s, v in cands.items()},
            "segs": segs_out.get(name),
        }
    )
json.dump(table, open(f"{S}/unmapped125_table.json", "w"), indent=0)
json.dump(segs_out, open(f"{S}/register_names_era_extra.json", "w"), indent=0)
print("grade counts (class, grade, coverage):")
for k, v in sorted(grade_ct.items()):
    print("  ", k, v)
for cls in ["has 2002-2015 events", "post-2015 only", "pre-2002 only"]:
    print(f"\n=== {cls} ===")
    for t in table:
        if t["class"] == cls:
            print(
                f"  {t['grade']} {t['name'][:44]:44s} {[(p[0], p[1], p[2], p[3]) for p in t['events']]}  cands={list(t['cands'])[:4]}"
            )
