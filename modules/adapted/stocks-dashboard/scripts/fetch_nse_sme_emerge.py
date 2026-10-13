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
"""Nifty SME Emerge — official daily level, today's official member list, new NSE Indices press releases
(runbook §210; the NSE twin of fetch_bse_sme_ipo.py, §195).

WHAT (all measured 2026-09-28)
  level    nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv — NSE's all-indices close file, one per
           session; the "NIFTY SME EMERGE" row carries close, P/E, P/B, dividend yield (open/high/low/volume print
           "-"). First row 20-Nov-2017 (the launch; base 01-Dec-2016 = 1000). The date INSIDE the row must equal the
           file's day (NSE re-serves a stale file on holidays, §89f) — otherwise the day is skipped.
  members  www.niftyindices.com/IndexConstituent/ind_niftysmelist.csv (fallback nsearchives …/content/indices/)
           → Company Name, Industry, Symbol, Series, ISIN Code. Only the CURRENT list is served, undated — stamped
           with the capture day.
  releases www.niftyindices.com/Press_Release/ind_prsDDMMYYYY[_1.._4].pdf (fallback nsearchives …/content/indices/ —
           it serves ind_prs29052026.pdf, which niftyindices 404s). Every weekday of the last 30 days is probed once;
           a release whose text names the index is parsed (nse_sme_emerge_prs) into scripts/nse_sme_emerge_events.json.

OUTPUT
  docs/nifty_sme_emerge.json                {updated, source, px:{date: close}, pe:{}, pb:{}, dy:{}}
  docs/nse_sme_emerge/members.json          {asof, source, members:[{sym, name, industry, series, isin}]}
  docs/nse_sme_emerge/changes.json          {events:[{date, action, sym, name, isin}]} — differences between OUR captures
  docs/nse_sme_emerge/snapshots/<date>.json the raw list as captured

  python3 scripts/fetch_nse_sme_emerge.py                 (level from the last stored day + members + releases)
  python3 scripts/fetch_nse_sme_emerge.py level --full    (whole level history 2017-11-20 →; ~2,200 files, cached)
"""
import csv
import datetime
import hashlib
import io
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import contextlib

import nse_sme_emerge_prs as N

ROOT = os.path.dirname(HERE)
OUT_LEVEL = os.path.join(ROOT, "docs", "nifty_sme_emerge.json")
DIR = os.path.join(ROOT, "docs", "nse_sme_emerge")
LEDGER = os.path.join(HERE, "nse_sme_emerge_events.json")
LAUNCH = datetime.date(2017, 11, 20)
UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120 Safari/537.36",
    "Accept": "*/*",
}
ARCH = "https://nsearchives.nseindia.com/content/indices/"
NI = "https://www.niftyindices.com/"
CACHE = os.path.expanduser(os.environ.get("NSE_INDCLOSE_CACHE", "~/stocks-cache/nse_ind_close"))


def get(url, tries=3, timeout=45):
    """bytes, or None on a definite miss (404 / an HTML error page where a file was asked for)"""
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout
            ) as r:
                b = r.read()
            if b[:15].lstrip().lower().startswith((b"<!doctype", b"<html")):
                return None  # niftyindices answers a missing file with a 200 HTML page
            return b
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except (
            Exception
        ) as e:  # read timeouts are not URLErrors (memory: URLError misses read timeout)
            last = e
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"GET {url} failed: {last!r}")


def load(p, d=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return d


def dump(p, o, compact=False):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p + ".tmp", "w", encoding="utf-8") as f:
        if compact:
            json.dump(o, f, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
        else:
            json.dump(o, f, indent=1, ensure_ascii=False)
    os.replace(p + ".tmp", p)


def ist_today():
    return (datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=5, minutes=30)).date()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


_MISS = None


def _misses():
    global _MISS
    if _MISS is None:
        p = os.path.join(CACHE, "_miss.txt")
        _MISS = set(open(p).read().split()) if os.path.exists(p) else set()
    return _MISS


