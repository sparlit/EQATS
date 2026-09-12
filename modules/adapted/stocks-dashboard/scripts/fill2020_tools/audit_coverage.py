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


"""FILL-2020 scoreboard: empty rev/PAT cells for the point-in-time Nifty 500, std vs consolidated.

Survivorship-free: membership is read per quarter-end from the nearest-prior snapshot in
scripts/indices_history.json (the exact json build_compressed.py embeds into stock_data.bin), so a
company counts only while it actually WAS a member, and delisted/merged constituents still count for
the quarters they were in.

Run from the repo root:   python -X utf8 scripts/fill2020_tools/audit_coverage.py [--json OUT]

WARNING: run it against a checkout synced to origin/main (`git fetch origin && git reset --hard
origin/main` in a throwaway worktree). The shared checkout drifts and other sessions leave these
files dirty -- measuring the local copy is how the first pass of this audit got wrong numbers.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WINDOW_START = 20191231  # campaign scope: "2020 -> date"
BASELINE = {"revS": 222, "revC": 1502, "patS": 6, "patC": 19}  # measured 2026-08-05, pre-campaign
LAST_DAY = {3: 31, 6: 30, 9: 30, 12: 31}


def load(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


idx_hist = load("scripts/indices_history.json")
rename_map = load("scripts/_rename_map.json")
snaps = sorted(idx_hist["Nifty 500"], key=lambda s: s["effectiveDate"])

fund = {
    s: {int(r[0]): (r[1], r[3]) for r in rows if len(r) > 3} for s, rows in load("docs/sf_fundamentals.json").items()
}
revop = {s: {int(q): (v[0], v[1]) for q, v in d.items()} for s, d in load("docs/sf_revop.json").items()}


def resolve(sym, target):
    """Chase the rename chain until the symbol is a key of `target` (old ticker -> current)."""
    cur, seen = sym, set()
    while cur not in target:
        if cur in seen or cur not in rename_map:
            return None
        seen.add(cur)
        cur = rename_map[cur]
    return cur


def members_at(qe):
    ds = "%04d-%02d-%02d" % (qe // 10000, (qe // 100) % 100, qe % 100)
    best = None
    for s in snaps:
        if s["effectiveDate"] <= ds:
            best = s
        else:
            break
    # DUMMY* are placeholder slots the index build inserts, not companies
    return [x for x in best["symbols"] if not x.upper().startswith("DUMMY")]


def quarter_ends(first=20150331, last=20260630):
    out = []
    for y in range(first // 10000, last // 10000 + 1):
        for m in (3, 6, 9, 12):
            qe = y * 10000 + m * 100 + LAST_DAY[m]
            if first <= qe <= last:
                out.append(qe)
    return out


# ── IS THERE A CONSOLIDATED RECORD FOR THIS COMPANY AT THIS QUARTER? ──────────────────────────
# USER RULE 2026-08-06, stated as a ROLLING window: "if u r checking mar 24 cons data and from
# there backwards, if there is no cons record for straight 4 quarters then [exclude] them from
# coverage". So the test is applied AS OF each quarter, not once for all time -- which also handles
# a company that pauses consolidated reporting and later resumes.
#
# "A consolidated record" = a quarter where stored con genuinely DIVERGES from std. That is the only
# signal that separates a real consolidated filing from standalone copied into the con slot (the
# is_con_basis bug, runbook §56) or from a no-subsidiary identity. A company with no divergence in
# the trailing 4 quarters is not filing consolidated, so its con cells are NOT gaps.
#
# The explicit ledger stays as a user-verified override (screener.in checks: SBFC/UCOBANK/JYOTHYLAB
# last filed Mar-2025, CERA Jun-2025, FACT Dec-2025, ALKYLAMINE Mar-2020, CUB/ENRIN/ALIVUS never).
try:
    _nc = load("scripts/no_con_filing.json")
    NO_CON = _nc.get("stopped_filing_con", {})
    STARTED_CON = _nc.get("started_filing_con", {})  # con cells BEFORE this quarter are n/a
    NEVER_CON = set(_nc.get("never_filed_con", []))
    CEASED = _nc.get("ceased_filing", {})  # entity gone: NO metric is a gap from this quarter
except Exception:
    NO_CON, STARTED_CON, NEVER_CON, CEASED = {}, {}, set(), {}


def ceased(sym, qe):
    """True when the company had stopped filing ANY results by this quarter (merger, dissolution,
    or a formal non-submission notice). Nothing about that quarter is a data gap -- there is no
    company left to report. Verified per entity across BSE announcements, BSE detailed-results and
    the NSE archive (runbook §51c / §52c)."""
    st = CEASED.get(sym)
    return bool(st and qe >= st)


_raw_fund = load("docs/sf_fundamentals.json")
DIVQ = {}  # sym -> sorted quarters where con genuinely differs from std
for _s, _rows in _raw_fund.items():
    _d = []
    for _r in _rows:
        if len(_r) > 3 and _r[1] is not None and _r[3] is not None:
            if abs(_r[3] - _r[1]) > max(0.05, abs(_r[1]) * 0.001):
                _d.append(_r[0])
    if _d:
        DIVQ[_s] = sorted(_d)


def _back4(qe):
    """qe and the three quarters before it."""
    y, m = qe // 10000, (qe // 100) % 100
    i = y * 4 + {3: 0, 6: 1, 9: 2, 12: 3}[m]
    out = []
    for k in range(4):
        yy, r = divmod(i - k, 4)
        mm = [3, 6, 9, 12][r]
        out.append(yy * 10000 + mm * 100 + LAST_DAY[mm])
    return out


try:
    EV = load("scripts/con_filer_evidence.json")
except Exception:
    EV = {}


def files_con(sym, qe):
    """False when there is no consolidated record for this company at this quarter.

    The trailing-4-quarter divergence test this replaces was CIRCULAR: divergence was read from our
    own stored con PAT, so a company whose con data was merely MISSING generated no signal and was
    recorded as "does not file consolidated". Verified against screener on 158 company/FY pairs it
    had excluded -- 63% WRONG, including ONGC, ITC, HDFCBANK, NTPC, IOC, HINDALCO and M&M. Two
    further sources agreed: our own history showed divergent con PAT in other quarters for 96 of 99,
    and NSE's filing index listed consolidated filings for 11 of 12 sampled.

    Now decided by POSITIVE evidence (build_con_filer_evidence.py). The user-verified ledger still
    wins where it applies."""
    if sym in NEVER_CON:
        return False
    start = NO_CON.get(sym)
    if start and qe >= start:
        return False
    # Symmetric counterpart: quarters BEFORE a company began consolidating are n/a, not gaps
    # (IOB std-only until Mar-2022, runbook §51c). Positive evidence only.
    began = STARTED_CON.get(sym)
    if began and qe < began:
        return False
    ev = EV.get(sym)
    if ev is not None:
        if not ev.get("files_con"):
            return False
        fy = ev.get("first_con_fy")
        if fy and qe < (fy - 1) * 10000 + 401:
            return False  # before our earliest evidence we do not know; claim nothing
        return True
    win = set(_back4(qe))
    return any(q in win for q in DIVQ.get(sym, ()))


rows = []
for qe in quarter_ends():
    mem = members_at(qe)
    c = {"rev_std": 0, "rev_con": 0, "pat_std": 0, "pat_con": 0}
    na = {"pat_con": 0, "rev_con": 0}  # not-applicable: company does not file consolidated
    for sym in mem:
        fk = resolve(sym, fund)
        if ceased(fk or sym, qe) or ceased(sym, qe):
            na["pat_con"] += 1  # counted as not-applicable, never as a gap
            na["rev_con"] += 1
            continue
        std, con = fund[fk].get(qe, (None, None)) if fk else (None, None)
        if std is None:
            c["pat_std"] += 1
        if con is None:
            if files_con(fk or sym, qe):
                c["pat_con"] += 1
            else:
                na["pat_con"] += 1
        rk = resolve(sym, revop)
        rs, rc = revop[rk].get(qe, (None, None)) if rk else (None, None)
        if rs is None:
            c["rev_std"] += 1
        if rc is None:
            if files_con(rk or sym, qe):
                c["rev_con"] += 1
            else:
                na["rev_con"] += 1
    rows.append(
        {
            "qe": qe,
            "members": len(mem),
            **{k + "_empty": v for k, v in c.items()},
            **{k + "_na": v for k, v in na.items()},
        }
    )

tot = {"revS": 0, "revC": 0, "patS": 0, "patC": 0}
for r in rows:
    if WINDOW_START <= r["qe"] <= 20260331:  # Jun-2026 excluded: still filing season
        tot["revS"] += r["rev_std_empty"]
        tot["revC"] += r["rev_con_empty"]
        tot["patS"] += r["pat_std_empty"]
        tot["patC"] += r["pat_con_empty"]

print("quarter    members |  rev std  rev con |  pat std  pat con")
for r in rows:
    print(
        "%8d %8d | %8d %8d | %8d %8d"
        % (r["qe"], r["members"], r["rev_std_empty"], r["rev_con_empty"], r["pat_std_empty"], r["pat_con_empty"])
    )

start, now = sum(BASELINE.values()), sum(tot.values())
print("\nCAMPAIGN WINDOW %d..20260331 (Jun-2026 excluded, still filing)" % WINDOW_START)
print("%-7s %7s %7s %7s" % ("field", "start", "now", "closed"))
for k in ("revS", "revC", "patS", "patC"):
    print("%-7s %7d %7d %7d" % (k, BASELINE[k], tot[k], BASELINE[k] - tot[k]))
print("%-7s %7d %7d %7d  (%.0f%% closed)" % ("TOTAL", start, now, start - now, 100.0 * (start - now) / start))
na_p = sum(r["pat_con_na"] for r in rows if WINDOW_START <= r["qe"] <= 20260331)
na_r = sum(r["rev_con_na"] for r in rows if WINDOW_START <= r["qe"] <= 20260331)
if na_p or na_r:
    print("\nNOT APPLICABLE (company stopped filing consolidated - nothing to fill):  patC %d, revC %d" % (na_p, na_r))
    print("  These are excluded from the gap counts above. Ledger: scripts/no_con_filing.json")

if "--json" in sys.argv:
    out = sys.argv[sys.argv.index("--json") + 1]
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"rows": rows, "window_totals": tot, "baseline": BASELINE}, f, indent=1)
    print("wrote", out)
