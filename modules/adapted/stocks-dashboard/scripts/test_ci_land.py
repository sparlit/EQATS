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


"""Race tests for the CI commit steps that land through scripts/ci_land.py (runbook §212; §144g's method).

Per workflow: the commit step's `run:` block is extracted from the YAML (only `/tmp/` is pointed at a sandbox dir),
and run with `bash -e` (Actions' default shell) in a depth-1 clone of a bare origin, like actions/checkout. A second
clone plays the other writer (a session). Helper scripts the block calls are stubbed; ci_land.py is the real one.

  S0 no race                      every file the run changed lands; files it left alone are untouched
  S1 commit lands mid-build       on a file the run ALSO changed: origin's copy kept, ::warning:: names it, its
                                  group-mates held back, every other group lands
  S2 commit lands mid-build       on a file the run did NOT change: origin's copy kept, no warning
  S3 git shim                     a commit lands between the first `git add` and the first push: push #1 is
                                  rejected, attempt #2 keeps origin's copy
  OLD (--old REV)                 S1/S2 replayed against the block at REV: must show the revert (proves
                                  the test can see the bug)

  python3 scripts/test_ci_land.py [--old REV] [workflow ...]      (needs PyYAML; ~2 min for all; temp dirs only)

--old REV also replays S1/S2 against each workflow's block at REV (e.g. 62d4bd9d2, the last commit before §212)
and reports whether that block KEPT or REVERTED the other writer's commit. Add a workflow here when its commit step
starts using ci_land.py: CFG names the files its build writes, the one a session changes and its group-mates.
"""
import gzip
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

NEW = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_a = sys.argv[1:]
OLD_REV = _a[_a.index("--old") + 1] if "--old" in _a else None
ONLY = [x for i, x in enumerate(_a) if x != "--old" and (i == 0 or _a[i - 1] != "--old")]
REAL_GIT = shutil.which("git")
RESULTS = []


def sh(cmd, cwd, env=None, check=True):
    r = subprocess.run(
        cmd, cwd=cwd, env=env, capture_output=True, text=True, shell=isinstance(cmd, str)
    )
    if check and r.returncode:
        raise RuntimeError(f"{cmd} failed in {cwd}: {r.stdout[-800:]} {r.stderr[-800:]}")
    return r


def g(cwd, *a, check=True):
    return sh([REAL_GIT, *a], cwd, check=check).stdout


def step_block(yml_text, marker):
    d = yaml.safe_load(yml_text)
    for job in d["jobs"].values():
        for st in job["steps"]:
            if st.get("run") and marker(st):
                return st["run"], st
    raise SystemExit("step not found")


