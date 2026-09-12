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
"""Resolve Moneycontrol ids for ERA symbols that autosuggest does not know (renamed / delisted).

agg_sources.mc_id accepts only an exact NSE-symbol token, so a worklist symbol like ALOKTEXT or
HEXAWARE (the name the company traded under in 2009-2014) resolves to nothing even though MC holds
the whole history under the CURRENT name (ALOKINDS, HEXT). Two routes, both gated:

  1. the repo's own rename maps (FUND_ALIAS in docs/backtest-engine.js, scripts/_rename_map.json):
     era -> current name, then mc_id(current). Same legal company, same sc_id.
  2. BSE scrip code (scripts/bse_scrips.json, fill2020_tools/_delisted_scrip_overrides.json):
     autosuggest by code; a row is accepted only when its "<ISIN>, <code>" tail carries OUR code
     exactly (memory reference-moneycontrol-deep-history).

Writes the hit under the ERA symbol in scripts/agg_tools/_agg_ids_mc.json (same shape mc_id uses),
so con_discover_pre2015.py --route mc --only <syms> can re-sweep them. Identity is then proven at
sweep time by the std-anchor count the sweep journals (MC std PAT vs our stored std, per quarter).

  python3 scripts/fill2020_tools/mc_resolve_era_ids.py SYM,SYM,...
"""
import json
import os
import re
import sys
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
ROOT = os.path.dirname(SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, "agg_tools"))
import agg_sources as A  # noqa: E402


def code_lookup(code):
    txt = A._get(
        "www.moneycontrol.com",
        A.MC_SUGGEST % quote(str(code), safe=""),
        A.MC_PACE,
        "mc",
        "sugg1_code_" + str(code),
        ttl=86400 * 30,
    )
    if not txt:
        return None
    try:
        rows = json.loads(txt)
    except ValueError:
        return None
    for r in rows if isinstance(rows, list) else []:
        dis = re.sub(r"<[^>]+>", "", (r.get("pdt_dis_nm") or "")).replace("&nbsp;", " ")
        m = re.search(r"(INE[0-9A-Z]{9}|IN[0-9A-Z]{10})\s*,\s*(?:([A-Z0-9&_-]+)\s*,\s*)?(\d+)\s*$", dis.strip())
        if not m or m.group(3) != str(code):
            continue
        link = r.get("link_src") or ""
        lm = re.search(r"/([A-Z0-9]+)/?$", link)
        return {
            "sc_id": r.get("sc_id") or (lm.group(1) if lm else ""),
            "sc_id_link": lm.group(1) if lm else "",
            "isin": m.group(1),
            "bse": m.group(3),
            "name": r.get("stock_name") or "",
            "resolved_via": f"bse-code {code}",
        }
    return None


def main():
    syms = sys.argv[1].split(",")
    src = open(os.path.join(ROOT, "docs", "backtest-engine.js")).read()
    alias = json.loads(re.search(r"const FUND_ALIAS = (\{.*?\});", src).group(1))
    rmap = json.load(open(os.path.join(SCRIPTS, "_rename_map.json")))
    bse = json.load(open(os.path.join(SCRIPTS, "bse_scrips.json")))["by_id"]
    ov = json.load(open(os.path.join(HERE, "_delisted_scrip_overrides.json")))
    ids = json.load(open(A._MC_IDS_PATH))
    for sym in syms:
        hit, how = None, None
        for cand in [alias.get(sym), rmap.get(sym)]:
            if cand and cand != sym:
                h = A.mc_id(cand)
                if h:
                    hit, how = dict(h), f"alias {cand}"
                    break
        if not hit:
            code = bse.get(sym) or (ov.get(sym) or {}).get("scrip")
            if code:
                h = code_lookup(code)
                if h:
                    hit, how = h, h["resolved_via"]
        if hit:
            hit["resolved_via"] = how
            ids[sym] = hit
            print("  %-12s -> sc_id %-6s (%s) %s" % (sym, hit["sc_id"], hit.get("name", "")[:30], how))
        else:
            print(
                "  %-12s -> UNRESOLVED (alias=%s code=%s)"
                % (sym, alias.get(sym) or rmap.get(sym), bse.get(sym) or (ov.get(sym) or {}).get("scrip"))
            )
    json.dump(ids, open(A._MC_IDS_PATH, "w"), indent=0, sort_keys=True)


if __name__ == "__main__":
    main()
