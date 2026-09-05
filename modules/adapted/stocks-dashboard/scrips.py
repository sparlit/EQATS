# -*- coding: utf-8 -*-
"""Scrip-code resolution INCLUDING delisted/suspended names (runbook §52b).

bse_scrips.json is built from the LIVE master, so every dead company resolves to None -- and this
audit's suspect population is full of them. ListofScripData/w with a blank status returns the whole
10,800-row universe. §0: VALIDATE THE ROW COUNT, a 162-byte body is BSE's rate-limit 302 stub and
curl/urllib exit cleanly on it.
"""
import json, os, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CACHE = os.path.join(HERE, "_scrip_master.json")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
URL = ("https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w?Group=&Scripcode=&industry="
       "&segment=Equity&status=%s")
FLOOR = 3000


def _fetch(status):
    req = urllib.request.Request(URL % status,
                                 headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
    if len(raw) < 1000:                      # the 162-byte "Object Moved" stub
        raise RuntimeError("rate-limit stub (%d bytes)" % len(raw))
    return json.loads(raw.decode("utf-8", "replace"))


def master():
    if os.path.exists(CACHE):
        return json.load(open(CACHE))
    out = {}
    for status in ("", "Delisted", "Suspended"):
        for attempt in (1, 2, 3, 4):
            try:
                rows = _fetch(status)
                break
            except Exception as ex:
                print("   [scrip master %r attempt %d: %s]" % (status, attempt, ex), flush=True)
                rows = []
                time.sleep(20 * attempt)
        for r in rows:
            sid = (r.get("scrip_id") or "").strip().upper()
            code = (r.get("SCRIP_CD") or r.get("Scrip_Cd") or "").strip()
            if sid and code:
                out.setdefault(sid, code)
        print("   scrip master %-10r -> %d rows (total %d)" % (status, len(rows), len(out)),
              flush=True)
    if len(out) < FLOOR:                     # §0: validate the COUNT, never the exit code
        raise RuntimeError("scrip master only %d rows -- refusing to cache a throttled fetch"
                           % len(out))
    json.dump(out, open(CACHE, "w"), sort_keys=True)
    return out


_LIVE = json.load(open(os.path.join(ROOT, "scripts", "bse_scrips.json")))["by_id"]
_M = None


def code_for(sym):
    global _M
    c = _LIVE.get(sym)
    if c:
        return str(c), "live-master"
    if _M is None:
        try:
            _M = master()
        except Exception as ex:
            print("   [scrip master unavailable: %s]" % ex, flush=True)
            _M = {}
    s = sym.upper()
    for cand in (s, s.split("-")[0], s.replace("&", "")):
        if cand in _M:
            return str(_M[cand]), "delisted-master"
    return None, "unresolved"


if __name__ == "__main__":
    for s in sys.argv[1:]:
        print(s, code_for(s))
