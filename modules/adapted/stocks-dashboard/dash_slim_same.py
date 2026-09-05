#!/usr/bin/env python3
"""Compare a freshly built dash_slim.bin against the committed copy.

Exit 0  -> data identical (only the generatedAt stamp differs): safe to SKIP
           committing the new file.
Exit 1  -> data changed (new trading day / corrected closes), or the committed
           copy is missing/corrupt, or anything else went wrong: COMMIT it.

Fail-open by design: any error means "commit the fresh file". The dashboard is
rebuilt 3x/day (refresh.yml) but its data only changes once per trading day —
skipping the identical re-runs keeps git history from growing ~2 MB per run,
while never risking the built-then-discarded bug (DATA_RUNBOOK.md section 18).

Usage: dash_slim_same.py NEW_FILE COMMITTED_FILE
"""
import gzip
import json
import sys


def load(path):
    d = json.loads(gzip.decompress(open(path, "rb").read()))
    d.pop("generatedAt", None)
    return d


def main():
    try:
        same = load(sys.argv[1]) == load(sys.argv[2])
    except Exception as e:
        print(f"dash_slim compare: treating as changed ({e})")
        return 1
    if same:
        print("dash_slim.bin data identical (only generatedAt differs) — skipping commit")
        return 0
    print("dash_slim.bin data changed — will commit")
    return 1


if __name__ == "__main__":
    sys.exit(main())
