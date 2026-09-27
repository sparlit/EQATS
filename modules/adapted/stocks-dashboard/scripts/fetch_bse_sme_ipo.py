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
"""BSE SME IPO index — official daily level + today's official member list  (runbook §195).

WHAT. Two BSE api feeds (both measured 2026-09-27, found in bseindia.com's own JS bundle):
  level    /IndexArchDailyPAR/w?fmdt=DD/MM/YYYY&index=SMEIPO&period=D&todt=DD/MM/YYYY
           → Table[{tdate, I_open, I_high, I_low, I_close, ...}]  (history back to the base date 16-Aug-2012 = 100)
  members  /NS_IndexWeight_SPDJ_ng/w?iname=SMEIPO
           → Table[{Date, Scrip_code, Scrip_Name, ISIN_NUMBER, Weightage, MKT_CAP, FreeFloat_MktCap, close_price}]
           (BSE serves only the CURRENT list, stamped with the date it applies to — no archive of past lists)

OUTPUT.
  docs/bse_sme_ipo.json                   {updated, px:{YYYY-MM-DD: close}, to:{date: turnover ₹cr}, vol:{date: shares cr}}
                                          (px = the nifty500.json shape — the
                                          home card + index-chart.html read it)
  docs/bse_sme_ipo/members.json           {asof, source, members:[{code,name,isin,sym,weight,mcap,ffmcap,close}]}
  docs/bse_sme_ipo/changes.json           {events:[{date, action:add|remove, code, name, isin}]} — every change BSE's
                                          list shows between two of OUR snapshots (a list's own Date decides the day)
  docs/bse_sme_ipo/snapshots/<date>.json  the raw official list as captured (one per list Date)

RULES. bse_headers on every request (§181); one request at a time; the level history is fetched in full only when
the file is absent, otherwise from 15 days before the last stored date (BSE revises nothing older in practice, and a
full re-pull is cheap anyway: 2 calls). A list whose Date is older than the stored one is ignored (never re-dates).

Run: python3 scripts/fetch_bse_sme_ipo.py            (level + members)
     python3 scripts/fetch_bse_sme_ipo.py --full     (re-pull the whole level history)
"""
import os as _o
import sys as _s

_s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))
import bse_headers
import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_LEVEL = os.path.join(ROOT, "docs", "bse_sme_ipo.json")
DIR = os.path.join(ROOT, "docs", "bse_sme_ipo")
OUT_MEM = os.path.join(DIR, "members.json")
OUT_CHG = os.path.join(DIR, "changes.json")
SNAPS = os.path.join(DIR, "snapshots")
UNIV = os.path.join(ROOT, "docs", "bse_universe.json")
API = "https://api.bseindia.com/BseIndiaAPI/api"
BASE = datetime.date(2012, 8, 16)  # BSE methodology: base date 16-Aug-2012, base value 100


def get_json(path, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(API + path, timeout=90) as r:
                body = r.read()
            return json.loads(body)
        except Exception as e:  # a 403/HTML body is a request problem (§181) — retry spaced, then fail loud
            last = e
            time.sleep(5 * (i + 1))
    msg = f"BSE {path} failed: {last!r}"
    raise RuntimeError(msg)


def load(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def dump(p, obj, compact=False):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, separators=(",", ":"), sort_keys=True)
        else:
            json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, p)


def fetch_level(full):
    cur = load(OUT_LEVEL, {"px": {}})
    px = dict(cur.get("px") or {})
    to = dict(cur.get("to") or {})  # BSE's daily turnover of the constituents (₹ cr) — the membership check
    vol = dict(cur.get("vol") or {})  # shares traded (crore) — same use
    today = datetime.date.today()
    start = BASE if (full or not px) else datetime.date.fromisoformat(max(px)) - datetime.timedelta(days=15)
    got = 0
    y = start
    while y <= today:
        end = min(datetime.date(y.year + 3, 12, 31), today)
        q = urllib.parse.urlencode(
            {"fmdt": y.strftime("%d/%m/%Y"), "index": "SMEIPO", "period": "D", "todt": end.strftime("%d/%m/%Y")}
        )
        rows = (get_json("/IndexArchDailyPAR/w?" + q) or {}).get("Table") or []
        for r in rows:
            d, c = (r.get("tdate") or "")[:10], r.get("I_close")
            if len(d) == 10 and isinstance(c, (int, float)) and c > 0:
                px[d] = round(float(c), 2)
                got += 1
                for key, dst in (("Turnover", to), ("TOTAL_SHARES_TRADED", vol)):
                    try:
                        dst[d] = float(r.get(key))
                    except (TypeError, ValueError):
                        pass  # BSE prints "-" on some days: leave the day out, never 0
        y = end + datetime.timedelta(days=1)
        time.sleep(1.5)
    if len(px) < 3000:  # measured 2026-09-27: 2012-08-16 → today ≈ 3,450 sessions
        raise SystemExit("level history too short (%d) — refusing to write" % len(px))
    dump(
        OUT_LEVEL,
        {
            "updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "BSE IndexArchDailyPAR index=SMEIPO",
            "px": dict(sorted(px.items())),
            "to": dict(sorted(to.items())),
            "vol": dict(sorted(vol.items())),
        },
        compact=True,
    )
    print("level: %d rows read, %d stored, last %s = %s" % (got, len(px), max(px), px[max(px)]))


