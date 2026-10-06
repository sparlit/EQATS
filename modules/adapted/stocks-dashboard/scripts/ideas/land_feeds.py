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


"""Land one ideas-feeds run on origin/main without reverting anyone else's commit (runbook §144g).

.github/workflows/ideas-feeds.yml builds docs/ideas/* from the commit it checked out (BASE), which takes
about four minutes, and then pushes. Its commit step used to `git reset --hard origin/main` and copy every
output file WHOLE over whatever origin held by then, so a docs/ideas/ commit another writer landed during
the run was silently reverted: on 2026-09-28 run 36344172861 dropped the two track.json rows 3afd6f4 had
added (restored by hand in 4d651db61). This script replaces that copy. Two phases, both called from the
workflow's commit step:

  snapshot BASE OUT PATH...  On the builders' own tree, before any reset. Copies to OUT only the files
                             under PATH this run actually changed (differ from BASE, or are new) and writes
                             OUT/manifest.json. A file the run left alone is never copied, so it can never
                             revert anything (the old copy rewrote every scan/ file, not only the one built).
  apply BASE OUT             On a fresh `git reset --hard origin/main`, once per push attempt. For each
                             file the run changed:
      origin still holds BASE's copy  -> this run's copy lands;
      origin holds the same bytes     -> nothing to do;
      origin changed it too           -> origin's copy STAYS and a ::warning:: names the file and origin's
                                         commit(s). So do the other files of the same builder: a builder's
                                         files land together or not at all (india_spot.json, its history
                                         CSV and india_history.json.gz describe one read).
    Two files are derived and are REBUILT on the fresh tree, instead of copied, when anything they are built
    from moved on origin or was refused above:
      track.json    <- score.py   (reads ideas.json and the previous track.json: a research session that
                                   appends an idea and its scorecard row mid-run keeps both)
      signals.json  <- signals.py (reads the committed price panels only; no network)
    A rebuild that exits non-zero or does not parse leaves origin's copy, with a ::warning::.

The decisions are printed, appended to $GITHUB_STEP_SUMMARY, written to OUT/landing.txt (the commit body)
and recorded in feeds_status.json as `landing`, so what a run did NOT land can be read off the file.
"""
import gzip
import json
import os
import shutil
import subprocess
import sys

IDEAS = "docs/ideas/"
# One builder's outputs. A path ending in '/' is a prefix. A scan/<date>.json file is its own group (one
# day's read); any other path not listed here is its own group too.
GROUPS = {
    "govt.py": ["docs/ideas/govt.json"],
    "spot.py": [
        "docs/ideas/spot.json",
        "docs/ideas/spot_series.json",
        "docs/ideas/spot_history.csv",
    ],
    # india_spot.py reads minsteel.py's file into india_spot.json and india_history.json.gz: one read.
    "minsteel.py + india_spot.py": [
        "docs/ideas/minsteel_mumbai.json",
        "docs/ideas/india_spot.json",
        "docs/ideas/india_spot_history.csv",
        "docs/ideas/nmdc_history.json",
        "docs/ideas/india_history.json.gz",
    ],
    "wpi.py": ["docs/ideas/wpi.json.gz"],
    "trade.py": ["docs/ideas/trade/"],
    "universe.py": ["docs/ideas/universe.json"],
}
DERIVED = {
    "docs/ideas/track.json": {
        "cmd": "scripts/ideas/score.py",
        "inputs": ["docs/ideas/track.json", "docs/ideas/ideas.json"],
    },
    "docs/ideas/signals.json": {
        "cmd": "scripts/ideas/signals.py",
        "inputs": [
            "docs/ideas/signals.json",
            "docs/ideas/commodity_map.json",
            "docs/ideas/spot.json",
            "docs/ideas/wpi.json.gz",
            "docs/ideas/trade/",
            "docs/ideas/india_spot.json",
            "docs/ideas/india_history.json.gz",
            "docs/ideas/india_spot_history.csv",
            "docs/ideas/india_retracted.csv",
        ],
    },
}
STATUS = "docs/ideas/feeds_status.json"


def git(*args, ok=(0,)):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode not in ok:
        raise SystemExit(f"git {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()[:400]}")
    return r.stdout


def blob(rev, path):
    """Blob id of path at rev, or None when rev has no such file. Tree-level: reads no file content."""
    out = git("rev-parse", "--verify", "-q", f"{rev}:{path}", ok=(0, 1)).strip()
    return out or None


def file_blob(path):
    return git("hash-object", "--", path).strip() if os.path.isfile(path) else None


def matches(path, patterns):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in patterns)


def group_of(path):
    for name, pats in GROUPS.items():
        if matches(path, pats):
            return name
    return path


def origin_commits(base, path):
    """The commits origin landed on path since BASE, newest first: '<sha> <author>: <subject>'."""
    out = (
        git("log", "--format=%h %an: %s", f"{base}..HEAD", "--", path, ok=(0, 128))
        .strip()
        .splitlines()
    )
    return [ln[:140] for ln in out[:3]] or [
        f"origin/main {git('rev-parse', '--short', 'HEAD').strip()}"
    ]


