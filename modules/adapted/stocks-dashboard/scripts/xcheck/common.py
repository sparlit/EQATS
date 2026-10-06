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


"""Shared plumbing for the second-reader audit (scripts/xcheck_run.py, runbook §214).

Every check compares TWO INDEPENDENT READINGS of the same served number (two sources, or one source through two
unrelated paths) and reports where they disagree. Internal-consistency checks (sums, jumps, sizes) already exist in
CI (guard_feed, parse gates …); they cannot see a plausible wrong number — only a second reader can.

Inputs are the LIVE stores: docs/* and scripts/* from the tree this runs in (CI = origin/main), and the live price
bin from the GitHub release (docs/sf_stock_data.bin in the repo is a FROZEN snapshot — PLAN_DATA_AUDIT §1a).
Scope = point-in-time Nifty 500 members (user rule 2026-09-05): a (symbol, date) pair is audited only while the
symbol was in the Nifty 500 snapshot in force on that date (scripts/indices_history.json, last snapshot <= date,
the engines' membersAsOf rule)."""
import bisect
import datetime
import gzip
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/
ROOT = os.path.dirname(HERE)
DOCS = os.path.join(ROOT, "docs")
CACHE = os.environ.get("XCHECK_CACHE") or os.path.expanduser("~/stocks-cache/xcheck")
SF_RELEASE = (
    "https://github.com/dhruvan246/stocks-dashboard/releases/download/data/sf_stock_data.bin"
)
UA = {"User-Agent": "stocks-dashboard-xcheck/1.0 (personal research)"}


def ymd(d):
    return d.year * 10000 + d.month * 100 + d.day


def day(i):
    return datetime.date(i // 10000, i // 100 % 100, i % 100)


def iso(i):
    return "%04d-%02d-%02d" % (i // 10000, i // 100 % 100, i % 100)


def jload(path):
    if path.endswith(".gz") or path.endswith(".bin"):
        return json.loads(gzip.decompress(open(path, "rb").read()))
    return json.load(open(path, encoding="utf-8"))


def sf_path():
    """The live NSE-bhavcopy price bin (release asset), cached for 12 h under CACHE; SF_BIN=<path> overrides."""
    p = os.environ.get("SF_BIN")
    if p:
        return p
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, "sf_stock_data.bin")
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < 12 * 3600:
        return p
    last = None
    for a in range(3):
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(SF_RELEASE, headers=UA), timeout=300
            ).read()
            with gzip.GzipFile(
                fileobj=__import__("io").BytesIO(raw)
            ) as g:  # a truncated download raises here
                while g.read(1 << 24):
                    pass
            open(p + ".part", "wb").write(raw)
            os.replace(p + ".part", p)
            return p
        except Exception as e:
            last = e
            time.sleep(15 * (a + 1))
    raise SystemExit(f"xcheck: live price bin unreachable ({last})")


def iter_section(path, section, chunk=1 << 22):
    """Stream (key, bytes) for every child object of the top-level object `section` of a gzipped JSON file whose
    children are FLAT objects of number arrays (the price bins: {"data": {"SYM": {"d": [...], "c": [...], ...}}}).
    json.loads of the whole 582 MB live bin builds ~10 GB of Python objects (the machine swapped to a halt,
    2026-09-28); this keeps one child's text at a time."""
    head = (f'"{section}":{{').encode()
    with gzip.open(path, "rb") as f:
        buf = f.read(chunk)
        pos = -1
        while pos < 0:
            pos = buf.find(head)
            if pos < 0:
                more = f.read(chunk)
                if not more:
                    raise ValueError(f"section {section} not found in {path}")
                buf = buf[-len(head) :] + more
        pos += len(head)
        while True:
            end = buf.find(b"}", pos)
            while end < 0:
                more = f.read(chunk)
                if not more:
                    raise ValueError(f"truncated {path}")
                buf = buf[pos:] + more
                pos = 0
                end = buf.find(b"}", pos)
            obj = buf[pos : end + 1]
            k = obj.find(b":{")
            if k < 0 or obj[:1] != b'"':
                raise ValueError(f"unexpected layout at {obj[:60]!r}")
            yield json.loads(obj[:k]), obj[k + 1 :]
            pos = end + 1
            while len(buf) <= pos:
                more = f.read(chunk)
                if not more:
                    return
                buf = buf[pos:] + more
                pos = 0
            c = buf[pos : pos + 1]
            if c == b",":
                pos += 1
            elif c == b"}":
                return
            else:
                raise ValueError(f"unexpected {c!r} after a child object")


def sf_closes(want):
    """{sym: (array('i') ymd, array('d') close)} for the symbols in `want` from the live bin (adjusted closes)."""
    from array import array

    out = {}
    for sym, raw in iter_section(sf_path(), "data"):
        if sym not in want:
            continue
        o = json.loads(raw)
        out[sym] = (array("i", o["d"]), array("d", [x if x is not None else 0.0 for x in o["c"]]))
    return out


