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
  gc     [--dry-run] [--idle-hours N] [--budget S] [--for-hook]   remove worktrees with nothing unique
         (unique includes GITIGNORED files not on origin — `git worktree remove` deletes those
         silently, so such a worktree is kept and listed with why; runbook §107)
         --budget S (the session-start hook): least-recently-checked trees first, fresh verdicts
         skipped, stop cleanly at S seconds; per-tree verdicts in <git common dir>/sync_checkout_gc.json

Every decision is MEASURED (git blob ids / commit content), never guessed:
  commit  '+' (git cherry) is "upstream" iff every file it touched is byte-identical at
          origin/main, OR origin has a same-subject commit with the same author time
          (the cherry-pick-through-a-worktree signature, runbook §38), OR it is --trust'ed
          by a human who verified it.  Otherwise it is UNIQUE and sync refuses.
  file    dirty/untracked is "stale" iff its bytes equal origin/main's copy, or equal a
          blob origin committed for that path in its last 600 commits (widened to reach this
          tree's HEAD when it is further behind — §107a).  Otherwise it is
          WIP: kept as-is; if origin ALSO changed that file since our HEAD, sync refuses
          (git reset --keep would refuse too — nothing is ever overwritten).
          GITIGNORED files never appear in git status and reset --keep overwrites them
          silently, so every path origin ADDED since HEAD that exists here untracked (e.g. an
          in-progress scripts/_x.py) is classified the same way — ignored_in_the_way().

Moving HEAD uses `git reset --keep` — the variant that keeps local edits and aborts on
any collision — never --hard.  Refreshed stale files are copied to
~/stocks-backups/sync-<stamp>/ first, and if local commits are dropped from `main` a
`backup/main-<stamp>` branch keeps them reachable.
"""
import argparse
import contextlib
import datetime
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

MAIN = "/Users/dhruvan/stocks-dashboard"
TARGET = "origin/main"
HISTORY_DEPTH = 600
TWIN_SECONDS = 900
BACKUP_ROOT = os.path.expanduser("~/stocks-backups")


# ----------------------------------------------------------------------------- git plumbing
class BudgetExhausted(Exception):
    """A budgeted gc's deadline passed mid-check.  Checks are read-only: abandoning one is safe."""


_deadline = None  # epoch; set by a budgeted gc (--budget) only around each tree's read-only check


def git(args, cwd, timeout=60, check=False, input=None):
    capped = False
    if _deadline is not None:  # a git call never outlives the gc budget (runbook §107)
        left = _deadline - time.time()
        if left <= 0:
            raise BudgetExhausted()
        if left < timeout:
            timeout, capped = left, True
    try:
        r = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            input=input,
        )
    except subprocess.TimeoutExpired:
        if capped:  # not a slow-git TimeoutExpired: callers' fallbacks must not run
            raise BudgetExhausted()
        raise
    if check and r.returncode != 0:
        raise RuntimeError(
            "git {} failed: {}".format(" ".join(args), (r.stderr or r.stdout).strip())
        )
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


# classify_tree's batch of classify_file inputs for ONE tree: {cwd: {"wt": {path: blob},
# "HEAD": {path: id}, TARGET: {path: id}}}.  Filled on entry, dropped on exit (HEAD moves between
# classify_tree calls in do_sync).  Runbook §107: gc measured 2026-09-28 spent 202 s of 274 s on
# ONE tree — ~/stocks-wt/ann-residue's 6,008 untracked scratch files, three git processes each.
_batch = {}
_keep_paths = {}  # commit sha -> ref_paths map, kept for TARGET only


def ref_paths(cwd, sha, keep=False):
    """{path: object id} for every blob, tree and submodule in commit `sha` — exactly what
    `rev-parse sha:path` returns for a git-normalized path, for all paths in ONE tree-level
    `ls-tree -r -t` (no blob reads in this partial clone).  {} when sha is None, like rev-parse."""
    if sha in _keep_paths:
        return _keep_paths[sha]
    m = {}
    if sha:
        for rec in out(["ls-tree", "-r", "-t", "-z", "--full-tree", sha], cwd, timeout=120).split(
            "\0"
        ):
            meta, _, p = rec.partition("\t")
            if p and len(meta.split()) == 3:
                m[p] = meta.split()[2]
    if keep and sha:
        _keep_paths.clear()  # origin/main moved (a fetch): the old map is dead weight
        _keep_paths[sha] = m
    return m


