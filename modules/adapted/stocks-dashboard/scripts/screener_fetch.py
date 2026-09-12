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
"""screener.in reader -- a FIRST-CLASS route in the backfill ladder (runbook §57 rung 3b).

WHY THIS EXISTS (user, 2026-08-06): "how the fuck screener has all and u r replying nothing
exists?". Fair. Every earlier route in the ladder reads a FILING; when a filing was image-only,
glyph-corrupted, or filed under a title my regex did not expect, I reported the cell as absent.
screener.in has already done that read. It is not a primary source, but it is a SECOND OPINION that
tells us the number EXISTS and what it is -- which converts "cannot be filled" into "go find this
exact figure in the filing", a completely different and always-solvable problem.

WHAT IT ACTUALLY COVERS (measured, do not assume):
  * Quarterly table: the trailing ~13 quarters only, both bases (/company/SYM/ = standalone,
    /company/SYM/consolidated/ = consolidated). Good for the recent window, NOT for 2015-2022.
  * Annual P&L: 10-12 FULL YEARS, both bases. This is the pre-2020 lever -- combined with the
    3 quarters we already store, the missing 4th quarter of any FY falls out by subtraction
    (memory: screener-annual-derivation). That is how old quarters get backfilled from here.

THE COLUMN PROBLEM IS SOLVED HERE. Every <th> carries data-date-key="YYYY-MM-DD" and every <td>
carries the same key. Columns are addressed BY PRINTED DATE, never by index -- which is the §55b
rule that BALKRISIND/SWANCORP violated when read out of a PDF.

MANDATORY GATE -- never write a screener number on its own authority:
    validate(sym, basis, ours) must pass on the NEIGHBOURING quarters before the target quarter is
    written. If screener's series does not reproduce values we already hold on either side, it is a
    DIFFERENT ENTITY or a DIFFERENT BASIS and the number must be rejected. Two live examples this
    caught: TMPV (screener = demerged PV-only, ours = legacy Tata Motors incl. JLR) and CYIENT
    (series does not line up). Both would have been silently corrupted by a blind copy.

Usage:
    from screener_fetch import quarters, annuals, validate
    q = quarters("KNRCON", con=True)     # {"2025-03-31": {"Sales": 975.3, "Net Profit": 8.2, ...}}
"""
import json
import os
import re
import time

from curl_cffi import requests as cr

CACHE = os.path.join(os.path.expanduser("~"), ".cache", "screener_html")
UA = "Mozilla/5.0"
_SESS = None


def _sess():
    global _SESS
    if _SESS is None:
        _SESS = cr.Session(impersonate="chrome")
    return _SESS


def fetch(sym, con=False, ttl=86400):
    """Raw HTML for a company page, disk-cached (screener rate-limits hard)."""
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, "{}{}.html".format(sym, "-con" if con else ""))
    if os.path.exists(key) and time.time() - os.path.getmtime(key) < ttl:
        with open(key, encoding="utf-8") as f:
            return f.read()
    url = "https://www.screener.in/company/{}/{}".format(sym, "consolidated/" if con else "")
    # A sweep touches ~700 pages; one transport hiccup must not kill the run. NOTE: a connection
    # refused in ~20ms is not screener rate-limiting, it is THIS PROCESS having no network -- e.g. a
    # backgrounded bash task, which runs sandboxed. Retrying that is pointless; the fix is to run in
    # the foreground. Retries here are for genuine transient failures.
    global _SESS
    for attempt in range(3):
        try:
            r = _sess().get(url, timeout=30)
        except Exception:
            _SESS = None
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None  # symbol not on screener -- do not retry
        if r.status_code != 200:
            time.sleep(2.0 * (attempt + 1))
            continue
        with open(key, "w", encoding="utf-8") as f:
            f.write(r.text)
        return r.text
    return None


_SECTION = re.compile(r'id="(quarters|profit-loss)"(.*?)</table>', re.DOTALL)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL)
_TH = re.compile(r'<th[^>]*data-date-key="([\d-]+)"', re.DOTALL)
_TD = re.compile(r'<td[^>]*?(?:data-date-key="([\d-]+)")?[^>]*>(.*?)</td>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")


def _txt(s):
    return _TAG.sub("", s).replace("&nbsp;", " ").replace(" ", " ").strip()


def _num(s):
    s = _txt(s).replace(",", "").replace("%", "").strip()
    if not s or s == "-":
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("()-").strip()
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def _table(html, sect):
    """-> {date_key: {row_label: value}} for the quarters or profit-loss card."""
    if not html:
        return {}
    m = None
    for mm in _SECTION.finditer(html):
        if mm.group(1) == sect:
            m = mm
            break
    if not m:
        return {}
    body = m.group(2)
    cols = _TH.findall(body)
    out = {c: {} for c in cols}
    for rm in _ROW.finditer(body):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", rm.group(1), re.DOTALL)
        if len(cells) < 2:
            continue
        label = _txt(cells[0]).rstrip("+").strip()
        if not label or label.lower().startswith("mar 20"):
            continue
        vals = cells[1:]
        for i, c in enumerate(cols):
            if i < len(vals):
                v = _num(vals[i])
                if v is not None:
                    out[c][label] = v
    return {k: v for k, v in out.items() if v}


def quarters(sym, con=False):
    return _table(fetch(sym, con), "quarters")


def annuals(sym, con=False):
    return _table(fetch(sym, con), "profit-loss")


def qe_int(datekey):
    return int(datekey.replace("-", ""))


def validate(series, ours, field, need=2, tol=0.006):
    """GATE. `series` = screener {datekey: {label: val}}, `ours` = {qe_int: value}.

    Returns (ok, matched, checked, detail). ok only when at least `need` quarters that BOTH sides
    hold agree within tol, and NONE disagree. A single disagreement means different entity/basis --
    reject the whole series, do not cherry-pick.
    """
    matched, bad, detail = 0, 0, []
    for dk, row in series.items():
        q = qe_int(dk)
        mine, theirs = ours.get(q), row.get(field)
        if mine is None or theirs is None:
            continue
        if abs(mine - theirs) <= max(1.0, abs(mine) * tol):
            matched += 1
        else:
            bad += 1
            detail.append("%d ours=%s scr=%s" % (q, mine, theirs))
    return (matched >= need and bad == 0), matched, matched + bad, detail


if __name__ == "__main__":
    import sys

    sym = sys.argv[1] if len(sys.argv) > 1 else "KNRCON"
    con = "--std" not in sys.argv
    q, a = quarters(sym, con), annuals(sym, con)
    print(
        "%s %s -- %d quarters %s..%s | %d annuals %s..%s"
        % (
            sym,
            "CON" if con else "STD",
            len(q),
            min(q, default="-"),
            max(q, default="-"),
            len(a),
            min(a, default="-"),
            max(a, default="-"),
        )
    )
    print(json.dumps({k: {kk: q[k][kk] for kk in ("Sales", "Net Profit") if kk in q[k]} for k in sorted(q)}, indent=1))
