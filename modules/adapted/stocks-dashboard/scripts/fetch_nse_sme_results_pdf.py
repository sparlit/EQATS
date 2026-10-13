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
"""NSE SME results from the filings' PDFs, 2020→, for every Nifty SME Emerge member ever  (runbook §210a).

WHY. NSE lists no XBRL for SME results before the FY24 year-end (the listing's `xbrl` is the placeholder
".../corporate/xbrl/-", §148/§181d), so SME half-years 2020→Mar-2024 exist only as the PDF each company attached to
its "Financial Result Updates" / "Outcome of Board Meeting" announcement.

STAGES (each resumable, raw inputs persisted under ~/stocks-cache/nse_sme_pdf — memory: persist raw rows)
  --inventory   corporate-announcements?index=sme&symbol=S&from_date=01-10-2019&to_date=<today>, every symbol the
                company ever traded under (renames) → ann/<SYM>.json (raw rows, one request per symbol, 1.2 s apart)
  --download    for each wanted fiscal year: every result-type announcement (desc contains "result", or "Outcome of
                Board Meeting") dated inside the reporting window (Sep half: Oct 1 → Jan 31; Mar half: Apr 1 → Sep 30)
                → pdf/<file> (a .zip is unpacked beside it)
Targets: the missing SME-era half-year cells (docs/nse_sme_emerge/ever.json members; a half is due when its results
fall due after the listing), plus the March filing of each such fiscal year (it prints H1, H2 and the year together).

  python3 scripts/fetch_nse_sme_results_pdf.py --targets
  python3 scripts/fetch_nse_sme_results_pdf.py --inventory
  python3 scripts/fetch_nse_sme_results_pdf.py --download
"""
import collections
import datetime
import io
import json
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

C = os.path.expanduser(os.environ.get("NSE_SME_PDF_CACHE", "~/stocks-cache/nse_sme_pdf"))
ANN = os.path.join(C, "ann")
PDF = os.path.join(C, "pdf")
TARGETS = os.path.join(C, "targets.json")


