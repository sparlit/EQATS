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
"""READ-ONLY screen: sf_revop operating profit that is NEGATIVE while the quarter's profit before tax is POSITIVE,
split into "the company's own numbers say so" versus "contradicted by the filing" (runbook §189, 2026-09-27).

Why it exists. KENNAMET carried op of about -200 cr in 8 quarters of 2021-23 on ~250 cr revenue while profitable: a
2026-07-27 BSE-PDF text sweep (backfill_revop_gaps.py) had stored -(Total expenses) as operating profit. A NEGATIVE op
with a POSITIVE PBT is not by itself a defect -- op = PBET + finance costs + depreciation - other income, so any company
whose other income exceeds its operating base (holding / investment companies, treasury-heavy filers) has one. Measured
2026-09-27: 3,840 of 4,132 such cells are exactly what the filing's own line items give. This screen separates them.

Per cell with op < 0 and profit > 0 (PBT from scripts/xbrl_extra.json.gz, else PAT from sf_fundamentals):
  EXPLAINED-line-items  op == PBET + FC + Dep - OI from xbrl_extra's line items (tolerance max(0.6, 3% of revenue))
  EXPLAINED-xbrl        op equals build_revop.xbrl_revop on a cached NSE XBRL of that quarter/basis (era symbols too)
  WRONG-vs-xbrl         a cached XBRL exists and gives a different op   -> the store is contradicted by the filing
  WRONG-vs-line-items   only line items exist and they give a different op (weaker: line items can come from the NSE
                        archive page or Moneycontrol, whose definitions differ pre-2018 -- adjudicate before healing)
  UNVERIFIED            neither exists locally -- read the filing (BSE Result_Arch_ng XBRL for 2018+, see §189)
`sig` marks the KENNAMET mechanism: op == PBET - revenue - OI (i.e. minus total expenses; ebit == op).

It writes nothing to any store. A WRONG verdict is a CANDIDATE: heal only after reading the quarter's own filing and a
second reader, through scripts/revop_cell_fix.json (never by editing sf_revop directly -- runbook §0 rule 5).

Run (from any worktree; the XBRL cache lives in the MAIN checkout):
  XBRL_CACHE=/Users/dhruvan/stocks-dashboard/scripts/_xbrl_cache python3 -X utf8 scripts/scan_negop_vs_filings.py [--out FILE]
"""
import collections
import gzip
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.environ.get("XBRL_CACHE") or os.path.join(HERE, "_xbrl_cache")
sys.path.insert(0, HERE)


def load_inputs():
    rv = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    fu = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    xe = json.loads(gzip.decompress(open(os.path.join(HERE, "xbrl_extra.json.gz"), "rb").read()))
    ren = json.load(open(os.path.join(HERE, "_rename_map.json")))
    fund = {}
    for s, rows in fu.items():
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, list) and r:
                    fund[(s, str(r[0]))] = r
    return rv, fund, xe, ren


def screen(rv, fund, xe):
    out = []
    for s, qm in rv.items():
        if not isinstance(qm, dict):
            continue
        for q, row in qm.items():
            if not isinstance(row, list):
                continue
            row = row + [None] * (9 - len(row))
            for b, ri, oi_, ei, fi in (("s", 0, 2, 7, 1), ("c", 1, 3, 8, 3)):
                rev, op = row[ri], row[oi_]
                if op is None or op >= 0:
                    continue
                li = ((xe.get(s) or {}).get(q) or {}).get(b) or {}
                pbt, pbet = li.get("pbt"), li.get("pbet")
                fr = fund.get((s, q))
                pat = fr[fi] if fr and len(fr) > fi else None
                prof = pbt if pbt is not None else pat
                if prof is None or prof <= 0:
                    continue
                base = pbet if pbet is not None else (pbt - (li.get("exc") or 0) if pbt is not None else None)
                opc = None
                if base is not None and li.get("oi") is not None:
                    opc = round(base + (li.get("fc") or 0) + (li.get("dep") or 0) - li["oi"], 2)
                sig = None
                if base is not None and li.get("oi") is not None and rev is not None:
                    sig = abs(op - (base - rev - li["oi"])) <= max(0.6, 0.01 * abs(rev))
                out.append(
                    {
                        "sym": s,
                        "qe": q,
                        "b": b,
                        "rev": rev,
                        "op": op,
                        "ebit": row[ei],
                        "prof": prof,
                        "prof_src": "pbt" if pbt is not None else "pat",
                        "fin": row[6],
                        "opc": opc,
                        "li_src": li.get("src"),
                        "sig": sig,
                        "strong": bool(rev) and op < -0.5 * abs(rev),
                    }
                )
    return out


def tol(o):
    return max(0.6, 0.03 * abs(o["rev"] or 0))


