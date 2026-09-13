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
"""LAND the adjudicated issuer-sweep renames into scripts/_rename_map.json.

Reads scripts/_isin_seam_verdicts.json and adds one `old -> surviving bin key` entry per
CONFIRMED (or hand-accepted SINGLE-LEG) seam, following the 30-4b/93d playbook:

  * the target is the END of the confirmed chain, matching build_sf_data's own `canon` rule
    (the latest-trading ticker of the ISIN group) — SUNDRMCLAY -> TVSHLTD, not -> SUNCLAYTON;
  * a REFUSED seam BREAKS the chain: keys before it map only as far as the break;
  * fill-only and idempotent — an entry that already points at the same target is left alone,
    and a DIFFERENT existing target is reported and never overwritten (that would be another
    session's or another campaign's call to make).

After this, run `python3 scripts/check_fund_alias.py --write` for the live-target entries, then
`--alias-dead` here for the rest: check_fund_alias's rule 3 requires the TARGET to be alive, and
a rename whose successor has since delisted (EONELECT -> EON, MONNETISPA -> JSWISPL, ...) is
refused by it. Those go into the same "extra (older hand-curated layer, kept)" bucket 93d used
for BILT -> BALLARPUR, written with check_fund_alias's OWN serializer so both copies stay
byte-identical and the checker stays green.

⚠️ `--alias-dead` re-applies rule 2 itself: an OLD symbol that is ALIVE in META is never aliased,
however well the rename is proved. ARL is the case that matters — NSE's own EQUITY_L calls it
Arvind Remedies in 2006, 2010 and 2011 and the pair ARL -> ARVINDREM is airtight (both ISINs read
off the bhavcopy, prevclose x10 exact), but the ticker ARL belongs TODAY to a live BSE company,
Anand Rayons (ARL.BO, scrip 542721, a different issuer). Aliasing it would hand Arvind Remedies'
fundamentals to Anand Rayons — the 89 recycled-ticker class, here in its cross-exchange form. It
is left out of the alias AND out of the rename map (89 step 3: a live symbol must not be
rewritten to another key by present-era joins).

⚠️ `_rename_map.json` is REGENERATED WHOLESALE by a full build_sf_data rebuild and none of these
pairs is discoverable that way (that is the defect), so the baked FUND_ALIAS is the durable copy.

Run:  python3 scripts/isin_seam_land.py [--write]
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VERD = os.path.join(HERE, "_isin_seam_verdicts.json")
SWEEP = os.path.join(HERE, "_isin_issuer_sweep.json")
MAP = os.path.join(HERE, "_rename_map.json")
ACCEPT = ("CONFIRMED", "SINGLE-LEG")


def live_meta_symbols():
    """The symbols META calls alive — the 30-4c / 89 reused-ticker guard, applied on BOTH legs.

    Without it this script is not idempotent: the ARL entry was deleted by hand after the first
    run and the second run put it straight back (a heal that re-applies is a nightly rewrite,
    87e-bis). The refusal belongs in the generator, not in a follow-up edit."""
    sys.path.insert(0, HERE)
    import check_fund_alias as C

    alive, total, source, stamp = C.load_meta()
    age = C.stamp_age(stamp)
    if total < C.MIN_SYMBOLS or len(alive) < C.MIN_ALIVE or age is None or age > C.MAX_META_AGE_DAYS:
        msg = f"META unusable ({source}, stamp {stamp}, age {age}) — refusing to judge"
        raise SystemExit(msg)
    return alive


def chains():
    """-> ({old: target}, [(issuer, [keys...])]) over the confirmed seams only."""
    V = json.load(open(VERD))
    S = json.load(open(SWEEP))
    alive = live_meta_symbols()
    ok = {(s["issuer"], s["old"], s["new"]) for s in V["seams"] if s["verdict"] in ACCEPT}
    out, ch, refused = {}, [], {}
    for g in S["groups"]:
        keys = [k["key"] for k in g["keys"]]
        i = 0
        while i < len(keys) - 1:
            j = i
            while j < len(keys) - 1 and (g["issuer"], keys[j], keys[j + 1]) in ok:
                j += 1
            if j > i:
                for o in keys[i:j]:
                    if o in alive:
                        refused[o] = keys[j]  # a live symbol is never rewritten (89 step 3)
                    else:
                        out[o] = keys[j]
                ch.append((g["issuer"], keys[i : j + 1]))
            i = max(j, i + 1)
    if refused:
        print(
            "REFUSED (OLD symbol is alive in META — reused-ticker guard): {}".format(
                ", ".join("{}->{}".format(*kv) for kv in sorted(refused.items()))
            )
        )
    return out, ch


def alias_dead(write):
    """Hand-add the confirmed pairs check_fund_alias refuses because the TARGET is dead."""
    sys.path.insert(0, HERE)
    import check_fund_alias as C

    add, _ = chains()
    rmap = json.load(open(MAP))
    alive, total, source, stamp = C.load_meta()
    age = C.stamp_age(stamp)
    if total < C.MIN_SYMBOLS or len(alive) < C.MIN_ALIVE or age is None or age > C.MAX_META_AGE_DAYS:
        print(f"META unusable ({source}, {stamp}, age {age}) — refusing to judge")
        return 1
    cur, _, _ = C.read_baked(C.TARGETS[0])

    want, skipped = {}, {}
    for old in sorted(add):
        if old not in rmap:  # chains() already refused it (see 89)
            skipped[old] = "not in _rename_map"
            continue
        target = C.resolve(old, rmap)
        if target in alive:
            skipped[old] = "target alive — check_fund_alias --write owns it"
        elif old in cur:
            skipped[old] = f"already baked -> {cur[old]}"
        elif target == old:
            skipped[old] = "resolves to itself"
        else:
            want[old] = target

    print("META: %s (cut from %s, %d d old) — %d alive | baked now: %d" % (source, stamp, age, len(alive), len(cur)))
    print("dead-target entries to hand-add: %d" % len(want))
    for o in sorted(want):
        print("   %-12s -> %s" % (o, want[o]))
    print("skipped: %d" % len(skipped))
    for o in sorted(skipped):
        if "already baked" not in skipped[o] and "target alive" not in skipped[o]:
            print("   %-12s %s" % (o, skipped[o]))
    if not write:
        print("\n(dry run; pass --write to apply)")
        return 0
    if not want:
        print("nothing to do")
        return 0
    merged = dict(cur)
    merged.update(want)
    payload = C._fmt(merged)
    for path in C.TARGETS:
        _, text, m = C.read_baked(path)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text[: m.start(1)] + payload + text[m.end(1) :])
    subprocess.run(["node", "--check", C.TARGETS[0]], check=True)
    print("\nbaked FUND_ALIAS %d -> %d in both copies; node --check OK" % (len(cur), len(merged)))
    return 0


def main():
    if "--alias-dead" in sys.argv:
        return alias_dead("--write" in sys.argv)
    add, ch = chains()
    cur = json.load(open(MAP))
    new = {o: t for o, t in add.items() if o not in cur}
    same = [o for o, t in add.items() if cur.get(o) == t]
    conflict = {o: (cur[o], t) for o, t in add.items() if o in cur and cur[o] != t}

    print("%d confirmed chains -> %d old keys" % (len(ch), len(add)))
    print("  already present and identical: %d" % len(same))
    print("  CONFLICT (left alone): %d %s" % (len(conflict), conflict or ""))
    print("  to add: %d" % len(new))
    for o in sorted(new):
        print("    %-12s -> %s" % (o, new[o]))
    if "--write" not in sys.argv:
        print("\n(dry run; pass --write to apply)")
        return 0
    if conflict:
        print("\nrefusing to write while a conflict is unresolved")
        return 1
    merged = dict(cur)
    merged.update(new)
    with open(MAP, "w") as fh:
        json.dump(merged, fh, indent=1, sort_keys=True)
    print("\n_rename_map.json: %d -> %d entries" % (len(cur), len(merged)))
    print("next: python3 scripts/check_fund_alias.py --write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