def hash_many(cwd, paths):
    """{path: blob id} for the regular files among `paths` — `hash_file` for all of them in ONE
    `git hash-object --stdin-paths` (same filters: both hash the working-tree file by its path).
    A path with a newline, or starting with '"' (stdin-paths C-unquotes those), is left out and
    hashed singly by classify_file; any failure or count mismatch -> {} (all hashed singly)."""
    files = [
        p
        for p in paths
        if "\n" not in p and not p.startswith('"') and os.path.isfile(os.path.join(cwd, p))
    ]
    if not files:
        return {}
    rc, o, _ = git(
        ["hash-object", "--stdin-paths"], cwd, timeout=300, input="\n".join(files) + "\n"
    )
    ids = o.split()
    return dict(zip(files, ids, strict=False)) if rc == 0 and len(ids) == len(files) else {}


_hist_cache = {}
_depth_cache = {}


def history_depth(cwd):
    """How far back to scan origin/main for a path's blobs: HISTORY_DEPTH, widened to reach this
    tree's HEAD when it is further behind.  Runbook §107a: a fixed 600-commit window on a tree
    3,706 commits behind called docs/sw.js "WIP that COLLIDES" although it was byte-identical to
    an August origin commit — every stale copy older than the window looks like unique work.
    `rev-list --count` is tree-level (no blob fetch in this partial clone)."""
    if cwd not in _depth_cache:
        behind = out(["rev-list", "--count", "HEAD.." + TARGET], cwd).strip()
        _depth_cache[cwd] = (
            max(HISTORY_DEPTH, int(behind) + 200) if behind.isdigit() else HISTORY_DEPTH
        )
    return _depth_cache[cwd]