def level_row(day):
    """(close, pe, pb, dy) for `day` from NSE's all-indices file, None when there is no session / no row."""
    s = day.strftime("%d%m%Y")
    fn = os.path.join(CACHE, f"ind_close_all_{s}.csv")
    b = None
    if os.path.exists(fn):
        b = open(fn, "rb").read()
    elif s in _misses():  # a day NSE has no file for (holiday / weekend), remembered once old
        return None
    else:
        b = get(ARCH + f"ind_close_all_{s}.csv")
        os.makedirs(CACHE, exist_ok=True)
        if b is not None:
            open(fn, "wb").write(b)
        elif (ist_today() - day).days > 10:
            with open(os.path.join(CACHE, "_miss.txt"), "a") as f:
                f.write(s + "\n")
            _MISS.add(s)
        time.sleep(0.35)
    if not b:
        return None
    for r in csv.reader(io.StringIO(b.decode("utf-8", "replace"))):
        if r and r[0].strip().upper() == "NIFTY SME EMERGE":
            inside = set()  # three Apr-2023 files print MM-DD-YYYY (04-06-2023 = 6 Apr)
            for fmt in ("%d-%m-%Y", "%m-%d-%Y", "%d-%b-%Y"):
                with contextlib.suppress(ValueError):
                    inside.add(datetime.datetime.strptime(r[1].strip(), fmt).date())
            if day not in inside:  # a re-served file (holiday) — the day has no session
                return None
            c = _f(r[5])
            return (c, _f(r[10]), _f(r[11]), _f(r[12])) if c and c > 0 else None
    return None


def fetch_level(full=False):
    cur = load(OUT_LEVEL, {}) or {}
    px, pe, pb, dy = (dict(cur.get(k) or {}) for k in ("px", "pe", "pb", "dy"))
    today = ist_today()
    d = (
        LAUNCH
        if (full or not px)
        else datetime.date.fromisoformat(max(px)) - datetime.timedelta(days=7)
    )
    got = 0
    while d <= today:
        row = level_row(d)  # every calendar day: NSE holds weekend special sessions (Budget days)
        if row:
            k = d.isoformat()
            px[k] = round(row[0], 2)
            for dst, v in ((pe, row[1]), (pb, row[2]), (dy, row[3])):
                if v is not None:
                    dst[k] = v
            got += 1
        d += datetime.timedelta(days=1)
    if len(px) < 2000:  # 20-Nov-2017 → today ≈ 2,200 sessions
        raise SystemExit("level history too short (%d) — refusing to write" % len(px))
    dump(
        OUT_LEVEL,
        {
            "updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "source": "NSE ind_close_all_DDMMYYYY.csv row NIFTY SME EMERGE (launch 20-Nov-2017; base 01-Dec-2016 = 1000)",
            "px": dict(sorted(px.items())),
            "pe": dict(sorted(pe.items())),
            "pb": dict(sorted(pb.items())),
            "dy": dict(sorted(dy.items())),
        },
        compact=True,
    )
    print(
        "level: %d session(s) read, %d stored, last %s = %s" % (got, len(px), max(px), px[max(px)])
    )


def fetch_members():
    b = get(NI + "IndexConstituent/ind_niftysmelist.csv") or get(ARCH + "ind_niftysmelist.csv")
    if not b:
        raise SystemExit("constituent list unavailable on both hosts")
    rows = list(csv.DictReader(io.StringIO(b.decode("utf-8-sig", "replace"))))
    if len(rows) < 20 or "Symbol" not in rows[0]:  # methodology floor: at least 20 constituents
        raise SystemExit(
            "constituent list has %d rows / header %s — refusing"
            % (len(rows), list(rows[0]) if rows else [])
        )
    asof = (
        ist_today().isoformat()
    )  # the capture day in IST — a CI runner's clock is UTC (20:08 UTC = 01:38 IST next day)
    mem = sorted(
        (
            {
                "sym": r["Symbol"].strip(),
                "name": r["Company Name"].strip(),
                "industry": r["Industry"].strip(),
                "series": r["Series"].strip(),
                "isin": r["ISIN Code"].strip(),
            }
            for r in rows
        ),
        key=lambda m: m["sym"],
    )
    prev = load(os.path.join(DIR, "members.json"))
    chg = load(os.path.join(DIR, "changes.json"), {"events": []})
    if prev and prev["asof"] > asof:
        asof = prev["asof"]  # never move the capture date backwards (the old UTC stamps)
    if prev and prev["asof"] <= asof:
        old = {m["sym"]: m for m in prev["members"]}
        new = {m["sym"]: m for m in mem}
        ev = [
            {
                "date": asof,
                "action": "add",
                "sym": s,
                "name": new[s]["name"],
                "isin": new[s]["isin"],
            }
            for s in sorted(set(new) - set(old))
        ]
        ev += [
            {
                "date": asof,
                "action": "remove",
                "sym": s,
                "name": old[s]["name"],
                "isin": old[s]["isin"],
            }
            for s in sorted(set(old) - set(new))
        ]
        if ev:
            chg["events"] += ev
            dump(os.path.join(DIR, "snapshots", asof + ".json"), {"asof": asof, "rows": rows})
        print(
            "members: %s -> %s  +%d / -%d"
            % (
                prev["asof"],
                asof,
                sum(e["action"] == "add" for e in ev),
                sum(e["action"] == "remove" for e in ev),
            )
        )
    else:
        dump(os.path.join(DIR, "snapshots", asof + ".json"), {"asof": asof, "rows": rows})
    dump(os.path.join(DIR, "changes.json"), chg)
    dump(
        os.path.join(DIR, "members.json"),
        {
            "asof": asof,
            "source": "niftyindices.com ind_niftysmelist.csv",
            "updated": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "members": mem,
        },
    )
    print("members: %d as of %s" % (len(mem), asof))


