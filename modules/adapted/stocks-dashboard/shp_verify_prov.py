# -*- coding: utf-8 -*-
"""Per-cell PROVENANCE map for shp_history — which route wrote each (sym, QE) cell.

Why this exists (SHP_VERIFY_CAMPAIGN trap T3, "circularity"): a site agreeing with us proves
nothing when our cell was harvested FROM that site. Our 2010-2015 cells came from archived
Moneycontrol; a few BSE-Ltd cells came from screener.in + Trendlyne. Those comparisons are
PROVENANCE_ECHO — transcription checks, not verification, and they must never count toward the
multi-site quorum in campaign rule 6b.

Route tags (value written per cell):
  wayback-mc   shp_fill_hist_2010_2016.json.gz   ECHOES: moneycontrol
  thirdparty   shp_fill_thirdparty.json.gz       ECHOES: screener, trendlyne
  bse-1619     shp_fill_hist_2016_2019.json.gz   independent (BSE XBRL)
  bse-sweep    shp_fill_n500_gaps.json.gz        independent (BSE SHPQNewFormat XBRL)
  nse-gaps     shp_fill_nse_gaps.json.gz         independent (NSE XBRL)
  mf-heal      shp_mf_heal.json.gz               independent (mf slot only)
  nse-live     everything else                   independent (live NSE pipeline)

  python3 -X utf8 scripts/shp_verify_prov.py --pin 93de247c --out prov.json.gz
"""
import os, sys, json, gzip, argparse, subprocess, collections

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)

# ledger file -> (route tag, sites this route ECHOES)
LEDGERS = [
    ("scripts/shp_fill_hist_2010_2016.json.gz", "wayback-mc", ["moneycontrol"]),
    ("scripts/shp_fill_thirdparty.json.gz",     "thirdparty", ["screener", "trendlyne"]),
    ("scripts/shp_fill_hist_2016_2019.json.gz", "bse-1619",   []),
    ("scripts/shp_fill_n500_gaps.json.gz",      "bse-sweep",  []),
    ("scripts/shp_fill_nse_gaps.json.gz",       "nse-gaps",   []),
    ("scripts/shp_mf_heal.json.gz",             "mf-heal",    []),
]
ECHOES = {tag: sites for _, tag, sites in LEDGERS}
ECHOES["nse-live"] = []


def git_show(path, pin):
    r = subprocess.run(["git", "show", "%s:%s" % (pin, path)], capture_output=True, cwd=REPO)
    if r.returncode:
        return None
    return r.stdout


def load_json_maybe_gz(raw, path):
    if path.endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw)


def fills_of(doc):
    """Ledgers are {_meta:…, fills:{SYM:{QE:row}}}; tolerate a bare {SYM:{QE:row}} too."""
    if isinstance(doc, dict) and isinstance(doc.get("fills"), dict):
        return doc["fills"]
    return {k: v for k, v in doc.items() if not k.startswith("_") and isinstance(v, dict)}


def build(pin):
    hist_raw = git_show("scripts/shp_history.json", pin)
    if hist_raw is None:
        sys.exit("cannot read shp_history.json at %s — git fetch origin first" % pin)
    HIST = json.loads(hist_raw)

    prov = {}                      # SYM -> {QE: route}
    counts = collections.Counter()
    for path, tag, _sites in LEDGERS:
        raw = git_show(path, pin)
        if raw is None:
            print("  (absent at pin: %s)" % path, file=sys.stderr)
            continue
        for sym, qes in fills_of(load_json_maybe_gz(raw, path)).items():
            for qe in qes:
                # a later ledger never demotes an earlier tag for the same cell: first writer wins,
                # and LEDGERS is ordered so the CIRCULAR routes claim their cells first (worst case
                # for us = the safest verdict, since an echo tag only ever removes quorum credit).
                if qe not in prov.setdefault(sym, {}):
                    prov[sym][qe] = tag

    for sym, qes in HIST.items():
        if sym.startswith("_"):
            continue
        for qe in qes:
            route = prov.setdefault(sym, {}).setdefault(qe, "nse-live")
            counts[route] += 1
        for qe in list(prov[sym]):          # ledger cell that never landed in history
            if qe not in HIST[sym]:
                del prov[sym][qe]

    return {"_meta": {"pin": pin, "echoes": ECHOES, "counts": dict(counts)}, "prov": prov}, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pin", default="origin/main")
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    doc, counts = build(a.pin)
    total = sum(counts.values())
    print("cells: %d" % total)
    for route, n in counts.most_common():
        echo = ECHOES.get(route) or []
        print("  %-12s %7d  %5.1f%%   %s" % (route, n, 100.0 * n / total,
                                             ("ECHOES " + ",".join(echo)) if echo else "independent"))
    if a.out:
        blob = json.dumps(doc, separators=(",", ":")).encode()
        if a.out.endswith(".gz"):
            gzip.open(a.out, "wb").write(blob)
        else:
            open(a.out, "wb").write(blob)
        print("wrote %s (%.1f KB)" % (a.out, os.path.getsize(a.out) / 1024.0))


if __name__ == "__main__":
    main()
