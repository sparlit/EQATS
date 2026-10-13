from __future__ import annotations

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


"""
Background jobs for dashboard.py's long-running scans (Screener's "Run
screen", Live Rebalance's "Run today's scan") that should keep running even
if you switch to a different page, and survive across page reruns.

This MUST be its own imported module, not code living in dashboard.py
itself. Streamlit re-executes dashboard.py (the entrypoint script) top to
bottom on every single rerun -- only imported modules are cached in
sys.modules after their first import. A module-level dict declared inside
dashboard.py itself gets reinitialized to empty on every rerun, including
the very next rerun after a job was just started -- which silently
undermined the whole point of this (a real bug found 2026-07-29: jobs never
appeared "running" one rerun later, so the disable-while-running button and
the "already in progress" message never fired). Living in a properly
imported module instead means Python's normal import caching keeps _JOBS
alive across every one of dashboard.py's repeated top-to-bottom re-runs,
the same mechanism that already keeps state_db/kite_client's own
module-level state persistent.

_JOBS is process-global (not st.session_state, which isn't safe to write
from a non-main thread, and not per-session) -- matches this app's
single-user assumption elsewhere.
"""


import datetime as dt
import threading

import state_db

_JOBS: dict[str, dict] = {}


class JobCancelled(Exception):
    """Raised inside a job's own progress_cb once cancel_background_job() has
    been called for its key. Cooperative, not instant: it only takes effect
    the next time the job's fn actually calls progress_cb (e.g. backtest.
    run_backtest's day loop calls it every ~1% of the date range) -- a job
    whose fn never calls progress_cb has no way in and just runs to
    completion, same as before this existed."""


# Runs exactly once per dashboard process (module-level code, not re-run on
# Streamlit's repeated script reruns thanks to Python's import cache -- same
# mechanism _JOBS itself relies on, see the module docstring above). Any
# job_runs row still 'running' with trigger_type='manual' at this point can
# only be orphaned from a PREVIOUS process instance -- see
# state_db.cleanup_stale_manual_jobs()'s docstring.
state_db.cleanup_stale_manual_jobs()


def start_background_job(
    key: str,
    fn,
    *args,
    job_type: str | None = None,
    summarize_fn=None,
    meta: dict | None = None,
    **kwargs,
) -> bool:
    """Runs fn(*args, **kwargs, progress_cb=...) in a background thread.
    No-ops (returns False) if a job with this key is already running --
    otherwise returns True. `progress_cb(stage, frac)` and the eventual
    result/error are stashed on the job dict for get_background_job() to
    read on a later poll.

    job_type: also wraps the run in state_db.job_run(job_type, "manual") --
    same job_runs table the scheduled systemd jobs write to (job_type
    matches their string, e.g. "rebalance_scan"), so the dashboard's Job
    Log page shows manual and scheduled runs of the same job type
    together. Omit to skip persisted logging (falls back to the old
    in-memory-only behavior). summarize_fn(result) -> str, if given,
    produces the one-line summary stashed on that job_runs row.

    meta: an arbitrary dict a caller wants to read back later via
    get_background_job(key)["meta"] -- e.g. the exact form values
    submitted for this run, so a page whose st.session_state gets wiped
    mid-run (a real risk for anything long enough to outlive a browser
    tab's WebSocket session -- switching away, closing the browser, or
    just a network blip over 15-50+ minutes) can still redraw its inputs
    from what was ACTUALLY submitted (this dict lives on the process-
    global _JOBS entry, not st.session_state, so it survives that) rather
    than silently reverting every field to its hardcoded default the
    moment the session resets. Never passed to fn -- purely for the
    caller's own later retrieval. None (default) -- unused by every
    existing caller (Screener, Live Rebalance) -- leaves job["meta"] as
    None, harmless since they don't read it back."""
    existing = _JOBS.get(key)
    if existing is not None and existing["thread"].is_alive():
        return False

    job = {
        "thread": None,
        "done": False,
        "result": None,
        "error": None,
        "cancelled": False,
        "cancel_requested": False,
        "meta": meta,
        "progress": (0.0, "Starting..."),
        "started_at": dt.datetime.now(),
    }

    def _progress_cb(stage, frac):
        if job["cancel_requested"]:
            raise JobCancelled("Stopped by user.")
        job["progress"] = (frac, stage)

    def _run_fn():
        job["result"] = fn(*args, progress_cb=_progress_cb, **kwargs)
        return job["result"]

    def _runner():
        try:
            if job_type:
                with state_db.job_run(job_type, "manual") as jr:
                    result = _run_fn()
                    if summarize_fn:
                        jr["summary"] = summarize_fn(result)
            else:
                _run_fn()
        except JobCancelled:
            job["cancelled"] = True
        except Exception as e:
            job["error"] = e
        finally:
            job["done"] = True

    job["thread"] = threading.Thread(target=_runner, daemon=True)
    _JOBS[key] = job
    job["thread"].start()
    return True


def get_background_job(key: str) -> dict | None:
    return _JOBS.get(key)


def clear_background_job(key: str) -> None:
    _JOBS.pop(key, None)


def cancel_background_job(key: str) -> bool:
    """Requests cooperative cancellation of a running job. Takes effect the
    next time the job's fn calls progress_cb, not instantly. Returns False
    if no job with this key is currently running."""
    job = _JOBS.get(key)
    if job is None or not job["thread"].is_alive():
        return False
    job["cancel_requested"] = True
    return True