_N500 = None


def n500():
    """[(effective ymd, frozenset(symbols))] sorted — the 'Nifty 500' roster history."""
    global _N500
    if _N500 is None:
        ih = jload(os.path.join(HERE, "indices_history.json"))["Nifty 500"]
        _N500 = sorted(
            (int(s["effectiveDate"].replace("-", "")), frozenset(s["symbols"])) for s in ih
        )
    return _N500


def member(sym, d):
    """Was `sym` in the Nifty 500 snapshot in force on ymd `d`?"""
    snaps = n500()
    i = bisect.bisect_right([s[0] for s in snaps], d) - 1
    return i >= 0 and sym in snaps[i][1]


def member_spans(sym):
    """[(from ymd, to ymd exclusive or None)] while `sym` was a member."""
    out, cur = [], None
    for d, s in n500():
        if sym in s and cur is None:
            cur = d
        elif sym not in s and cur is not None:
            out.append((cur, d))
            cur = None
    if cur is not None:
        out.append((cur, None))
    return out


def ever_members():
    s = set()
    for _, m in n500():
        s |= m
    return s


def load_accept():
    p = os.path.join(HERE, "xcheck_accept.json")
    return jload(p) if os.path.exists(p) else {}


class Check:
    """One comparison. Subclasses set id/title/domain/reader_a/reader_b/scope and implement run() → self.add(...)."""

    id = title = domain = reader_a = reader_b = scope = ""
    tolerance = ""
    max_listed = 400

    def __init__(self):
        self.compared = 0
        self.agree = 0
        self.findings = []
        self.notes = []
        self.calibration = None

    def add(self, key, **f):
        f["key"] = key
        self.findings.append(f)

    def note(self, s):
        self.notes.append(s)

    def report(self, accept):
        acc = accept.get(self.id) or {}
        open_, accepted, explained = [], [], []
        for f in self.findings:
            if f["key"] in acc:
                f["accepted"] = acc[f["key"]].get("why", "")
                accepted.append(f)
            elif f.get("explained"):
                explained.append(f)
            else:
                open_.append(f)

        def sev(f):
            return -(f.get("weight") or 0)

        open_.sort(key=sev)
        explained.sort(key=sev)
        return {
            "id": self.id,
            "title": self.title,
            "domain": self.domain,
            "reader_a": self.reader_a,
            "reader_b": self.reader_b,
            "scope": self.scope,
            "tolerance": self.tolerance,
            "compared": self.compared,
            "agree": self.agree,
            "agree_pct": round(100.0 * self.agree / self.compared, 3) if self.compared else None,
            "n_open": len(open_),
            "n_explained": len(explained),
            "n_accepted": len(accepted),
            "open": open_[: self.max_listed],
            "explained": explained[: self.max_listed // 4],
            "accepted": accepted[:50],
            "notes": self.notes,
            "calibration": self.calibration,
        }


def top_values(path, keys):
    """{key: json value} for top-level `keys` of a gzipped JSON file, decoding only those values (one decompress)."""
    txt = gzip.decompress(open(path, "rb").read()).decode("utf-8")
    dec = json.JSONDecoder()
    out = {}
    for key in keys:
        i = txt.find(f'"{key}":')
        if i < 0:
            raise ValueError(f"{key} not in {path}")
        out[key] = dec.raw_decode(txt, i + len(key) + 3)[0]
    return out


def yahoo_bin():
    """(start date, end ymd, meta, iterator of (ticker, {"d": day offsets, "p": close*100})) — docs/stock_data.bin."""
    p = os.path.join(DOCS, "stock_data.bin")
    v = top_values(p, ["startTs", "endTs", "meta"])
    start = datetime.datetime.utcfromtimestamp(v["startTs"]).date()
    end = ymd(
        (
            datetime.datetime.utcfromtimestamp(v["endTs"]) + datetime.timedelta(hours=5, minutes=30)
        ).date()
    )
    return start, end, v["meta"], ((k, json.loads(x)) for k, x in iter_section(p, "series"))


def late_value(path, key, chunk=1 << 22):
    """json value of a top-level `key` that sits AFTER the bulk of a gzipped JSON file (the live bin's "meta"),
    streaming past everything before it: only the tail from the key on is ever held."""
    head = (f'"{key}":').encode()
    keep = b""
    with gzip.open(path, "rb") as f:
        buf = b""
        while True:
            more = f.read(chunk)
            if not more:
                raise ValueError(f"{key} not in {path}")
            buf = buf[-len(head) :] + more
            i = buf.find(head)
            if i >= 0:
                keep = buf[i + len(head) :]
                while True:
                    more = f.read(chunk)
                    if not more:
                        break
                    keep += more
                break
    return json.JSONDecoder().raw_decode(keep.decode("utf-8"))[0]