def snapshot(base, out, paths):
    head = git("rev-parse", "HEAD").strip()
    if head != base:
        raise SystemExit(
            f"snapshot must run on the builders' tree: HEAD {head[:9]} is not BASE {base[:9]}"
        )
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    raw = git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *paths)
    changed = []
    for ent in raw.split("\0"):
        if len(ent) < 4:
            continue
        xy, path = ent[:2], ent[3:]
        if "D" in xy or not os.path.isfile(path):
            continue  # the builders never delete an output; a vanished file is not something to land
        changed.append(path)
        os.makedirs(os.path.join(out, os.path.dirname(path)), exist_ok=True)
        shutil.copy2(path, os.path.join(out, path))
    changed.sort()
    json.dump(
        {"base": base, "files": changed}, open(os.path.join(out, "manifest.json"), "w"), indent=1
    )
    print(f"snapshot: this run changed {len(changed)} file(s) against {base[:9]}:")
    for f in changed:
        print("  " + f)


def parses(path):
    try:
        if path.endswith(".gz"):
            json.load(gzip.open(path, "rt"))
        elif path.endswith(".json"):
            json.load(open(path))
        return True
    except Exception:
        return False


def restore_origin(path):
    if blob("HEAD", path):
        git("checkout", "HEAD", "--", path)
    elif os.path.exists(path):
        os.remove(path)


def warn(msg):
    print(f"::warning title=ideas-feeds landing::{msg}", flush=True)


def apply(base, out):
    man = json.load(open(os.path.join(out, "manifest.json")))
    if man["base"] != base:
        raise SystemExit(f"manifest was taken on {man['base'][:9]}, not BASE {base[:9]}")
    changed = man["files"]
    head = git("rev-parse", "HEAD").strip()
    moved = set(git("diff", "--name-only", base, head, "--", IDEAS).split())
    print(
        f"apply: onto origin/main {head[:9]}; origin changed {len(moved)} docs/ideas/ file(s) since {base[:9]}"
        + (": " + ", ".join(sorted(moved)) if moved else "")
    )

    # 1. Files both sides changed, to different bytes. Their builder's files are refused as a set.
    conflict = {}
    for f in changed:
        if f in DERIVED or f not in moved:
            continue
        if file_blob(os.path.join(out, f)) != blob(head, f):
            conflict[f] = origin_commits(base, f)
    refused_groups = {group_of(f) for f in conflict}

    landed, same, refused, rebuilt = [], [], [], []
    for f in changed:
        if f in DERIVED:
            continue
        g = group_of(f)
        if g in refused_groups:
            if f in conflict:
                why = "origin changed it during the run: " + " | ".join(conflict[f])
            else:
                why = (
                    f"kept with its builder ({g}), whose "
                    + ", ".join(sorted(c for c in conflict if group_of(c) == g))
                    + " origin changed during the run"
                )
            refused.append({"file": f, "why": why})
            warn(f"kept origin's {f}, this run's copy NOT landed - {why}")
            continue
        if f in moved and file_blob(os.path.join(out, f)) == blob(head, f):
            same.append(f)
            continue
        os.makedirs(os.path.dirname(f) or ".", exist_ok=True)
        shutil.copy2(os.path.join(out, f), f)
        landed.append(f)

    # 2. Derived files: rebuild on the tree as it now stands when anything they read moved or was refused.
    refused_files = [r["file"] for r in refused]
    for d, spec in DERIVED.items():
        because = sorted(f for f in moved if matches(f, spec["inputs"])) + sorted(
            f"{f} (refused)" for f in refused_files if matches(f, spec["inputs"])
        )
        if not because:
            if d in changed:
                shutil.copy2(os.path.join(out, d), d)
                landed.append(d)
            continue
        print(
            f"rebuild {d}: {spec['cmd']} on the fresh tree, because " + ", ".join(because),
            flush=True,
        )
        r = subprocess.run(
            [sys.executable, "-X", "utf8", spec["cmd"]], capture_output=True, text=True, timeout=900
        )
        tail = (r.stdout + r.stderr).strip().splitlines()[-6:]
        for ln in tail:
            print("    " + ln)
        if r.returncode != 0 or not parses(d):
            restore_origin(d)
            why = f"rebuild failed (exit {r.returncode}{', output does not parse' if r.returncode == 0 else ''})"
            refused.append({"file": d, "why": why + "; origin's copy kept"})
            warn(f"kept origin's {d}: {why}; its inputs moved on origin ({', '.join(because)})")
            continue
        rebuilt.append({"file": d, "because": because})
        print(
            f"::notice title=ideas-feeds landing::rebuilt {d} on origin/main {head[:9]} because "
            + ", ".join(because)
        )

    # 3. Record what landed, so a refusal can be read off the committed file and not only off a run log.
    rec = {
        "base": base[:9],
        "onto": head[:9],
        "moved_on_origin": sorted(moved),
        "landed": len(landed),
        "identical": len(same),
        "refused": refused,
        "rebuilt": rebuilt,
    }
    if STATUS in landed:
        try:
            st = json.load(open(STATUS))
            st["landing"] = rec
            json.dump(st, open(STATUS, "w"), indent=1)
        except Exception as e:
            warn(f"could not record the landing in {STATUS}: {e}")
    lines = [f"Landed {len(landed)} file(s) built on {base[:9]} onto origin/main {head[:9]}."]
    lines += [f"Rebuilt {x['file']} on origin: " + ", ".join(x["because"]) for x in rebuilt]
    lines += [f"NOT landed {x['file']}: {x['why']}" for x in refused]
    open(os.path.join(out, "landing.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write("### Landing\n\n" + "\n".join("- " + ln for ln in lines) + "\n")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "snapshot":
        snapshot(sys.argv[2], sys.argv[3], sys.argv[4:] or [IDEAS])
    elif len(sys.argv) == 4 and sys.argv[1] == "apply":
        apply(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(__doc__)