def history_blobs(cwd, path):
    """Blob ids origin/main ever committed for `path` (last history_depth(cwd) commits).
    Uses `log --raw` (tree diffs only): this repo is a PARTIAL CLONE (blob:none), so anything
    that touches blob CONTENT (cat-file, patch-id, diff) lazily fetches from GitHub and stalls."""
    key = (cwd, path)
    if key in _hist_cache:
        return _hist_cache[key]
    raw = out(
        [
            "log",
            "-n",
            str(history_depth(cwd)),
            "--format=",
            "--raw",
            "--no-abbrev",
            "--no-renames",
            TARGET,
            "--",
            path,
        ],
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
    files = [
        f
        for f in out(["show", "--name-only", "--no-renames", "--format=", sha], cwd).splitlines()
        if f
    ]
    if files and all(blob_at(cwd, sha, f) == blob_at(cwd, TARGET, f) for f in files):
        return "upstream-identical", subject
    atime = out(["log", "-1", "--format=%at", sha], cwd).strip()
    adate = out(["log", "-1", "--format=%ai", sha], cwd).strip()
    if atime.isdigit() and subject:
        twins = out(
            ["log", TARGET, "--format=%at", "-F", "--grep=" + subject, "--since=" + adate], cwd
        )
        for t in twins.split():
            if t.isdigit() and abs(int(t) - int(atime)) <= TWIN_SECONDS:
                return "upstream-twin", subject
    return "unique", subject


def classify_file(cwd, path, tracked):
    """-> (cls, detail).  cls in same | old-build | wip | wip-collides | leftover | untracked-collides | deleted"""
    b = _batch.get(cwd)
    if b is not None:  # inside classify_tree: same answers, batched (see _batch)
        wt = b["wt"].get(path) or hash_file(cwd, path)
        tgt, head = b[TARGET].get(path), b["HEAD"].get(path)
    else:
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


def ignored_in_the_way(cwd, listed):
    """[(xy='!!', path, False, cls, detail)] for untracked paths `git status` never lists
    (GITIGNORED — `.gitignore` has `scripts/_*`) that `git reset --keep TARGET` would destroy.
    reset --keep treats ignored files as expendable: it silently overwrites one where TARGET
    tracks that path, deletes an ignored directory where TARGET has a file, and replaces an
    ignored file with TARGET's directory — no error, no backup.  2026-09-28 08:54 it replaced an
    in-progress scripts/_shp_164r_quantmac_v4.py in the shared checkout with origin's copy
    (runbook §107).  Each such path gets classify_file's verdict: same/old-build are backed up
    and refreshed like any untracked stale copy; different bytes -> untracked-collides blocker.
    Only paths TARGET ADDS can be untracked here — a path HEAD tracks is in the index (status
    sees its edits) or shows as a staged deletion.  A tree-to-tree `diff --no-renames
    --name-only` reads no blobs (partial clone)."""
    if rev(cwd, "HEAD") == rev(cwd, TARGET):
        return []
    raw = out(
        ["diff", "--name-only", "-z", "--no-renames", "--diff-filter=A", "HEAD", TARGET],
        cwd,
        timeout=120,
    )
    added = [p for p in raw.split("\0") if p]
    parents = {}  # dir TARGET creates -> one file origin puts under it
    for p in added:
        d = os.path.dirname(p)
        while d and d not in parents:
            parents[d] = p
            d = os.path.dirname(d)

    def full(p):
        return os.path.join(cwd, p)

    cand = [p for p in added if p not in listed and os.path.lexists(full(p))]
    cand += [
        d
        for d in parents
        if d not in listed
        and os.path.lexists(full(d))
        and (os.path.islink(full(d)) or not os.path.isdir(full(d)))
    ]
    in_index = set()
    for i in range(0, len(cand), 500):
        in_index.update(
            p
            for p in out(
                ["--literal-pathspecs", "ls-files", "-z", "--"] + cand[i : i + 500], cwd
            ).split("\0")
            if p
        )
    res = []
    for p in cand:
        if p in in_index:
            continue
        xy = "??" if any(l.startswith(p + "/") for l in listed) else "!!"
        if p in parents:
            res.append(
                (
                    xy,
                    p,
                    False,
                    "untracked-collides",
                    f"is a file where origin now tracks a directory ({parents[p]})",
                )
            )
        elif os.path.islink(full(p)) or not os.path.isfile(full(p)):
            kind = (
                "symlink"
                if os.path.islink(full(p))
                else "directory"
                if os.path.isdir(full(p))
                else "special file"
            )
            res.append(
                (xy, p, False, "untracked-collides", f"is a {kind} where origin now tracks a file")
            )
        else:
            res.append((xy, p, False) + classify_file(cwd, p, False))
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
    commits = [(sha,) + classify_commit(cwd, sha, trusted) for sha in ahead]
    entries = status_entries(cwd)
    try:
        if entries:
            _batch[cwd] = {
                "wt": hash_many(cwd, [p for _, p, _ in entries]),
                "HEAD": ref_paths(cwd, head),
                TARGET: ref_paths(cwd, tgt, keep=True),
            }
        files = [(xy, p, tracked) + classify_file(cwd, p, tracked) for xy, p, tracked in entries]
        files += ignored_in_the_way(cwd, {p for _, p, _ in entries})
    finally:
        _batch.pop(cwd, None)
    return {
        "head": head,
        "target": tgt,
        "behind": int(behind or 0),
        "dup": dup,
        "commits": commits,
        "files": files,
    }


def blockers(info):
    b = []
    for sha, verdict, subj in info["commits"]:
        if verdict == "unique":
            b.append(
                f'local commit {sha[:9]} "{subj[:60]}" has content NOT on origin -> push it (runbook '
                "§38 worktree cherry-pick recipe); if you have VERIFIED it is already "
                f"upstream under another shape, rerun with --trust {sha[:9]}"
            )
    for xy, p, _tracked, cls, detail in info["files"]:
        if cls == "wip-collides":
            b.append(
                f"work-in-progress file {p} was edited here AND changed on origin -> "
                "commit+push it, or move it to a worktree (cp it out, sync, cp back)"
            )
        elif cls == "untracked-collides" and xy == "!!":
            b.append(
                "gitignored {} (git status never shows it) {} -> `git reset --keep` would "
                "replace it WITHOUT a backup: commit+push your version (git add -f) or move it "
                "out, then rerun".format(
                    p, detail or "differs from the file origin now tracks there"
                )
            )
        elif cls == "untracked-collides":
            b.append(
                "untracked {} {} -> rename it or delete it if it is a leftover".format(
                    p, detail or "exists on origin with DIFFERENT content"
                )
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
        "untracked-collides": "untracked/ignored but origin has a different file",
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
                say(
                    f"[sync] git fetch failed ({err.strip()[:120]}) — comparing against the LAST fetched origin/main"
                )
        info = classify_tree(tree, trusted)
        clean = not info["files"] and info["head"] == info["target"]
        if clean:
            say(
                "[sync] ✓ {} is at origin/main {} and clean ({})".format(
                    tree, info["target"][:9], now_ist()
                )
            )
            return log, True
        bl = blockers(info)
        for l in summarize(info, tree):
            say("[sync] " + l)
        if bl:
            say("[sync] ✗ NOT synced — %d blocker(s):" % len(bl))
            for b in bl:
                say("[sync]   - " + b)
            say(
                "[sync]   nothing was changed. Fix the blocker(s) and rerun: python3 scripts/sync_checkout.py sync"
            )
            return log, False
        if dry_run:
            say(
                "[sync] (dry-run) would refresh stale copies, keep WIP, and `git reset --keep origin/main`"
            )
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
            say(
                f"[sync]   stale copies were refreshed from origin (backups in {bdir}); HEAD unchanged"
            )
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
    for line in out(["worktree", "list", "--porcelain"], MAIN).splitlines() + [""]:
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
# The worktree's own Claude Code config (launch.json, settings.local.json, scheduled_tasks.lock):
# `.claude/*` is ignored except the tracked settings.json.  Measured 2026-09-28: 52/52
# settings.local.json byte-identical to the shared checkout's, launch.json = older snapshots of
# its preview list, the locks name dead pids.  User: disposable.  Untracked paths only.
DISPOSABLE_ROOT = (".claude/",)


def disposable(path, tracked=False):
    return (not tracked and path.startswith(DISPOSABLE_ROOT)) or any(
        d in "/" + path for d in DISPOSABLE
    )


def ignored_files(cwd):
    """This tree's GITIGNORED files — what `git worktree remove` (no --force) deletes silently:
    measured 2026-09-28, rc 0 and an ignored scripts/_wip.py gone.  `ls-files --others --ignored`
    walks the working tree against the index: no blob reads (partial clone), ~0.1 s a tree.
    None when git fails — the caller must then keep the tree, never remove it blind."""
    rc, raw, _ = git(
        ["ls-files", "-z", "--others", "--ignored", "--exclude-standard"], cwd, timeout=120
    )
    return [p for p in raw.split("\0") if p] if rc == 0 else None


_tree_cache = {}


def target_blobs(cwd):
    """{path: blob id} for every file TARGET tracks — one tree-level `ls-tree -r` per gc run
    (all worktrees share the object store and origin/main)."""
    sha = rev(cwd, TARGET)
    if sha not in _tree_cache:
        m = {}
        for rec in out(["ls-tree", "-r", "-z", "--full-tree", sha], cwd, timeout=120).split("\0"):
            meta, _, p = rec.partition("\t")
            parts = meta.split()
            if p and len(parts) == 3 and parts[1] == "blob":
                m[p] = parts[2]
        _tree_cache[sha] = m
    return _tree_cache[sha]


def ignored_unique(cwd, ignored, listed):
    """[(path, detail, bytes)] for ignored files whose content exists nowhere else — gc must not
    `git worktree remove` a tree holding them (runbook §107, trap 2026-09-28).  Not unique:
    DISPOSABLE paths, and files byte-identical to TARGET's blob or an older blob origin
    committed there (classify_file's same/old-build).  An ignored path TARGET tracks is normally
    already in `listed` (ignored_in_the_way judged it); the classify_file branch is the backstop."""
    tb = target_blobs(cwd)
    res = []
    for p in ignored:
        if p in listed or disposable(p):
            continue
        full = os.path.join(cwd, p)
        size = os.lstat(full).st_size if os.path.lexists(full) else 0
        if os.path.islink(full) or not os.path.isfile(full):
            res.append((p, "symlink" if os.path.islink(full) else "not a regular file", size))
        elif p not in tb:
            res.append((p, "not on origin", size))
        elif classify_file(cwd, p, False)[0] not in ("same", "old-build"):
            res.append((p, "differs from origin", size))
    return res


def ignored_summary(uniq, shown=4):
    """'scripts/_live/ (7 files, 226.0 MB), scripts/_x.py (8 KB) …' — grouped by the first
    directory under a top-level folder, so a 5,000-file cache is one entry."""
    groups = {}
    for p, detail, size in uniq:
        parts = p.split("/")
        key = "/".join(parts[:2]) + "/" if len(parts) > 2 else p
        n, b, _ = groups.get(key, (0, 0, ""))
        groups[key] = (n + 1, b + size, detail)

    def fmt(b):
        return "%.1f MB" % (b / 1e6) if b >= 1e6 else "%d KB" % max(1, round(b / 1e3))

    items = sorted(groups.items(), key=lambda kv: -kv[1][1])

    def one(b, d):
        return d if d in ("symlink", "not a regular file") else fmt(b)

    return ", ".join(
        "{} ({})".format(k, one(b, d) if n == 1 else "%d files, %s" % (n, fmt(b)))
        for k, (n, b, d) in items[:shown]
    ) + (" …+%d more" % (len(items) - shown) if len(items) > shown else "")


def idle_hours(wt, files, ignored=()):
    """Hours since the last WRITE in this worktree: newest of HEAD/ORIG_HEAD (commit, checkout,
    reset), any dirty/untracked file, and any gitignored file (a job writing scripts/_x.py or its
    cache IS activity; git status never lists those).  NOT the index (a read-only `git status`
    rewrites it) and NOT logs/HEAD (reflog maintenance from the main repo touches every worktree's)."""
    gd = out(["rev-parse", "--absolute-git-dir"], wt).strip()
    newest = 0
    for f in ("ORIG_HEAD", "HEAD"):
        p = os.path.join(gd, f)
        if os.path.exists(p):
            newest = max(newest, os.path.getmtime(p))
    for p in [entry[1] for entry in files] + list(ignored):
        p = os.path.join(wt, p)
        if os.path.lexists(p):
            newest = max(newest, os.lstat(p).st_mtime)
    return (time.time() - newest) / 3600.0 if newest else 1e9


GC_STATE = "sync_checkout_gc.json"  # in the COMMON git dir — never a working-tree file
GC_STATE_VERSION = 1
RECHECK_KEPT_HOURS = 24
HOOK_GC_BUDGET = 60  # --for-hook default; the guard kills gc at 90 s


def short(path):
    return path.replace("/Users/dhruvan/", "~/")


def common_dir():
    c = out(["rev-parse", "--git-common-dir"], MAIN).strip()
    return c if os.path.isabs(c) else os.path.join(MAIN, c)


def gc_lock(cdir):
    """Exclusive flock on <common git dir>/sync_checkout_gc.lock — the kernel drops it when this
    process dies, even on SIGKILL, so there is no stale lock.  Two sessions starting together
    must not check (or both try to remove) the same trees.  None = another gc holds it."""
    f = open(os.path.join(cdir, "sync_checkout_gc.lock"), "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return f
    except OSError:
        f.close()
        return None


def load_gc_state(path):
    """{worktree realpath: {"t": last check (epoch), "secs", "verdict", "why", "idle", ...}}"""
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        if (
            isinstance(s, dict)
            and s.get("v") == GC_STATE_VERSION
            and isinstance(s.get("trees"), dict)
        ):
            return s["trees"]
    except (OSError, ValueError):
        pass
    return {}


def save_gc_state(path, trees):
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"v": GC_STATE_VERSION, "trees": trees}, f, indent=1, sort_keys=True)
        os.replace(tmp, path)  # atomic: a kill mid-write leaves the previous state
    except OSError:
        pass


def verdict_fresh(e, idle_min, now):
    """True while a stored verdict cannot yet have become 'remove' — budgeted runs skip such trees.
    KEPT (something unique in it): re-checked after RECHECK_KEPT_HOURS.  ACTIVE: not before its
    idle clock can reach idle_min (idle grows only with elapsed time).  Skipping only ever DELAYS a
    removal, and every removal follows a fresh full check."""
    v, t = e.get("verdict"), e.get("t", 0)
    if v == "kept":
        return now < t + RECHECK_KEPT_HOURS * 3600
    if v == "active":
        return now < t + max(0.0, idle_min - e.get("idle", 0)) * 3600
    return False


def pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, TypeError, ValueError):
        return False


