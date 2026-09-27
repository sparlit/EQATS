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
"""Take the ALIAS TARGET's NSE-era rows off a BSE-ticker collision key (runbook §197).

WHY. docs/bse_alias_collisions.json lists BSE-only dashboard tickers that are also a FORMER NSE ticker of
another company (WORTH = Worth Investment on BSE; NSE's WORTH was Worth Peripherals until 2025-10-10). The
NSE results pipeline stored that other company's filings under the old NSE symbol — sf_revop['WORTH'] is
Worth Peripherals' 2020-09..2025-06, identical to WORTHPERI's own rows — so every site consumer that reads a
store by the bare ticker (the stock page slice, discovery buckets) served Worth Peripherals' numbers under
Worth Investment's name. Runbook §30 step 4 is the rule for a rename's old key: its rows belong under the
current key, and the old key goes.

WHAT IT DOES, per collision key OLD -> TARGET, per store:
  1. PROOF the rows are TARGET's (key level): at least one quarter's headline agrees with TARGET's own stored
     row (revenue / operating profit / EBIT, or standalone PAT) and NO quarter agrees with the BSE company's
     own filings (docs/bse_fundamentals.json px[scrip]). Unproven keys (AZTEC: 2023-26 rows under a ticker whose
     target stopped filing in 2009) are left untouched and named.
  2. MOVE, fill-only, only where the served headline corroborates it (every field both rows carry agrees,
     ignoring slot 5 — the never-rendered PAT mirror — and slot 6, the bank flag):
       revop rows  -> fill TARGET's null fields for that quarter, or add the quarter TARGET lacks
       xbrl_extra  -> add the quarter, or the basis block (s/c), TARGET lacks — whole blocks only, a block
                      is one filing's detail and is never blended with another filing's fields
     TARGET's existing values are never changed. Standalone-PAT rows (fund) are never moved: TARGET already
     holds every quarter, and PAT authority stays with its own rows.
  3. DROP everything else and the OLD key itself. Every removed value is written to
     scripts/bse_alias_collision_retractions.json with its action, so the retraction is reversible.
  4. RE-KEY the fill/heal LEDGERS that journal a cell under OLD (every file verify_fills_live.py registers,
     + stdpat_adjud_verdicts.json) to TARGET — else verify_fills_live reads them MISSING (it BLOCKS the
     nightly refresh-fundamentals commit) and a replay would write the other company back under OLD.
     An entry the target already journals is marked skip instead (first run: 9 re-keyed, 6 skipped).
Idempotent: a second run finds no OLD rows and writes nothing.

Run:  python3 scripts/retract_bse_alias_collision_rows.py [--apply]     (default: dry run, prints the plan)
"""
import gzip
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LEDGER = os.path.join(ROOT, "docs", "bse_alias_collisions.json")
OUT = os.path.join(HERE, "bse_alias_collision_retractions.json")
FUND_STORES = [os.path.join(ROOT, "docs", "sf_fundamentals.json"), os.path.join(HERE, "fundamentals.json")]
REVOP_STORES = [os.path.join(ROOT, "docs", "sf_revop.json"), os.path.join(HERE, "revop_fundamentals.json")]
XTRA = os.path.join(HERE, "xbrl_extra.json.gz")
AGREE_IDX = (0, 1, 2, 3, 4, 7, 8)  # revop slots that must agree; 5 = PAT mirror (never rendered), 6 = fin flag
FILL_IDX = (0, 1, 2, 3, 4, 7, 8)


def _load(p):
    raw = open(p, "rb").read()
    return json.loads(gzip.decompress(raw) if p.endswith(".gz") else raw)


def _save(p, d):
    blob = json.dumps(d, separators=(",", ":")).encode("utf-8")
    open(p, "wb").write(gzip.compress(blob, 9) if p.endswith(".gz") else blob)


def _same(a, b):
    return a is not None and b is not None and abs(float(a) - float(b)) < 1e-9


def agrees(a, b):
    """Every slot in AGREE_IDX that both rows carry is equal, and they share at least one."""
    shared = [i for i in AGREE_IDX if i < len(a) and i < len(b) and a[i] is not None and b[i] is not None]
    return bool(shared) and all(_same(a[i], b[i]) for i in shared)


