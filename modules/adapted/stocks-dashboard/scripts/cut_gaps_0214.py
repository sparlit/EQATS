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
"""STEP G (scripts/PRE2015_CAMPAIGN.md) -- cut the pre-2015 gap universe.

For every quarter 2002Q1->2014Q4: members = _n500_member_bin.membership(qe) (the real,
point-in-time N500 roster now that STEP M1+M2 are live). A cell is a (sym, qe)
member-quarter that is missing its STANDALONE PAT and/or STANDALONE revenue in the live
fundamentals ledgers (docs/sf_fundamentals.json, docs/sf_revop.json) -- the "dual-form"
gap: a cell already PAT-filled by the old 2012-14 batch but never given a rev row still
needs work, so it is emitted with need=["rev"] rather than being dropped as "stored".
CONSOLIDATED is out of scope everywhere (optional pre-2015 under SEBI Clause 41 -- con
blanks are not gaps and are never counted here, per the campaign doc).

BSE scrip-code resolution per symbol, in order, NO fuzzy matching anywhere:
  1. bse_scrips.json by_id, direct on the symbol.
  2. _scrip_extra.json (existing delisted-code supplement), direct.
  3. Same two lookups against every rename-chain alias of the symbol (_rename_map.json,
     both directions -- a dead symbol may be known to BSE under a different alias than
     the one sf data keys it under, and vice versa).
  4. Exact (not fuzzy) match against _bse_master_all.json's own `scrip_id` mnemonic field,
     across ALL statuses (Active/Delisted/Suspended) -- accepted only when exactly one
     master row carries that scrip_id. Newly-resolved codes are folded back into
     _scrip_extra.json so later steps inherit them for free.
  5. Normalized company-NAME exact match: pull the symbol's registered name out of NSE's
     own symbol-change master (symchg.csv carries NAME,OLD_SYMBOL,NEW_SYMBOL), normalize
     (strip Ltd/Limited/Pvt/.../punctuation), and match against _bse_master_all.json's
     Issuer_Name/Scrip_Name -- accepted only when the normalized name is UNIQUE in the
     master. Also folded back into _scrip_extra.json.
  Anything left after all five is reported unresolved per era, not guessed.

Run: python -X utf8 scripts/cut_gaps_0214.py
Writes: scripts/_gaps_0214.json (per cell: sym, qe, era, need, bse_code, resolve_method,
nse_sym_era_chain); extends scripts/_scrip_extra.json with newly-proven codes.
"""
import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import _n500_member_bin as MB  # noqa: E402
import bse_resolve as BR  # noqa: E402  — ISIN guard on symbol->scrip (runbook §76)

QES = [y * 10000 + md for y in range(2002, 2015) for md in (331, 630, 930, 1231)]  # 2002Q1..2014Q4


def era_of(qe):
    y = qe // 10000
    if y <= 2004:
        return "2002-04"
    if y <= 2007:
        return "2005-07"
    return "2008-14"


def load_json(name, default=None):
    p = os.path.join(HERE, name)
    if os.path.exists(p):
        return json.load(open(p, encoding="utf8"))
    return default


# ---------- symbol <-> BSE scrip-code resolution ----------

NAME_STOP = re.compile(r"\b(LIMITED|LTD|PRIVATE|PVT|COMPANY|COMPANIES|CO|CORPORATION|CORP|INDIA|INDUSTRIES|IND)\b\.?")
PUNCT = re.compile(r"[^A-Z0-9]+")


def norm_name(s):
    s = (s or "").upper()
    s = NAME_STOP.sub(" ", s)
    s = PUNCT.sub(" ", s)
    return " ".join(s.split())


def build_alias_fn(rmap):
    """symbol -> set of every symbol linked to it by a rename edge (both directions),
    always including itself. The map is a flat era->current dict (797 entries, one hop
    per entity per build_sf_data.py) -- walk forward if `s` is an old key, then collect
    everything that points at the resolved end AND everything that points at `s` itself."""
    fwd = rmap
    rev = {}
    for old, new in rmap.items():
        rev.setdefault(new, []).append(old)

    def aliases_of(s):
        seen = {s}
        cur = s
        while cur in fwd and fwd[cur] not in seen:
            seen.add(fwd[cur])
            cur = fwd[cur]
        seen |= set(rev.get(cur, []))
        seen |= set(rev.get(s, []))
        return seen

    return aliases_of


