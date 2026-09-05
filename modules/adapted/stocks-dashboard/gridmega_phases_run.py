# -*- coding: utf-8 -*-
"""Drive the whole Strategy Phases Lab refresh: 11 windows × 5 basket variants (DATA_RUNBOOK §7.4).

  python3 scripts/gridmega_phases_run.py <END> [--jobs N]

Each job is one `grid_search_mega.js` run in MAIN_ONLY mode (grid + top-2000, no refine/OOS).
RESUMABLE: a job whose `_gridmega_top_<tag>.json` marker already exists is skipped, so an
interrupted sweep picks up where it stopped. Jobs are ordered longest-first so the full-cycle
windows — the ones with the headline answer — finish earliest.

Run `python3 scripts/gridmega_fetch_live.py` first; every job reads scripts/_live/.
"""
import argparse, os, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LOGD = os.path.join(HERE, "_gmlog")

# (vtag, env overrides) — vtag must match grid_search_mega.js's VTAG and the page's SUFS map
VARIANTS = [
    ("",         {}),                                                          # top-5 reset  (default)
    ("_h3",      {"TOPN": "3", "METHOD": "hold"}),
    ("_r3",      {"TOPN": "3", "METHOD": "reset"}),
    ("_h5",      {"TOPN": "5", "METHOD": "hold"}),
    ("_fno_h3",  {"TOPN": "3", "METHOD": "hold", "UNIVERSE": "__FNO__"}),
]


def windows(end):
    return [
        ("2004-03-31", end),           # since 2004 — LONGEST (269 rebalances), start it first
        ("2020-03-31", end),           # full cycle
        ("2018-01-23", "2020-03-23"),  # 2018-20 bear: measured Nifty 500 peak -> trough, -36.8%
        ("2020-03-31", "2021-09-30"),  # covid recovery
        ("2023-03-31", "2024-09-30"),  # 2023-24 bull
        ("2020-03-31", "2020-12-31"),
        ("2020-12-31", "2021-12-31"),
        ("2021-12-31", "2022-12-31"),
        ("2022-12-31", "2023-12-31"),
        ("2023-12-31", "2024-12-31"),
        ("2024-12-31", "2025-12-31"),
        ("2025-12-31", end),           # 2026 YTD
        ("2026-03-31", end),           # 2026 phase — shortest
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("end")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    os.makedirs(LOGD, exist_ok=True)

    runner = os.path.join(HERE, "_gridmega_run.js")
    with open(runner, "wb") as out:
        for part in ("scripts/gridmega_shim.js", "docs/backtest-engine.js", "scripts/grid_search_mega.js"):
            with open(os.path.join(ROOT, part), "rb") as f:
                out.write(f.read())
    subprocess.run(["node", "--check", runner], check=True)
    print("runner built + syntax-checked", flush=True)

    # The marker name must match grid_search_mega.js's TAG exactly, basis suffix included —
    # otherwise a `con` sweep sees the `std` markers and skips every window as "already done".
    basis = os.environ.get("EARN_BASIS", "con")
    jobs = []
    for start, end in windows(a.end):
        for vtag, env in VARIANTS:
            tag = "%s_%s%s_%s" % (start, end, vtag, basis)
            if os.path.exists(os.path.join(HERE, "_gridmega_top_%s.json" % tag)):
                continue
            jobs.append((tag, start, end, env))
    print("%d job(s) to run, %d at a time" % (len(jobs), a.jobs), flush=True)

    lock, state = threading.Lock(), {"n": 0, "fail": []}
    t0 = time.time()

    def work(job):
        tag, start, end, extra = job
        env = dict(os.environ, MAIN_ONLY="1", **extra)
        log = os.path.join(LOGD, tag + ".log")
        with open(log, "wb") as lf:
            r = subprocess.run(["node", "--max-old-space-size=3072", runner, start, end],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=lf)
        with lock:
            state["n"] += 1
            ok = r.returncode == 0 and os.path.exists(os.path.join(HERE, "_gridmega_top_%s.json" % tag))
            if not ok:
                state["fail"].append(tag)
            print("[%2d/%2d] %-42s %s  (%.0f min elapsed)"
                  % (state["n"], len(jobs), tag, "ok" if ok else "FAILED rc=%s" % r.returncode,
                     (time.time() - t0) / 60), flush=True)

    q = list(jobs)
    qlock = threading.Lock()

    def loop(slot):
        # Each run peaks near 3.3 GB while it parses the 9.3M-bar dataset, then settles much lower
        # (measured 2026-08-25: ~0.5 GB steady). Staggering the starts keeps those load peaks from
        # landing together on a 16 GB box — the stagger must grow with --jobs, since it is the peak
        # OVERLAP that OOMs, not the steady state.
        time.sleep(slot * 40)
        while True:
            with qlock:
                if not q:
                    return
                job = q.pop(0)
            work(job)

    threads = [threading.Thread(target=loop, args=(i,), daemon=True) for i in range(min(a.jobs, len(jobs)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("\nall done in %.0f min" % ((time.time() - t0) / 60), flush=True)
    if state["fail"]:
        print("FAILED: %s" % ", ".join(state["fail"]), flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