# ---------------------------------------------------------------- per-workflow scenario config
# outs: files the "build" rewrites (run content); quiet: covered by the step but left alone by the run;
# P: the file the session changes in S1/S3 (always one of outs); mates: P's group-mates (held back with it);
# Q: a quiet file the session changes in S2; extra: {path: content} seeded beside the defaults.
CFG = {
    "monthly-returns": {"outs": ["docs/monthly_returns.json"], "P": "docs/monthly_returns.json"},
    "xcheck": {"outs": ["docs/xcheck.json"], "P": "docs/xcheck.json"},
    "refresh-ipo-prehistory": {
        "outs": ["docs/ipo_prehistory.json"],
        "P": "docs/ipo_prehistory.json",
    },
    "refresh-capex": {
        "outs": ["docs/capex.json", "scripts/capex_budget_ledger.json"],
        "P": "scripts/capex_budget_ledger.json",
        "mates": ["docs/capex.json"],
    },
    "refresh-fo": {
        "outs": ["docs/fo/fo_2026.bin.gz", "docs/fo/manifest.json", "scripts/fo_spot_nse.json"],
        "quiet": ["docs/fo/fo_2025.bin.gz"],
        "P": "scripts/fo_spot_nse.json",
        "mates": ["docs/fo/fo_2026.bin.gz", "docs/fo/manifest.json"],
        "Q": "docs/fo/fo_2025.bin.gz",
    },
    "refresh-fii-dii": {
        "outs": [
            "docs/fii_dii.json",
            "docs/fii_dii_monthly.json",
            "docs/fii_fo.json",
            "docs/fii_fo_lots.json",
            "docs/nifty.json",
            "docs/nifty500.json",
            "docs/nifty_bank.json",
            "docs/india_vix.json",
            "scripts/_fo_stk_state.json",
            "scripts/_fo_stk_lots/2026-09.json.gz",
        ],
        "quiet": ["scripts/_fo_stk_lots/2026-08.json.gz"],
        "P": "docs/fii_fo.json",
        "mates": [
            "docs/fii_fo_lots.json",
            "scripts/_fo_stk_state.json",
            "scripts/_fo_stk_lots/2026-09.json.gz",
        ],
        "Q": "scripts/_fo_stk_lots/2026-08.json.gz",
    },
    "refresh-backtest-data": {
        "outs": [
            "docs/sf_meta.json",
            "docs/search_index.json",
            "scripts/_rename_suspects.json",
            "scripts/demerger_adj.json",
            "docs/liquid_universe.json",
            "scripts/gate_calendar.json",
            "scripts/corp_actions.json",
        ],
        "quiet": ["scripts/unconfirmed_ca.json"],
        "P": "scripts/demerger_adj.json",
        "Q": "scripts/unconfirmed_ca.json",
        "extra": {"docs/.sf_updated": None},
    },
    "refresh-headcount": {
        "outs": ["scripts/headcount/AAA.json", "scripts/headcount/NEW.json"],
        "quiet": ["scripts/headcount/BBB.json"],
        "P": "scripts/headcount/AAA.json",
        "Q": "scripts/headcount/BBB.json",
    },
    "refresh-headcount-vision": {
        "outs": ["scripts/headcount/AAA.json"],
        "quiet": ["scripts/headcount/BBB.json"],
        "P": "scripts/headcount/AAA.json",
        "Q": "scripts/headcount/BBB.json",
    },
    "refresh-market-mood": {
        "outs": [
            "docs/nifty500_turnover.json",
            "docs/market_breadth.json",
            "docs/market_breadth_pit.json",
            "docs/survivorship/nifty500.json",
            "docs/survivorship/nifty50.json",
        ],
        "quiet": ["docs/survivorship/bsesmeipo.json"],
        "P": "docs/survivorship/nifty50.json",
        "Q": "docs/survivorship/bsesmeipo.json",
    },
    "refresh-mf": {
        "outs": [
            "docs/mutual-funds.html",
            "docs/mf_funds.json",
            "docs/mf_history.bin",
            "scripts/mutual_funds.json",
        ],
        "quiet": ["scripts/gold_inr.json"],
        "P": "docs/mutual-funds.html",
        "mates": ["docs/mf_funds.json", "docs/mf_history.bin", "scripts/mutual_funds.json"],
        "Q": "scripts/gold_inr.json",
    },
    "refresh-shareholding": {
        "outs": [
            "docs/shareholding.json",
            "docs/shp_meta.json",
            "docs/shp_engine.json",
            "scripts/shp_history.json",
            "scripts/shp_revisions.json",
        ],
        "quiet": [
            "scripts/shares_outstanding.json",
            "scripts/shp_events.json",
            "docs/shp_gov.json",
        ],
        "P": "scripts/shp_history.json",
        "mates": [
            "docs/shareholding.json",
            "docs/shp_meta.json",
            "docs/shp_engine.json",
            "scripts/shp_revisions.json",
        ],
        "Q": "scripts/shares_outstanding.json",
    },
    "shp-allstocks-update": {
        "outs": [
            "scripts/shp_fill_allstocks.json.gz",
            "scripts/_shp_allstocks_holds.json",
            "scripts/shares_history.json",
        ],
        "P": "scripts/shp_fill_allstocks.json.gz",
        "mates": ["scripts/_shp_allstocks_holds.json", "scripts/shares_history.json"],
        "derived_ok": True,
    },
    "refresh-bse-sme-ipo": {
        "outs": [
            "docs/bse_sme_ipo.json",
            "docs/bse_sme_ipo/members.json",
            "docs/bse_sme_ipo/snapshots/2026-09-28.json",
            "scripts/bse_sme_ipo_px.json.gz",
            "docs/survivorship/bsesmeipo.json",
        ],
        "quiet": ["docs/bse_sme_ipo/stints.json"],
        "P": "docs/bse_sme_ipo/members.json",
        "mates": [
            "docs/bse_sme_ipo.json",
            "scripts/bse_sme_ipo_px.json.gz",
            "docs/survivorship/bsesmeipo.json",
        ],
        "Q": "docs/bse_sme_ipo/stints.json",
    },
    "refresh-nse-sme-emerge": {
        "outs": [
            "docs/nifty_sme_emerge.json",
            "docs/nse_sme_emerge/members.json",
            "docs/nse_sme_emerge/snapshots/2026-09-28.json",
            "scripts/nse_sme_emerge_events.json",
        ],
        "quiet": ["scripts/nse_sme_emerge_renames.json", "docs/nse_sme_emerge/stints.json"],
        "P": "scripts/nse_sme_emerge_events.json",
        "mates": ["docs/nifty_sme_emerge.json", "docs/nse_sme_emerge/members.json"],
        "Q": "docs/nse_sme_emerge/stints.json",
    },
    "refresh-bse": {
        "outs": ["docs/bse_universe.json", "docs/bse_prices.bin", "scripts/bse_seen_scrips.json"],
        "quiet": ["scripts/_bse_sectors.json"],
        "P": "docs/bse_prices.bin",
        "mates": ["docs/bse_universe.json", "scripts/bse_seen_scrips.json"],
        "Q": "scripts/_bse_sectors.json",
    },
    "refresh-fundamentals": {
        "outs": [
            "scripts/ipo_base_fills.json",
            "scripts/_ipo_base_skips.json",
            "scripts/excise_duty.json",
        ],
        "P": "scripts/ipo_base_fills.json",
        "mates": ["scripts/_ipo_base_skips.json"],
        "extra": {"docs/.fund_updated": None},
    },
    "xbrl-extra-nightly": {
        "outs": ["scripts/xbrl_extra.json.gz", "scripts/xtra_seen_window.json.gz"],
        "P": "scripts/xbrl_extra.json.gz",
        "mates": ["scripts/xtra_seen_window.json.gz"],
    },
    "refresh": {
        "outs": ["docs/nse-bse-dashboard.html", "docs/dash_slim.bin", "docs/stock_data.bin"],
        "P": "docs/dash_slim.bin",
    },
    "refresh-stock-fin": {"special": "fin"},
}
MARK = {  # which step is the commit step
    "refresh-stock-fin": lambda st: st.get("name", "").startswith("Commit refreshed slices"),
}
UNTRACKED_MARKERS = {"docs/.sf_updated", "docs/.fund_updated"}