def check_tree(w, idle_min, trusted):
    """Read-only verdict for one worktree -> (verdict, label, why, idle, force), verdict in
    remove (nothing unique, idle >= idle_min) | kept (something unique) | active."""
    path = w["path"]
    info = classify_tree(path, trusted)
    ignored = ignored_files(path)
    idle = idle_hours(path, info["files"], ignored or ())
    unique_commits = [c for c in info["commits"] if c[1] == "unique"]
    wip = [
        f for f in info["files"] if f[3] not in ("same", "old-build") and not disposable(f[1], f[2])
    ]
    listed = {f[1] for f in info["files"]}
    ign = ignored_unique(path, ignored, listed) if ignored is not None else []
    label = "%s (%s, idle %.0fh, %d behind)" % (
        short(path),
        (w.get("branch") or "detached").replace("refs/heads/", ""),
        idle,
        info["behind"],
    )
    if ignored is None:
        return (
            "kept",
            label,
            ["`git ls-files --ignored` failed — gitignored files unknown, not removing blind"],
            idle,
            False,
        )
    if unique_commits or wip or ign:
        why = []
        if unique_commits:
            why.append(
                "%d unpushed commit(s): %s"
                % (
                    len(unique_commits),
                    "; ".join(f"{c[0][:9]} {c[2][:40]}" for c in unique_commits[:2]),
                )
            )
        if wip:
            why.append(
                "%d file(s) with content not on origin: %s"
                % (len(wip), ", ".join(f[1] for f in wip[:4]) + (" …" if len(wip) > 4 else ""))
            )
        if ign:
            why.append(
                "%d gitignored file(s) not on origin — `git worktree remove` would delete "
                "them silently: %s" % (len(ign), ignored_summary(ign))
            )
        return "kept", label, why, idle, False
    if idle < idle_min:
        return (
            "active",
            label,
            ["active within %dh — nothing unique in it; gc later" % idle_min],
            idle,
            False,
        )
    stale = list(info["files"])
    extra = [p for p in ignored if p not in listed]
    note = ", ".join(
        x
        for x in (
            "%d stale copies" % len(stale) if stale else "",
            "%d ignored file(s), all disposable or on origin" % len(extra) if extra else "",
        )
        if x
    )
    label += f" [{note}]" if note else ""
    return "remove", label, [], idle, bool(stale)


