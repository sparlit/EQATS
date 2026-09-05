#!/usr/bin/env python3
"""Pre-commit feed guard (DATA_RUNBOOK.md section 18).

Run inside CI right after a fetch/build step, BEFORE the commit step.
Looks at every modified tracked .json/.bin/.html under docs/ or scripts/
and refuses (exit 1) to let a broken or drastically shrunken file replace
the good committed copy:

  - .json must parse
  - new size must be >= min_ratio * committed size (per-file min_ratio from
    docs/feeds.json; feeds that legitimately shrink set min_ratio 0)
  - new size must be >= min_bytes (from docs/feeds.json when listed)

A guard failure fails the workflow loudly (so the feed-monitor/auto-rerun
notice it) and the previous good data stays live. Deleted files are ignored
(deletions are assumed intentional).
"""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RATIO = {".json": 0.5, ".bin": 0.9, ".html": 0.5}


def git(*args):
    return subprocess.run(["git"] + list(args), capture_output=True, text=True, cwd=ROOT)


def main():
    # per-file rules from the manifest
    rules = {}
    try:
        with open(os.path.join(ROOT, "docs", "feeds.json"), encoding="utf-8") as fh:
            for f in json.load(fh)["feeds"]:
                rules["docs/" + f["file"]] = f
    except Exception as e:
        print(f"guard: could not read docs/feeds.json ({e}) — using defaults only")

    changed = set()
    for cmd in (["diff", "--name-only", "HEAD"], ["diff", "--name-only", "--cached"]):
        changed.update(p for p in git(*cmd).stdout.split("\n") if p)

    problems = []
    checked = 0
    for path in sorted(changed):
        ext = os.path.splitext(path)[1]
        if ext not in DEFAULT_RATIO or not (path.startswith("docs/") or path.startswith("scripts/")):
            continue
        full = os.path.join(ROOT, path)
        if not os.path.exists(full):
            continue  # deletion — intentional
        checked += 1
        rule = rules.get(path, {})
        new_size = os.path.getsize(full)

        if ext == ".json":
            try:
                with open(full, encoding="utf-8") as fh:
                    json.load(fh)
            except Exception as e:
                problems.append(f"{path}: INVALID JSON — {str(e)[:100]}")
                continue

        min_bytes = rule.get("min_bytes", 1)
        if new_size < min_bytes:
            problems.append(f"{path}: {new_size} B < manifest min_bytes {min_bytes}")
            continue

        old = git("cat-file", "-s", f"HEAD:{path}")
        if old.returncode != 0:
            continue  # new file — nothing to compare against
        old_size = int(old.stdout.strip())
        ratio = rule.get("min_ratio", DEFAULT_RATIO[ext])
        if ratio and old_size > 4096 and new_size < ratio * old_size:
            problems.append(
                f"{path}: shrank {old_size} -> {new_size} B "
                f"({new_size/old_size:.0%}, floor {ratio:.0%}) — refusing to overwrite good data")

    if problems:
        print("FEED GUARD FAILED — nothing was committed; the previous good data stays live.")
        for p in problems:
            print("  !! " + p)
        print("Investigate the fetch step's output above; if the shrink is legitimate,")
        print("adjust min_ratio/min_bytes for that file in docs/feeds.json.")
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("### Feed guard failed\n" + "\n".join("- " + p for p in problems) + "\n")
        sys.exit(1)
    print(f"feed guard OK — {checked} changed feed file(s) sane")


if __name__ == "__main__":
    main()