STUBS = {
    "build_headcount.py": """import json,glob
d={p:json.load(open(p)) for p in sorted(glob.glob("scripts/headcount/*.json"))}
json.dump(d,open("docs/employee_headcount.json","w"),sort_keys=True)""",
    "dash_slim_same.py": 'raise SystemExit(1)   # "differs"',
    "stock_bin_stale.py": 'raise SystemExit(1)  # "stale"',
    "build_stock_fin.py": """import json,os,shutil
f=json.load(open("docs/sf_fundamentals.json"))
shutil.rmtree("docs/fin",ignore_errors=True); os.makedirs("docs/fin")
for k,v in f.items(): json.dump({"v":v},open("docs/fin/%s.json"%k,"w"))
json.dump({"n":len(f)},open("docs/fund_months.json","w"))""",
}


CORP_RUN = json.dumps({"factors": {"A": [[1, 0.5]], "B": [[2, 0.1]]}, "noadjust": {}}).encode()
CORP_SEED = json.dumps({"factors": {"A": [[1, 0.5]]}, "noadjust": {}}).encode()


def content(path, tag):
    if path == "scripts/corp_actions.json":
        return CORP_RUN if tag == "run" else CORP_SEED
    s = json.dumps({"by": tag, "path": path})
    if path.endswith(".gz"):
        return gzip.compress(s.encode(), mtime=0)
    if path.endswith(".bin"):
        return ("BIN:" + s).encode()
    if path.endswith(".html"):
        return f"<html>{s}</html>".encode()
    return s.encode()