def build_targets():
    """missing SME-era half-year cells of every member ever: a half is due when its results fall due (60 days) after
    the company's first SME trading day, and until it left the SME series (or 60 days ago); held = a PAT or revenue
    figure in docs/sf_fundamentals.json / docs/sf_revop.json under any symbol the company traded as"""
    import gzip

    ROOT = os.path.dirname(HERE)
    sf = json.load(open(os.path.join(ROOT, "docs", "sf_fundamentals.json")))
    rv = json.load(open(os.path.join(ROOT, "docs", "sf_revop.json")))
    P = json.load(
        gzip.open(
            os.path.join(os.path.expanduser("~/stocks-cache/nse_sme_emerge"), "sme_panel.json.gz"),
            "rt",
        )
    )["s"]
    ever = json.load(open(os.path.join(ROOT, "docs", "nse_sme_emerge", "ever.json")))["members"]
    RN = [
        tuple(x[:3])
        for x in json.load(open(os.path.join(HERE, "nse_sme_emerge_renames.json")))["renames"]
    ]

    def olds(s):
        out, ch = {s}, True
        while ch:
            ch = False
            for o, nw, _d in RN:
                if nw in out and o not in out:
                    out.add(o)
                    ch = True
        return out

    cutoff = datetime.date.today() - datetime.timedelta(days=60)
    T, due = [], 0
    for s in sorted(ever):
        syms = olds(s)
        bars = sorted(x for o in syms for x in P.get(o, []))
        sme = [x for x in bars if x[1] in ("SM", "ST", "SZ")]
        if not sme:
            continue

        def ymd(k):
            return datetime.date(k // 10000, k // 100 % 100, k % 100)

        first, last = ymd(sme[0][0]), ymd(sme[-1][0])
        end = cutoff if bars[-1][1] in ("SM", "ST", "SZ") else min(cutoff, last)
        for y in range(2019, 2027):
            for q in (y * 10000 + 930, (y + 1) * 10000 + 331):
                qd = ymd(q)
                if not (
                    datetime.date(2020, 3, 31) <= qd <= end
                    and qd + datetime.timedelta(days=60) >= first
                ):
                    continue
                due += 1
                ok = False
                for o in syms:
                    r = {x[0]: x for x in sf.get(o, [])}.get(q)
                    if r and (r[1] is not None or r[3] is not None):
                        ok = True
                    v = (rv.get(o) or {}).get(str(q))
                    if v and (v[0] is not None or v[1] is not None):
                        ok = True
                if not ok:
                    T.append(
                        {
                            "sym": s,
                            "olds": sorted(syms),
                            "isin": sme[-1][10],
                            "qe": q,
                            "first": sme[0][0],
                        }
                    )
    os.makedirs(C, exist_ok=True)
    json.dump(T, open(TARGETS, "w"))
    print(
        "targets: %d half-years due, %d held, %d missing (%d companies)"
        % (due, due - len(T), len(T), len({t["sym"] for t in T}))
    )


def nse():
    import fetch_sme_xbrl as F  # the curl_cffi Chrome session every NSE reader here uses

    return F.NSE()


def inventory():
    os.makedirs(ANN, exist_ok=True)
    T = json.load(open(TARGETS))
    syms = sorted({o for t in T for o in t["olds"]})
    n = nse()
    to = datetime.date.today().strftime("%d-%m-%Y")
    done = 0
    for s in syms:
        p = os.path.join(ANN, s.replace("/", "_") + ".json")
        if os.path.exists(p):
            continue
        u = "https://www.nseindia.com/api/corporate-announcements?index=sme&symbol={}&from_date=01-10-2019&to_date={}".format(
            s.replace("&", "%26"), to
        )
        j = json.loads(n.get(u))
        rows = j if isinstance(j, list) else j.get("data", [])
        json.dump(rows, open(p, "w"))
        done += 1
        if done % 50 == 0:
            print("inventory: %d / %d symbols" % (done, len(syms)), flush=True)
        time.sleep(1.2)
    print("inventory: %d symbols listed (%d new)" % (len(syms), done))


def windows(qe):
    y, m = qe // 10000, qe // 100 % 100
    if m == 9:
        return datetime.date(y, 10, 1), datetime.date(y + 1, 1, 31)
    return datetime.date(y, 4, 1), datetime.date(y, 9, 30)


def wanted():
    """{(company, qe)} — each missing cell and, for a Sep cell, the March filing of the same fiscal year"""
    T = json.load(open(TARGETS))
    W = {}
    for t in T:
        W[(t["sym"], t["qe"])] = t
        if t["qe"] % 10000 == 930:
            W.setdefault(
                (t["sym"], (t["qe"] // 10000 + 1) * 10000 + 331),
                dict(t, qe=(t["qe"] // 10000 + 1) * 10000 + 331),
            )
    return W


def is_result(r):
    d = (r.get("desc") or "").lower()
    return "result" in d or "outcome of board" in d


def candidates(t):
    a, b = windows(t["qe"])
    out = []
    for s in t["olds"]:
        p = os.path.join(ANN, s.replace("/", "_") + ".json")
        for r in json.load(open(p)) if os.path.exists(p) else []:
            d = datetime.date.fromisoformat(r["sort_date"][:10])
            u = r.get("attchmntFile") or ""
            if a <= d <= b and is_result(r) and u.lower().endswith((".pdf", ".zip")):
                out.append({"sym": s, "dt": r["sort_date"], "desc": r.get("desc"), "url": u})
    return sorted(out, key=lambda x: x["dt"])


def download():
    os.makedirs(PDF, exist_ok=True)
    n = nse()
    W = wanted()
    urls = {}
    for _k, t in W.items():
        for c in candidates(t):
            urls[c["url"]] = c
    got = skip = fail = 0
    for u in sorted(urls):
        fn = os.path.join(PDF, u.rsplit("/", 1)[-1])
        if os.path.exists(fn):
            skip += 1
            continue
        try:
            b = n.s.get(u, timeout=90).content if n.s else None
            if b is None:
                n.get("https://www.nseindia.com/")  # warm the session once
                b = n.s.get(u, timeout=90).content
        except Exception as e:
            fail += 1
            print(f"download failed {u}: {e!r}")
            continue
        if not (b[:4] == b"%PDF" or b[:2] == b"PK"):
            fail += 1
            print("not a PDF/ZIP (%d bytes): %s" % (len(b), u))
            continue
        open(fn, "wb").write(b)
        if b[:2] == b"PK":
            try:
                z = zipfile.ZipFile(io.BytesIO(b))
                for m in z.namelist():
                    if m.lower().endswith(".pdf"):
                        open(fn + "__" + os.path.basename(m), "wb").write(z.read(m))
            except zipfile.BadZipFile:
                print(f"bad zip: {u}")
        got += 1
        if got % 100 == 0:
            print("download: %d fetched" % got, flush=True)
        time.sleep(0.6)
    json.dump(urls, open(os.path.join(C, "candidates.json"), "w"))
    print(
        "download: %d attachments wanted, %d fetched, %d already cached, %d failed"
        % (len(urls), got, skip, fail)
    )


OFFLINE = "--offline" in sys.argv
SHARD = None
if "--shard" in sys.argv:  # --shard k/N: this process reads companies with crc32 % N == k
    _k, _n = sys.argv[sys.argv.index("--shard") + 1].split("/")
    SHARD = (int(_k), int(_n))
READS = os.path.join(C, "reads.json" if SHARD is None else "reads_%d_of_%d.json" % SHARD)


def prefetch(workers=8, per_window=4):
    """download, in parallel, the first `per_window` candidates (by prio) of every window the read stage will open"""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    T = json.load(open(TARGETS))
    years = {}
    for t in T:
        fy = t["qe"] // 10000 + (1 if t["qe"] % 10000 == 930 else 0)
        years.setdefault((t["sym"], fy), t)
    urls = []
    for (_sym, fy), t in years.items():
        for win_q in (fy * 10000 + 331, fy * 10000 + 930):
            urls += [c["url"] for c in sorted(candidates(dict(t, qe=win_q)), key=prio)[:per_window]]
    urls = sorted({u for u in urls if not os.path.exists(os.path.join(PDF, u.rsplit("/", 1)[-1]))})
    print("prefetch: %d attachments to download" % len(urls), flush=True)
    local = threading.local()
    cnt = collections.Counter()

    def one(u):
        if not hasattr(local, "n"):
            local.n = nse()
            local.n.get("https://www.nseindia.com/")
        try:
            fetch_one(local.n, u)
            cnt["ok"] += 1
        except Exception:
            cnt["fail"] += 1
        if sum(cnt.values()) % 200 == 0:
            print(f"prefetch: {dict(cnt)}", flush=True)

    os.makedirs(PDF, exist_ok=True)
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, urls))
    print(f"prefetch: done {dict(cnt)}")


def fetch_one(n, u):
    fn = os.path.join(PDF, u.rsplit("/", 1)[-1])
    if not os.path.exists(fn):
        if n.s is None:
            n.get("https://www.nseindia.com/")
        b = n.s.get(u, timeout=90).content
        open(fn, "wb").write(b)
        time.sleep(0.5)
        if b[:2] == b"PK":
            try:
                z = zipfile.ZipFile(io.BytesIO(b))
                for m in z.namelist():
                    if m.lower().endswith(".pdf"):
                        open(fn + "__" + os.path.basename(m).replace("/", "_"), "wb").write(
                            z.read(m)
                        )
            except zipfile.BadZipFile:
                pass
    outs = [fn] if open(fn, "rb").read(4) == b"%PDF" else []
    if open(fn, "rb").read(2) == b"PK":
        import glob

        outs = sorted(glob.glob(fn + "__*"))
    return outs


def prio(c):
    d = (c["desc"] or "").lower()
    u = c["url"].lower()
    return (
        0
        if "result" in d
        else 1
        if any(k in u for k in ("result", "financ", "fr_", "fr2", "_fr", "audit"))
        else 2,
        c["dt"],
    )


def read_stage(limit=None):
    """Prove each company-year that has a missing half from two filings: its March filing (H1, H2, year) and the next
    September filing (which reprints the year beside the next H1). In each window the first 4 candidates by priority
    are read until one standalone statement CLOSES. Every statement read is kept raw in reads.json."""
    import read_sme_result_pdf as R

    os.makedirs(PDF, exist_ok=True)
    T = json.load(open(TARGETS))
    years = {}
    for t in T:
        fy = t["qe"] // 10000 + (1 if t["qe"] % 10000 == 930 else 0)
        years.setdefault((t["sym"], fy), t)
    reads = json.load(open(READS)) if os.path.exists(READS) else {}
    n = nse()
    done = 0
    import zlib

    for (sym, fy), t in sorted(years.items()):
        key = "%s|%d" % (sym, fy)
        if key in reads:
            continue
        if SHARD and zlib.crc32(sym.encode()) % SHARD[1] != SHARD[0]:
            continue
        rec = {"sym": sym, "fy": fy, "tried": [], "stmts": [], "proved": None}
        for win_q in (
            fy * 10000 + 331,
            fy * 10000 + 930,
        ):  # March filing of the year AND next September's
            win_ok = False  # (it reprints this year beside next year's H1 —
            for c in sorted(candidates(dict(t, qe=win_q)), key=prio)[
                :4
            ]:  # often a held XBRL value: the unit anchor)
                if win_ok:
                    break
                if OFFLINE and not os.path.exists(os.path.join(PDF, c["url"].rsplit("/", 1)[-1])):
                    rec["pending"] = True
                    continue  # not downloaded yet: this year is read again later
                try:
                    files = fetch_one(n, c["url"])
                except Exception as e:
                    rec["tried"].append([c["url"], f"download failed {e!r}"])
                    continue
                for f in files:
                    try:
                        sts = R.read(f)
                    except Exception as e:
                        rec["tried"].append([c["url"], f"unreadable {e!r}"])
                        continue
                    import fitz

                    chars = sum(len(p.get_text()) for p in fitz.open(f))
                    rec["tried"].append([c["url"], "chars %d, statements %d" % (chars, len(sts))])
                    for st in sts:
                        st.update(
                            {
                                "url": c["url"],
                                "dt": c["dt"],
                                "desc": c["desc"],
                                "file": os.path.basename(f),
                            }
                        )
                        rec["stmts"].append(st)
                        d = R.decide(st, fy)
                        if "FY" in d and st["basis"] == "s":
                            win_ok = True
                            if not rec["proved"]:
                                rec["proved"] = {
                                    "url": c["url"],
                                    "dt": c["dt"],
                                    "page": st["page"],
                                    "how": d["how"],
                                }
        if rec.get("pending") and not rec["proved"]:
            continue  # never mark a year done on missing files
        rec.pop("pending", None)
        reads[key] = rec
        done += 1
        if done % 25 == 0:
            json.dump(reads, open(READS, "w"))
            print(
                "read: %d company-years, %d proved so far"
                % (len(reads), sum(1 for r in reads.values() if r["proved"])),
                flush=True,
            )
        if limit and done >= limit:
            break
    json.dump(reads, open(READS, "w"))
    print(
        "read: %d company-years, %d proved"
        % (len(reads), sum(1 for r in reads.values() if r["proved"]))
    )


def read_orig():
    """§210c: for every company-year read, also read the ORIGINAL September filing of its H1 (Oct 1 fy-1 → Jan 31 fy) —
    its current H1 column is the as-published figure. Statements are appended (text reader); no closure needed here."""
    import read_sme_result_pdf as R

    reads = json.load(open(os.path.join(C, "reads.json")))
    T = {t["sym"]: t for t in json.load(open(TARGETS))}
    n = done = 0
    for _key, rec in sorted(reads.items()):
        t = T.get(rec["sym"])
        if not t or rec.get("orig_read"):
            continue
        seen = {x[0] for x in rec["tried"]}
        for c in sorted(candidates(dict(t, qe=(rec["fy"] - 1) * 10000 + 930)), key=prio)[:4]:
            fn = os.path.join(PDF, c["url"].rsplit("/", 1)[-1])
            if c["url"] in seen or not os.path.exists(fn):
                continue
            files = (
                sorted(__import__("glob").glob(fn + "__*"))
                if open(fn, "rb").read(2) == b"PK"
                else [fn]
            )
            for f in files:
                try:
                    sts = R.read(f)
                except Exception:
                    continue
                for st in sts:
                    st.update(
                        {
                            "url": c["url"],
                            "dt": c["dt"],
                            "desc": c["desc"],
                            "file": os.path.basename(f),
                            "orig": True,
                        }
                    )
                    rec["stmts"].append(st)
                    n += 1
            rec["tried"].append([c["url"], "original-H1 read"])
        rec["orig_read"] = True
        done += 1
    json.dump(reads, open(os.path.join(C, "reads.json"), "w"))
    print("original H1 filings: %d years, %d statements appended" % (done, n))


def merge_vision():
    """image reads (vision/out/b*.json, user-approved 2026-09-28) → reads.json statements tagged vision, held to the OCR
    rule (revenue AND profit must close); the unit comes from the printed unit text via the reader's own patterns"""
    import glob
    import re

    import read_sme_result_pdf as R

    reads = json.load(open(os.path.join(C, "reads.json")))
    byfile = {}
    for t in json.load(open(TARGETS)):
        for win_q in (
            t["qe"] // 10000 * 10000 + 331,
            t["qe"] // 10000 * 10000 + 930,
            (t["qe"] // 10000 + 1) * 10000 + 331,
        ):
            for c in candidates(dict(t, qe=win_q)):
                byfile[c["url"].rsplit("/", 1)[-1]] = c
    n = bad = 0
    for f in sorted(glob.glob(os.path.join(C, "vision", "out", "b*.json"))):
        for r in json.load(open(f)):
            base = os.path.basename(r.get("file") or "").split("__")[0]
            c = byfile.get(base)
            if not c or not r.get("cols"):
                bad += 1
                continue
            ut = (r.get("unit_text") or "").lower()
            unit = next(((m, lab) for pat, m, lab in R.UNIT if re.search(pat, ut)), (None, None))
            vals = [v for v in (r.get("rev") or []) + (r.get("pat") or []) if v is not None]
            st = {
                "page": r.get("page"),
                "basis": r.get("basis") or "s",
                "unit": unit[0],
                "unit_txt": unit[1],
                "cols": [
                    {"date": int(x["date"]), "x": i, "kind": x.get("kind")}
                    for i, x in enumerate(r["cols"])
                ],
                "rev": r.get("rev"),
                "pat": r.get("pat"),
                "eps": r.get("eps"),
                "ocr": True,
                "vision": True,
                "dec": max(
                    [len(str(v).split(".")[1]) if "." in str(v) else 0 for v in vals] or [0]
                ),
                "url": c["url"],
                "dt": c["dt"],
                "desc": c["desc"],
                "file": os.path.basename(r.get("file") or ""),
            }
            key = "%s|%d" % (r["sym"], int(r["fy"]))
            rec = reads.setdefault(
                key, {"sym": r["sym"], "fy": int(r["fy"]), "tried": [], "stmts": [], "proved": None}
            )
            if not any(
                x.get("vision")
                and x["file"] == st["file"]
                and x["page"] == st["page"]
                and x["basis"] == st["basis"]
                for x in rec["stmts"]
            ):
                rec["stmts"].append(st)
                n += 1
    json.dump(reads, open(os.path.join(C, "reads.json"), "w"))
    print("vision: %d statements merged, %d rows without a known filing / columns" % (n, bad))


def merge_reads():
    import glob

    out = (
        json.load(open(os.path.join(C, "reads.json")))
        if os.path.exists(os.path.join(C, "reads.json"))
        else {}
    )
    for f in sorted(glob.glob(os.path.join(C, "reads_*_of_*.json"))):
        out.update(json.load(open(f)))
    json.dump(out, open(os.path.join(C, "reads.json"), "w"))
    print(
        "merged: %d company-years, %d proved"
        % (len(out), sum(1 for r in out.values() if r["proved"]))
    )


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--merge" in a:
        merge_reads()
    if "--read-orig" in a:
        read_orig()
    if "--merge-vision" in a:
        merge_vision()
    if "--targets" in a:
        build_targets()
    if "--inventory" in a:
        inventory()
    if "--download" in a:
        download()
    if "--prefetch" in a:
        prefetch()
    if "--read" in a:
        read_stage(int(a[a.index("--limit") + 1]) if "--limit" in a else None)
