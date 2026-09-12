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
"""HTML-ESCAPED PHANTOM SYMBOLS — the guard that stops them coming back  (2026-08-26)

THE CLASS. An `&` HTML-escaped during ingestion and then upper-cased with the ticker gives a symbol
no exchange ever listed: `M&M` -> `M&AMP;M`, `SURANAT&P` -> `SURANAT&AMP;P`. Such a key is not inert.
It is a duplicate the site's own coverage scans read as "already filled", it resolves happily through
Moneycontrol's autosuggest (which answers for the unescaped name), and — measured 2026-08-26 — it was
RENDERING on the site: `docs/discovery.json`'s results buckets carried 46 phantom rows across 21
buckets, labelled `M&AMP;M` / `J&AMP;KBANK` to the user's face. Both prior memories recorded these
keys as "invisible to the site". They were not.

WHAT THIS GUARD DOES. Every phantom key that exists today is recorded in `_phantom_key_baseline.json`.
The guard fails when a file gains one that is not in its baseline, and when either fundamentals store
gains one at all (they were retracted to zero on 2026-08-26 — `retract_phantom_symbols.py`). It is
deliberately a RATCHET, not a fixed list: as a store is cleaned, re-baseline with --bless and the new,
lower number becomes the ceiling. It prints when a count SHRINKS so the ratchet actually gets tightened
instead of quietly drifting.

⚠️ A GUARD THAT CHECKS NOTHING IS WORSE THAN NO GUARD (memory:
feedback-ledger-guard-count-must-move — a ledger guard whose count never moves is checking nothing). So this refuses to pass if a zero-tolerance file is missing or
unparseable, rather than skipping it and reporting a clean run over an empty set.

DETECTION IS BY `html.unescape`, NOT BY THE STRING "&AMP;" — `&amp;`, `&AMP;`, `&#38;` and
`&#x26;` are all the same defect and only one of them was ever grepped for.

Run:  python3 scripts/phantom_key_guard.py [--bless]
Exit 1 on any new phantom key.
"""
import html
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# NOT `_phantom_key_baseline.json`: .gitignore excludes `scripts/_*`, and a ratchet only CI can see
# is no ratchet at all. (The `!` exception route was available but .gitignore was another session's
# work-in-progress — CLAUDE.md rule 1.)
BASELINE = os.path.join(HERE, "phantom_key_baseline.json")

# Stores that must NEVER carry a phantom key again. Missing/unparseable here is a FAILURE.
ZERO_TOLERANCE = [
    "docs/sf_fundamentals.json",
    "scripts/fundamentals.json",
    # added 2026-08-26 when sf_revop was closed too (runbook §115). The ledger is on
    # the list for the same reason it had to be retracted: build_revop.py RESUMES from
    # it, so a phantom there re-seeds the served payload on the very next build.
    "docs/sf_revop.json",
    "scripts/revop_fundamentals.json",
]
# Everything else is scanned and ratcheted against the baseline.
SCANNED = [
    *ZERO_TOLERANCE,
    "docs/sf_revop.json",
    "docs/discovery.json",
    "scripts/revop_fundamentals.json",
    "scripts/mc_pat_fills.json",
    "scripts/mc_history_fills.json",
    "scripts/mc_fyident_fills.json",
    "scripts/xbrl_comparative_fills.json",
    "scripts/xbrl_nature.json",
    "scripts/copied_con_purge.json",
    "scripts/no_con_filing.json",
    "scripts/n500_cov_facts.json",
    "scripts/agg_tools/_agg_ids_tl.json",
    "scripts/agg_tools/_agg_ids_mc.json",
    "scripts/fill2020_tools/_mc_codes.json",
    "scripts/fill2020_tools/_mc_reresolved.json",
]
# The retraction journal is ABOUT phantom keys, so it is keyed by them on purpose.
EXEMPT = {"scripts/phantom_symbol_retract.json", "scripts/phantom_symbol_merge.json"}


def is_escaped(sym):
    """True when an HTML unescape would change the symbol -- &amp; / &AMP; / &#38; alike."""
    return isinstance(sym, str) and html.unescape(sym) != sym


def real_symbol(sym, renames=None):
    """Phantom -> the ticker that actually holds the data, following the rename chain.

    Unescaping ALONE is not enough: GET&D and L&TFH were renamed to GVT&D and LTF, so the unescaped
    key is itself dead (memory: project-stocks-phantom-escaped-symbols)."""
    cur = html.unescape(sym)
    if renames is None:
        try:
            renames = json.load(open(os.path.join(HERE, "_rename_map.json")))
        except Exception:
            renames = {}
    seen = {cur}
    while renames.get(cur) and renames[cur] not in seen:
        cur = renames[cur]
        seen.add(cur)
    return cur