def write(repo, path, data):
    p = os.path.join(repo, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(data)


def read(repo, path):
    p = os.path.join(repo, path)
    return open(p, "rb").read() if os.path.exists(p) else None


def seed_paths(block):
    """Every docs/… or scripts/… file the block names (globs and dirs skipped) -> seeded so `git add` finds it."""
    out = set()
    for m in re.finditer(
        r"(?<![\w/$.])((?:docs|scripts)/[\w./-]+\.(?:json|gz|bin|html|csv))", block
    ):
        p = m.group(1)
        if "*" not in p and not p.startswith("scripts/ci_land"):
            out.add(p)
    return out


def stubs_needed(block):
    return {
        m.group(1)
        for m in re.finditer(r"scripts/([\w/]+\.py)", block)
        if m.group(1) != "ci_land.py"
    }


def make_world(T, wf, blocks, cfg):
    origin, seed = os.path.join(T, "origin.git"), os.path.join(T, "seed")
    g(T, "init", "-q", "--bare", "-b", "main", origin)
    g(T, "init", "-q", "-b", "main", seed)
    for r in (seed,):
        g(r, "config", "user.name", "seed")
        g(r, "config", "user.email", "s@x")
    paths = set()
    for b in blocks:
        paths |= seed_paths(b)
    paths |= (
        set(cfg.get("outs", []))
        | set(cfg.get("quiet", []))
        | {"scripts/headcount/AAA.json", "scripts/headcount/BBB.json"}
    )
    for p in sorted(paths):
        if "snapshots/" in p or p.endswith("/NEW.json"):
            continue  # new files this run creates
        write(seed, p, content(p, "seed"))
    # json-shaped seeds some blocks parse
    for tc in ("scripts/filing_times_cache.json.gz", "scripts/result_times_cache.json.gz"):
        write(seed, tc, gzip.compress(b'{"2026-09-01": 1}', mtime=0))
    for lf in (
        "scripts/ann_date_fills.json",
        "scripts/_ann_recon_skips.json",
        "scripts/bse_result_fills.json",
        "scripts/_missing_quarter_pending.json",
        "scripts/_missing_quarter_skips.json",
        "scripts/manual_result_reads.json",
    ):
        write(seed, lf, b'{"k": 1}')
    write(seed, "docs/sf_fundamentals.json", json.dumps({"AAA": 1, "BBB": 2, "CCC": 3}).encode())
    stubs = set()
    for b in blocks:
        stubs |= stubs_needed(b)
    if cfg.get("special") == "fin":
        stubs.add("build_stock_fin.py")
    for s in stubs:
        write(seed, "scripts/" + s, (STUBS.get(os.path.basename(s), "pass") + "\n").encode())
    shutil.copy2(os.path.join(NEW, "scripts/ci_land.py"), os.path.join(seed, "scripts/ci_land.py"))
    if (
        cfg.get("special") == "fin"
    ):  # committed slices a day stale: built from older inputs than the seed's
        write(
            seed, "docs/sf_fundamentals.json", json.dumps({"AAA": 0, "BBB": 2, "CCC": 3}).encode()
        )
        sh([sys.executable, "scripts/build_stock_fin.py"], seed)
        write(
            seed, "docs/sf_fundamentals.json", json.dumps({"AAA": 1, "BBB": 2, "CCC": 3}).encode()
        )
    g(seed, "add", "-A")
    g(seed, "commit", "-qm", "seed")
    g(seed, "push", "-q", origin, "main")
    other = os.path.join(T, "other")
    g(T, "clone", "-q", "file://" + origin, other)
    g(other, "config", "user.name", "session")
    g(other, "config", "user.email", "u@x")
    runner = os.path.join(T, "runner")
    g(T, "clone", "-q", "--depth", "1", "file://" + origin, runner)
    return origin, other, runner


def session_commit(other, changes, msg="session: concurrent heal"):
    g(other, "fetch", "-q", "origin")
    g(other, "reset", "-q", "--hard", "origin/main")
    for p, data in changes.items():
        write(other, p, data)
    if any(os.path.basename(p) == "sf_fundamentals.json" for p in changes):
        sh(
            [sys.executable, "scripts/build_stock_fin.py"], other
        )  # a session re-bakes the slices with its heal
    g(other, "add", "-A", "-f")
    g(other, "commit", "-qm", msg)
    g(other, "push", "-q", "origin", "HEAD:main")
    return g(other, "rev-parse", "--short", "HEAD").strip()


def run_step(T, wf, block, runner, other, shim=None):
    tmp = os.path.join(T, "tmp")
    os.makedirs(tmp, exist_ok=True)
    bindir = os.path.join(T, "bin")
    os.makedirs(bindir, exist_ok=True)
    for name, body in (("gh", "exit 0"), ("sleep", "exit 0")):
        open(os.path.join(bindir, name), "w").write("#!/bin/bash\n" + body + "\n")
        os.chmod(os.path.join(bindir, name), 0o755)
    gs = os.path.join(bindir, "git")
    if os.path.exists(gs):
        os.remove(gs)
    if shim:
        payload = os.path.join(T, "shim_payload")
        open(payload, "wb").write(shim[1])
        open(gs, "w").write(f'''#!/bin/bash
if [ "$1" = "push" ] && [ ! -f "{T}/shim_done" ]; then
  touch "{T}/shim_done"
  ( cd "{other}" && "{REAL_GIT}" fetch -q origin && "{REAL_GIT}" reset -q --hard origin/main \
    && mkdir -p "$(dirname "{shim[0]}")" && cp "{payload}" "{shim[0]}" && "{REAL_GIT}" add -f "{shim[0]}" \
    && "{REAL_GIT}" commit -qm "session: lands right before the first push" && "{REAL_GIT}" push -q origin HEAD:main ) >&2
fi
exec "{REAL_GIT}" "$@"
''')
        os.chmod(gs, 0o755)
    script = os.path.join(T, "step.sh")
    open(script, "w").write(block.replace("/tmp/", tmp + "/"))
    env = dict(
        os.environ,
        PATH=bindir + ":" + os.environ["PATH"],
        GITHUB_OUTPUT=os.path.join(T, "gh_out"),
        GITHUB_STEP_SUMMARY=os.path.join(T, "gh_summary"),
        GITHUB_WORKFLOW=wf,
        GH_TOKEN="x",
    )
    for f in ("gh_out", "gh_summary"):
        open(os.path.join(T, f), "w").close()
    r = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", script],
        cwd=runner,
        env=env,
        capture_output=True,
        text=True,
    )
    return r


