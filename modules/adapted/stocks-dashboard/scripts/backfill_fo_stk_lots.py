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
"""Backfill of stock-futures lots (2026-09-25, runbook §162a): scripts/_fo_stk_lots/YYYY-MM.json.gz,
scripts/_fo_stk_state.json (corporate-action ledger + last day's per-contract tail) and "lfs" on
docs/fii_fo.json.  Same parsers as the daily job (fetch_fii_dii.fo_futures_contracts /
fo_lots_summary / detect_stk_ca / apply_stk_lot_factor).  Per-day contract rows cache under CACHE.
Run:  python3 scripts/backfill_fo_stk_lots.py
"""
import collections
import datetime as dt
import gzip
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_fii_dii as F
from fetch_fo_bhavcopy import url_for

CACHE = os.path.expanduser("~/stocks-wt/fo_stk_cache_v2")
os.makedirs(CACHE, exist_ok=True)
H = {"User-Agent": F.UA, "Referer": "https://www.nseindia.com/"}


def day(ds):
    cp = os.path.join(CACHE, ds + ".json.gz")
    if os.path.exists(cp):
        return ds, json.load(gzip.open(cp, "rt"))
    d = dt.date.fromisoformat(ds)
    for a in range(4):
        try:
            blob = F._get(url_for(d), headers=H, timeout=60, binary=True)
            break
        except Exception as e:
            if getattr(e, "code", None) == 404:
                json.dump({"none": True}, gzip.open(cp, "wt"))
                return ds, {"none": True}
            time.sleep(2 + 3 * a)
    else:
        return ds, {"err": True}
    c = F.fo_futures_contracts(d, blob=blob)
    out = {"stk": c["stk"]} if c and c["stk"] else {"none": True}
    json.dump(out, gzip.open(cp, "wt"))
    return ds, out


