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


#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bring the shared checkout (or any worktree) up to origin/main WITHOUT losing anyone's
work, and garbage-collect worktrees that hold nothing unique.  Runbook §107.

Why this exists: the shared checkout drifted 900+ commits behind origin while its
session-start banner listed 16 "dirty" files and "23 commits ahead" — every one of them a
STALE COPY of something already on origin (measured 2026-08-23).  Meanwhile 36 worktrees
sat around, most of them abandoned.  Models reading different copies reported different
coverage counts and backtest results for the same question.

The rule it enforces: ONE source of truth = origin/main.  A local copy is either exactly
what origin has (refresh it), an OLDER version origin once committed (refresh it, keep a
backup), or real work-in-progress (never touched; sync refuses if it collides).

Modes:
  status [--tree PATH]                read-only classification, writes nothing
  sync   [--tree PATH] [--dry-run] [--trust SHA,..] [--no-fetch] [--for-hook]
  gc     [--dry-run] [--idle-hours N] [--for-hook]   remove worktrees with nothing unique

Every decision is MEASURED (git blob ids / commit content), never guessed:
  commit  '+' (git cherry) is "upstream" iff every file it touched is byte-identical at
          origin/main, OR origin has a same-subject commit with the same author time
          (the cherry-pick-through-a-worktree signature, runbook §38), OR it is --trust'ed
          by a human who verified it.  Otherwise it is UNIQUE and sync refuses.
  file    dirty/untracked is "stale" iff its bytes equal origin/main's copy, or equal a
          blob origin committed for that path in its last 600 commits.  Otherwise it is
          WIP: kept as-is; if origin ALSO changed that file since our HEAD, sync refuses
          (git reset --keep would refuse too — nothing is ever overwritten).

