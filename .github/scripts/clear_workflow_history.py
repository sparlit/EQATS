#!/usr/bin/env python3
"""
EQATS Workflow Run History & Telemetry Cleaner
Queries past GitHub Actions workflow runs via gh CLI / REST API and deletes them.
Also purges local historical log artifacts.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: str) -> tuple[int, str]:
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
        return (res.returncode, res.stdout + "\n" + res.stderr)
    except Exception as e:
        return (1, str(e))


def clear_workflow_history() -> dict[str, int]:
    """Queries and deletes all past GitHub Actions workflow runs and purges historical log files."""
    print("[*] Initiating GitHub Actions Workflow History Cleanup...")
    deleted_count = 0
    failed_count = 0

    # 1. Fetch workflow run IDs via gh CLI
    code, out = run_cmd("gh run list --limit 500 --json databaseId,workflowName,status")
    if code == 0 and out.strip():
        try:
            runs = json.loads(out)
            print(f"[+] Found {len(runs)} past workflow runs to delete.")
            for run in runs:
                run_id = run.get("databaseId")
                if run_id:
                    del_code, _ = run_cmd(f"gh run delete {run_id} --yes")
                    if del_code == 0:
                        deleted_count += 1
                    else:
                        failed_count += 1
        except Exception as err:
            print(f"[-] Error parsing workflow runs JSON: {err}")
    else:
        print("[*] gh CLI run query completed or no runs found via CLI.")

    # 2. Purge local historical logs
    root_dir = Path.cwd()
    log_files = [
        "master_healing_input.log",
        "phase_1_output.log",
        "phase_2_output.log",
        "p3_s1_output.log",
        "p3_s2_output.log",
        "p3_s3_output.log",
        "master_analysis_input.log",
    ]
    for lf in log_files:
        p = root_dir / lf
        if p.exists():
            p.unlink()

    print(f"[+] Workflow history cleanup completed: {deleted_count} runs deleted, {failed_count} skipped/failed.")
    return {"deleted": deleted_count, "failed": failed_count}


if __name__ == "__main__":
    res = clear_workflow_history()
    print(f"[+] Result: {res}")