def check(wf, scen, cond, what):
    RESULTS.append((wf, scen, bool(cond), what))
    if not cond:
        print(f"   FAIL {wf} {scen}: {what}")


def origin_file(T, path):
    v = os.path.join(T, "verify")
    if not os.path.exists(v):
        g(T, "clone", "-q", "file://" + os.path.join(T, "origin.git"), v)
    g(v, "fetch", "-q", "origin")
    g(v, "reset", "-q", "--hard", "origin/main")
    return read(v, path)


def build(runner, cfg, tag="run"):
    for p in cfg["outs"]:
        write(runner, p, content(p, tag))
    for p, v in (cfg.get("extra") or {}).items():
        write(runner, p, v if isinstance(v, bytes) else b"")
    if cfg.get("corp_shrink"):
        write(
            runner,
            "scripts/corp_actions.json",
            json.dumps({"factors": {}, "noadjust": {}}).encode(),
        )


def scenario(wf, block, cfg, scen, old=False):
    if scen == "S2" and not cfg.get("Q"):
        return None
    T = tempfile.mkdtemp(prefix=f"lt_{wf}_{scen}_", dir=os.environ.get("LT_DIR"))
    blocks = [block]
    origin, other, runner = make_world(T, wf, blocks, cfg)
    if (
        old and wf == "refresh-headcount"
    ):  # the old block copies files newer than the build step's marker
        os.makedirs(os.path.join(T, "tmp"), exist_ok=True)
        open(os.path.join(T, "tmp", "hc_run_start"), "w").close()
    build(runner, cfg)
    P, Q, mates = cfg.get("P"), cfg.get("Q"), cfg.get("mates", [])
    sess = content(P or "x", "session")
    shim = None
    if scen == "S1":
        session_commit(other, {P: sess})
    elif scen == "S2":
        session_commit(other, {Q: content(Q, "session")})
    elif scen == "S3":
        shim = (P, sess)
    r = run_step(T, wf, block, runner, other, shim)
    out = r.stdout + r.stderr
    tag = ("OLD " if old else "") + scen
    if not old:
        check(wf, tag, r.returncode == 0, f"step exit 0 (got {r.returncode}): {out[-600:]}")

    def runval(p):
        return content(p, "run")

    def warned(p):
        return any(ln.startswith("::warning") and p in ln for ln in out.splitlines())

    if old:
        res = {"S1": (P, sess), "S2": (Q, content(Q, "session") if Q else None)}[scen]
        kept = origin_file(T, res[0]) == res[1]
        RESULTS.append(
            (wf, tag, True, f"old block {'KEPT' if kept else 'REVERTED'} the session's {res[0]}")
        )
        shutil.rmtree(T)
        return kept
    if scen == "S0":
        for p in cfg["outs"]:
            check(wf, tag, origin_file(T, p) == runval(p), f"{p} landed")
        for p in cfg.get("quiet", []):
            check(
                wf,
                tag,
                origin_file(T, p) == content(p, "seed"),
                f"{p} (untouched by the run) unchanged",
            )
        if cfg.get("corp_shrink"):
            check(
                wf,
                tag,
                origin_file(T, "scripts/corp_actions.json") == CORP_SEED,
                "shrunken corp_actions.json NOT landed",
            )
        check(wf, tag, not any(ln.startswith("::warning") for ln in out.splitlines()), "no warning")
    elif scen in ("S1", "S3"):
        check(wf, tag, origin_file(T, P) == sess, f"session's {P} kept on origin")
        check(wf, tag, warned(P), f"::warning names {P}")
        for m in mates:
            want = content(m, "seed") if "snapshots/" not in m else None
            check(
                wf, tag, origin_file(T, m) == want, f"group-mate {m} held back (origin copy kept)"
            )
        for p in cfg["outs"]:
            if p != P and p not in mates:
                check(wf, tag, origin_file(T, p) == runval(p), f"{p} (other group) landed")
        if scen == "S3":
            check(
                wf,
                tag,
                "Push attempt #1 rejected" in out or "push #1 rejected" in out or "rejected" in out,
                "push #1 rejected, retried",
            )
        if wf == "xbrl-extra-nightly":
            check(
                wf,
                tag,
                "refused=2" in open(os.path.join(T, "gh_out")).read(),
                "GITHUB_OUTPUT refused=2 (cache save gated)",
            )
        if wf.startswith("refresh-headcount"):
            v = os.path.join(T, "verify")
            want = json.dumps(
                {
                    f"scripts/headcount/{n}": json.loads(read(v, f"scripts/headcount/{n}"))
                    for n in sorted(os.listdir(os.path.join(v, "scripts/headcount")))
                },
                sort_keys=True,
            ).encode()
            check(
                wf,
                tag,
                read(v, "docs/employee_headcount.json") == want,
                "employee_headcount.json rebuilt from origin's ledgers",
            )
        if "NOT landed" not in out:
            check(wf, tag, False, "landing report says NOT landed")
    elif scen == "S2":
        check(wf, tag, origin_file(T, Q) == content(Q, "session"), f"session's {Q} kept on origin")
        check(wf, tag, not warned(Q), f"no warning for {Q}")
        for p in cfg["outs"]:
            check(wf, tag, origin_file(T, p) == runval(p), f"{p} landed")
    if wf == "xbrl-extra-nightly" and scen in ("S0", "S2"):
        check(
            wf,
            tag,
            "refused=0" in open(os.path.join(T, "gh_out")).read(),
            "GITHUB_OUTPUT refused=0",
        )
    shutil.rmtree(T)


