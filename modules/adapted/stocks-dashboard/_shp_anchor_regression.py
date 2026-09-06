# -*- coding: utf-8 -*-
"""Regression harness for the parse_shp scale-anchor ladder (2026-08-07).

Parses the SAME bytes with origin/main's parse_shp and the patched one. The change is meant to be
purely additive, so the ONLY legal transition is None -> dict. Any dict -> different dict is a
scale/value regression and fails the run.
"""
import os, sys, json, subprocess, importlib.util, collections
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from curl_cffi import requests as cr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fetch_shareholding as NEW

OLDP = "/tmp/_fs_old_%d.py" % os.getpid()
open(OLDP, "wb").write(subprocess.run(["git", "show", "origin/main:scripts/fetch_shareholding.py"],
                                      capture_output=True, cwd=os.path.dirname(HERE)).stdout)
spec = importlib.util.spec_from_file_location("fs_old", OLDP)
OLD = importlib.util.module_from_spec(spec)
spec.loader.exec_module(OLD)

H = {"Referer": "https://www.bseindia.com/"}
QMON = {"March": "-03-31", "June": "-06-30", "September": "-09-30", "December": "-12-31"}
# spread: mega caps, promoter-less names, banks, PSUs, an ESOP-heavy one, a DR-heavy one
CODES = [500325, 532540, 500180, 500209, 500875, 500034, 532174, 500112, 500510,
         534091, 500790, 500488, 506285, 500002, 532555, 500247, 500696, 532978,
         540719, 543320, 500114, 532281]


def qe_of(q):
    p = str(q or "").split()
    return p[1] + QMON[p[0]] if len(p) == 2 and p[0] in QMON and p[1].isdigit() else None


def get(u, tries=3):
    last = None
    for _ in range(tries):
        try:
            r = cr.get(u, headers=H, impersonate="chrome", timeout=40)
            if r.status_code == 200:
                return r.content
            last = Exception("HTTP %d" % r.status_code)
        except Exception as e:
            last = e
    raise last


def jobs():
    out = []
    for code in CODES:
        try:
            rows = json.loads(get("https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w?scripcode=%d" % code))["Table"]
        except Exception as e:
            print("  qlist fail %d %r" % (code, e)); continue
        for r in rows:
            qe = qe_of(r.get("qtr"))
            if qe and (r.get("XbrlFile") or "").strip():
                out.append((code, qe, "https://www.bseindia.com/XBRLFILES/SHPXBRLDataXML/" + r["XbrlFile"].strip()))
    return out


def one(job):
    code, qe, url = job
    try:
        root = ET.fromstring(get(url))
    except Exception:
        return None
    try:
        o = OLD.parse_shp(root, qe)
    except Exception:
        o = "ERR"
    try:
        n = NEW.parse_shp(root, qe)
    except Exception:
        n = "ERR"
    return (code, qe, o, n)


todo = jobs()
print("regression sample: %d filings across %d companies" % (len(todo), len(CODES)))
res = []
with ThreadPoolExecutor(6) as ex:
    for r in ex.map(one, todo):
        if r: res.append(r)

same = gained = changed = nsh_dropped = 0
mf_only = 0
for code, qe, o, n in res:
    if o == n:
        same += 1
    elif o is None and isinstance(n, dict):
        gained += 1
    elif isinstance(o, dict) and isinstance(n, dict):
        diff = {k for k in set(o) | set(n) if o.get(k) != n.get(k)}
        if diff == {"mf"}:                     # the separately-verified MF spelling fix
            mf_only += 1
        elif diff == {"nsh"} and "nsh" not in n:   # implausible count dropped by the new gate
            nsh_dropped += 1
        else:
            changed += 1
            print("  ⚠ CHANGED %s %s  keys=%s\n      old=%s\n      new=%s" % (code, qe, sorted(diff), o, n))
    else:
        changed += 1
        print("  ⚠ ODD %s %s old=%r new=%r" % (code, qe, o, n))

print("\nparsed %d filings: identical %d, mf-only %d, nsh-dropped %d, NEWLY PARSED %d, REGRESSIONS %d"
      % (len(res), same, mf_only, nsh_dropped, gained, changed))
if gained:
    print("\nnewly parsed (was refused):")
    for code, qe, o, n in res:
        if o is None and isinstance(n, dict):
            print("  %s %s -> prom=%s pub=%s fii=%s dii=%s" % (code, qe, n["prom"], n["pub"], n["fii"], n["dii"]))
os.unlink(OLDP)
sys.exit(1 if changed else 0)
