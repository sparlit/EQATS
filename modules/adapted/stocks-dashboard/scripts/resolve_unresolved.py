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
"""Resolve the 131 era symbols that today's BSE master (even status-blank) cannot name.

Route: Moneycontrol autosuggest — its pdt_dis_nm carries "<ISIN>, <NSE SYMBOL>, <BSE code>"
and MC keeps pages for dead companies. Acceptance, strongest first:
  A. the row's NSE SYMBOL token == our era symbol (exact)  -> via=mc:symbol
  B. else query the ledger/company name; accept when norm-name containment holds AND the row
     carries a 6-digit BSE code                             -> via=mc:name (page-level identity
     gate still applies at harvest: the aspx page prints the company name)
Everything else stays unresolved (journalled). Writes:
  frontier_unres.json   — harvest frontier for the resolved (sym, qe) cells
  unres_evidence.json   — per-symbol {code, via, mc_name, isin} evidence journal
"""
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter

from curl_cffi import requests as cr

SP = os.path.dirname(os.path.abspath(__file__))
REPO = "/Users/dhruvan/stocks-dashboard"
UA = {"Accept": "application/json"}
QOFF = {3: 29, 6: 30, 9: 31, 12: 32}


def gitshow(path):
    r = subprocess.run(["git", "show", "origin/main:" + path], capture_output=True, cwd=REPO)
    if r.returncode:
        sys.exit("git show failed: " + path)
    return json.loads(r.stdout)


def norm_name(s):
    s = re.sub(r"&amp;", "&", s or "")
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("limited", "").replace("ltd", ""))


def mc_query(q):
    u = f"https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php?classic=true&query={q}&type=1&format=json"
    try:
        r = cr.get(u, headers=UA, impersonate="chrome", timeout=25)
        d = json.loads(r.text)
        return d if isinstance(d, list) else d.get("data", []) or []
    except Exception:
        return []


def parse_row(row):
    # pdt_dis_nm: 'Alok Industries&nbsp;<span>INE270A01029, ALOKINDS, 521070</span>'
    dn = row.get("pdt_dis_nm") or ""
    name = re.sub(r"&nbsp;.*$", "", dn).strip()
    m = re.search(r"<span>\s*([A-Z0-9]{12})?\s*,?\s*([A-Z0-9&\-]*)\s*,\s*(\d{6})\s*</span>", dn)
    if not m:
        return None
    return {
        "name": name,
        "isin": m.group(1) or "",
        "nsesym": (m.group(2) or "").strip().upper(),
        "code": int(m.group(3)),
    }


def main():
    unres = json.load(open(SP + "/unresolved.json"))
    hist = gitshow("scripts/shp_history.json")
    ih = gitshow("scripts/indices_history.json")
    rmap = gitshow("scripts/_rename_map.json")
    skipf = gitshow("scripts/shp_no_filing.json").get("cells", {})
    names = hist.get("_names", {})

    def norm(s):
        seen = set()
        while s in rmap and s not in seen and rmap[s] != s:
            seen.add(s)
            s = rmap[s]
        return s

    have = {}
    for k, v in hist.items():
        if not k.startswith("_") and isinstance(v, dict):
            have.setdefault(norm(k), {}).update(v)
    skip = {(norm(s), qe) for s, qs in skipf.items() for qe in qs}
    snaps = sorted(
        (s["effectiveDate"], [norm(x) for x in s["symbols"] if not x.startswith("DUMMY")]) for s in ih["Nifty 500"]
    )

    def members(qe):
        best = []
        for ed, syms in snaps:
            if ed <= qe:
                best = syms
            else:
                break
        return best

    qes = ["%d%s" % (y, sfx) for y in range(2002, 2017) for sfx in ("-03-31", "-06-30", "-09-30", "-12-31")]
    qes = [q for q in qes if "2002-12-31" <= q <= "2016-03-31" and q not in ("2015-12-31", "2016-03-31")]
    missing_by_sym = {}
    for qe in qes:
        for s in members(qe):
            if s in unres and (s, qe) not in skip and qe not in have.get(s, {}):
                missing_by_sym.setdefault(s, []).append(qe)

    evidence, front = {}, []
    stats = Counter()
    for i, sym in enumerate(sorted(unres)):
        hit = None
        rows = [parse_row(r) for r in mc_query(sym)]
        rows = [r for r in rows if r]
        exact = [r for r in rows if r["nsesym"] == sym]
        if exact:
            hit = dict(exact[0], via="mc:symbol")
        else:
            lname = names.get(sym) or ""
            if lname:
                time.sleep(0.3)
                rows2 = [parse_row(r) for r in mc_query(lname.split()[0] if lname else sym)]
                rows2 = [r for r in rows2 if r]
                nn = norm_name(lname)
                cand = [r for r in rows2 if nn and (nn in norm_name(r["name"]) or norm_name(r["name"]) in nn)]
                if len(cand) == 1:
                    hit = dict(cand[0], via="mc:name")
        if hit:
            evidence[sym] = hit
            stats[hit["via"]] += 1
            for qe in missing_by_sym.get(sym, []):
                y, mth = int(qe[:4]), int(qe[5:7])
                front.append(
                    {
                        "sym": sym,
                        "qe": qe,
                        "code": hit["code"],
                        "qtrid": (y - 2001) * 4 + QOFF[mth],
                        "bname": hit["name"],
                        "lname": names.get(sym, "") or hit["name"],
                    }
                )
        else:
            stats["unresolved"] += 1
        time.sleep(0.35)
        if (i + 1) % 25 == 0:
            print("  %d/%d resolved-so-far=%d" % (i + 1, len(unres), len(evidence)), flush=True)

    json.dump(front, open(SP + "/frontier_unres.json", "w"), indent=0)
    json.dump(evidence, open(SP + "/unres_evidence.json", "w"), indent=1, sort_keys=True)
    print(
        "\nRESOLVED %d/%d symbols (%s) -> %d frontier cells; evidence -> unres_evidence.json"
        % (len(evidence), len(unres), dict(stats), len(front))
    )
    left = sorted(set(unres) - set(evidence))
    print("still unresolved (%d): %s%s" % (len(left), ", ".join(left[:15]), " ..." if len(left) > 15 else ""))


if __name__ == "__main__":
    main()