def _symbols(obj, out, depth=0):
    """Collect escaped symbol-shaped strings from keys AND values (discovery.json holds them as
    values, not keys -- a key-only scan reported that file clean while it was serving them)."""
    if isinstance(obj, str):
        # A SYMBOL NEVER CONTAINS `|`. Retraction provenance records the old key verbatim
        # (`"rekeyed_from": "M&AMP;M|20200630|std"`), and without this the guard flagged its own
        # audit trail as a fresh phantom — a guard tripping on the evidence that it worked.
        if is_escaped(obj) and len(obj) <= 24 and "&AMP;" in obj.upper() and "|" not in obj:
            out.add(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                head = k.split("|")[0]
                if is_escaped(head):
                    out.add(head)
            _symbols(v, out, depth + 1)
    elif isinstance(obj, list) and depth < 8:
        for v in obj:
            _symbols(v, out, depth + 1)


def scan():
    found, unreadable = {}, []
    for rel in SCANNED:
        p = os.path.join(ROOT, rel)
        try:
            d = json.load(open(p, encoding="utf-8"))
        except Exception as e:
            unreadable.append((rel, str(e)))
            continue
        got = set()
        _symbols(d, got)
        found[rel] = sorted(got)
    return found, unreadable


def check():
    """(ok, lines) — the whole verdict without exiting, so verify_fills_live.py can call it and
    inherit the blocking CI wiring without a workflow edit."""
    lines = []
    found, unreadable = scan()
    for rel, e in unreadable:
        if rel in ZERO_TOLERANCE:
            lines.append(
                f"phantom-key guard: FAIL — {rel} is unreadable ({e}); refusing to report a "
                "clean run over a file it never checked"
            )
            return False, lines
    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    bad = []
    for rel, syms in sorted(found.items()):
        allowed = set() if rel in ZERO_TOLERANCE else set(base.get(rel, []))
        extra = sorted(set(syms) - allowed)
        if extra:
            bad.append((rel, extra))
    if not bad:
        return True, [
            "phantom-key guard OK — %d phantom symbol entries, all within baseline; both "
            "fundamentals stores clean" % sum(len(v) for v in found.values())
        ]
    lines.append("phantom-key guard: FAIL — an HTML-escaped symbol appeared where it must not.")
    for rel, extra in bad:
        lines.append(
            "  {}  ({})".format(rel, "must stay at ZERO" if rel in ZERO_TOLERANCE else "not in the recorded baseline")
        )
        for s_ in extra:
            lines.append("      %-18s  real symbol = %s" % (s_, real_symbol(s_)))
    lines.append("  Fix the write path (unescape at the SOURCE), never bless it away. Runbook §114.")
    return False, lines


def main():
    bless = "--bless" in sys.argv
    found, unreadable = scan()

    hard = [(r, e) for r, e in unreadable if r in ZERO_TOLERANCE]
    if hard:
        for r, e in hard:
            print(
                f"phantom-key guard: FAIL — {r} is unreadable ({e}); refusing to report a clean run "
                "over a file it never checked"
            )
        sys.exit(1)
    for r, e in unreadable:
        print(f"phantom-key guard: note — {r} not present, skipped ({e})")

    if bless:
        json.dump({k: v for k, v in found.items() if v}, open(BASELINE, "w"), indent=1, sort_keys=True)
        print(
            "phantom-key guard: baseline blessed — %d file(s), %d symbol entries"
            % (len([v for v in found.values() if v]), sum(len(v) for v in found.values()))
        )
        return

    base = json.load(open(BASELINE)) if os.path.exists(BASELINE) else {}
    new, shrunk, fail = [], [], False
    for rel, syms in sorted(found.items()):
        allowed = set(base.get(rel, []))
        if rel in ZERO_TOLERANCE:
            allowed = set()
        extra = sorted(set(syms) - allowed)
        gone = sorted(allowed - set(syms))
        if extra:
            fail = True
            new.append((rel, extra))
        if gone:
            shrunk.append((rel, gone))

    total = sum(len(v) for v in found.values())
    if fail:
        print("phantom-key guard: FAIL — an HTML-escaped symbol appeared where it must not.\n")
        for rel, extra in new:
            why = (
                "this store was retracted to ZERO on 2026-08-26 and must stay there"
                if rel in ZERO_TOLERANCE
                else "not in the recorded baseline"
            )
            print(f"  {rel}  ({why})")
            for s in extra:
                print("      %-18s  real symbol = %s" % (s, real_symbol(s)))
        print(
            "\nAn `&` was HTML-escaped before the symbol was used as a key. Find the write path,\n"
            "unescape at the SOURCE (html.unescape), and re-run. Do NOT bless this away: a phantom\n"
            "key is a duplicate row the coverage scans read as already-filled, and it renders.\n"
            "See runbook §114 and scripts/retract_phantom_symbols.py."
        )
        sys.exit(1)

    for rel, gone in shrunk:
        print(
            "phantom-key guard: %s lost %d phantom key(s) (%s) — re-bless to tighten the ratchet:"
            "  python3 scripts/phantom_key_guard.py --bless" % (rel, len(gone), ", ".join(gone))
        )
    print(
        "phantom-key guard OK — %d phantom symbol entries, all within baseline; all %d "
        "zero-tolerance stores clean" % (total, len(ZERO_TOLERANCE))
    )


if __name__ == "__main__":
    main()
