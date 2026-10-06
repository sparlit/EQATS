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


"""Land a CI job's outputs on origin/main without reverting anyone else's commit (runbook §212).

The generalised form of scripts/ideas/land_feeds.py (§144g). A refresh workflow builds its files from the
commit it checked out (BASE), then pushes minutes (sometimes hours) later. Its commit step used to
`git reset --hard origin/main` and `cp` every output WHOLE over whatever origin held by then, so a commit
another writer (a session, a routine PR, another workflow) landed on one of those paths during the run was
silently reverted. Measured on origin 2026-09-28: refresh-backtest-data did it twice in 30 days, byte for byte -
f6169f292 put scripts/unconfirmed_ca.json back to `{}` ten minutes after the §161g routine parked three
WRONG_FACTOR events in it (4d4be240c), and c0971890e undid fb9ea4cde's demerger_adj.json four minutes after it
landed. This script replaces the copy. Three subcommands, all run from the repository root:

  snapshot BASE OUT PATH...   On the builders' own tree, before any reset. Copies to OUT only the files under
                              PATH (a file, or a directory) this run CHANGED - their bytes differ from BASE's
                              blob, or they are new - and writes OUT/manifest.json. A file the run left alone is
                              never copied, so it can never revert anything. A file the run deleted is ignored
                              (no workflow using this lands deletions).
  apply BASE OUT [--each] [--group 'P P...']... [--single 'P P...']...
                              On a fresh `git reset --hard origin/main`, once per push attempt. Per changed file:
      origin still holds BASE's copy  -> this run's copy lands;
      origin holds the same bytes     -> nothing to do;
      origin changed it too           -> origin's copy STAYS, a ::warning:: names the file and origin's commit(s),
                                         and every other file of the same GROUP is held back with it.
    Groups say which outputs are one read and must land together or not at all. By DEFAULT everything the run
    changed is one group. --each makes every file its own group. --group 'A B dir/' binds those paths into one
    group (a path ending in / is a prefix). --single 'dir/' makes each matching file its own group whatever else
    is set - for one-time captures (a dated snapshot of a list the source never serves again) that must not be
    held back by an unrelated conflict. The decisions go to stdout, OUT/landing.txt (the commit body),
    OUT/landing.json (`refused` = what did NOT land) and $GITHUB_STEP_SUMMARY.
  unchanged BASE PATH...      Exit 0 when origin still holds BASE's copy of every PATH; otherwise a ::warning::
                              naming origin's commit(s) and exit 1. The gate for a copy the step makes itself
                              under its own condition (refresh.yml's dash_slim.bin / stock_data.bin).

A refused file is not lost work in these jobs: the next run rebuilds it from origin's (newer) copy. Where a job
keeps state OUTSIDE git that would advance anyway (xbrl-extra-nightly's seen-set in the Actions cache), the
workflow must not save that state when landing.json lists a refusal.

Tree-level only (ls-tree / hash-object / log): this repo is a blob:none partial clone and the runner a depth-1
checkout; nothing here reads an old blob's content.
"""
import json
import os
import shutil
import subprocess
import sys

TITLE = os.environ.get("GITHUB_WORKFLOW") or "ci_land"


def git(*args, ok=(0,), inp=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, input=inp)
    if r.returncode not in ok:
        raise SystemExit(
            f"git {' '.join(args)[:200]} failed ({r.returncode}): {r.stderr.strip()[:400]}"
        )
    return r.stdout


def tree(rev, paths):
    """{path: blob id} for every file under `paths` at `rev`. Tree level: reads no file content."""
    if not paths:
        return {}
    out = {}
    for ent in git("ls-tree", "-r", "-z", "--full-tree", rev, "--", *paths).split("\0"):
        if not ent:
            continue
        meta, path = ent.split("\t", 1)
        if meta.split()[1] == "blob":
            out[path] = meta.split()[2]
    return out


def hashes(paths):
    """{path: blob id} of the files as they are on disk now (what `git add` would store)."""
    if not paths:
        return {}
    got = git("hash-object", "--stdin-paths", inp="\n".join(paths) + "\n").split()
    return dict(zip(paths, got, strict=False))


def matches(path, pats):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in pats)


def warn(msg):
    print(f"::warning title={TITLE} landing::{msg}", flush=True)


def origin_commits(base, path):
    """The commits origin landed on `path` since BASE, newest first: '<sha> <author>: <subject>'."""
    out = (
        git("log", "--format=%h %an: %s", f"{base}..HEAD", "--", path, ok=(0, 128))
        .strip()
        .splitlines()
    )
    return [ln[:140] for ln in out[:3]] or [
        f"origin/main {git('rev-parse', '--short', 'HEAD').strip()}"
    ]