def fin_scenarios(block, old_block):
    """refresh-stock-fin: rebuild on origin's tree. The committed slices are a day stale (built from older inputs), so
    every run has something to push; the session heals an input (and re-bakes the slices) mid-run."""
    wf, cfg = "refresh-stock-fin", {"special": "fin", "outs": []}
    heal = json.dumps(
        {"AAA": 10, "BBB": 2, "DDD": 4}
    ).encode()  # AAA healed, CCC retracted, DDD added
    seedv = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": None}
    healv = {"AAA": 10, "BBB": 2, "CCC": None, "DDD": 4}
    for scen, blk, is_old, want in (
        ("S0", block, False, seedv),
        ("S1", block, False, healv),
        ("S3", block, False, healv),
        ("OLD S1", old_block, True, healv),
    ):
        if blk is None:
            continue
        T = tempfile.mkdtemp(prefix="lt_fin_", dir=os.environ.get("LT_DIR"))
        origin, other, runner = make_world(T, wf, [blk], cfg)
        sh(
            [sys.executable, "scripts/build_stock_fin.py"], runner
        )  # the Build step: the checkout's inputs
        shim = None
        if scen.endswith("S1"):
            session_commit(other, {"docs/sf_fundamentals.json": heal})
        elif scen == "S3":
            shim = ("docs/sf_fundamentals.json", heal)
        r = run_step(T, wf, blk, runner, other, shim)
        out = r.stdout + r.stderr
        fin = {k: origin_file(T, f"docs/fin/{k}.json") for k in want}
        ok = all(
            fin[k] == (json.dumps({"v": v}).encode() if v is not None else None)
            for k, v in want.items()
        )
        if is_old:
            RESULTS.append(
                (
                    wf,
                    scen,
                    True,
                    f"old block {'KEPT' if ok else 'REVERTED'} the session's re-baked slices "
                    f"(origin AAA={fin['AAA']}, CCC {'present' if fin['CCC'] else 'gone'})",
                )
            )
        else:
            check(wf, scen, r.returncode == 0, f"step exit 0 ({out[-400:]})")
            check(wf, scen, ok, f"slices = build of origin's inputs {want}: got {fin}")
            n = sum(v is not None for v in want.values())
            check(
                wf,
                scen,
                origin_file(T, "docs/fund_months.json") == json.dumps({"n": n}).encode(),
                f"fund_months rebuilt (n={n})",
            )
            if scen == "S3":
                check(wf, scen, "rejected" in out, "push #1 rejected, retried")
        shutil.rmtree(T)


