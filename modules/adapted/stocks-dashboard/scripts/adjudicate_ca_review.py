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
"""Adjudicate scripts/ca_review_evidence.json (DATA_RUNBOOK §161g). Rules fixed BEFORE the evidence
was read; every verdict names the records it rests on. Prints a summary and writes
scripts/ca_review_verdicts.json. `--apply` also writes the resulting ledger entries.

  F   = factor baked into the published bins at the boundary (a -> b)
  raw = the exchange's own close-to-close move (bhavcopy when fetched, else the audit's value)

Verdicts
  REAL            an EXCHANGE record (NSE either board, or BSE) of a split/bonus/consolidation whose
                  factor (same parser as build_corp_actions) matches F within 3% (same-day records
                  multiplied). The adjustment is right; --apply records the factor in
                  corp_actions_hist.json so it is officially backed from now on.
  WRONG_FACTOR    an exchange split/bonus record exists but its factor differs from F by > 3%.
  OTHER_ACTION    an exchange record of a demerger / scheme / rights issue and none of a split/bonus —
                  the move is real value leaving (or a rights dilution), not a split.
  PHANTOM         NO split/bonus/consolidation/demerger/scheme/rights on ANY reachable exchange feed,
                  with the NSE feed proven to know the company (covered: >=1 row of any purpose), AND
                  Yahoo's split-event record covering both dates holds no split in the window, AND the
                  bhavcopy raw move (when fetched) confirms the move. From 2006 (dense NSE feed) that
                  suffices; BEFORE 2006 the NSE feed is too sparse to prove absence, so BSE must also
                  have been reached and show no split/bonus. --apply adds it to phantom_crashes.json
                  (self_heal restores the raw move on the next run).
  YAHOO_SPLIT     no exchange record, but Yahoo records a split matching F within 3% — conflict
                  between a third party and the exchange; left as is, listed.
  UNRESOLVED      a source needed for any verdict above was unreachable or did not cover the dates.

v2 rules (2026-09-25, committed before the v2 evidence run):
  NOT_ADJUSTED    NSE's bhavcopy raw move equals our published move (±5%): no factor is baked in at
                  all — a false detection by the turnover/volume audit (noisy t or v). Nothing to fix.
  covered_in_era  the NSE feed holds >= 1 row of ANY purpose for the company within 3 years of the
                  event — the exchange was demonstrably recording this company's actions then.
  PHANTOM by era  2016+: no split/bonus/demerger/scheme/rights on EITHER NSE board, covered_in_era,
                  bhavcopy confirms the raw move, no Yahoo split listed (DATA_RUNBOOK §87c standing rule).
                  2006-15: the same PLUS a second reader showing no split — Yahoo's split record covering
                  both dates, or the §87 campaign's recorded BSE check (bse_reach, no bse_factor/rights).
                  pre-2006: Yahoo AND BSE (live or §87-recorded) must both show no split.

v3 rules (2026-09-25, AFTER reading v2 evidence — changed because it exposed a contradiction):
  REAL_TAPE       no official record, but the §87 campaign's tape analysis confirmed a real action
                  (ex-day open at the adjusted basis + ~1/f volume step). Data unchanged.
  PHANTOM <2016   additionally requires the §87 campaign to call it PHANTOM-CONFIRMED/LIKELY: v2 said
                  "phantom" for 9 events the campaign had tape-confirmed as real (ADANIENT 2004 x0.1…),
                  proving NSE feed + Yahoo + BSE are all incomplete before 2016.
  PHANTOM         never across a boundary spanning > 1 year without NSE bars (ARENTERP 1999->2017,
                  NOVARTIND 2003->2020…): BSE-only filings in the gap are unverifiable.
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
_argv = sys.argv
sys.argv = _argv[:1]
import build_corp_actions as BCA

sys.argv = _argv

RIGHTS_KW = ("rights",)
TOL = 0.03


def match(f, F):
    return f is not None and F and abs(f / F - 1) <= TOL


def day_products(rows):  # multiply same-ex-date split/bonus factors (a combined bonus + split)
    by = collections.defaultdict(lambda: 1.0)
    for r in rows:
        by[r["ex"]] *= r["factor"]
    return dict(by)


def yahoo_splits(yev, a, b):
    out = []
    for k in ("ns", "bo"):
        y = yev.get(k) or {}
        for s in y.get("splits") or []:
            if a - 15 <= s["date"] <= b + 15 and s.get("num") and s.get("den"):
                out.append({"src": k, "date": s["date"], "factor": s["den"] / s["num"]})
    return out


def yahoo_covered(yev):
    return any((yev.get(k) or {}).get("status") == "ok" and (yev.get(k) or {}).get("covered") for k in ("ns", "bo"))


import gzip

_CAMP = collections.defaultdict(list)
try:
    for _v in json.loads(gzip.open(os.path.join(HERE, "ca2002_campaign", "verdicts.json.gz")).read()):
        _CAMP[_v["sym"]].append(_v)
except Exception as _e:
    print(f"  (§87 campaign verdicts unavailable: {_e})")


_DEM = json.load(open(os.path.join(HERE, "demerger_adj.json")))


def campaign(sym, a, b):  # §87 campaign's recorded BSE/Yahoo checks for an ex-date inside [a-7d, b+7d]
    return [v for v in _CAMP.get(sym, []) if a - 7 <= v["ex"] <= b + 7]


def verdict(e):
    F = e["F"]
    a, b = e["a"], e["b"]
    rb = e.get("raw_ratio_bhav")
    if rb is not None and e.get("adj_a") and abs((e["adj_b"] / e["adj_a"]) / rb - 1) <= 0.05:
        return "NOT_ADJUSTED", {"ours": round(e["adj_b"] / e["adj_a"], 4), "exchange_raw": rb}
    nse = e.get("nse") or {}
    rows = nse.get("rows") or []
    split_rows = [r for r in rows if r.get("factor")]
    other_rows = [
        r
        for r in rows
        if not r.get("factor") and (r.get("demerger") or any(k in (r.get("subject") or "").lower() for k in RIGHTS_KW))
    ]
    bse = e.get("bse") or {}
    bse_ok = bse.get("status") == "ok"
    bse_split, bse_other = [], []
    for r in bse.get("rows") or []:
        p = r.get("purpose") or ""
        f, _ = BCA.official_factor(p)
        if f:
            bse_split.append({"ex": r.get("ex"), "factor": f, "subject": p})
        elif BCA.is_demerger(p) or "rights" in p.lower():
            bse_other.append({"ex": r.get("ex"), "subject": p})
    ys = yahoo_splits(e.get("yahoo_events") or {}, a, b)
    e.get("raw_ratio_bhav") or e.get("raw")
    raw_ok = e.get("raw_ratio_bhav") is None or abs(e["raw_ratio_bhav"] / e["raw"] - 1) <= 0.05

    nse_prod = day_products(split_rows)
    if any(match(f, F) for f in nse_prod.values()) or any(match(r["factor"], F) for r in bse_split):
        return "REAL", {"nse": split_rows, "bse": bse_split}
    for ex_, f_ in nse_prod.items():  # exchange row names a split without its ratio; Yahoo supplies it
        for y in ys:
            if abs(y["date"] - ex_) <= 3 and match(f_ * y["factor"], F):
                return "REAL", {
                    "nse": [dict(r, factor=f_ * y["factor"]) for r in split_rows if r["ex"] == ex_][:1],
                    "bse": [],
                    "combined_with_yahoo": y,
                }
    if split_rows or bse_split:
        return "WRONG_FACTOR", {"nse": split_rows, "bse": bse_split}
    if other_rows or bse_other:
        dem = [x for x in _DEM if x[0] == e["sym"] and a - 7 <= int(x[1]) <= b + 7 and match(x[2], F)]
        if dem:
            return "LEDGER_DEMERGER", {"demerger_adj": dem, "nse": other_rows}
        return "OTHER_ACTION", {"nse": other_rows, "bse": bse_other}
    if any(match(y["factor"], F) for y in ys):
        return "YAHOO_SPLIT", {"yahoo": ys}
    need = []
    all_ex = nse.get("all_ex") or []
    in_era = any(abs(x // 10000 - b // 10000) <= 3 for x in all_ex)
    camp = campaign(e["sym"], a, b)
    camp_bse_none = any(c.get("bse_reach") and not c.get("bse_factor") and not c.get("bse_rights") for c in camp)
    camp_bse_split = [c for c in camp if c.get("bse_factor")]
    if camp_bse_split and any(match(c["bse_factor"], F) for c in camp_bse_split):
        return "REAL", {
            "nse": [],
            "bse": [
                {"ex": c["ex"], "factor": c["bse_factor"], "subject": "§87 campaign BSE record"} for c in camp_bse_split
            ],
        }
    y_none = yahoo_covered(e.get("yahoo_events") or {}) and not ys
    bse_none = (bse_ok and not bse_split) or camp_bse_none
    if not nse.get("covered") or not in_era:
        need.append("NSE feed shows no record-keeping for this company within 3y of the event")
    if e.get("raw_ratio_bhav") is None:
        need.append("no bhavcopy raw move")
    elif not raw_ok:
        need.append("bhavcopy raw move {} disagrees with audit raw {}".format(e.get("raw_ratio_bhav"), e["raw"]))
    if ys:
        need.append(f"Yahoo lists a non-matching split {ys}")
    if 20060101 <= b < 20160101 and not (y_none or camp_bse_none):
        need.append("2006-15: no second reader (Yahoo covered / §87 BSE record) showing no split")
    if b < 20060101 and not (y_none and bse_none):
        need.append(
            "pre-2006: needs Yahoo AND BSE showing no split (yahoo_none={}, bse_none={}; live BSE {})".format(
                y_none, bse_none, bse.get("status")
            )
        )
    # v3 (2026-09-25, after v2 evidence): before 2016 NSE's feed, Yahoo's split list AND BSE's record
    # are ALL incomplete — the §87 campaign tape-confirmed real splits (ex-day open at the adjusted
    # basis + a persistent ~1/f volume step: ADANIENT 2004 x0.1 open-gate 1.021 vol x9.0, GLENMARK 2005,
    # JSL 2004, GABRIEL 2005, GAEL/AARTIIND/VIMTALABS 2006) that every record source omits. So absence
    # alone never proves a crash before 2016: the campaign's independent tape analysis must agree.
    camp_v = [c.get("verdict") for c in camp]
    if any(v.startswith("REAL") for v in camp_v):
        return "REAL_TAPE", {
            "campaign": camp,
            "note": "no official record; §87 tape analysis confirms the action — data unchanged",
        }
    import datetime as _dt

    if (_dt.date(b // 10000, b // 100 % 100, b % 100) - _dt.date(a // 10000, a // 100 % 100, a % 100)).days > 365:
        need.append(
            "boundary spans >1 year with no NSE bars — actions filed only on BSE in that span are "
            "invisible to the NSE feed and BSE is unreachable"
        )
    if b < 20160101 and not any(v.startswith("PHANTOM") for v in camp_v):
        need.append(
            "pre-2016: absence from every record source is not proof (all incomplete) and the §87 tape analysis does not call it a crash (%s)"
            % (camp_v or "no campaign verdict")
        )
    if need:
        return "UNRESOLVED", {"missing": need}
    return "PHANTOM", {
        "nse_era_rows": len([x for x in all_ex if abs(x // 10000 - b // 10000) <= 3]),
        "campaign": [c.get("verdict") for c in camp],
        "nse_status": nse.get("status"),
        "yahoo": {k: (e["yahoo_events"].get(k) or {}).get("status") for k in ("ns", "bo")},
        "bse": bse.get("status"),
        "raw_bhav": e.get("raw_ratio_bhav"),
    }


def main():
    E = json.load(open(os.path.join(HERE, "ca_review_evidence.json")))["events"]
    res = []
    for e in E:
        v, why = verdict(e)
        res.append(
            {
                "sym": e["sym"],
                "a": e["a"],
                "b": e["b"],
                "F": e["F"],
                "raw": e["raw"],
                "raw_bhav": e.get("raw_ratio_bhav"),
                "verdict": v,
                "evidence": why,
            }
        )
    json.dump({"rules": __doc__, "verdicts": res}, open(os.path.join(HERE, "ca_review_verdicts.json"), "w"), indent=0)

    def era(y):
        return "pre2006" if y < 20060101 else "2006-15" if y < 20160101 else "2016+"

    c = collections.Counter((r["verdict"], era(r["b"])) for r in res)
    for k, v in sorted(c.items()):
        print("%-14s %-8s %d" % (k[0], k[1], v))
    if "--apply" in sys.argv:
        pc_p = os.path.join(HERE, "phantom_crashes.json")
        pc = json.load(open(pc_p))
        n_pc = 0
        for r in res:
            if r["verdict"] == "PHANTOM":
                v = pc.setdefault(r["sym"], [])
                if r["b"] not in v:
                    v.append(r["b"])
                    v.sort()
                    n_pc += 1
        json.dump(dict(sorted(pc.items())), open(pc_p, "w"), indent=0)
        h_p = os.path.join(HERE, "corp_actions_hist.json")
        H = json.load(open(h_p))
        n_h = 0
        for r in res:
            if r["verdict"] != "REAL":
                continue
            recs = r["evidence"]["nse"] or r["evidence"]["bse"]
            best = min(recs, key=lambda x: abs((x["factor"]) / r["F"] - 1))
            ex = int(best["ex"]) if str(best["ex"]).isdigit() else r["b"]
            lst = H.setdefault("factors", {}).setdefault(r["sym"], [])
            if not any(int(x[0]) == ex for x in lst):
                lst.append([ex, round(best["factor"], 6)])
                lst.sort()
                n_h += 1
        # WRONG_FACTOR: the exchange's exact factor goes in the hist ledger AND the event is parked in
        # unconfirmed_ca.json keyed by the official ex-date, so self_heal reconciles it at any age
        # (baked guess -> official factor) and prune_unconfirmed clears it once measured applied.
        E = {(x["sym"], x["b"]): x for x in json.load(open(os.path.join(HERE, "ca_review_evidence.json")))["events"]}
        u_p = os.path.join(HERE, "unconfirmed_ca.json")
        U = json.load(open(u_p)) if os.path.exists(u_p) else {}
        raw_p = os.path.join(HERE, "crash_raw_prices.json")
        RAW = json.load(open(raw_p))
        n_wf = 0
        for r in res:
            if r["verdict"] != "WRONG_FACTOR":
                continue
            ev = E[(r["sym"], r["b"])]
            bh = ev.get("bhav") or {}
            pa, pb = bh.get(str(r["a"])), bh.get(str(r["b"]))
            recs = r["evidence"]["nse"]
            if not recs or not isinstance(pa, dict) or not isinstance(pb, dict):
                continue
            prod = day_products(recs)
            ex, f = min(prod.items(), key=lambda kv: abs(kv[0] - r["b"]))
            if not (0.75 <= (pb["close"] / pa["close"]) / f <= 1.30):
                continue  # tape must agree with the record
            lst = H["factors"].setdefault(r["sym"], [])
            lst[:] = [x for x in lst if int(x[0]) != ex] + [[ex, round(f, 6)]]
            lst.sort()
            U.setdefault(r["sym"], {})[str(ex)] = {
                "prev_d": r["a"],
                "prev": pa["close"],
                "close": pb["close"],
                "open": pb.get("open"),
                "ratio": round(pb["close"] / pa["close"], 4),
                "seen": "2026-09-25",
                "note": "§161g WRONG_FACTOR: baked {:.4f}, official {:.6f} ({}) — self_heal reconciles".format(
                    r["F"], f, recs[0]["subject"][:60]
                ),
            }
            RAW.setdefault(r["sym"], {}).update({str(r["a"]): pa["close"], str(r["b"]): pb["close"]})
            n_wf += 1
        # RIGHTS: TERP residual vs the factor actually baked (exchange raw move / our published move)
        rt_p = os.path.join(HERE, "rights_terp.json")
        RT = json.load(open(rt_p))
        n_rt = 0
        rte_p = os.path.join(HERE, "ca_rights_terp_evidence.json")
        RTE = {(x["sym"], x["b"]): x for x in json.load(open(rte_p))["events"]} if os.path.exists(rte_p) else {}
        for r in res:
            if r["verdict"] != "OTHER_ACTION":
                continue
            t = RTE.get((r["sym"], r["b"]))
            if not t or not t.get("terp_factor") or not r.get("raw_bhav"):
                continue
            cur = t["adj_b"] / t["adj_a"]  # ex ratio currently baked into the series
            baked = r["raw_bhav"] / cur  # factor the old guess divided out
            if abs(r["raw_bhav"] / t["terp_factor"] - 1) > 0.15:
                continue  # TERP inputs must fit the tape
            resid = t["terp_factor"] / baked
            if any(x[0] == r["sym"] and int(x[1]) == r["b"] for x in RT):
                continue
            RT.append([r["sym"], r["b"], round(resid, 4), round(cur, 4)])
            n_rt += 1
        # OTHER_ACTION demerger with no demerger_adj factor -> official keep-drop (the day-of policy)
        n_kd = 0
        for r in res:
            if r["verdict"] == "OTHER_ACTION" and any(x.get("demerger") for x in r["evidence"]["nse"]):
                v = pc.setdefault(r["sym"], [])
                if r["b"] not in v:
                    v.append(r["b"])
                    v.sort()
                    n_kd += 1
        json.dump(dict(sorted(pc.items())), open(pc_p, "w"), indent=0)
        json.dump(H, open(h_p, "w"), indent=0)
        json.dump(U, open(u_p, "w"), indent=1, sort_keys=True)
        json.dump(RAW, open(raw_p, "w"), indent=0)
        json.dump(RT, open(rt_p, "w"), indent=0)
        print(
            "applied: %d phantom_crashes, %d hist factors, %d wrong-factor reconciliations, %d rights TERP, %d demerger keep-drops"
            % (n_pc, n_h, n_wf, n_rt, n_kd)
        )


if __name__ == "__main__":
    main()