def remove_worktree(path, force, started):
    """`git worktree remove` in its OWN session with output to a file, not a pipe: a gc killed
    mid-removal (the guard's subprocess timeout kills this process; a harness may kill the whole
    process group) must not stop git half-way.  Measured 2026-09-28, 20,000-file scratch tree: the
    process group killed 0.4 s in -> 14,924 files left, 5,077 tracked files 'deleted', tree still
    registered (every later gc: "kept, files not on origin").  Detached, git finishes on its own.
    started(pid) runs before the wait so the state file names the process.  -> (rc|None, text)"""
    with tempfile.TemporaryFile() as log:
        p = subprocess.Popen(
            ["git", "worktree", "remove"] + (["--force"] if force else []) + [path],
            cwd=MAIN,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        started(p.pid)
        try:
            rc = p.wait(timeout=300)
        except subprocess.TimeoutExpired:
            return None, "still running after 300 s (pid %d) — left to finish on its own" % p.pid
        log.seek(0)
        return rc, log.read().decode("utf-8", "replace").strip()


def do_gc(dry_run, idle_min, for_hook, protect, trusted=(), budget=0):
    """Remove worktrees holding nothing unique; each removal is printed (flushed) the moment it is
    made.  budget > 0 (the session-start hook, killed at 90 s): trees go least-recently-checked
    first, a tree whose stored verdict is still fresh is skipped, and past `budget` seconds no tree
    is started and no git call keeps running — the rest wait for the next run.  Runbook §107
    (2026-09-28): a full run took 4.5-17 min, the hook killed it every session, and it re-probed
    the same first trees each time."""
    global _deadline
    t0 = time.time()
    deadline = t0 + budget if budget > 0 else None

    def say(s):
        return print(s, flush=True)

    cdir = common_dir()
    lock = gc_lock(cdir)
    if lock is None:
        say("[gc] another gc is running — skipped this time (it reports in its own session)")
        return
    try:
        git(["worktree", "prune"], MAIN)
        wts = worktrees()
        if not wts:
            return
        main_path = os.path.realpath(wts[0]["path"])
        spath = os.path.join(cdir, GC_STATE)
        state = load_gc_state(spath)
        live = {os.path.realpath(w["path"]) for w in wts}
        busy = set()  # trees an earlier run's `git worktree remove` did not finish
        for key, e in list(state.items()):
            if key not in live:
                if e.get("verdict") == "removing":
                    say(
                        "[gc] removed {} — the removal an earlier gc started ({}) has finished".format(
                            short(key), e.get("when", "?")
                        )
                    )
                del state[key]
            elif e.get("verdict") == "removing":
                if pid_alive(e.get("pid")) and time.time() - e.get("t", 0) < 3600:
                    busy.add(key)
                    say(
                        "[gc] {}: `git worktree remove` (pid {}) still running — left alone".format(
                            short(key), e.get("pid")
                        )
                    )
                else:  # a by-hand run (no budget) re-checks it: its deleted files read as WIP -> kept
                    if deadline:
                        busy.add(key)
                    say(
                        "[gc] ⚠ {}: the `git worktree remove` an earlier gc started ({}) stopped part-way — "
                        "still registered. It held nothing unique when checked; look at it, then "
                        "`git worktree remove --force {}` (a by-hand `gc` re-checks it and clears this line)".format(
                            short(key), e.get("when", "?"), key
                        )
                    )
        cands = [
            w
            for w in wts[1:]
            if os.path.realpath(w["path"]) not in protect | {main_path}
            and os.path.realpath(w["path"]) not in busy
            and os.path.isdir(w["path"])
        ]
        cands.sort(
            key=lambda w: state.get(os.path.realpath(w["path"]), {}).get("t", 0)
        )  # never checked = 0
        kept, cut, n_checked, n_removed, skipped, not_reached = [], [], 0, 0, 0, 0
        for w in cands:
            key = os.path.realpath(w["path"])
            if deadline and verdict_fresh(state.get(key, {}), idle_min, time.time()):
                skipped += 1
                continue
            # budgeted: don't start a tree whose last check won't fit in what is left — unless it is
            # this run's first, so a tree slower than the whole budget still gets the full budget
            need = state.get(key, {}).get("secs", 0) if n_checked else 0
            if deadline and time.time() + need >= deadline:
                not_reached += 1
                continue
            t = time.time()
            _deadline = deadline
            try:
                verdict, label, why, idle, force = check_tree(w, idle_min, trusted)
            except BudgetExhausted:
                verdict, label, idle, force = "cut", short(w["path"]), None, False
                why = ["check cut off by the %d s budget after %.1f s" % (budget, time.time() - t)]
                cut.append(label)
            except Exception as ex:  # one broken tree must not end the whole gc
                verdict, label, idle, force = "error", short(w["path"]), None, False
                why = [f"check failed ({type(ex).__name__}: {str(ex)[:120]}) — kept"]
            finally:
                _deadline = None
            n_checked += 1
            entry = {
                "t": int(t),
                "secs": round(time.time() - t, 1),
                "verdict": verdict,
                "why": why[:3],
            }
            if verdict == "cut":  # time-to-cut is only a lower bound on what the check needs
                entry["secs"] = max(entry["secs"], state.get(key, {}).get("secs", 0))
            if idle is not None:
                entry["idle"] = round(idle, 1)
            if verdict == "remove" and dry_run:
                say(f"[gc] would remove {label}")
                n_removed += 1
                entry["verdict"] = "removable"  # never "fresh": the next budgeted run re-checks it
                state[key] = entry
            elif verdict == "remove":
                entry.update(verdict="removing", when=now_ist())

                def started(pid, entry=entry, key=key):
                    entry["pid"] = pid
                    state[key] = entry
                    save_gc_state(spath, state)

                try:
                    rc, msg = remove_worktree(w["path"], force, started)
                except Exception as ex:  # git never started: nothing was deleted
                    rc, msg = -1, f"{type(ex).__name__}: {ex}"
                if rc == 0:
                    say(f"[gc] removed {label} — held nothing unique")
                    n_removed += 1
                    state.pop(key, None)
                elif rc is None:
                    say(f"[gc] removing {label}: {msg}")
                else:
                    entry.update(verdict="error", why=["git worktree remove failed: " + msg[:120]])
                    entry.pop("pid", None)
                    state[key] = entry
                    kept.append((label, entry["why"]))
            else:
                state[key] = entry
                if verdict != "cut":
                    kept.append((label, why))
            save_gc_state(spath, state)  # per tree: a killed run still advances the rotation
        git(["worktree", "prune"], MAIN)
        if kept:
            say("[gc] kept %d worktree(s):" % len(kept))
            for label, why in kept:
                say(f"[gc]   - {label}")
                for y in why:
                    say(f"[gc]       {y}")
        if not cands and not busy:
            say("[gc] no extra worktrees")
            return
        parts = [
            "checked %d of %d worktree(s) in %.0f s%s"
            % (
                n_checked,
                len(cands),
                time.time() - t0,
                " (budget %d s, least-recently-checked first)" % budget if budget > 0 else "",
            )
        ]
        parts.append("%d %s" % (n_removed, "would be removed" if dry_run else "removed"))
        if cut:
            parts.append(
                "%d cut off by the budget mid-check, not judged, back of the queue (%s)"
                % (len(cut), ", ".join(cut))
            )
        if skipped:
            parts.append(
                "%d skipped, verdict still fresh (kept: re-checked after %dh; active: once it "
                "can reach %dh idle)" % (skipped, RECHECK_KEPT_HOURS, idle_min)
            )
        if not_reached:
            parts.append("%d not reached — the next session starts with them" % not_reached)
        say("[gc] " + "; ".join(parts))
    finally:
        lock.close()


# ----------------------------------------------------------------------------- cli
def main(argv):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mode", choices=["status", "sync", "gc"])
    ap.add_argument("--tree", default=MAIN)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--trust", default="", help="comma-separated SHAs a human VERIFIED are upstream"
    )
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--idle-hours", type=float, default=24)
    ap.add_argument(
        "--protect", default="", help="comma-separated worktree paths gc must never touch"
    )
    ap.add_argument(
        "--for-hook", action="store_true", help="terse output for the session-start banner"
    )
    ap.add_argument(
        "--budget",
        type=float,
        default=None,
        help="gc: stop cleanly after this many seconds (0 = check every tree; default 0, or "
        "%d with --for-hook); see do_gc" % HOOK_GC_BUDGET,
    )
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
        protect = {
            os.path.realpath(os.path.expanduser(p)) for p in a.protect.split(",") if p.strip()
        }
        protect.add(os.path.realpath(os.getcwd()))
        # A guard older than 2026-09-28 passes --for-hook without --budget (89 of 90 worktrees carried
        # one when this landed) and kills gc at 90 s: give it the budgeted behaviour too.
        budget = a.budget if a.budget is not None else (HOOK_GC_BUDGET if a.for_hook else 0)
        do_gc(a.dry_run, a.idle_hours, a.for_hook, protect, trusted, budget)  # prints as it goes
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
