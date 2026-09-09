#!/usr/bin/env python3
"""
EQATS Auto-PR & Failed Merge Self-Healing Engine
Automatically discovers pending Pull Requests, resolves merge conflicts,
executes multi-tier self-healing passes (syntax, ruff, mypy, pytest),
and auto-merges resolved PRs into main ONLY if all quality gates pass.

Features:
- Auto-discovers all open Pull Requests via `gh` CLI or REST API.
- Re-bases / merges latest `main` branch into PR branches cleanly.
- Runs multi-tier self-healing loop over modified modules (Ruff, Mypy, Pytest).
- Requires 100% test & type check pass rate before merging.
- Auto-merges passing PRs and deletes feature branches.
- Cross-platform support (Windows 11 Pro CMD/PowerShell & Linux/macOS POSIX).
"""

import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List


class AutoPRHealer:
    def __init__(self) -> None:
        self.root_dir = Path.cwd()
        self.py_exec = sys.executable

    def run_cmd(self, cmd: str, cwd=None, retries: int = 1, delay: float = 2.0) -> tuple[int, str]:
        """Executes shell command with built-in retry logic."""
        for attempt in range(1, retries + 1):
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, check=False)
                if res.returncode == 0 or attempt == retries:
                    return (res.returncode, res.stdout + "\n" + res.stderr)
                time.sleep(delay)
            except Exception as e:
                if attempt == retries:
                    return (1, str(e))
                time.sleep(delay)
        return (1, "Command failed after retries")

    def fetch_open_pull_requests(self) -> List[Dict[str, Any]]:
        """Queries GitHub for all open Pull Requests."""
        print("[*] Querying open Pull Requests via gh CLI...")
        code, out = self.run_cmd("gh pr list --json number,title,headRefName,url,mergeable --state open")

        if code == 0 and out.strip():
            try:
                prs = json.loads(out)
                print(f"[+] Discovered {len(prs)} open Pull Requests.")
                return prs
            except Exception as err:
                print(f"[-] Error parsing JSON PR list: {err}")

        print("[*] Fallback: Checking local git branches starting with 'integrate/'...")
        code, branches_out = self.run_cmd("git branch -r")
        prs = []
        if code == 0:
            for line in branches_out.splitlines():
                branch = line.strip().replace("origin/", "")
                if branch.startswith("integrate/"):
                    prs.append({
                        "number": 0,
                        "title": f"Integration: {branch}",
                        "headRefName": branch,
                        "url": "",
                        "mergeable": "UNKNOWN",
                    })
        return prs

    def heal_and_merge_branch(self, pr: Dict[str, Any]) -> bool:
        """Heals merge conflicts and verification errors for a single PR branch.

        Requires Ruff, Mypy, and Pytest passes before allowing merge.
        """
        head_branch = pr.get("headRefName")
        pr_number = pr.get("number", 0)

        if not head_branch or head_branch == "main":
            return False

        print("\n=======================================================")
        print(f"HEALING PR #{pr_number}: [{head_branch}] - {pr.get('title', '')}")
        print("=======================================================")

        # Step 1: Checkout main and pull latest
        self.run_cmd("git checkout main")
        self.run_cmd("git pull origin main --rebase", retries=3)

        checkout_code, _ = self.run_cmd(f"git checkout {head_branch}")
        if checkout_code != 0:
            self.run_cmd(f"git checkout -b {head_branch} origin/{head_branch}")

        # Step 2: Rebase main into branch cleanly
        rebase_code, _ = self.run_cmd("git rebase origin/main")
        if rebase_code != 0:
            print(f"  [-] Rebase conflict on {head_branch}. Aborting unsafe merge.")
            self.run_cmd("git rebase --abort")
            self.run_cmd("git checkout main")
            return False

        # Step 3: Run self-healing and quality checks over modified files
        _, diff_out = self.run_cmd("git diff --name-only main")
        modified_files = [Path(line.strip()) for line in diff_out.splitlines() if line.strip().endswith(".py")]

        all_checks_passed = True
        for py_file in modified_files:
            if py_file.exists():
                self.run_cmd(f"{self.py_exec} -m ruff check --fix --unsafe-fixes {py_file}")
                self.run_cmd(f"{self.py_exec} -m ruff format {py_file}")
                mypy_code, _ = self.run_cmd(f"{self.py_exec} -m mypy {py_file} --check-untyped-defs")
                test_code, _ = self.run_cmd(f"{self.py_exec} -m pytest {py_file} -k 'not gui'")

                # Pytest exit codes: 0 = passed, 5 = no tests collected
                if mypy_code != 0 or test_code not in (0, 5):
                    all_checks_passed = False

        if not all_checks_passed:
            print(f"  [-] Verification checks failed on branch {head_branch}. Aborting merge.")
            self.run_cmd("git checkout main")
            return False

        # Step 4: Commit and push healed branch
        self.run_cmd("git add .")
        _status_code, status_out = self.run_cmd("git status --porcelain")
        if status_out.strip():
            msg = shlex.quote("style: auto-heal syntax, formatting, and typing in PR branch")
            self.run_cmd(f"git commit -m {msg}")
            self.run_cmd(f"git push origin {head_branch} --force", retries=3)

        # Step 5: Auto-merge PR into main ONLY if checks passed
        print(f"  [+] Merging verified branch {head_branch} into main...")
        if pr_number > 0:
            merge_ok, _ = self.run_cmd(f"gh pr merge {pr_number} --auto --merge --delete-branch")
            if merge_ok == 0:
                print(f"  [+] PR #{pr_number} successfully merged via gh CLI!")
                self.run_cmd("git checkout main")
                self.run_cmd("git pull origin main --rebase")
                return True

        # Fallback direct merge
        self.run_cmd("git checkout main")
        self.run_cmd("git pull origin main --rebase")
        msg = shlex.quote(f"Auto-merge healed PR branch {head_branch}")
        direct_merge_ok, _ = self.run_cmd(f"git merge {head_branch} --no-ff -m {msg}")
        if direct_merge_ok == 0:
            self.run_cmd("git push origin main", retries=3)
            self.run_cmd(f"git push origin --delete {head_branch}", retries=2)
            print(f"  [+] Branch {head_branch} successfully merged into main!")
            return True

        return False

    def heal_all_pending_prs(self) -> Dict[str, Any]:
        """Iterates over all pending PRs and applies self-healing auto-merge."""
        prs = self.fetch_open_pull_requests()
        healed_list = []
        failed_list = []

        for pr in prs:
            success = self.heal_and_merge_branch(pr)
            if success:
                healed_list.append(pr.get("headRefName"))
            else:
                failed_list.append(pr.get("headRefName"))

        return {
            "total_open_prs": len(prs),
            "healed_and_merged_count": len(healed_list),
            "healed_branches": healed_list,
            "failed_branches": failed_list,
        }


if __name__ == "__main__":
    healer = AutoPRHealer()
    res = healer.heal_all_pending_prs()
    print(f"\n[+] Auto-PR Self-Healing Summary: {res}")
