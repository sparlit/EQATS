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


"""Run the full pipeline once and save a digest markdown file.

Triggered by cron-job.org against the GitHub Actions workflow_dispatch API;
can also be run by hand. Digests land in digests/ with the latest copy always
at digests/LATEST.md.

Two accounts are tracked: the self-trading bot and the NIFTY 50 shadow. The
manual "you + Claude" paper account was retired 2026-07-30 (paper_portfolio.py
stays as the shared price/fee helper that alerts.py and autotrader.py import).
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from newslib import atomic_write_text

BASE = Path(__file__).parent
DIGESTS = BASE / "digests"
STATUS = BASE / "pipeline_status.json"
STEP_TIMEOUT = 600

# The publishing step. It is last on purpose, so by the time it runs every
# earlier failure is known and can be stamped into news_signal.json.
EXPORT_STEP = "export_signal.py"

# (heading, argv, critical). A CRITICAL step builds the state later steps read:
# migrate.py deletes and re-inserts article_tickers in 2000-article batches, and
# monitor.py is what puts fresh articles there at all. If either dies partway,
# the database is half-built, so publishing from it would hand the real-money
# consumer a file that looks healthy and is not.
STEPS = [
    # Idempotent, ~20s over 10k articles. Runs EVERY time on purpose: it is what
    # makes the cloud self-heal after a tickers.csv or noise-rule change, so the
    # derived columns are always reproducible from the raw articles rather than
    # depending on a committed database being in the right state.
    ("Rescan history (tickers, noise, after-hours)", ["migrate.py"], True),
    ("News & signals", ["monitor.py"], True),
    # Per-(headline, company) scoring. Runs before the scoreboard so this run's
    # fresh news is graded with LLM scores, not the VADER fallback.
    ("LLM analyst (per-ticker)", ["llm_analyst.py"], False),
    ("Signal scoreboard (last 30 days)", ["scoreboard.py"], False),
    ("Bot account (self-trading)", ["autotrader.py"], False),
    ("Alert scan", ["alerts.py"], False),
    # export runs LAST so it reflects this run's fresh news + updated grades;
    # news_signal.json is consumed by trading-bot's fused momentum+news bot.
    ("Sentiment export", [EXPORT_STEP], False),
]


def main():
    DIGESTS.mkdir(exist_ok=True)
    now = datetime.now()
    parts = [f"# Stock digest — {now:%Y-%m-%d %H:%M}\n"]
    failures = []
    critical_failed = False
    for heading, args, critical in STEPS:
        if args[0] == EXPORT_STEP:
            # Hand the exporter this run's health so it can publish it. Written
            # here rather than by the exporter itself because only the runner
            # knows what happened upstream of it.
            atomic_write_text(STATUS, json.dumps({"ok": not failures, "failed": failures}))
            if critical_failed:
                parts.append(
                    f"## {heading}\n\n```\n[SKIPPED] a critical step failed — "
                    "refusing to publish news_signal.json from a half-built "
                    "database.\n```\n"
                )
                continue
        try:
            r = subprocess.run(
                # -u is load-bearing, not tidiness. Python block-buffers stdout
                # when it is a pipe, so a step killed by the timeout below dies
                # with its prints still in an unflushed buffer and `e.stdout`
                # arrives EMPTY — the handler faithfully records nothing. That is
                # why six hours of llm_analyst timeouts on 2026-09-09 said only
                # "[FAILED timeout after 600s]" and never which model or status
                # code hung. Measured: buffered -> '', with -u -> the real lines.
                [sys.executable, "-u", str(BASE / args[0]), *args[1:]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=BASE,
                timeout=STEP_TIMEOUT,
            )
        except subprocess.TimeoutExpired as e:
            # Uncaught, this killed the run before the digest was written — i.e.
            # it destroyed the evidence in exactly the case the digest exists
            # for. Record it as a failure and carry on.
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            body = f"{out.strip()}\n[FAILED timeout after {STEP_TIMEOUT}s]"
            failures.append(f"{heading} ({args[0]} timed out after {STEP_TIMEOUT}s)")
            critical_failed = critical_failed or critical
            parts.append(f"## {heading}\n\n```\n{body.strip()}\n```\n")
            continue
        body = r.stdout.strip()
        if r.returncode != 0:
            body += f"\n[FAILED exit {r.returncode}]\n{r.stderr.strip()[-1000:]}"
            failures.append(f"{heading} ({args[0]} exit {r.returncode})")
            critical_failed = critical_failed or critical
        parts.append(f"## {heading}\n\n```\n{body}\n```\n")

    digest = "\n".join(parts)
    out = DIGESTS / f"{now:%Y-%m-%d_%H%M}.md"
    # Atomic: the digest is the ONLY evidence a red run leaves behind, and the
    # workflow commits it with `if: always()`. A truncated one is worse than none.
    atomic_write_text(out, digest)
    atomic_write_text(DIGESTS / "LATEST.md", digest)
    print(f"Digest written to {out}")

    # Exit non-zero so the runner goes RED. This used to always exit 0, which is
    # exactly how a crashing scrape hid for ~3.5 weeks in July 2026: the failure
    # was written into the digest, nobody reads every digest, and Actions showed
    # a green tick on all 407 broken runs. Silence must never mean success.
    # The digest is written BEFORE this, and the workflow commits with
    # `if: always()`, so a red run still preserves its evidence.
    if failures:
        print(f"\n[PIPELINE FAILED] {len(failures)} of {len(STEPS)} steps:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    main()