def fetch_members():
    rows = (get_json("/NS_IndexWeight_SPDJ_ng/w?iname=SMEIPO") or {}).get("Table") or []
    if len(rows) < 10:  # methodology floor: the index always holds >= 10 companies
        raise SystemExit("member list has %d rows — refusing to write" % len(rows))
    dates = {(r.get("Date") or "")[:10] for r in rows}
    if len(dates) != 1:
        msg = f"member list carries several dates {sorted(dates)} — refusing"
        raise SystemExit(msg)
    asof = dates.pop()
    # scrip code -> our BSE key (bse_universe rows: [code, scrip_id, name, isin, group, fv, mcap, industry])
    code2id = {}
    for u in load(UNIV, {}).get("rows") or []:
        code2id[str(u[0])] = u[1]
    mem = []
    for r in rows:
        code = str(r.get("Scrip_code") or "").strip()
        sid = code2id.get(code)
        mem.append(
            {
                "code": code,
                "name": (r.get("Scrip_Name") or "").strip(),
                "isin": (r.get("ISIN_NUMBER") or "").strip(),
                "sym": (sid + ".BO") if sid else None,
                "weight": r.get("Weightage"),
                "mcap": r.get("MKT_CAP"),
                "ffmcap": r.get("FreeFloat_MktCap"),
                "close": _num(r.get("close_price")),
            }
        )
    mem.sort(key=lambda m: -(m["weight"] or 0))

    prev = load(OUT_MEM, None)
    if prev and prev.get("asof", "") > asof:
        print("members: BSE list dated {} is OLDER than stored {} — ignored".format(asof, prev["asof"]))
        return
    dump(os.path.join(SNAPS, asof + ".json"), {"asof": asof, "rows": rows})
    chg = load(OUT_CHG, {"events": []})
    if prev and prev.get("asof") != asof:
        old = {m["code"]: m for m in prev["members"]}
        new = {m["code"]: m for m in mem}
        ev = [
            {"date": asof, "action": "add", "code": c, "name": new[c]["name"], "isin": new[c]["isin"]}
            for c in sorted(set(new) - set(old))
        ]
        ev += [
            {"date": asof, "action": "remove", "code": c, "name": old[c]["name"], "isin": old[c]["isin"]}
            for c in sorted(set(old) - set(new))
        ]
        if ev:
            chg["events"].extend(ev)
            chg["events"].sort(key=lambda e: (e["date"], e["action"], e["code"]))
        print("members: %s -> %s  +%d / -%d" % (prev["asof"], asof, len(set(new) - set(old)), len(set(old) - set(new))))
    dump(OUT_CHG, chg)
    dump(
        OUT_MEM,
        {
            "asof": asof,
            "source": "BSE NS_IndexWeight_SPDJ_ng iname=SMEIPO",
            "updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "members": mem,
        },
    )
    print("members: %d as of %s (%d mapped to a BSE key)" % (len(mem), asof, sum(1 for m in mem if m["sym"])))
    # point-in-time history (docs/bse_sme_ipo/history.json, built 2020→ by build_bse_sme_ipo_pit.py): from here on BSE's
    # own captured list IS the record — append a snapshot dated by the list whenever the member set changes
    hp = os.path.join(DIR, "history.json")
    h = load(hp, None)
    if h and h.get("BSE SME IPO"):
        snaps = h["BSE SME IPO"]
        syms = sorted((m["sym"] or m["code"]) for m in mem)
        last = snaps[-1]
        if asof >= last["effectiveDate"] and syms != last["symbols"]:
            if asof == last["effectiveDate"]:
                last["symbols"] = syms
            else:
                snaps.append({"effectiveDate": asof, "symbols": syms})
            with open(hp + ".tmp", "w") as f:
                json.dump(h, f, separators=(",", ":"))
            os.replace(hp + ".tmp", hp)
            print(
                "history: snapshot %s (%d members) %s"
                % (asof, len(syms), "replaced" if asof == last["effectiveDate"] else "appended")
            )
    # stints (the every-member table's membership): open a stint for a code that appears on BSE's list, close the open
    # stint of a code that left it — dated by the list's own Date, source "official list"
    sp = os.path.join(DIR, "stints.json")
    sj = load(sp, None)
    if sj and sj.get("stints") is not None:
        st = sj["stints"]
        cur = {m["code"]: m for m in mem}
        open_ = {x["code"]: x for x in st if x.get("join") and x.get("leave") is None}
        changed = 0
        for code, m in cur.items():
            if code not in open_:
                st.append(
                    {
                        "code": code,
                        "id": (m["sym"] or "")[:-3] or None,
                        "isin": m["isin"],
                        "name": m["name"],
                        "status": "Active",
                        "listing": None,
                        "join": asof,
                        "leave": None,
                        "join_src": "official list " + asof,
                        "leave_src": None,
                        "from_start": False,
                    }
                )
                changed += 1
        for code, x in open_.items():
            if code not in cur and x["join"] < asof:
                x["leave"], x["leave_src"] = asof, "official list " + asof
                changed += 1
        if changed:
            sj["updated"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            dump(sp, sj)
            print("stints: %d change(s) from the %s list" % (changed, asof))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    fetch_level("--full" in sys.argv)
    fetch_members()