def rekey_ledgers(coll, proven, run):
    """4. FILL / HEAL LEDGERS that journal a cell under a proven collision key. They are re-applied and re-checked
    against the served stores (verify_fills_live.py — BLOCKING in refresh-fundamentals), so once the key is gone
    they read MISSING, and a replay would write the other company back under the BSE ticker. The value is the
    target's (proven above), so the entry moves to the target's key when the target has none for that cell;
    otherwise it is marked skip. Ledgers scanned: every file verify_fills_live registers (LEDGERS, BASIS_KEYED,
    NESTED) + stdpat_adjud_verdicts.
    -> {path: (data, trailing_newline)} of ledgers changed."""
    sys.path.insert(0, HERE)
    import verify_fills_live as V

    names = sorted(
        {l[0] for reg in (V.LEDGERS, getattr(V, "BASIS_KEYED", []), getattr(V, "NESTED", [])) for l in reg}
        | {"stdpat_adjud_verdicts.json"}
    )
    out = {}

    def note(old, c):
        return "§197: re-keyed from {} — {} on this site is {} (BSE {}); this cell is {}'s".format(
            old, old, c["bse_name"], c["bse_code"], c["target"]
        )

    def move(container, k, newk, old, c, log_):
        v = container[k]
        if isinstance(v, dict) and v.get("skip") and v.get("rekeyed"):
            return  # skipped by an earlier run
        if newk not in container:
            container[newk] = container.pop(k)
            if isinstance(container[newk], dict):
                container[newk]["rekeyed"] = note(old, c)
            log_.append({"key": k, "to": newk, "action": "re-keyed"})
        elif isinstance(v, dict):
            v["skip"] = True
            v["rekeyed"] = note(old, c) + " (target already journals this cell — skipped)"
            log_.append({"key": k, "to": newk, "action": "skip (target entry exists)"})

    for n in names:
        p = os.path.join(HERE, n)
        if not os.path.exists(p):
            continue
        raw = open(p, encoding="utf-8").read()
        d = json.loads(raw)
        if not isinstance(d, dict):
            continue
        log_ = []
        for old in sorted(proven):
            c = coll[old]
            tgt = c["target"]
            if isinstance(d.get(old), dict):  # SYM -> {QE: entry}
                if tgt not in d:
                    d[tgt] = d.pop(old)
                    for e in d[tgt].values():
                        if isinstance(e, dict):
                            e["rekeyed"] = note(old, c)
                    log_.append({"key": old, "to": tgt, "action": "re-keyed"})
                else:
                    for q in list(d[old]):
                        if q not in d[tgt]:
                            d[tgt][q] = d[old].pop(q)
                            if isinstance(d[tgt][q], dict):
                                d[tgt][q]["rekeyed"] = note(old, c)
                            log_.append({"key": f"{old}/{q}", "to": f"{tgt}/{q}", "action": "re-keyed"})
                        elif isinstance(d[old][q], dict) and not (d[old][q].get("skip") and d[old][q].get("rekeyed")):
                            d[old][q]["skip"] = True
                            d[old][q]["rekeyed"] = note(old, c) + " (target already journals it)"
                            log_.append({"key": f"{old}/{q}", "action": "skip (target entry exists)"})
                    if not d[old]:
                        d.pop(old)
            if isinstance(d.get(old), dict) and all(isinstance(e, dict) and e.get("skip") for e in d[old].values()):
                pass  # only skipped entries left: nothing to do
            for cont in [d] + [v for v in d.values() if isinstance(v, dict)]:  # "SYM|QE…" keys, top level or one down
                for k in [k for k in cont if isinstance(k, str) and k.startswith(old + "|")]:
                    move(cont, k, tgt + k[len(old) :], old, c, log_)
        if log_:
            out[p] = (d, raw.endswith("\n"))
            run.setdefault("ledgers", {})[n] = log_
            print(
                "ledger %-32s %d entr(ies) re-keyed/skipped: %s"
                % (
                    n,
                    len(log_),
                    ", ".join("{}->{}".format(e["key"], e.get("to", "skip")) for e in log_[:4])
                    + (" ..." if len(log_) > 4 else ""),
                )
            )
    return out