def main():
    fo = F._load_rows(F.OUT_FO)
    with ThreadPoolExecutor(6) as ex:
        res = {}
        for i, (ds, o) in enumerate(ex.map(day, sorted(fo))):
            res[ds] = o
            if i % 500 == 0:
                print(i, len(fo), ds, flush=True)
    errs = [d for d, o in res.items() if o.get("err")]
    if errs:
        print("fetch errors", errs[:20], "— re-run (cached days are skipped)")
        return
    days, ca, rejected, tail = {}, {}, [], None
    resid = []
    order = [d for d in sorted(res) if "stk" in res[d]]
    tails = {d: F.stk_tail([tuple(x) for x in res[d]["stk"]]) for d in order}
    # corporate actions (runbook §162a): before UDiFF (2024-07-08) the lots are inferred and a
    # lot revision on a crashing stock can mimic a bonus, so an event counts only when the OFFICIAL
    # ledger (corp_actions.json + _hist, price factor f) lists it AND NSE's lots changed by 1/f
    # (most-held contract both sides: last stored day before the ex-date vs the 3rd stored day
    # from it, within 3%).  From UDiFF on, lots are exact: detect_stk_ca's own finding stands
    # (all 27 events it found 2024-07..2026-09 are also in the ledger).
    import bisect

    led = collections.defaultdict(list)
    for f in ("corp_actions.json", "corp_actions_hist.json"):
        for s0, v in json.load(open(os.path.join(HERE, f))).get("factors", {}).items():
            for x in v:
                d0 = "%04d-%02d-%02d" % (
                    int(x[0]) // 10000,
                    int(x[0]) // 100 % 100,
                    int(x[0]) % 100,
                )
                if "2012-01-01" < d0 < "2024-07-08" and float(x[1]) > 0:
                    led[F.canon(s0)].append((d0, 1 / float(x[1])))
    by_canon = collections.defaultdict(set)
    for d in order:
        for s0 in tails[d]:
            by_canon[F.canon(s0)].add(s0)
    verified, unverified = 0, []
    qty = {d: {(x[0], x[1]): x[2] for x in res[d]["stk"]} for d in order}

    def mode_lot(ds, s0, e):
        v = [tails[d][s0][e][0] for d in ds if e in tails[d].get(s0, {})]
        return collections.Counter(v).most_common(1)[0][0] if v else None

    for cs, evs in led.items():
        for d0, r in sorted(set(evs)):
            i = bisect.bisect_left(order, d0)
            if i < 3 or i + 3 > len(order):
                continue
            before, after = order[i - 3 : i], order[i : i + 3]
            ok = None
            for s0 in by_canon.get(cs, ()):
                # the stock's most-held contract (by open quantity) that spans the ex-date; its
                # usual lot over 3 days either side — a single day's inferred lot can be off
                # (LT 2013-07-10 read 378 for 250)
                exps = {e for (s1, e), q in qty[after[-1]].items() if s1 == s0}
                exps &= {e for (s1, e) in qty[before[0]] if s1 == s0}
                if not exps:
                    continue
                e0 = max(exps, key=lambda e: qty[after[-1]].get((s0, e), 0))
                la, lb = mode_lot(before, s0, e0), mode_lot(after, s0, e0)
                if not la or not lb:
                    continue
                ok = abs(lb / la / r - 1) < 0.03
                if ok:
                    break
            if ok:
                ca.setdefault(cs, []).append([order[i], round(r, 6)])
                verified += 1
            elif ok is False:
                unverified.append([d0, cs, round(r, 4)])
    print(
        "ledger events on F&O stocks: verified",
        verified,
        "| lots did NOT move by the ledger ratio",
        len(unverified),
        unverified[:15],
    )
    for i, d in enumerate(order):
        rows = [tuple(x) for x in res[d]["stk"]]
        if tail is not None and d >= "2024-07-08":
            found, rej = F.detect_stk_ca(tail, rows)
            for s0, r in found:
                ca.setdefault(F.canon(s0), []).append([d, r])
            rejected += [[d, s0, why] for s0, why in rej]
        tail = tails[d]
        S = F.fo_lots_summary(rows)
        days[d] = S
        tot = sum(fo[d]["oi"][p]["futStk"][0] for p in fo[d]["oi"])
        n = sum(v[1] for v in S["q"].values())
        if abs(n - tot) > 0.5:
            resid.append((d, round((tot - n) / tot * 100, 3)))
    collections.Counter("exact" if not any(x[0] == d for x in resid) else "x" for d in days)
    ab = sorted(abs(x[1]) for x in resid)
    print("stock days", len(days), "no bhavcopy", [d for d, o in res.items() if "stk" not in o])
    print(
        "contract-count vs participant: exact",
        len(days) - len(resid),
        "| off",
        len(resid),
        "| within 0.1%",
        len(days) - sum(1 for v in ab if v >= 0.1),
        "| within 1%",
        len(days) - sum(1 for v in ab if v >= 1),
        "| worst",
        sorted(resid, key=lambda x: -abs(x[1]))[:6],
    )
    print(
        "corporate actions found",
        sum(len(v) for v in ca.values()),
        "rejected lot changes",
        len(rejected),
    )
    # share of contracts in stocks not in F&O today (kept at their own count)
    ref = {F.canon(k) for k in days[max(days)]["ref"]}
    dead = collections.defaultdict(list)
    for d, S in days.items():
        n = sum(v[1] for v in S["q"].values())
        dn = sum(v[1] for s, v in S["q"].items() if F.canon(s) not in ref)
        dead[d[:4]].append(dn / n * 100)
    print(
        "share of stock-futures contracts in stocks not in F&O today, by year (median %):",
        {y: round(sorted(v)[len(v) // 2], 1) for y, v in sorted(dead.items())},
    )
    json.dump(
        {"ca": ca, "rejected": rejected}, open(os.path.join(CACHE, "_review.json"), "w"), indent=1
    )
    # write shards + state + lfs
    shard_dir = os.path.join(HERE, "_fo_stk_lots")
    os.makedirs(shard_dir, exist_ok=True)
    by_m = collections.defaultdict(dict)
    for d, S in days.items():
        by_m[d[:7]][d] = S
    for m, dd in by_m.items():
        with gzip.GzipFile(os.path.join(shard_dir, m + ".json.gz"), "wb", mtime=0) as fh:
            fh.write(json.dumps(dd, separators=(",", ":"), sort_keys=True).encode())
    json.dump(
        {"ca": ca, "rejected": rejected[-200:], "tail_date": max(days), "tail": tail},
        open(os.path.join(HERE, "_fo_stk_state.json"), "w"),
        separators=(",", ":"),
        sort_keys=True,
    )
    F.apply_stk_lot_factor(fo, days, ca)
    doc = json.load(open(F.OUT_FO))
    rows = [fo[d] for d in sorted(fo)]
    json.dump(
        {"updated": doc["updated"], "rows": rows},
        open(F.OUT_FO, "w", encoding="utf-8"),
        separators=(",", ":"),
    )
    print("wrote", len(by_m), "shards, lfs on", sum(1 for r in rows if "lfs" in r), "rows")


if __name__ == "__main__":
    main()
