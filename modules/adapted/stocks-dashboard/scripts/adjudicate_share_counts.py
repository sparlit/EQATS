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
"""Share-count witness for the UNRESOLVED 2016+ review events (DATA_RUNBOOK §161i).

A split/bonus multiplies a company's share count by 1/F; a crash leaves it unchanged. The company's own
results filings give the count independently of any price: shares = PAT / basic EPS (docs/fin/<SYM>.json:
`fund` = [qe, PAT std, ann std, PAT con, ann con], `x[qe][s|c].eps_b`, 2018+). Ind AS 33 restates EPS
for a split/bonus retrospectively in every result ANNOUNCED after it, so:
  pre  = quarters whose results were announced BEFORE the event (count at the old basis)
  post = quarters ending AFTER the event
Rules, fixed before the run:
  - usable quarter: |EPS| >= 0.50 (smaller EPS is rounding-dominated) and PAT != 0; same basis (s or c) both sides
  - windows: pre quarters ending within 9 months before the event, post within 9 months after; >= 2 each side
  - step = median(post shares) / median(pre shares); each side's quarters must agree within 5% (stable count)
  REAL_FILING  step within 10% of 1/F                       -> keep the adjustment; record F in corp_actions_hist
  PHANTOM_FILING step within 10% of 1.0 (count unchanged)   -> keep the raw move (phantom_crashes.json)
  otherwise stays UNRESOLVED, with the measured step.
Second witness when no filing exists (funds/ETFs, entitlements, tiny-EPS companies) — the §87 tape
standard, both signals required, large factors only (F <= 0.25 or >= 4, where the unit count dominates volume):
  REAL_TAPE  ex-day open at the adjusted basis ((open/prev)/F in [0.88,1.12]) AND a persistent volume step
             (median 10 sessions after / 10 before) within 2x of 1/F  -> keep; record F in corp_actions_hist.
Run: python3 scripts/adjudicate_share_counts.py [--apply] [--bins <dir with sf_deep_*/sf_recent_* bins>]
"""
import datetime
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def od(y):
    return datetime.date(y // 10000, y // 100 % 100, y % 100)


def counts(fin, basis):
    """[(qe, ann, shares)] for one basis from a docs/fin file."""
    out = []
    fund = {int(r[0]): r for r in fin.get("fund") or []}
    for q, x in (fin.get("x") or {}).items():
        q = int(q)
        b = (x or {}).get(basis) or {}
        eps = b.get("eps_b")
        r = fund.get(q)
        if not r or eps is None or abs(eps) < 0.5:
            continue
        pat, ann = (r[1], r[2]) if basis == "s" else (r[3], r[4] if len(r) > 4 else None)
        if not pat or not ann:
            continue
        out.append((q, int(ann), pat / eps))
    return sorted(out)


def judge(sym, b, F):
    p = os.path.join(ROOT, "docs", "fin", sym + ".json")
    if not os.path.exists(p):
        return "UNRESOLVED", {"why": "no results-filing data for this company"}
    fin = json.load(open(p))
    ev = od(b)
    best = None
    for basis in ("s", "c"):
        C = counts(fin, basis)
        pre = [s for q, a, s in C if a < b and (ev - od(q)).days <= 275]
        post = [s for q, a, s in C if q > b and (od(q) - ev).days <= 275]
        if len(pre) < 2 or len(post) < 2:
            continue
        mp, mq = statistics.median(pre), statistics.median(post)
        stable = all(abs(s / mp - 1) <= 0.05 for s in pre) and all(abs(s / mq - 1) <= 0.05 for s in post)
        cand = {
            "basis": basis,
            "pre_cr": [round(s, 3) for s in pre],
            "post_cr": [round(s, 3) for s in post],
            "step": round(mq / mp, 4),
            "expected_split_step": round(1 / F, 4),
            "stable": stable,
        }
        if stable:
            best = cand
            break
        best = best or cand
    if not best:
        return "UNRESOLVED", {"why": "fewer than 2 usable quarters (|EPS|>=0.5) on a side within 9 months"}
    if not best["stable"]:
        return "UNRESOLVED", dict(best, why="share counts unstable within a side (>5%)")
    if abs(best["step"] * F - 1) <= 0.10:
        return "REAL_FILING", best
    if abs(best["step"] - 1) <= 0.10:
        return "PHANTOM_FILING", best
    return "UNRESOLVED", dict(best, why="share-count step matches neither the split (1/F) nor no-change")


def tape(bins, todo):
    import glob
    import gzip

    need = {v["sym"] for v in todo}
    vol = {}
    for f in sorted(glob.glob(os.path.join(bins, "*deep_*.bin"))) + sorted(
        glob.glob(os.path.join(bins, "*recent_*.bin"))
    ):
        D = json.loads(gzip.open(f).read())
        for sname in need:
            o = D["data"].get(sname)
            if o:
                for i, x in enumerate(o["d"]):
                    vol.setdefault(sname, {})[x] = o["v"][i]
    E = {(e["sym"], e["b"]): e for e in json.load(open(os.path.join(HERE, "ca_review_evidence.json")))["events"]}
    out = {}
    for v in todo:
        F = v["F"]
        m = vol.get(v["sym"], {})
        ds = sorted(m)
        if v["b"] not in m:
            continue
        j = ds.index(v["b"])
        pre = [m[x] for x in ds[max(0, j - 10) : j] if m[x]]
        post = [m[x] for x in ds[j + 1 : j + 11] if m[x]]
        vr = statistics.median(post) / statistics.median(pre) if len(pre) >= 3 and len(post) >= 3 else None
        og = E[(v["sym"], v["b"])].get("open_over_prev_bhav")
        g = og / F if og else None
        if (F <= 0.25 or F >= 4) and g is not None and 0.88 <= g <= 1.12 and vr is not None and 0.5 <= vr * F <= 2:
            out[(v["sym"], v["b"])] = {"open_gate": round(g, 4), "vol_step": round(vr, 3), "expected": round(1 / F, 2)}
    return out


def main():
    VP = os.path.join(HERE, "ca_review_verdicts.json")
    VV = json.load(open(VP))
    todo = [v for v in VV["verdicts"] if v["verdict"] == "UNRESOLVED" and v["b"] >= 20160101]
    T = tape(sys.argv[sys.argv.index("--bins") + 1], todo) if "--bins" in sys.argv else {}
    res = []
    for v in todo:
        verdict, ev = judge(v["sym"], v["b"], v["F"])
        if verdict == "UNRESOLVED" and (v["sym"], v["b"]) in T:
            verdict, ev = "REAL_TAPE", dict(T[(v["sym"], v["b"])], filing_witness=ev.get("why"))
        res.append((v, verdict, ev))
        print(
            "%-15s %-11s %d F=%.3f %s"
            % (verdict, v["sym"], v["b"], v["F"], {k: ev[k] for k in ("step", "expected_split_step", "why") if k in ev})
        )
    print({k: sum(1 for r in res if r[1] == k) for k in ("REAL_FILING", "PHANTOM_FILING", "REAL_TAPE", "UNRESOLVED")})
    if "--apply" in sys.argv:
        H = json.load(open(os.path.join(HERE, "corp_actions_hist.json")))
        PC = json.load(open(os.path.join(HERE, "phantom_crashes.json")))
        for v, verdict, ev in res:
            if verdict == "UNRESOLVED":
                v["evidence"].setdefault("missing", []).append("share-count witness: {}".format(ev.get("why")))
                if "step" in ev:
                    v["evidence"]["share_count"] = ev
                continue
            v["verdict"] = verdict
            v["evidence"] = {("share_count" if verdict != "REAL_TAPE" else "tape"): ev, "earlier": v["evidence"]}
            if verdict in ("REAL_FILING", "REAL_TAPE"):
                lst = H["factors"].setdefault(v["sym"], [])
                if not any(abs(int(x[0]) - v["b"]) <= 3 for x in lst):
                    lst.append([v["b"], round(v["F"], 6)])
                    lst.sort()
            else:
                lst = PC.setdefault(v["sym"], [])
                if v["b"] not in lst:
                    lst.append(v["b"])
                    lst.sort()
        json.dump(VV, open(VP, "w"), indent=0)
        json.dump(H, open(os.path.join(HERE, "corp_actions_hist.json"), "w"), indent=0)
        json.dump(dict(sorted(PC.items())), open(os.path.join(HERE, "phantom_crashes.json"), "w"), indent=0)
        print("applied")


if __name__ == "__main__":
    main()
