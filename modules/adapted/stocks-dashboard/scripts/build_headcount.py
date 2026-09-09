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
"""Aggregate per-symbol headcount ledgers (scripts/headcount/<SYM>.json) into the slim payload the
employees.html dashboard reads: docs/employee_headcount.json.

Survivorship-free universe = union of Nifty-500 members across every _wb_n500_snaps.json snapshot
dated >= 2020-01-01 (current members + names that have since left). Each row is flagged `now`
(in the latest snapshot) so the page can show "In N500" vs "Left N500" without hiding anyone.

Headline series = permanent on-roll employees (emp_perm + wrk_perm); `total` = total workforce incl
contractual. Every FY value keeps a source tag (filing FY, page, method) for provenance.
"""
import json
import os
import re
import statistics
from datetime import date, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DOCS = os.path.abspath(os.path.join(HERE, "..", "docs"))
LEDGERS = os.path.join(HERE, "headcount")
SNAPS = os.path.join(HERE, "_wb_n500_snaps.json")
MASTER = os.path.join(HERE, "_bse_master_all.json")
SECTORS = os.path.join(HERE, "_bse_sectors.json")
RENAME = os.path.join(HERE, "_rename_map.json")
START_FY = 2020


def _max_ratio(series):
    """Largest ratio between consecutive-FY values (>=1). 1.0 for <2 points."""
    ys = sorted(series, key=int)
    v = [series[y] for y in ys]
    return max((max(v[i], v[i - 1]) / min(v[i], v[i - 1]) for i in range(1, len(v)) if v[i - 1] and v[i]), default=1.0)


CLIFF = 1.8  # a >1.8x step between consecutive FYs marks a basis flip worth resolving
CLUSTER = 1.6  # once flagged, group same-basis years within this ratio (tighter, to isolate outliers)


def implausible_years(emp):
    """FYs to DROP because the series mixes reporting bases across years (a company that files a
    standalone BRSR one year and a consolidated one the next — Apollo 82,786↔42,497, Biocon
    9,805↔4,204). Signature = a NON-monotonic series with a >1.8x cliff (a real hiring/attrition trend
    is monotonic and survives untouched: BLS 357→737→1,747, BEL 11,444→11,199→9,420). When a basis
    flip is detected we keep the largest same-basis cluster, tie-broken toward the most recent year
    (the current basis), and drop the rest. <3 points: can't judge, keep all."""
    ys = sorted(emp, key=int)
    if len(ys) < 3:
        return set()
    v = [emp[y] for y in ys]
    monotonic = all(v[i] >= v[i - 1] for i in range(1, len(v))) or all(v[i] <= v[i - 1] for i in range(1, len(v)))
    has_cliff = any(max(v[i], v[i - 1]) / min(v[i], v[i - 1]) > CLIFF for i in range(1, len(v)) if v[i - 1])
    if monotonic or not has_cliff:
        return set()
    best = None
    for anchor in v:
        grp = [y for y in ys if anchor and 1 / CLUSTER <= emp[y] / anchor <= CLUSTER]
        key = (len(grp), max(int(y) for y in grp))  # most years, then most recent
        if best is None or key > best[0]:
            best = (key, set(grp))
    return set(ys) - best[1]


def fy_of(iso):
    d = datetime.strptime(iso[:10], "%Y-%m-%d").date()
    return d.year + 1 if d.month >= 4 else d.year  # Apr-Mar → FY-end year


def load_membership():
    snaps = json.load(open(SNAPS))
    dates = sorted(snaps)
    d2020 = [d for d in dates if d >= "2020-01-01"]
    latest = set(snaps[dates[-1]])
    per = {}  # sym -> {"snaps":[dates], "now":bool}
    for d in d2020:
        for s in snaps[d]:
            per.setdefault(s, {"snaps": [], "now": False})
            per[s]["snaps"].append(d)
    for s in per:
        per[s]["now"] = s in latest
    return per, dates[-1]


def load_names():
    name, sector = {}, {}
    master = json.load(open(MASTER))
    secmap = json.load(open(SECTORS))  # {bse_code(str): sector}
    for x in master:
        sid = x.get("scrip_id")
        if not sid:
            continue
        name[sid] = re.sub(r"\s+(Ltd|Limited)\.?$", "", (x.get("Scrip_Name") or "").strip())
        cd = str(x.get("SCRIP_CD") or "")
        if cd in secmap:
            sector[sid] = secmap[cd]
    return name, sector