def main():
    for wf, cfg in CFG.items():
        if ONLY and wf not in ONLY:
            continue
        path = f".github/workflows/{wf}.yml"
        new_text = open(os.path.join(NEW, path)).read()
        mk = MARK.get(wf, lambda st: "reset --hard origin/main" in st["run"])
        block, _ = step_block(new_text, mk)
        old_block = step_block(g(NEW, "show", f"{OLD_REV}:{path}"), mk)[0] if OLD_REV else None
        print(f"== {wf}")
        if cfg.get("special") == "fin":
            fin_scenarios(block, old_block)
            continue
        for scen in ("S0", "S1", "S2", "S3"):
            scenario(wf, block, cfg, scen)
        for scen in ("S1", "S2") if old_block else ():
            scenario(wf, old_block, cfg, scen, old=True)
        if wf == "refresh-backtest-data":
            scenario(
                wf,
                block,
                dict(
                    cfg,
                    corp_shrink=True,
                    outs=[p for p in cfg["outs"] if p != "scripts/corp_actions.json"],
                ),
                "S0",
            )
    bad = [r for r in RESULTS if not r[2]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} assertions passed")
    for r in RESULTS:
        if r[1].startswith("OLD"):
            print(f"  {r[0]:26} {r[1]:7} {r[3]}")
    sys.exit(1 if bad else 0)


main()
