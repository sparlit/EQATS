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
"""SCAN for rename aliases that point a BSE-ONLY dashboard ticker at a DIFFERENT company (runbook §197).

THE CLASS. `scripts/_rename_map.json` and the baked `FUND_ALIAS` are NSE facts: "NSE's old symbol WORTH is
now WORTHPERI" (Worth Peripherals, symbol change 2025-10-10). They are right for the NSE namespace — the price
tape, point-in-time rosters (RDEL sits in fnoHistory and resolves through FUND_ALIAS), and old NSE filings.
But the SITE also lists BSE-only companies under their BSE scrip_id, and a scrip_id can equal an old NSE
ticker of an unrelated company: the dashboard's WORTH is Worth Investment & Trading (BSE 538451,
INE114O01020). Every site consumer that applied the NSE alias to the BSE ticker served the other company:
stock.html redirected WORTH -> WORTHPERI, docs/fin/WORTH.json carried Worth Peripherals' shareholding, and
the shareholding fill held Worth Investment's own filings (§180c).

THE TEST. Only ISIN separates two companies (§76). For every alias OLD -> TARGET (FUND_ALIAS, and
_rename_map chained to its end) where the dashboard lists OLD as a BSE-only company (OLD.BO in
docs/stock_data.bin meta, no OLD.NS, and a bse_universe scrip mapped to OLD), compare the ISIN issuer
(isin[:7]) of that BSE scrip with every ISIN on record for TARGET:
  collision      BSE issuer is none of TARGET's issuers   -> recorded in docs/bse_alias_collisions.json
  same-company   BSE issuer is one of TARGET's issuers    -> the alias is right for the site too
  unproven       no ISIN on record for TARGET             -> named, exit 1 (never passed silently)
TARGET ISIN sources, each named in the ledger: its own BSE listing (bse_scrips by_isin), BSE's all-scrips
master incl. delisted (scripts/_bse_master_all.json — only when BSE's scrip name equals the tape's name for
TARGET, the §76 coincidence guard), the live sf-data tape meta, NSE's 2020 ISIN list and EQUITY_L.

CONSUMERS of the ledger (the site namespace; the engine's NSE-namespace FUND_ALIAS is left as is):
  scripts/build_stock_fin.py      never aliases OLD, never folds OLD into TARGET's page as a former symbol
  docs/stock.html                 never redirects OLD to TARGET; a live page never borrows an alias's data
  scripts/fetch_shp_allstocks.py  a FUND_ALIAS entry on OLD no longer blocks OLD's own BSE shareholding
  scripts/check_fund_alias.py     nightly: ledger consistent with the aliases, and no NSE-namespace store
                                  re-seeded with TARGET's rows under OLD

Run:  python3 scripts/scan_bse_alias_collisions.py [--write] [--tape BIN[,BIN...]]
      --tape  sf-data parts (sf_recent_1.bin, sf_deep_*.bin) whose meta carries ISINs; default: the live
              parts' meta, cached in ~/stocks-cache/univ/tape_meta.json (refetched when older than 1 day)
Exit 1 when a collision is not yet recorded, or a pair is unproven.
"""
import csv
import gzip
import json
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "docs", "bse_alias_collisions.json")
CACHE = os.path.expanduser("~/stocks-cache/univ")
SF_BASE = "https://dhruvan246.github.io/sf-data/"


def _j(p):
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def chain(old, m):
    seen, t = {old}, m[old]
    while t in m and m[t] not in seen:
        seen.add(t)
        t = m[t]
    return t


def tape_meta(paths):
    """{SYM: meta} merged over the given sf-data parts (recent last, so it wins)."""
    sys.path.insert(0, HERE)
    from build_search_index import _scan_top_level

    out = {}
    for p in paths:
        out.update(_scan_top_level(p, ["meta"]).get("meta") or {})
    return out


def live_tape_meta():
    cp = os.path.join(CACHE, "tape_meta.json")
    if os.path.exists(cp) and time.time() - os.path.getmtime(cp) < 86400:
        return _j(cp)
    M = json.loads(
        urllib.request.urlopen(SF_BASE + "sf_meta.json?t=%d" % time.time(), timeout=60).read()
    )
    names = ["sf_deep_%d.bin" % (i + 1) for i in range(M.get("deep", 0))] + [
        "sf_recent_%d.bin" % (i + 1) for i in range(M.get("recent", 1))
    ]
    tmp = []
    for n in names:
        p = os.path.join(CACHE, "_tape_" + n)
        with open(p, "wb") as fh:
            fh.write(urllib.request.urlopen(SF_BASE + n + "?v=" + M["end"], timeout=600).read())
        tmp.append(p)
    meta = tape_meta(tmp)
    for p in tmp:
        os.remove(p)
    os.makedirs(CACHE, exist_ok=True)
    with open(cp, "w") as fh:
        json.dump(meta, fh)
    return meta