Moving HEAD uses `git reset --keep` — the variant that keeps local edits and aborts on
any collision — never --hard.  Refreshed stale files are copied to
~/stocks-backups/sync-<stamp>/ first, and if local commits are dropped from `main` a
`backup/main-<stamp>` branch keeps them reachable.
"""
import argparse
import contextlib
import datetime
import os
import shutil
import subprocess
import sys
import time

MAIN = "/Users/dhruvan/stocks-dashboard"
TARGET = "origin/main"
HISTORY_DEPTH = 600
TWIN_SECONDS = 900
BACKUP_ROOT = os.path.expanduser("~/stocks-backups")


# ----------------------------------------------------------------------------- git plumbing
def git(args, cwd, timeout=60, check=False):
    r = subprocess.run(
        ["git", *list(args)],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if check and r.returncode != 0:
        msg = "git {} failed: {}".format(" ".join(args), (r.stderr or r.stdout).strip())
        raise RuntimeError(msg)
    return r.returncode, (r.stdout or ""), (r.stderr or "")


def out(args, cwd, timeout=60):
    return git(args, cwd, timeout)[1]


def rev(cwd, spec):
    rc, o, _ = git(["rev-parse", "-q", "--verify", spec], cwd)
    return o.strip() if rc == 0 and o.strip() else None


def blob_at(cwd, ref, path):
    return rev(cwd, f"{ref}:{path}")


def hash_file(cwd, path):
    full = os.path.join(cwd, path)
    if not os.path.isfile(full):
        return None
    return out(["hash-object", "--", path], cwd, timeout=120).strip() or None


_hist_cache = {}


def history_blobs(cwd, path):
    """Blob ids origin/main ever committed for `path` (last HISTORY_DEPTH commits).
    Uses `log --raw` (tree diffs only): this repo is a PARTIAL CLONE (blob:none), so anything
    that touches blob CONTENT (cat-file, patch-id, diff) lazily fetches from GitHub and stalls."""
    key = (cwd, path)
    if key in _hist_cache:
        return _hist_cache[key]
    raw = out(
        ["log", "-n", str(HISTORY_DEPTH), "--format=", "--raw", "--no-abbrev", "--no-renames", TARGET, "--", path],
        cwd,
        timeout=120,
    )
    blobs = set()
    for line in raw.splitlines():
        if line.startswith(":"):
            parts = line.split()
            if len(parts) >= 4:
                blobs.update(b for b in parts[2:4] if b and not set(b) <= {"0"})
    _hist_cache[key] = blobs
    return blobs


# ----------------------------------------------------------------------------- classification
def classify_commit(cwd, sha, trusted):
    """-> (verdict, subject).  verdict in upstream-identical | upstream-twin | trusted | unique"""
    subject = out(["log", "-1", "--format=%s", sha], cwd).strip()
    if any(sha.startswith(t) for t in trusted):
        return "trusted", subject
    files = [f for f in out(["show", "--name-only", "--no-renames", "--format=", sha], cwd).splitlines() if f]
    if files and all(blob_at(cwd, sha, f) == blob_at(cwd, TARGET, f) for f in files):
        return "upstream-identical", subject
    atime = out(["log", "-1", "--format=%at", sha], cwd).strip()
    adate = out(["log", "-1", "--format=%ai", sha], cwd).strip()
    if atime.isdigit() and subject:
        twins = out(["log", TARGET, "--format=%at", "-F", "--grep=" + subject, "--since=" + adate], cwd)
        for t in twins.split():
            if t.isdigit() and abs(int(t) - int(atime)) <= TWIN_SECONDS:
                return "upstream-twin", subject
    return "unique", subject


def classify_file(cwd, path, tracked):
    """-> (cls, detail).  cls in same | old-build | wip | wip-collides | leftover | untracked-collides | deleted"""
    wt = hash_file(cwd, path)
    tgt = blob_at(cwd, TARGET, path)
    head = blob_at(cwd, "HEAD", path)
    if wt is None:  # deleted in the working tree
        if tracked:
            return ("deleted-collides" if tgt != head else "deleted"), ""
        return "leftover", "vanished"
    if tgt is not None and wt == tgt:
        return "same", ""
    if tgt is not None and wt in history_blobs(cwd, path):
        return "old-build", ""
    if not tracked:
        return ("leftover", "not on origin") if tgt is None else ("untracked-collides", "")
    return ("wip-collides" if (tgt != head) else "wip"), ""


def status_entries(cwd):
    """[(xy, path, tracked)] from `git status --porcelain -z -uall` (handles spaces/renames)."""
    raw = out(["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd, timeout=120)
    items = raw.split("\0")
    res, i = [], 0
    while i < len(items):
        it = items[i]
        if not it:
            i += 1
            continue
        xy, path = it[:2], it[3:]
        if xy[0] in "RC":  # rename/copy: next NUL field is the old path
            i += 1
        res.append((xy, path, xy != "??"))
        i += 1
    return res


def classify_tree(cwd, trusted=()):
    head = rev(cwd, "HEAD")
    tgt = rev(cwd, TARGET)
    if git(["merge-base", "--is-ancestor", "HEAD", TARGET], cwd)[0] == 0:
        cherry = []  # nothing local-only: skip the (blob-fetching) patch-id pass
    else:
        try:  # patch-ids need blob content -> lazy fetch in this partial clone
            cherry = out(["cherry", TARGET, "HEAD"], cwd, timeout=240).splitlines()
        except subprocess.TimeoutExpired:
            cherry = ["+ " + l for l in out(["rev-list", f"{TARGET}..HEAD"], cwd).split()]
    ahead = [l.split()[1] for l in cherry if l.startswith("+")]
    dup = sum(1 for l in cherry if l.startswith("-"))
    behind = out(["rev-list", "--count", f"HEAD..{TARGET}"], cwd).strip()
    commits = [(sha, *classify_commit(cwd, sha, trusted)) for sha in ahead]
    files = [(xy, p, tracked, *classify_file(cwd, p, tracked)) for xy, p, tracked in status_entries(cwd)]
    return {"head": head, "target": tgt, "behind": int(behind or 0), "dup": dup, "commits": commits, "files": files}


def blockers(info):
    b = []
    for sha, verdict, subj in info["commits"]:
        if verdict == "unique":
            b.append(
                f'local commit {sha[:9]} "{subj[:60]}" has content NOT on origin -> push it (runbook '
                "§38 worktree cherry-pick recipe); if you have VERIFIED it is already "
                f"upstream under another shape, rerun with --trust {sha[:9]}"
            )
    for _xy, p, _tracked, cls, _detail in info["files"]:
        if cls == "wip-collides":
            b.append(
                f"work-in-progress file {p} was edited here AND changed on origin -> "
                "commit+push it, or move it to a worktree (cp it out, sync, cp back)"
            )
        elif cls == "untracked-collides":
            b.append(
                f"untracked file {p} exists on origin with DIFFERENT content -> rename it "
                "or delete it if it is a leftover"
            )
        elif cls == "deleted-collides":
            b.append(
                f"{p} is deleted here but origin changed it -> restore it "
                f"(git checkout origin/main -- {p}) or push the deletion"
            )
    return b


# ----------------------------------------------------------------------------- reporting
def now_ist():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M IST")


def summarize(info, tree):
    lines = []
    lines.append(
        "tree %s: HEAD %s, origin/main %s, %d behind, %d local-only commit(s) "
        "(+%d duplicates of upstream patches)"
        % (
            tree,
            (info["head"] or "?")[:9],
            (info["target"] or "?")[:9],
            info["behind"],
            len(info["commits"]),
            info["dup"],
        )
    )
    for sha, verdict, subj in info["commits"]:
        lines.append("  commit %s %-18s %s" % (sha[:9], verdict, subj[:70]))
    buckets = {}
    for _xy, p, _tracked, cls, _detail in info["files"]:
        buckets.setdefault(cls, []).append(p)
    names = {
        "same": "stale copy, identical to origin",
        "old-build": "stale copy (an older committed build)",
        "wip": "work-in-progress, kept",
        "wip-collides": "WIP that COLLIDES with origin",
        "leftover": "untracked leftover (not on origin), left alone",
        "untracked-collides": "untracked but origin has a different file",
        "deleted": "deleted here (origin unchanged), kept",
        "deleted-collides": "deleted here but origin changed it",
    }
    for cls in [
        "same",
        "old-build",
        "wip",
        "wip-collides",
        "leftover",
        "untracked-collides",
        "deleted",
        "deleted-collides",
    ]:
        if cls in buckets:
            ps = buckets[cls]
            shown = ", ".join(ps[:6]) + (" … +%d more" % (len(ps) - 6) if len(ps) > 6 else "")
            lines.append("  %2d file(s) %-42s %s" % (len(ps), names[cls] + ":", shown))
    return lines


# ----------------------------------------------------------------------------- sync
def do_sync(tree, dry_run, trusted, fetch, for_hook):
    log = []
    say = log.append
    if not os.path.isdir(os.path.join(tree)) or not rev(tree, "HEAD"):
        say(f"[sync] {tree} is not a git tree — nothing done")
        return log, False
    gitdir = out(["rev-parse", "--absolute-git-dir"], tree).strip()
    common = out(["rev-parse", "--git-common-dir"], tree).strip()
    common = common if os.path.isabs(common) else os.path.join(tree, common)
    if any(os.path.exists(os.path.join(d, "index.lock")) for d in (gitdir, common)):
        say("[sync] another git process holds index.lock — skipped this time")
        return log, False
    lock = os.path.join(gitdir, "sync_checkout.lock")
    try:
        if os.path.exists(lock) and time.time() - os.path.getmtime(lock) < 600:
            say("[sync] another sync is running (lock < 10 min old) — skipped")
            return log, False
        with open(lock, "w") as f:
            f.write(str(os.getpid()))
        if fetch:
            rc, _, err = git(["fetch", "origin", "-q"], tree, timeout=90)
            if rc != 0:
                say(f"[sync] git fetch failed ({err.strip()[:120]}) — comparing against the LAST fetched origin/main")
        info = classify_tree(tree, trusted)
        clean = not info["files"] and info["head"] == info["target"]
        if clean:
            say("[sync] ✓ {} is at origin/main {} and clean ({})".format(tree, info["target"][:9], now_ist()))
            return log, True
        bl = blockers(info)
        for l in summarize(info, tree):
            say("[sync] " + l)
        if bl:
            say("[sync] ✗ NOT synced — %d blocker(s):" % len(bl))
            for b in bl:
                say("[sync]   - " + b)
            say("[sync]   nothing was changed. Fix the blocker(s) and rerun: python3 scripts/sync_checkout.py sync")
            return log, False
        if dry_run:
            say("[sync] (dry-run) would refresh stale copies, keep WIP, and `git reset --keep origin/main`")
            return log, False
        # --- act
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        bdir = os.path.join(BACKUP_ROOT, "sync-" + stamp)
        refreshed, kept, removed = [], [], []
        for _xy, p, tracked, cls, _detail in info["files"]:
            if cls in ("same", "old-build"):
                if cls == "old-build" or not tracked:
                    dst = os.path.join(bdir, p)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(os.path.join(tree, p), dst)
                if tracked:
                    git(["checkout", TARGET, "--", p], tree, timeout=120, check=True)
                    refreshed.append(p)
                else:
                    os.remove(os.path.join(tree, p))  # reset --keep re-creates it, tracked
                    removed.append(p)
            elif cls in ("wip", "deleted", "leftover"):
                kept.append(p)
        if info["commits"]:
            branch = out(["rev-parse", "--abbrev-ref", "HEAD"], tree).strip()
            if branch and branch != "HEAD":
                bname = f"backup/{branch}-{stamp}"
                git(["branch", bname, "HEAD"], tree)
                say(
                    "[sync] %d local-only commit(s) leave `%s`; still reachable as %s"
                    % (len(info["commits"]), branch, bname)
                )
        rc, o, err = git(["reset", "--keep", TARGET], tree, timeout=300)
        if rc != 0:
            say(f"[sync] ✗ git reset --keep refused: {(err or o).strip()[:300]}")
            say(f"[sync]   stale copies were refreshed from origin (backups in {bdir}); HEAD unchanged")
            return log, False
        post = classify_tree(tree, trusted)
        say(
            "[sync] refreshed %d stale copies%s, kept %d WIP file(s)%s"
            % (
                len(refreshed) + len(removed),
                (f" (backups: {bdir})") if os.path.isdir(bdir) else "",
                len(kept),
                (": " + ", ".join(kept[:8])) if kept else "",
            )
        )
        say(
            "[sync] ✓ %s now at origin/main %s, %d uncommitted file(s) remain (%s)"
            % (tree, post["target"][:9], len(post["files"]), now_ist())
        )
        return log, True
    finally:
        with contextlib.suppress(OSError):
            os.remove(lock)


# ----------------------------------------------------------------------------- gc worktrees
def worktrees():
    res, cur = [], {}
    for line in [*out(["worktree", "list", "--porcelain"], MAIN).splitlines(), ""]:
        if not line:
            if cur:
                res.append(cur)
            cur = {}
        elif line.startswith("worktree "):
            cur["path"] = line[9:]
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch "):
            cur["branch"] = line[7:]
        elif line == "detached":
            cur["branch"] = None
        elif line.startswith("prunable"):
            cur["prunable"] = True
    return res


DISPOSABLE = ("/_cache/", "docs/.sf_updated", "/__pycache__/", ".DS_Store")


def idle_hours(wt, files):
    """Hours since the last WRITE in this worktree: newest of HEAD/ORIG_HEAD (commit, checkout,
    reset) and any dirty/untracked file.  NOT the index (a read-only `git status` rewrites it)
    and NOT logs/HEAD (reflog maintenance from the main repo touches every worktree's)."""
    gd = out(["rev-parse", "--absolute-git-dir"], wt).strip()
    newest = 0
    for f in ("ORIG_HEAD", "HEAD"):
        p = os.path.join(gd, f)
        if os.path.exists(p):
            newest = max(newest, os.path.getmtime(p))
    for entry in files:
        p = os.path.join(wt, entry[1])
        if os.path.exists(p):
            newest = max(newest, os.path.getmtime(p))
    return (time.time() - newest) / 3600.0 if newest else 1e9


def do_gc(dry_run, idle_min, for_hook, protect, trusted=()):
    log = []
    say = log.append
    git(["worktree", "prune"], MAIN)
    wts = worktrees()
    if not wts:
        return log
    main_path = os.path.realpath(wts[0]["path"])
    removed, kept = [], []
    for w in wts[1:]:
        path = w["path"]
        if os.path.realpath(path) == main_path or os.path.realpath(path) in protect:
            continue
        if not os.path.isdir(path):
            continue
        info = classify_tree(path, trusted)
        idle = idle_hours(path, info["files"])
        unique_commits = [c for c in info["commits"] if c[1] == "unique"]
        wip = [
            f
            for f in info["files"]
            if f[3] not in ("same", "old-build") and not any(d in "/" + f[1] for d in DISPOSABLE)
        ]
        label = "%s (%s, idle %.0fh, %d behind)" % (
            path.replace("/Users/dhruvan/", "~/"),
            (w.get("branch") or "detached").replace("refs/heads/", ""),
            idle,
            info["behind"],
        )
        if unique_commits or wip:
            why = []
            if unique_commits:
                why.append(
                    "%d unpushed commit(s): %s"
                    % (len(unique_commits), "; ".join(f"{c[0][:9]} {c[2][:40]}" for c in unique_commits[:2]))
                )
            if wip:
                why.append(
                    "%d file(s) with content not on origin: %s"
                    % (len(wip), ", ".join(f[1] for f in wip[:4]) + (" …" if len(wip) > 4 else ""))
                )
            kept.append((label, why))
            continue
        if idle < idle_min:
            kept.append((label, ["active within %dh — nothing unique in it; gc later" % idle_min]))
            continue
        stale = list(info["files"])
        if dry_run:
            removed.append(label + (" [%d stale copies]" % len(stale) if stale else ""))
            continue
        args = ["worktree", "remove"] + (["--force"] if stale else []) + [path]
        rc, o, err = git(args, MAIN, timeout=300)
        if rc == 0:
            removed.append(label)
        else:
            kept.append((label, ["git worktree remove failed: " + (err or o).strip()[:120]]))
    git(["worktree", "prune"], MAIN)
    if removed:
        say("[gc] %s %d worktree(s) holding nothing unique:" % ("would remove" if dry_run else "removed", len(removed)))
        for r in removed:
            say("[gc]   - " + r)
    if kept:
        say("[gc] kept %d worktree(s):" % len(kept))
        for label, why in kept:
            say(f"[gc]   - {label}")
            for y in why:
                say(f"[gc]       {y}")
    if not removed and not kept:
        say("[gc] no extra worktrees")
    return log


# ----------------------------------------------------------------------------- cli
def main(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["status", "sync", "gc"])
    ap.add_argument("--tree", default=MAIN)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--trust", default="", help="comma-separated SHAs a human VERIFIED are upstream")
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--idle-hours", type=float, default=24)
    ap.add_argument("--protect", default="", help="comma-separated worktree paths gc must never touch")
    ap.add_argument("--for-hook", action="store_true", help="terse output for the session-start banner")
    a = ap.parse_args(argv)
    trusted = [t.strip() for t in a.trust.split(",") if t.strip()]
    tree = os.path.realpath(os.path.expanduser(a.tree))
    if a.mode == "status":
        if not a.no_fetch:
            git(["fetch", "origin", "-q"], tree, timeout=90)
        info = classify_tree(tree, trusted)
        for l in summarize(info, tree):
            print(l)
        bl = blockers(info)
        print("blockers: %d" % len(bl))
        for b in bl:
            print("  - " + b)
        return 0
    if a.mode == "sync":
        log, ok = do_sync(tree, a.dry_run, trusted, not a.no_fetch, a.for_hook)
        print("\n".join(log))
        return 0 if ok or a.for_hook else 1
    if a.mode == "gc":
        protect = {os.path.realpath(os.path.expanduser(p)) for p in a.protect.split(",") if p.strip()}
        protect.add(os.path.realpath(os.getcwd()))
        print("\n".join(do_gc(a.dry_run, a.idle_hours, a.for_hook, protect, trusted)))
        return 0
    return None


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