def snapshot(base, out, args):
    head = git("rev-parse", "HEAD").strip()
    if head != git("rev-parse", base).strip():
        raise SystemExit(
            f"snapshot must run on the builders' tree: HEAD {head[:9]} is not BASE {base[:9]}"
        )
    at_base = tree(base, [a.rstrip("/") for a in args])
    cand = set()
    for a in args:
        p = a.rstrip("/")
        if os.path.isdir(p) or a.endswith("/") or any(f.startswith(p + "/") for f in at_base):
            cand |= {f for f in at_base if f.startswith(p + "/") and os.path.isfile(f)}
            cand |= {
                f
                for f in git("ls-files", "-z", "--others", "--exclude-standard", "--", p).split(
                    "\0"
                )
                if f and os.path.isfile(f)
            }
        elif os.path.isfile(p):
            cand.add(
                p
            )  # named explicitly: taken even when .gitignore matches it (the step add -f's it)
        elif p not in at_base:
            print(f"snapshot: {a} matches nothing (not on disk, not at {head[:9]})")
    now = hashes(sorted(cand))
    changed = sorted(f for f, b in now.items() if b != at_base.get(f))
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, "files"))
    for f in changed:
        os.makedirs(os.path.join(out, "files", os.path.dirname(f)), exist_ok=True)
        shutil.copy2(f, os.path.join(out, "files", f))
    man = {"base": head, "files": {f: {"base": at_base.get(f), "ours": now[f]} for f in changed}}
    json.dump(man, open(os.path.join(out, "manifest.json"), "w"), indent=1)
    print(
        f"snapshot: this run changed {len(changed)} file(s) against {head[:9]}"
        + (":" if changed else " - nothing to land")
    )
    for f in changed[:60]:
        print("  " + f)
    if len(changed) > 60:
        print(f"  ... and {len(changed) - 60} more")


def parse_apply(argv):
    each, groups, singles, i = False, [], [], 0
    while i < len(argv):
        a = argv[i]
        if a == "--each":
            each = True
        elif a in ("--group", "--single") and i + 1 < len(argv):
            (groups if a == "--group" else singles).append(argv[i + 1].split())
            i += 1
        else:
            raise SystemExit(f"apply: unknown argument {a!r}\n\n{__doc__}")
        i += 1
    return each, groups, singles


def apply(base, out, argv):
    each, groups, singles = parse_apply(argv)
    man = json.load(open(os.path.join(out, "manifest.json")))
    base = git("rev-parse", base).strip()
    if man["base"] != base:
        raise SystemExit(f"manifest was taken on {man['base'][:9]}, not BASE {base[:9]}")
    files = man["files"]
    head = git("rev-parse", "HEAD").strip()
    theirs = tree(head, sorted(files))

    def group_of(f):
        if any(matches(f, s) for s in singles):
            return f
        for g in groups:
            if matches(f, g):
                return " ".join(g)
        return f if each else "(everything this run changed)"

    conflict = {
        f: origin_commits(base, f)
        for f, m in files.items()
        if theirs.get(f) not in (m["base"], m["ours"])
    }
    held = {group_of(f) for f in conflict}
    landed, same, refused = [], [], []
    for f, m in sorted(files.items()):
        g = group_of(f)
        if g in held:
            if f in conflict:
                why = "origin changed it during the run: " + " | ".join(conflict[f])
            else:
                why = (
                    "held back with its group ("
                    + ", ".join(sorted(c for c in conflict if group_of(c) == g))
                    + " changed on origin during the run)"
                )
            refused.append({"file": f, "why": why})
            warn(f"kept origin's {f}, this run's copy NOT landed - {why}")
        elif theirs.get(f) == m["ours"]:
            same.append(f)
        else:
            os.makedirs(os.path.dirname(f) or ".", exist_ok=True)
            shutil.copy2(os.path.join(out, "files", f), f)
            landed.append(f)

    rec = {
        "base": base[:9],
        "onto": head[:9],
        "landed": landed,
        "identical": same,
        "refused": refused,
    }
    json.dump(rec, open(os.path.join(out, "landing.json"), "w"), indent=1)
    lines = [
        f"Landed {len(landed)} of {len(files)} changed file(s) built on {base[:9]} onto origin/main {head[:9]}"
        + (f" ({len(same)} already identical on origin)" if same else "")
        + "."
    ]
    lines += [f"NOT landed {x['file']}: {x['why']}" for x in refused]
    open(os.path.join(out, "landing.txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write("### Landing\n\n" + "\n".join("- " + ln for ln in lines) + "\n")


def unchanged(base, paths):
    head = git("rev-parse", "HEAD").strip()
    b, h = tree(base, paths), tree(head, paths)
    moved = [p for p in paths if b.get(p) != h.get(p)]
    for p in moved:
        warn(
            f"kept origin's {p}, this run's copy NOT landed - origin changed it during the run: "
            + " | ".join(origin_commits(base, p))
        )
    return 1 if moved else 0


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 4 and a[0] == "snapshot":
        snapshot(a[1], a[2], a[3:])
    elif len(a) >= 3 and a[0] == "apply":
        apply(a[1], a[2], a[3:])
    elif len(a) >= 3 and a[0] == "unchanged":
        sys.exit(unchanged(a[1], a[2:]))
    else:
        raise SystemExit(__doc__)