def main():
    per, latest_date = load_membership()
    name, sector = load_names()
    fys = list(range(START_FY, date.today().year + 1))
    # Rename-orphans: an old ticker in an early snapshot and its current ticker in a later one are the
    # SAME company (CADILAHC→ZYDUSLIFE, ADANIGAS→ATGL…). Fold the old name into the current row (carry
    # its membership, list it as an alias) rather than listing one company twice. An old name whose
    # current ticker sits outside the universe keeps its own row but reads the current ticker's ledger.
    rmap = json.load(open(RENAME)) if os.path.exists(RENAME) else {}
    fold, aliases, ledger_of = set(), {}, {}
    for sym in list(per):
        if sym.startswith("DUMMY") or os.path.exists(os.path.join(LEDGERS, sym + ".json")):
            continue
        tgt = rmap.get(sym)
        if not tgt or tgt == sym:
            continue
        if tgt in per:
            fold.add(sym)
            aliases.setdefault(tgt, []).append(sym)
            per[tgt]["now"] = per[tgt]["now"] or per[sym]["now"]
            per[tgt]["snaps"] = sorted(set(per[tgt]["snaps"]) | set(per[sym]["snaps"]))
        elif os.path.exists(os.path.join(LEDGERS, tgt + ".json")):
            ledger_of[sym] = tgt
    rows, covered = [], 0
    for sym in sorted(per):
        if sym.startswith("DUMMY") or sym in fold:
            continue
        led_path = os.path.join(LEDGERS, ledger_of.get(sym, sym) + ".json")
        emp, total, mf, src = {}, {}, {}, {}
        onroll, etot = {}, {}
        if os.path.exists(led_path):
            led = json.load(open(led_path))
            for y, c in led.get("fy", {}).items():
                yi = int(y)
                if yi < START_FY or not isinstance(c.get("count"), int):
                    continue
                b = c.get("brsr") or {}
                onroll[yi] = c["count"]  # perm employees + perm workers
                etot[yi] = b["emp_total"] if isinstance(b.get("emp_total"), int) else c["count"]  # BRSR D+E
                if isinstance(c.get("total_workforce"), int):
                    total[yi] = c["total_workforce"]
                if isinstance(b.get("male"), int) and isinstance(b.get("female"), int):
                    mf[yi] = [b["male"], b["female"]]
                s = c.get("src", {})
                src[yi] = "{} p{}".format(s.get("method", "?"), s.get("page", "?"))
            # Basis per company: on-roll by default (matches companies' own "Number of Employees"),
            # BUT on-roll silently switches to total-employees whenever the "Permanent"/workers row
            # fails to parse in a year, faking a cliff (Whirlpool, TMPV, NMDC…). When that makes the
            # on-roll series jumpy AND total-employees (the summary row) is smoother, use total-employees
            # — a single consistent basis for that company. Clean series (INFY, Asian Paints, Bharti,
            # banks) keep on-roll untouched.
            emp = etot if (_max_ratio(onroll) > 1.8 and _max_ratio(etot) < _max_ratio(onroll)) else onroll
        for y in implausible_years(emp):  # drop spikes rather than ship a wrong headcount
            emp.pop(y, None)
            total.pop(y, None)
            mf.pop(y, None)
            src.pop(y, None)
        for y in list(total):  # total workforce can never be below on-roll; when the
            if y in emp and total[y] < emp[y]:  # workers subtotal didn't parse, floor it at on-roll
                total[y] = emp[y]
        if emp:
            covered += 1
        yrs = sorted(emp)
        latest_fy = yrs[-1] if yrs else None
        prev_fy = yrs[-2] if len(yrs) >= 2 else None
        yoy = None
        if latest_fy and prev_fy and emp[prev_fy]:
            yoy = round((emp[latest_fy] - emp[prev_fy]) / emp[prev_fy], 4)
        rows.append(
            {
                "sym": sym,
                "name": name.get(sym, sym),
                "sector": sector.get(sym, ""),
                "aliases": aliases.get(sym, []),
                "alias_of": ledger_of.get(sym),
                "now": per[sym]["now"],
                "emp": emp,
                "total": total,
                "mf": mf,
                "src": src,
                "latest": emp.get(latest_fy),
                "latest_fy": latest_fy,
                "yoy": yoy,
            }
        )
    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M IST"),
        "basis": "Employee headcount — permanent on-roll employees (permanent employees + permanent "
        "workers), or total reported employees where that gives a consistent year-on-year series. "
        "Source: company annual reports on BSE (BRSR 'Employees and workers' table). "
        "'Total workforce' additionally includes contractual/other.",
        "note": "India does not report employee count quarterly — this is annual (fiscal year ending March).",
        "fys": fys,
        "universe": len(rows),
        "covered": covered,
        "as_of_snapshot": latest_date,
        "rows": rows,
    }
    os.makedirs(DOCS, exist_ok=True)
    out = os.path.join(DOCS, "employee_headcount.json")
    json.dump(payload, open(out, "w"), separators=(",", ":"), default=str)
    print(
        "wrote %s : %d symbols, %d covered (%.0f%%), FYs %s"
        % (out, len(rows), covered, 100 * covered / max(len(rows), 1), fys)
    )


if __name__ == "__main__":
    main()