def load_symchg_names():
    """OLD/NEW symbol -> registered company name, from NSE's symbol-change master
    (NAME,OLD_SYMBOL,NEW_SYMBOL,DATE, no header row)."""
    by_sym = {}
    p = os.path.join(HERE, "symchg.csv")
    with open(p, encoding="utf8", errors="replace") as f:
        for row in csv.reader(f):
            if len(row) < 3:
                continue
            name, old, new = row[0].strip(), row[1].strip().upper(), row[2].strip().upper()
            if not name:
                continue
            by_sym.setdefault(old, name)
            by_sym.setdefault(new, name)
    return by_sym


def build_scripid_index(master):
    idx = {}
    for row in master:
        sid = (row.get("scrip_id") or "").strip().upper()
        if sid:
            idx.setdefault(sid, []).append(row)
    return idx


def build_name_index(master):
    idx = {}
    for row in master:
        for field in ("Issuer_Name", "Scrip_Name"):
            nm = norm_name(row.get(field))
            if nm:
                idx.setdefault(nm, []).append(row)
    return idx


def resolve_codes(symbols, rmap, byid, scrip_extra, master):
    aliases_of = build_alias_fn(rmap)
    scripid_idx = build_scripid_index(master)
    name_idx = build_name_index(master)
    symchg_names = load_symchg_names()

    code_of, method_of, chain_of, new_extra = {}, {}, {}, {}
    for sym in symbols:
        aliases = sorted(aliases_of(sym))
        chain_of[sym] = aliases

        if byid.get(sym):
            code_of[sym], method_of[sym] = byid[sym], "by_id"
            continue
        if scrip_extra.get(sym):
            code_of[sym], method_of[sym] = scrip_extra[sym], "scrip_extra"
            continue

        hit = None
        for a in aliases:
            if a == sym:
                continue
            if byid.get(a):
                hit = (byid[a], "by_id_rename_chain")
                break
            if scrip_extra.get(a):
                hit = (scrip_extra[a], "scrip_extra_rename_chain")
                break
        if hit:
            code_of[sym], method_of[sym] = hit
            continue

        hit = None
        for a in aliases:
            rows = scripid_idx.get(a)
            if rows and len(rows) == 1:
                hit = (int(rows[0]["SCRIP_CD"]), "scrip_id_match")
                break
        if hit:
            code_of[sym], method_of[sym] = hit
            new_extra[sym] = hit[0]
            continue

        hit = None
        for a in aliases:
            nm = symchg_names.get(a)
            if not nm:
                continue
            rows = name_idx.get(norm_name(nm))
            if rows and len(rows) == 1:
                hit = (int(rows[0]["SCRIP_CD"]), "name_match")
                break
        if hit:
            code_of[sym], method_of[sym] = hit
            new_extra[sym] = hit[0]
            continue

    # ISIN GUARD (§76) — applied to the FINAL map so it covers all five routes above, including
    # scrip_id_match and name_match, which match on a BSE-side label and so can land a different
    # company whose scrip_id happens to equal our ticker (the KALYANI trap).
    for s in list(code_of):
        why = BR.blocked(s)
        if why:
            print(f"  [isin-guard] dropping {s} ({why}) via {method_of.get(s)}")
            code_of.pop(s, None)
            method_of.pop(s, None)
            new_extra.pop(s, None)

    return code_of, method_of, chain_of, new_extra