def xbrl_index(cands, ren):
    """{SYM|qe|b: [[ts, file, rev, op, ebit], ...]} (oldest filing first) for the candidates' cached XBRLs, era
    symbols folded into the current symbol via _rename_map.json."""
    import build_revop as BR

    if not os.path.isdir(CACHE):
        sys.exit(f"XBRL cache not found at {CACHE} -- set XBRL_CACHE (it lives in the MAIN checkout)")
    rev_map = collections.defaultdict(set)
    for old, new in ren.items():
        rev_map[new].add(old)

    def olds(s, seen):
        for o in rev_map.get(s, ()):
            if o not in seen:
                seen.add(o)
                olds(o, seen)
        return seen

    cur = {}
    for s in {c["sym"] for c in cands}:
        cur[s] = s
        for o in olds(s, set()):
            cur[o] = s
    pat = 'NSESymbol">(' + "|".join(re.escape(n).replace("&", "&amp;") for n in sorted(cur)) + ")<"
    r = subprocess.run(["grep", "-rlE", pat, "."], cwd=CACHE, capture_output=True, text=True)
    files = sorted((l.removeprefix("./") for l in r.stdout.split() if l), key=BR.ts_key)
    idx = collections.defaultdict(list)
    for f in files:
        try:
            p = BR.parse_file(os.path.join(CACHE, f), f)
        except Exception:
            continue
        if not p:
            continue
        sym = cur.get(p["sym"], p["sym"])
        for b in ("std", "con"):
            d = p.get(b)
            if d:
                idx["{}|{}|{}".format(sym, p["qe"], b[0])].append(
                    [p["ts"], f] + [None if d[k] is None else round(d[k], 2) for k in ("rev", "op", "ebit")]
                )
    for k in idx:
        idx[k].sort(key=lambda e: e[0])
    return idx, len(files)


def classify(out, idx):
    for o in out:
        x = idx.get("{}|{}|{}".format(o["sym"], o["qe"], o["b"]))
        xops = sorted({e[3] for e in x if e[3] is not None}) if x else []
        o["xop"] = x[-1][3] if x else None  # latest filing wins (build_revop convention)
        if o["opc"] is not None and abs(o["op"] - o["opc"]) <= tol(o):
            o["cls"] = "EXPLAINED-line-items"
        elif xops and any(abs(o["op"] - v) <= tol(o) for v in xops):
            o["cls"] = "EXPLAINED-xbrl"
        elif o["xop"] is not None:
            o["cls"] = "WRONG-vs-xbrl"
        elif o["opc"] is not None:
            o["cls"] = "WRONG-vs-line-items"
        else:
            o["cls"] = "UNVERIFIED"
    return out


def main():
    args = sys.argv[1:]
    dest = args[args.index("--out") + 1] if "--out" in args else None
    rv, fund, xe, ren = load_inputs()
    out = screen(rv, fund, xe)
    cands = [o for o in out if not (o["opc"] is not None and abs(o["op"] - o["opc"]) <= tol(o))]
    idx, nfiles = xbrl_index(cands, ren)
    classify(out, idx)
    print(
        "op < 0 while PBT/PAT > 0: %d cells, %d symbols   (cached XBRLs read for candidates: %d)"
        % (len(out), len({o["sym"] for o in out}), nfiles)
    )
    for name, pop in (("ALL", out), ("STRONG (op < -50% of revenue)", [o for o in out if o["strong"]])):
        c = collections.Counter(o["cls"] for o in pop)
        print(
            "  %-30s %5d cells %4d symbols  %s"
            % (name, len(pop), len({o["sym"] for o in pop}), dict(sorted(c.items())))
        )
    wrong = [o for o in out if o["cls"].startswith("WRONG")]
    by = collections.defaultdict(list)
    for o in wrong:
        by[o["sym"]].append(o)
    print(
        "\nWRONG: %d cells / %d symbols (KENNAMET signature op = -total expenses where line items allow the test: %d)"
        % (len(wrong), len(by), sum(1 for o in wrong if o["sig"]))
    )
    for s in sorted(by, key=lambda s: (-sum(o["strong"] for o in by[s]), -len(by[s]), s)):
        L = sorted(by[s], key=lambda o: (o["qe"], o["b"]))
        print(
            "  %-11s %2d  %s"
            % (
                s,
                len(L),
                "; ".join(
                    "{}{} op {} ref {}".format(
                        o["qe"], o["b"], o["op"], o["xop"] if o["cls"] == "WRONG-vs-xbrl" else o["opc"]
                    )
                    for o in L[:4]
                )
                + (" …" if len(L) > 4 else ""),
            )
        )
    if dest:
        json.dump(out, open(dest, "w"), indent=0)
        print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
