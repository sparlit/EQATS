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
"""Nifty SME Emerge — point-in-time membership 2020→ from NSE Indices' own press releases  (runbook §210).

SOURCES
  events   scripts/nse_sme_emerge_events.json — every NSE Indices press release that names the index, parsed by
           nse_sme_emerge_prs.parse_text (kept verbatim: stem, title, eff, ex, inc, revoke) + `adjust`, the few
           changes a release states in prose (re-dated exclusions, the March-2020 review NSE declared null and void,
           the Emkay demerger entity) — each with the release that says it.
  anchor   docs/nse_sme_emerge/members.json — NSE's official constituent list (ind_niftysmelist.csv) as captured.
  renames  scripts/nse_sme_emerge_renames.json — [old, new, first day under new]: NSE's symbolchange.csv rows plus
           renames seen in the bhavcopies by ISIN (same ISIN, new symbol the next session) that NSE's file lacks.

METHOD  Walk BACK from the official list: undo each event (an inclusion removes the stock, an exclusion puts it back)
  from the latest in-force one down to 2020-01-01 (user scope: data from 1-Jan-2020). Every symbol is carried in
  TODAY's spelling (renames folded forward) so one company is one key. A change dated after the list's capture is an
  ANNOUNCED reshuffle — kept as a future snapshot, never applied to "today".
  Every inconsistency is printed and stored, never smoothed: an inclusion of a stock that is not in the later roster
  or an exclusion of one already in it means an event is missing between them.
  Checks: NSE's archived official lists (Wayback: 2019-03-19, 2023-08-03) against the walk on the same day; no member
  before its first SME trading day (bhavcopy, by ISIN) — both computed locally with --check (needs the caches).

OUTPUT  docs/nse_sme_emerge/history.json    {"Nifty SME Emerge": [{effectiveDate, symbols}…]} — indicesHistory shape,
                                              first snapshot 2020-01-01, one per event date, last = any announced one
        docs/nse_sme_emerge/stints.json     {stints:[{sym, name, join, leave, join_src, leave_src, from_start}]}
        docs/nse_sme_emerge/ever.json       {sym: [[join, leave|null]…]} — the stock page's chip (small; in-force stints)
        docs/nse_sme_emerge/events.json     the dated changes as applied (for the page's change log)
        docs/nse_sme_emerge/validation.json conflicts, archived-list checks, unread releases

  python3 scripts/build_nse_sme_emerge_pit.py              (CI + local)
  python3 scripts/build_nse_sme_emerge_pit.py --check      (+ archived lists / listing floor from ~/stocks-cache)
  python3 scripts/build_nse_sme_emerge_pit.py --seed DIR   (local: (re)parse every release text in DIR/prtxt into the ledger)
"""
import csv
import datetime
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import nse_sme_emerge_prs as N

ROOT = os.path.dirname(HERE)
DIR = os.path.join(ROOT, "docs", "nse_sme_emerge")
LEDGER = os.path.join(HERE, "nse_sme_emerge_events.json")
RENAMES = os.path.join(HERE, "nse_sme_emerge_renames.json")
START = "2020-01-01"
NAME = "Nifty SME Emerge"
CACHE = os.path.expanduser(os.environ.get("NSE_SME_EMERGE_CACHE", "~/stocks-cache/nse_sme_emerge"))