RENAMES = os.path.join(HERE, "nse_sme_emerge_renames.json")


def fetch_renames():
    """NSE's symbolchange.csv (company, old, new, DD-MON-YYYY) merged into the renames ledger — rows are only added."""
    b = get("https://nsearchives.nseindia.com/content/equities/symbolchange.csv")
    if not b:
        print("::warning::symbolchange.csv unavailable — renames ledger unchanged")
        return
    R = load(RENAMES, {"renames": []})
    have = {(r[0], r[1], r[2]) for r in R["renames"]}
    add = 0
    for r in csv.reader(io.StringIO(b.decode("utf-8", "replace"))):
        if len(r) < 4:
            continue
        try:
            d = datetime.datetime.strptime(r[3].strip(), "%d-%b-%Y").date().isoformat()
        except ValueError:
            continue
        k = (r[1].strip(), r[2].strip(), d)
        if k[0] and k[1] and k not in have:
            R["renames"].append([k[0], k[1], d, "NSE symbolchange.csv"])
            have.add(k)
            add += 1
    R["renames"].sort(key=lambda x: (x[2], x[0]))
    dump(RENAMES, R)
    print("renames: +%d (%d total)" % (add, len(R["renames"])))


def pdf_text(b):
    from pypdf import PdfReader

    return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(b)).pages)


def fetch_releases(days=30):
    L = load(LEDGER, {}) or {}
    rel = L.setdefault("releases", {})
    probed = set(L.get("probed", []))
    today = ist_today()
    new = 0
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        if d.weekday() >= 5:
            continue
        for suf in ("", "_1", "_2", "_3", "_4"):
            stem = "ind_prs{}{}".format(d.strftime("%d%m%Y"), suf)
            if stem in rel or stem in probed:
                continue
            b = get(NI + f"Press_Release/{stem}.pdf", tries=2) or get(ARCH + f"{stem}.pdf", tries=2)
            time.sleep(0.4)
            if not b or not b.startswith(b"%PDF"):
                if i > 3:  # a miss this recent may still be uploaded — re-probe for 3 days
                    probed.add(stem)
                continue
            try:
                t = pdf_text(b)
            except Exception as e:
                print(f"release {stem}: unreadable PDF ({e!r}) — left for the next run")
                continue
            r = N.parse_text(t)
            if not r.get("sme"):
                probed.add(stem)
                continue
            r.pop("sme")
            r["sha1"] = hashlib.sha1(b).hexdigest()
            if len(t.strip()) < 200:
                L.setdefault("unread", []).append(
                    {"stem": stem, "why": "image-only PDF (no text layer)"}
                )
                print(
                    f"::warning::release {stem} names Nifty SME Emerge but has no text layer — needs a read"
                )
                continue
            if not (r["ex"] or r["inc"] or r["revoke"]):
                print(
                    f"::warning::release {stem} names Nifty SME Emerge but no table was read — check it (adjust entry?)"
                )
            rel[stem] = r
            new += 1
            print(
                "release %s: eff %s, -%d +%d, revoke %s"
                % (stem, r["eff"], len(r["ex"]), len(r["inc"]), r["revoke"])
            )
    L["probed"] = sorted(probed)
    dump(LEDGER, L)
    print("releases: %d new" % new)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] == "level":
        fetch_level(full="--full" in a)
    if not a or a[0] == "members":
        fetch_members()
    if not a or a[0] == "releases":
        fetch_renames()
        fetch_releases()