def main():
    apply = "--apply" in sys.argv
    coll = _load(LEDGER)["collisions"]
    served_rv = _load(REVOP_STORES[0])
    served_fd = _load(FUND_STORES[0])
    bse_px = _load(os.path.join(ROOT, "docs", "bse_fundamentals.json")).get("px", {})
    fund = {p: _load(p) for p in FUND_STORES}
    revop = {p: _load(p) for p in REVOP_STORES}
    xtra = _load(XTRA)
    log = _load(OUT) if os.path.exists(OUT) else {"_README": __doc__.split("\n\n")[0].strip(), "runs": []}
    run = {"at": time.strftime("%Y-%m-%d %H:%M"), "keys": {}}
    changed = set()

    for old, c in sorted(coll.items()):
        tgt = c["target"]
        present = [os.path.relpath(p, ROOT) for p, d in list(fund.items()) + list(revop.items()) if d.get(old)] + (
            ["scripts/xbrl_extra.json.gz"] if xtra.get(old) else []
        )
        if not present:
            continue
        # ---- 1. proof, on the served stores ------------------------------------------------------------------
        hits = [
            q
            for q, r in (served_rv.get(old) or {}).items()
            if (served_rv.get(tgt) or {}).get(q) and agrees(r, served_rv[tgt][q])
        ]
        tf = {r[0]: r for r in served_fd.get(tgt) or []}
        hits += [str(r[0]) for r in served_fd.get(old) or [] if r[0] in tf and _same(r[1], tf[r[0]][1])]
        own = bse_px.get(str(c["bse_code"])) or {}
        clash = [
            q
            for q, r in (served_rv.get(old) or {}).items()
            if own.get(q) and (_same(own[q].get("rev"), r[0]) or _same(own[q].get("rev"), r[1]))
        ]
        clash += [
            str(r[0])
            for r in served_fd.get(old) or []
            if own.get(str(r[0])) and (_same(own[str(r[0])].get("pat"), r[1]) or _same(own[str(r[0])].get("pat"), r[3]))
        ]
        if not hits or clash:
            print(
                "%-10s -> %-10s NOT PROVEN (agree-with-target %d, agree-with-own-BSE-filings %d) — left as is: %s"
                % (old, tgt, len(set(hits)), len(set(clash)), ", ".join(present))
            )
            run["keys"][old] = {
                "target": tgt,
                "action": "left: not proven to be the target's rows",
                "agree_target": sorted(set(hits)),
                "agree_own_bse": sorted(set(clash)),
            }
            continue
        rec = run["keys"].setdefault(
            old, {"target": tgt, "proof_quarters": sorted(set(hits))[:8], "proof_count": len(set(hits)), "stores": {}}
        )
        corroborated = {
            q
            for q, r in (served_rv.get(old) or {}).items()
            if (served_rv.get(tgt) or {}).get(q) and agrees(r, served_rv[tgt][q])
        }
        # ---- 2/3. per store -----------------------------------------------------------------------------------
        for p, d in fund.items():
            rows = d.pop(old, None)
            if rows:
                rec["stores"][os.path.relpath(p, ROOT)] = [
                    {
                        "row": r,
                        "action": "dropped (target holds the quarter)"
                        if r[0] in {x[0] for x in d.get(tgt) or []}
                        else "dropped (fund rows are never moved)",
                    }
                    for r in rows
                ]
                changed.add(p)
        for p, d in revop.items():
            rows = d.pop(old, None)
            if not rows:
                continue
            out = []
            t = d.setdefault(tgt, {})
            for q, r in sorted(rows.items()):
                cur = t.get(q)
                ref = (served_rv.get(tgt) or {}).get(q)
                if cur is None and ref is not None and agrees(r, ref):
                    t[q] = list(r)
                    out.append(
                        {
                            "q": q,
                            "row": r,
                            "action": "moved (target lacked the quarter here; agrees with the served target row)",
                        }
                    )
                elif cur is not None and agrees(r, cur):
                    filled = [i for i in FILL_IDX if i < len(r) and r[i] is not None and cur[i] is None]
                    if filled:
                        cur = list(cur)
                        for i in filled:
                            cur[i] = r[i]
                        t[q] = cur
                    out.append(
                        {
                            "q": q,
                            "row": r,
                            "action": f"merged, filled slots {filled}"
                            if filled
                            else "dropped (duplicate of the target row)",
                        }
                    )
                else:
                    out.append({"q": q, "row": r, "action": f"dropped (disagrees with the target row {cur})"})
            if not t:
                d.pop(tgt, None)
            rec["stores"][os.path.relpath(p, ROOT)] = out
            changed.add(p)
        cells = xtra.pop(old, None)
        if cells:
            out = []
            t = xtra.setdefault(tgt, {})
            for q, cell in sorted(cells.items()):
                if q not in corroborated:
                    out.append(
                        {"q": q, "cell": cell, "action": "dropped (no served headline ties this filing to the target)"}
                    )
                    continue
                # a basis block is ONE filing's detail: move whole blocks the target lacks, never blend two filings
                tc = t.setdefault(q, {})
                added = [b for b in cell if b not in tc and cell[b]]
                for b in added:
                    tc[b] = cell[b]
                if not tc:
                    t.pop(q)
                out.append(
                    {
                        "q": q,
                        "cell": cell,
                        "action": "moved basis {}".format(",".join(added))
                        if added
                        else "dropped (target holds this quarter's {} detail)".format(",".join(sorted(cell))),
                    }
                )
            if not t:
                xtra.pop(tgt, None)
            rec["stores"]["scripts/xbrl_extra.json.gz"] = out
            changed.add(XTRA)
        n = {s: len(v) for s, v in rec["stores"].items()}
        mv = sum(1 for v in rec["stores"].values() for e in v if e["action"].startswith(("moved", "merged, filled")))
        print(
            "%-10s -> %-10s proven by %d quarter(s); rows per store %s; %d moved/merged into %s, rest dropped"
            % (old, tgt, rec["proof_count"], n, mv, tgt)
        )

    # a key is proven once any run moved/dropped its store rows (this run or an earlier one in the log)
    proven = {o for r in log["runs"] + [run] for o, v in r["keys"].items() if v.get("stores")}
    led_changed = rekey_ledgers(coll, proven, run)

    if not changed and not led_changed:
        print("nothing to retract (already applied)")
        return 0
    if not apply:
        print(
            "DRY RUN — re-run with --apply to write %d store(s) + %d ledger(s) + %s"
            % (len(changed), len(led_changed), os.path.relpath(OUT, ROOT))
        )
        return 0
    for p in changed:
        _save(p, xtra if p == XTRA else (fund[p] if p in fund else revop[p]))
    for p, (d, nl) in led_changed.items():
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(d, indent=1) + ("\n" if nl else ""))
    log["runs"].append(run)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(log, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(
        "wrote {} + {}".format(", ".join(os.path.relpath(p, ROOT) for p in sorted(changed)), os.path.relpath(OUT, ROOT))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
