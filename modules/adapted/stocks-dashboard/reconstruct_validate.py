# -*- coding: utf-8 -*-
"""
Reconstruct point-in-time Nifty 500 membership by anchoring on the CURRENT official
list and walking the parsed change log BACKWARD, then VALIDATE against independent
archived full lists (Wayback). The validation is the integrity proof: if reconstruction
matches every archived checkpoint, no change was missed in that range.
Run: python -X utf8 reconstruct_validate.py
"""
import os, json, gzip, csv, io, urllib.request, time
HERE = os.path.dirname(os.path.abspath(__file__)); UA = {"User-Agent": "Mozilla/5.0"}
IDX = "Nifty 500"

changelog = json.load(open(os.path.join(HERE, "_changelog.json")))[IDX]
changelog.sort(key=lambda c: c["eff"])

def parse_csv(raw):
    if raw[:2] == b"\x1f\x8b": import gzip as g; raw = g.decompress(raw)
    rows = list(csv.reader(raw.decode("utf-8","ignore").splitlines()))
    hdr = [h.strip() for h in rows[0]]; si = hdr.index("Symbol") if "Symbol" in hdr else 2
    return {r[si].strip() for r in rows[1:] if len(r) > si and r[si].strip()}
def get(u):
    for _ in range(5):
        try: return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read()
        except Exception: time.sleep(3)
    return b""

# anchor = current official list
cur = parse_csv(get("https://archives.nseindia.com/content/indices/ind_nifty500list.csv"))
print(f"Anchor (today) Nifty 500: {len(cur)} stocks")

# walk backward: membership_before(E) = after(E) - included(E) + excluded(E)
# snapshots[eff] = membership in force FROM eff (until next eff)
snapshots = {}
latest_eff = changelog[-1]["eff"]
snapshots[latest_eff] = set(cur)
m = set(cur)
for c in reversed(changelog):
    before = (m - set(c["included"])) | set(c["excluded"])
    snapshots[c["eff"]] = m            # m is the membership in force FROM c['eff']
    m = before
# m now = membership before the earliest change (the pre-changelog baseline)
earliest_eff = changelog[0]["eff"]
snapshots["1900-01-01"] = m            # baseline before earliest parsed change

def members_asof(d):
    best = None
    for eff in sorted(snapshots):
        if eff <= d: best = eff
    return snapshots[best]

# validate against Wayback archived full lists
wb = json.load(open(os.path.join(HERE, "_wb_n500_snaps.json")))  # {date: [symbols]}
# rename map old->new (resolve chains) so we compare on a canonical (current) ticker
rename = {}
try:
    import csv
    for r in csv.reader(open(os.path.join(os.path.dirname(HERE), "..", "symchg.csv"), encoding="utf-8", errors="replace")):
        if len(r) >= 3 and r[1].strip() and r[2].strip() and r[1].strip().upper() != "SYMBOL":
            rename[r[1].strip().upper()] = r[2].strip().upper()
except Exception as e:
    print("(no rename map:", e, ")")
def canon(s):
    seen = set()
    while s in rename and s not in seen: seen.add(s); s = rename[s]
    return s
def cset(S): return {canon(x) for x in S}

print("\nVALIDATION — reconstructed vs official archived full list (rename-normalised):")
print("%-12s %8s %8s %9s %8s %8s" % ("archive date","official","recon","match","off-by","raw-off"))
for d in sorted(wb):
    off = cset(wb[d]); rec = cset(members_asof(d)); rawoff = len(set(wb[d]) ^ members_asof(d))
    inter = off & rec; offby = len(off ^ rec)
    print("%-12s %8d %8d %8.1f%% %8d %8d" % (d, len(off), len(rec), 100*len(inter)/len(off), offby, rawoff))
    if offby:
        print("      official\\recon:", sorted(off - rec)[:14])
        print("      recon\\official:", sorted(rec - off)[:14])
print("\nChange events used:", len(changelog), "| span", changelog[0]["eff"], "..", changelog[-1]["eff"])