def load(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return d


def dump(p, o, compact=False):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        if compact:
            json.dump(o, f, separators=(",", ":"), ensure_ascii=False)
        else:
            json.dump(o, f, indent=1, ensure_ascii=False)
    os.replace(p + ".tmp", p)


def seed(src):
    """Local: parse every cached release text into the ledger (keeps adjust / unread / titles already there)."""
    L = load(LEDGER, {}) or {}
    rel = L.get("releases", {})
    titles = dict(load(os.path.join(src, "pr_list_2019on.json"), []) or [])
    txt = os.path.join(src, "prtxt")
    for f in sorted(os.listdir(txt)):
        r = N.parse_text(open(os.path.join(txt, f), encoding="utf-8").read())
        if not r.get("sme"):
            continue
        stem = f[:-4]
        r.pop("sme")
        r["title"] = titles.get(stem + ".pdf") or (rel.get(stem) or {}).get("title")
        rel[stem] = r
    L["releases"] = dict(
        sorted(rel.items(), key=lambda kv: (kv[0][11:15] + kv[0][9:11] + kv[0][7:9], kv[0]))
    )
    dump(LEDGER, L)
    print("ledger: %d releases naming the index" % len(rel))


class Renames:
    def __init__(self):
        self.r = [tuple(x[:3]) for x in (load(RENAMES, {}) or {}).get("renames", [])]

    def cur(self, s, d):
        """today's spelling of symbol s as announced on day d (renames after d, chained)"""
        for _ in range(12):
            nxt = [x for x in self.r if x[0] == s and x[2] > d]
            if not nxt:
                return s
            o, n, x = min(nxt, key=lambda t: t[2])
            s, d = n, x
        return s


def events(L):
    """[(eff, stem, kind, SYM-as-announced, name)] after voids, revocations and adjustments."""
    rel = L.get("releases", {})
    void = {v["stem"] for v in L.get("void", [])}
    out = []
    revoked = set()
    for stem, r in rel.items():
        for sym, d in r.get("revoke") or []:
            revoked.add((sym, d))
    for stem, r in rel.items():
        if stem in void or not r.get("eff"):
            continue
        for kind in ("ex", "inc"):
            for sym, nm in r.get(kind) or []:
                if kind == "inc" and (sym, r["eff"]) in revoked:
                    continue
                out.append([r["eff"], stem, kind, sym, nm])
    for a in L.get("adjust", []):
        if a["op"] == "redate":  # an announced exclusion moved to another day by a later release
            hit = [e for e in out if e[1] == a["of"] and e[3] == a["sym"] and e[2] == a["kind"]]
            if len(hit) != 1:
                raise SystemExit("adjust %r matches %d events" % (a, len(hit)))
            hit[0][0], hit[0][1] = a["eff"], a["stem"]
        elif a["op"] == "add":
            out.append([a["eff"], a["stem"], a["kind"], a["sym"], a.get("name", "")])
        else:
            raise SystemExit(f"unknown adjust op {a!r}")
    out.sort(key=lambda e: (e[0], e[1], e[2], e[3]))
    return out


def main():
    a = sys.argv[1:]
    if "--seed" in a:
        seed(os.path.expanduser(a[a.index("--seed") + 1]))
    L = load(LEDGER)
    mem = load(os.path.join(DIR, "members.json"))
    if not L or not mem:
        raise SystemExit(f"need {LEDGER} and docs/nse_sme_emerge/members.json")
    RN = Renames()
    asof = mem["asof"]
    today = {m["sym"] for m in mem["members"]}
    names = {m["sym"]: m["name"] for m in mem["members"]}
    EV = events(L)
    for e in EV:
        e.append(RN.cur(e[3], e[0]))  # [eff, stem, kind, sym_then, name, sym_now]
        names.setdefault(e[5], e[4])
    past = [e for e in EV if START < e[0] <= asof]
    future = [e for e in EV if e[0] > asof]
    # walk back
    R = set(today)
    snaps = {}
    conflicts = []
    for d in sorted({e[0] for e in past}, reverse=True):
        snaps[d] = sorted(R)
        for e in [x for x in past if x[0] == d]:
            s = e[5]
            if e[2] == "inc":
                if s in R:
                    R.discard(s)
                else:
                    conflicts.append(
                        {
                            "eff": d,
                            "stem": e[1],
                            "kind": "inc",
                            "sym": e[3],
                            "now": s,
                            "why": "included here but not in the later roster — an exclusion after this is missing",
                        }
                    )
            else:
                if s in R:
                    conflicts.append(
                        {
                            "eff": d,
                            "stem": e[1],
                            "kind": "ex",
                            "sym": e[3],
                            "now": s,
                            "why": "excluded here but already in the earlier roster — an inclusion before this is missing",
                        }
                    )
                R.add(s)
    snaps[START] = sorted(R)
    hist = [{"effectiveDate": d, "symbols": snaps[d]} for d in sorted(snaps)]
    # announced, not yet in force
    if future:
        F = set(today)
        for e in future:
            (F.discard if e[2] == "ex" else F.add)(e[5])
        hist.append(
            {"effectiveDate": max(e[0] for e in future), "symbols": sorted(F), "announced": True}
        )
    # stints
    st = []
    prev, opened = set(), {}
    src_of = {}
    for e in EV:
        src_of[(e[5], e[0], e[2])] = e[1]
    for i, h in enumerate(hist):
        S = set(h["symbols"])
        for s in prev - S:
            x = opened.pop(s)
            x["leave"], x["leave_src"] = (
                h["effectiveDate"],
                src_of.get((s, h["effectiveDate"], "ex")),
            )
        for s in S - prev:
            x = {
                "sym": s,
                "name": names.get(s),
                "join": h["effectiveDate"],
                "leave": None,
                "join_src": src_of.get((s, h["effectiveDate"], "inc")),
                "leave_src": None,
                "from_start": i == 0,
                "announced": bool(h.get("announced")),
            }
            opened[s] = x
            st.append(x)
        prev = S
    dump(os.path.join(DIR, "history.json"), {NAME: hist}, compact=True)
    dump(
        os.path.join(DIR, "stints.json"),
        {
            "updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "start": START,
            "rosterAsOf": asof,
            "stints": st,
        },
    )
    # compact per-stock membership for the stock page's chip: {sym: [[join, leave|null]…]} — stints in force only
    ever = {}
    for x in st:
        if not x["announced"]:
            ever.setdefault(x["sym"], []).append([x["join"], x["leave"]])
    dump(
        os.path.join(DIR, "ever.json"),
        {"asof": asof, "start": START, "members": ever},
        compact=True,
    )
    dump(
        os.path.join(DIR, "events.json"),
        {
            "events": [
                {
                    "eff": e[0],
                    "src": e[1],
                    "action": "add" if e[2] == "inc" else "remove",
                    "sym": e[5],
                    "asAnnounced": e[3],
                    "name": e[4],
                }
                for e in EV
                if e[0] > START
            ]
        },
    )
    val = load(os.path.join(DIR, "validation.json"), {}) or {}
    val.update(
        {
            "built": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "rosterAsOf": asof,
            "rosterNow": len(today),
            "roster2020": len(snaps[START]),
            "snapshots": len(hist),
            "events": len(past),
            "announced": len(future),
            "conflicts": conflicts,
            "unread": L.get("unread", []),
        }
    )
    if "--check" in a:
        val["checks"] = checks(hist, RN)
    dump(os.path.join(DIR, "validation.json"), val)
    print(
        "pit: roster %s = %d, 2020-01-01 = %d, %d snapshots, %d events (+%d announced), %d stints, %d conflict(s)"
        % (
            asof,
            len(today),
            len(snaps[START]),
            len(hist),
            len(past),
            len(future),
            len(st),
            len(conflicts),
        )
    )
    for c in conflicts:
        print("  CONFLICT", c["eff"], c["stem"], c["kind"], c["sym"], "->", c["now"])


def roster_on(hist, d):
    cur = None
    for h in hist:
        if h["effectiveDate"] <= d and not h.get("announced"):
            cur = h
    return set(cur["symbols"]) if cur else set()


def checks(hist, RN):
    out = {"archived": [], "beforeFirstTrade": []}
    for f in sorted(os.listdir(os.path.join(CACHE, "archived"))):
        ts = f[:14]
        d = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        if d < START:
            continue
        arch = {
            RN.cur(r["Symbol"].strip(), d)
            for r in csv.DictReader(open(os.path.join(CACHE, "archived", f)))
        }
        R = roster_on(hist, d)
        out["archived"].append(
            {
                "capture": ts,
                "official": len(arch),
                "rebuilt": len(R),
                "both": len(arch & R),
                "officialOnly": sorted(arch - R),
                "rebuiltOnly": sorted(R - arch),
            }
        )
    P = json.load(gzip.open(os.path.join(CACHE, "sme_panel.json.gz"), "rt"))["s"]
    isin_of, first = {}, {}
    for s, rows in P.items():
        for x in rows:
            if x[10]:
                isin_of.setdefault(s, set()).add(x[10][:7])
                if x[1] in ("SM", "ST", "SZ"):
                    first[x[10][:7]] = min(first.get(x[10][:7], 99999999), x[0])
    seen = set()
    for h in hist:
        k = int(h["effectiveDate"].replace("-", ""))
        for s in h["symbols"]:
            f = min(
                [first[i] for i in isin_of.get(s, ()) if i in first] or [None], key=lambda v: v or 0
            )
            if f and f > k + 3 and s not in seen:
                seen.add(s)
                out["beforeFirstTrade"].append(
                    {"sym": s, "snapshot": h["effectiveDate"], "firstSmeBar": f}
                )
    for c in out["archived"]:
        print(
            "  check: official list %s — %d official, %d rebuilt, %d both; official-only %s rebuilt-only %s"
            % (
                c["capture"],
                c["official"],
                c["rebuilt"],
                c["both"],
                c["officialOnly"],
                c["rebuiltOnly"],
            )
        )
    for b in out["beforeFirstTrade"]:
        print(
            "  check: {} in the {} roster before its first SME trade {}".format(
                b["sym"], b["snapshot"], b["firstSmeBar"]
            )
        )
    return out


if __name__ == "__main__":
    main()