def norm_name(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\b(limited|ltd|the|co|company|corporation|corp|inc)\b", " ", s)
    return " ".join(s.split())


def scan(tape):
    rmap = _j(os.path.join(HERE, "_rename_map.json"))
    js = open(os.path.join(ROOT, "docs", "backtest-engine.js"), encoding="utf-8").read()
    fa = json.loads(re.search(r"^const FUND_ALIAS = (\{.*?\});$", js, re.M).group(1))
    bs = _j(os.path.join(HERE, "bse_scrips.json"))
    code2isin = {str(c): i for i, c in bs["by_isin"].items()}
    univ = {str(r[0]): r for r in _j(os.path.join(ROOT, "docs", "bse_universe.json"))["rows"]}
    sym2code = {r[1]: c for c, r in univ.items()}  # the dashboard's own ticker -> scrip
    dash = json.loads(
        gzip.decompress(open(os.path.join(ROOT, "docs", "stock_data.bin"), "rb").read())
    )["meta"]
    master = {}
    mp = os.path.join(HERE, "_bse_master_all.json")
    if os.path.exists(mp):
        for r in _j(mp):
            if r.get("scrip_id") and r.get("ISIN_NUMBER"):
                master.setdefault(r["scrip_id"].upper(), []).append(r)
    nse20, eq = {}, {}
    p = os.path.join(CACHE, "nse_sym_isin_2020.json")
    if os.path.exists(p):
        nse20 = _j(p)
    p = os.path.join(CACHE, "EQUITY_L.csv")
    if os.path.exists(p):
        for r in csv.DictReader(open(p, encoding="utf-8", errors="replace")):
            r = {k.strip(): (v or "").strip() for k, v in r.items()}
            if r.get("SYMBOL") and r.get("ISIN NUMBER"):
                eq[r["SYMBOL"]] = r["ISIN NUMBER"]

    def target_isins(t):
        src = {}
        c = bs["by_id"].get(t)
        if c and code2isin.get(str(c)):
            src.setdefault(code2isin[str(c)], []).append(f"bse_scrips {c}")
        tm = tape.get(t) or {}
        if tm.get("isin"):
            src.setdefault(tm["isin"], []).append("sf-data tape meta")
        for i in nse20.get(t) or []:
            src.setdefault(i, []).append("nse_sym_isin_2020")
        if eq.get(t):
            src.setdefault(eq[t], []).append("EQUITY_L")
        for r in master.get(t, []):
            if tm.get("name") and norm_name(r["Scrip_Name"]) == norm_name(tm["name"]):
                src.setdefault(r["ISIN_NUMBER"], []).append(
                    "BSE master {} {} ({}; name = tape name)".format(
                        r["SCRIP_CD"], r["Scrip_Name"], r["Status"]
                    )
                )
        return src

    pairs = {}
    for old, t in fa.items():
        pairs.setdefault(old, {"target": t, "fund_alias": True, "rename_map": False})
    for old in rmap:
        e = pairs.setdefault(
            old, {"target": chain(old, rmap), "fund_alias": False, "rename_map": True}
        )
        e["rename_map"] = True
    rows = {}
    for old, e in sorted(pairs.items()):
        code = sym2code.get(old)
        if not code or (old + ".BO") not in dash or (old + ".NS") in dash:
            continue  # not a BSE-only dashboard company
        bisin = (univ[code][3] if len(univ[code]) > 3 else "") or code2isin.get(code, "")
        ti = target_isins(e["target"])
        if not bisin or not ti:
            verdict = "unproven"
        elif bisin[:7] in {i[:7] for i in ti}:
            verdict = "same-company"
        else:
            verdict = "collision"
        rows[old] = {
            "target": e["target"],
            "bse_code": code,
            "bse_name": univ[code][2],
            "bse_isin": bisin,
            "target_name": (tape.get(e["target"]) or {}).get("name"),
            "target_isins": dict(sorted(ti.items())),
            "in_fund_alias": e["fund_alias"],
            "in_rename_map": e["rename_map"],
            "verdict": verdict,
        }
    return rows


def main():
    tape_arg = None
    if "--tape" in sys.argv:
        tape_arg = sys.argv[sys.argv.index("--tape") + 1].split(",")
    tape = tape_meta(tape_arg) if tape_arg else live_tape_meta()
    rows = scan(tape)
    led = _j(OUT) if os.path.exists(OUT) else {"collisions": {}}
    have = led.get("collisions", {})
    new = {o: r for o, r in rows.items() if r["verdict"] == "collision" and o not in have}
    unproven = {o: r for o, r in rows.items() if r["verdict"] == "unproven"}
    for o, r in sorted(rows.items()):
        print(
            "%-11s -> %-10s BSE %s %-40s %s | target %s | %s%s"
            % (
                o,
                r["target"],
                r["bse_code"],
                r["bse_name"][:40],
                r["bse_isin"],
                sorted(r["target_isins"]) or "-",
                r["verdict"],
                "" if r["verdict"] != "collision" else (" (recorded)" if o in have else " (NEW)"),
            )
        )
    gone = sorted(set(have) - {o for o, r in rows.items() if r["verdict"] == "collision"})
    if gone:
        print(
            f"recorded but no longer measured as a collision (review by hand, never auto-removed): {gone}"
        )
    if "--write" in sys.argv and new:
        for o, r in new.items():
            r = dict(r)
            r.pop("verdict")
            r["found"] = time.strftime("%Y-%m-%d")
            have[o] = r
        led["collisions"] = dict(sorted(have.items()))
        with open(OUT, "w", encoding="utf-8") as fh:
            json.dump(led, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
        print("wrote %s: +%d (%d recorded)" % (os.path.relpath(OUT, ROOT), len(new), len(have)))
        new = {}
    print(
        "%d BSE-only aliased tickers: %d collision (%d new), %d same-company, %d unproven"
        % (
            len(rows),
            sum(r["verdict"] == "collision" for r in rows.values()),
            len(new),
            sum(r["verdict"] == "same-company" for r in rows.values()),
            len(unproven),
        )
    )
    return 1 if (new or unproven) else 0


if __name__ == "__main__":
    sys.exit(main())