def main():
    fund = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json"), encoding="utf8"))
    revop = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json"), encoding="utf8"))
    rmap = load_json("_rename_map.json", {})
    byid = load_json("bse_scrips.json", {"by_id": {}})["by_id"]
    scrip_extra = load_json("_scrip_extra.json", {})
    master = load_json("_bse_master_all.json", [])

    fmap = {s: {r[0]: r for r in rows} for s, rows in fund.items()}

    # 1) walk every quarter's real N500 membership -> the true member-quarter cell set
    cellset = []
    per_era_members = {}
    for qe in QES:
        members = MB.membership(qe)
        era = era_of(qe)
        per_era_members.setdefault(era, set()).update(members)
        for sym in members:
            cellset.append((sym, qe))

    # 2) subtract stored cells -> gaps, tagging what's actually missing (dual-form aware)
    gaps = []
    stored_pat_only = 0
    for sym, qe in cellset:
        row = fmap.get(sym, {}).get(qe)
        has_pat = row is not None and row[1] is not None
        rr = revop.get(sym, {}).get(str(qe))
        has_rev = rr is not None and rr[0] is not None
        if has_pat and has_rev:
            continue
        need = []
        if not has_pat:
            need.append("pat")
        if not has_rev:
            need.append("rev")
        if has_pat and not has_rev:
            stored_pat_only += 1
        gaps.append({"sym": sym, "qe": qe, "era": era_of(qe), "need": need})

    # 3) resolve a BSE scrip code for every symbol that actually has an open cell
    symbols = sorted({g["sym"] for g in gaps})
    code_of, method_of, chain_of, new_extra = resolve_codes(symbols, rmap, byid, scrip_extra, master)

    for g in gaps:
        sym = g["sym"]
        g["bse_code"] = code_of.get(sym)
        g["resolve_method"] = method_of.get(sym)
        g["nse_sym_era_chain"] = chain_of.get(sym, [sym])

    gaps.sort(key=lambda g: (g["sym"], g["qe"]))
    json.dump(gaps, open(os.path.join(HERE, "_gaps_0214.json"), "w", encoding="utf8"), indent=0)

    if new_extra:
        scrip_extra.update(new_extra)
        json.dump(
            scrip_extra, open(os.path.join(HERE, "_scrip_extra.json"), "w", encoding="utf8"), indent=1, sort_keys=True
        )

    # ---- reachability / sanity report ----
    print("=== STEP G -- gap universe cut ===")
    print("2002-2014 member-quarter cells (real bin membership):", len(cellset))
    print("stored (std PAT + std rev both present):", len(cellset) - len(gaps))
    print(
        "OPEN gap cells:",
        len(gaps),
        "  [of which %d already have std PAT and only need rev -- dual-form gaps]" % stored_pat_only,
    )
    pat_missing = sum(1 for g in gaps if "pat" in g["need"])
    print("  PAT still missing (comparable to the campaign doc's 707/26,022/~25,300 baseline):", pat_missing)
    print()
    print("Ever-members per era (sanity check vs doc's 708 / 552 / 566):")
    for era in ("2008-14", "2005-07", "2002-04"):
        print("  %s: %d distinct members ever" % (era, len(per_era_members.get(era, ()))))
    print()
    print("BSE-code reachability per era (companies with >=1 open cell in that era):")
    for era in ("2008-14", "2005-07", "2002-04"):
        era_syms = sorted({g["sym"] for g in gaps if g["era"] == era})
        resolved = [s for s in era_syms if code_of.get(s)]
        by_method = {}
        for s in resolved:
            by_method[method_of[s]] = by_method.get(method_of[s], 0) + 1
        print(
            "  %s: %d/%d resolved  (%s)"
            % (era, len(resolved), len(era_syms), ", ".join("%s=%d" % kv for kv in sorted(by_method.items())) or "-")
        )
    print()
    for era in ("2008-14", "2005-07", "2002-04"):
        era_syms = sorted({g["sym"] for g in gaps if g["era"] == era})
        unresolved = [s for s in era_syms if not code_of.get(s)]
        if unresolved:
            print("  %s UNRESOLVED (%d): %s" % (era, len(unresolved), ", ".join(unresolved)))
    if new_extra:
        print()
        print("New BSE codes folded into _scrip_extra.json: %d (%s)" % (len(new_extra), ", ".join(sorted(new_extra))))


if __name__ == "__main__":
    main()
