# -*- coding: utf-8 -*-
"""Post-backfill sanity sweep for sf_revop revenue fills. Nulls two error classes the anchor
can't catch on its own, logging every removal to _revgap_nulled.json:

  1. SCALE SPIKE  — a filled cell whose revenue is >4x the company's established (pre-existing,
     XBRL-reliable) max, when there is a solid reference (>=6 old cells, max>=20). Catches
     power-of-ten mis-reads (UNITDSPR 64223 vs ~7000).
  2. DUPLICATE    — the SAME revenue value (to the paisa) in two+ different quarters of one
     company. Real quarterly revenue essentially never repeats exactly; this is a comparative
     column mis-attributed to the wrong quarter (SIEMENS 3398.5 in both Jun-25 and Dec-25).
     Both offending cells are blanked (safer than keeping one wrong one).
  3. TINY-CON     — con rev present but < 5%% of std rev AND < 20 cr: a filer's junk/mis-scaled
     consolidated context (3MINDIA Dec-25 con 1.23 vs std 1228.05; 58-cell sweep 2026-07-22).
     A real consolidation can't shrink revenue below ~5%% of standalone. Only the CON slots are
     blanked (std verified fine in every swept case). The 20-cr floor protects real-but-small con
     values from a scale-inflated std (the ACUTAAS inversion).

Run:  python scripts/revop_sanity.py [--dry]   (compares docs/sf_revop.json vs git HEAD)
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RV = os.path.join(ROOT, "docs", "sf_revop.json")
LED = os.path.join(HERE, "_revgap_nulled.json")


def revof(a):
    if not a:
        return None
    return a[0] if a[0] is not None else a[1]


def main():
    global OK
    dry = "--dry" in sys.argv
    # reviewed allowlist: PAT-anchored as-filed reads for companies whose LATER scale collapsed
    # (IBC-era UTTAMSTL/GAMMONIND class) — "established max" there reflects the dying years and
    # the 4x rule misfires on healthy earlier quarters. The anchor already proved the scale:
    # the page's NP/10 had to match the stored PAT for the cell to land at all.
    okp = os.path.join(HERE, "sanity_ok.json")
    OK = set(json.load(open(okp))) if os.path.exists(okp) else set()
    rv = json.load(open(RV))
    old = json.loads(subprocess.run(["git", "show", "HEAD:docs/sf_revop.json"],
                                    capture_output=True, text=True, cwd=ROOT).stdout or "{}")
    led = json.load(open(LED)) if os.path.exists(LED) else {}

    def wasold(s, qe):
        o = old.get(s, {}).get(str(qe))
        return bool(o) and (o[0] is not None or o[1] is not None)

    kill = []       # (sym, qe, val, reason) — nulls the whole row
    kill_con = []   # (sym, qe, val, reason) — nulls only the con slots
    for s, d in rv.items():
        # Established reference from pre-existing cells, PER SLOT. A holding company's
        # consolidated revenue is legitimately several times its standalone (EQUITAS con
        # 384-1133 vs std 3-163), so comparing a new CON value against a std-derived maximum
        # nulls perfectly good data — that was the long-standing "MFSL casualty" false positive.
        def slot_max(i):
            vals = [c[i] for c in old.get(s, {}).values()
                    if c and len(c) > i and c[i] is not None]
            return max(vals) if len(vals) >= 6 else None
        ref_by_slot = {0: slot_max(0), 1: slot_max(1)}

        # value -> [quarters] for duplicate detection (only among NEW fills)
        seen = {}
        for qe, a in d.items():
            v = revof(a)
            if v is None:
                continue
            # tiny-con: junk/mis-scaled consolidated context beside a healthy standalone.
            # Gated on the CON SLOT being new (old row's con empty) — NOT on the whole cell being
            # new: con fills usually land beside a pre-existing std, which is exactly when the
            # junk arrives (first real catch: the 2026-07-22 rescue re-read 12 junk comparatives).
            o = old.get(s, {}).get(str(qe))
            con_is_new = not (o and o[1] is not None)
            if (con_is_new and a[0] is not None and a[1] is not None and a[0] > 20
                    and 0 <= a[1] < 0.05 * a[0] and a[1] < 20):
                kill_con.append((s, qe, a[1], "junk-tiny-con(con %.2f < 5%% of std %.2f)" % (a[1], a[0])))
            if not wasold(s, qe):
                # scale spike, compared against the SAME slot's history (allowlisted cells exempt)
                ref_max = ref_by_slot[0 if a[0] is not None else 1]
                if ref_max is not None and ref_max >= 20 and v > 4 * ref_max \
                        and "%s|%s" % (s, qe) not in OK:
                    kill.append((s, qe, v, "scale-spike>4x-established-max(%.0f)" % ref_max))
                    continue
                if v > 50:
                    seen.setdefault(round(v, 2), []).append(qe)
        for v, qs in seen.items():
            if len(qs) >= 2:                     # same paisa in >=2 quarters -> mis-attribution
                for qe in qs:
                    if "%s|%s" % (s, qe) in OK:   # allowlisted: genuine near-identical as-filed
                        continue
                    kill.append((s, qe, v, "duplicate-value-across-quarters(%s)" % ",".join(sorted(qs))))

    # de-dup kill list (a cell could hit both rules)
    seen_keys = set()
    kills = []
    for s, qe, v, why in kill:
        k = (s, qe)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        kills.append((s, qe, v, why))

    kill_con = [k for k in kill_con if (k[0], k[1]) not in seen_keys]
    print("sanity: %d cells to null (%d scale, %d duplicate) + %d con-only" % (
        len(kills),
        sum(1 for k in kills if k[3].startswith("scale")),
        sum(1 for k in kills if k[3].startswith("duplicate")),
        len(kill_con)))
    for s, qe, v, why in sorted(kills) + sorted(kill_con):
        print("  %-12s %s  rev=%-10s  %s" % (s, qe, v, why))

    if not dry and (kills or kill_con):
        for s, qe, v, why in kills:
            a = rv[s][qe]
            a[0] = a[1] = a[2] = a[3] = a[7] = a[8] = None
            rv[s][qe] = a
            led["%s|%s" % (s, qe)] = {"nulled_rev": v, "reason": why}
        for s, qe, v, why in kill_con:
            a = rv[s][qe]
            a[1] = a[3] = a[8] = None
            rv[s][qe] = a
            led["%s|%s" % (s, qe)] = {"nulled_rev": v, "reason": why}
        json.dump(rv, open(RV, "w"), separators=(",", ":"))
        json.dump(led, open(LED, "w"), indent=0)
        print("nulled %d cells; ledger now %d entries" % (len(kills) + len(kill_con), len(led)))


if __name__ == "__main__":
    main()
