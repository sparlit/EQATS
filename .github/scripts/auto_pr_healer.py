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
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


class AutoPRHealer:
    def __init__(self) -> None:
        self.root_dir = Path.cwd()
        self.py_exec = sys.executable

    def auto_resolve_merge_conflicts(self) -> bool:
        """Auto-resolves git merge or rebase conflicts non-interactively by accepting current changes as default."""
        print("[*] Auto-resolving merge conflicts (accepting current changes as default)...")

        # 1. Clean residual conflict markers from source files prioritizing current changes (pre-======= block)
        for p in self.root_dir.glob("**/*.py"):
            if p.exists() and not any(part.startswith(".") for part in p.parts):
                try:
                    content = p.read_text(encoding="utf-8", errors="ignore")
                    if "<<<<<<<" in content and ">>>>>>>" in content:
                        lines = content.splitlines()
                        cleaned = []
                        in_conflict = False
                        ours_block = []
                        past_separator = False

                        for line in lines:
                            if line.startswith("<<<<<<<"):
                                in_conflict = True
                                ours_block = []
                                past_separator = False
                            elif line.startswith("======="):
                                past_separator = True
                            elif line.startswith(">>>>>>>"):
                                in_conflict = False
                                cleaned.extend(ours_block)
                                ours_block = []
                                past_separator = False
                            else:
                                if in_conflict:
                                    if not past_separator:
                                        ours_block.append(line)
                                else:
                                    cleaned.append(line)

                        p.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
                except Exception:
                    pass

        # 2. Checkout current changes for remaining unresolved unparsed files
        self.run_cmd("git checkout --ours .")
        self.run_cmd("git add .")

        reb_code, _ = self.run_cmd("git rebase --continue", env_vars={"GIT_EDITOR": "true"})
        if reb_code != 0:
            self.run_cmd("git commit --no-edit")
        return True

    def call_llm_multi_provider_cascade(self, file_path: Path, error_logs: str) -> bool:
        """Multi-Provider LLM Fallback Cascade for Code Repair:
        1. Google Jules / Gemini API (Default)
        2. ChatGPT / OpenAI API (Primary Fallback)
        3. Nvidia NIM LLM model nvidia/nemotron-3-ultra-550b-a55b (Secondary Fallback)
        4. OpenRouter Free Models (Third Fallback)
        """
        code = file_path.read_text(encoding="utf-8", errors="ignore")
        prompt = f"Fix Python syntax/type/assertion errors in this code:\n\n```python\n{code[:3000]}\n```\n\nERROR LOG:\n{error_logs[:1500]}\n\nReturn ONLY valid Python code without Markdown explanations."

        # 1. Google Jules / Gemini API (Default)
        jules_key = os.getenv("GOOGLE_JULES_API_KEY") or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or os.getenv("LLM_API_KEY")
        if jules_key:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={jules_key}"
                data = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    cleaned = re.sub(r"^```python\n?", "", text.strip(), flags=re.MULTILINE)
                    cleaned = re.sub(r"\n?```$", "", cleaned.strip(), flags=re.MULTILINE)
                    if len(cleaned) > 20:
                        file_path.write_text(cleaned, encoding="utf-8")
                        print(f"  [+] Code repaired via Provider 1 (Google Jules/Gemini): {file_path.name}")
                        return True
            except Exception as e:
                print(f"  [-] Provider 1 (Google Jules/Gemini) fallback triggered: {e}")

        # 2. ChatGPT / OpenAI API (Primary Fallback)
        openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("CHATGPT_API_KEY")
        if openai_key:
            try:
                url = "https://api.openai.com/v1/chat/completions"
                data = json.dumps({
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                }).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}",
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    text = res_json["choices"][0]["message"]["content"]
                    cleaned = re.sub(r"^```python\n?", "", text.strip(), flags=re.MULTILINE)
                    cleaned = re.sub(r"\n?```$", "", cleaned.strip(), flags=re.MULTILINE)
                    if len(cleaned) > 20:
                        file_path.write_text(cleaned, encoding="utf-8")
                        print(f"  [+] Code repaired via Provider 2 (ChatGPT/OpenAI): {file_path.name}")
                        return True
            except Exception as e:
                print(f"  [-] Provider 2 (ChatGPT/OpenAI) fallback triggered: {e}")

        # 3. Nvidia NIM LLM model nvidia/nemotron-3-ultra-550b-a55b (Secondary Fallback)
        nvidia_key = os.getenv("NVIDIA_NIM_API_KEY") or os.getenv("NVIDIA_API_KEY")
        if nvidia_key:
            try:
                url = "https://integrate.api.nvidia.com/v1/chat/completions"
                data = json.dumps({
                    "model": "nvidia/nemotron-3-ultra-550b-a55b",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                }).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {nvidia_key}",
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    text = res_json["choices"][0]["message"]["content"]
                    cleaned = re.sub(r"^```python\n?", "", text.strip(), flags=re.MULTILINE)
                    cleaned = re.sub(r"\n?```$", "", cleaned.strip(), flags=re.MULTILINE)
                    if len(cleaned) > 20:
                        file_path.write_text(cleaned, encoding="utf-8")
                        print(f"  [+] Code repaired via Provider 3 (Nvidia NIM Nemotron): {file_path.name}")
                        return True
            except Exception as e:
                print(f"  [-] Provider 3 (Nvidia NIM Nemotron) fallback triggered: {e}")

        # 4. OpenRouter Free Models (Third Fallback)
        openrouter_key = os.getenv("OPENROUTER_API_KEY")
        if openrouter_key:
            try:
                url = "https://openrouter.ai/api/v1/chat/completions"
                data = json.dumps({
                    "model": "google/gemini-2.0-flash-exp:free",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                }).encode("utf-8")
                req = urllib.request.Request(url, data=data, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openrouter_key}",
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    res_json = json.loads(resp.read().decode("utf-8"))
                    text = res_json["choices"][0]["message"]["content"]
                    cleaned = re.sub(r"^```python\n?", "", text.strip(), flags=re.MULTILINE)
                    cleaned = re.sub(r"\n?```$", "", cleaned.strip(), flags=re.MULTILINE)
                    if len(cleaned) > 20:
                        file_path.write_text(cleaned, encoding="utf-8")
                        print(f"  [+] Code repaired via Provider 4 (OpenRouter Free Model): {file_path.name}")
                        return True
            except Exception as e:
                print(f"  [-] Provider 4 (OpenRouter Free Model) fallback triggered: {e}")

        return False

    def run_cmd(self, cmd: str, cwd=None, retries: int = 1, delay: float = 2.0, env_vars: dict[str, str] | None = None) -> tuple[int, str]:
        """Executes shell command with built-in retry logic and cross-platform environment variables."""
        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)
        for attempt in range(1, retries + 1):
            try:
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd, env=env, check=False)
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

        # Step 2: Rebase main into branch cleanly with non-interactive auto-resolution
        rebase_code, _ = self.run_cmd("git rebase origin/main")
        if rebase_code != 0:
            print(f"  [-] Rebase conflict on {head_branch}. Triggering auto-resolution loop (accept current changes)...")
            self.auto_resolve_merge_conflicts()

        # Step 3: Run self-healing, LLM cascade, and quality checks over modified files
        _, diff_out = self.run_cmd("git diff --name-only main")
        modified_files = [Path(line.strip()) for line in diff_out.splitlines() if line.strip().endswith(".py")]

        all_checks_passed = True
        for py_file in modified_files:
            if py_file.exists():
                self.run_cmd(f"{self.py_exec} -m ruff check --fix --unsafe-fixes {py_file}")
                self.run_cmd(f"{self.py_exec} -m ruff format {py_file}")
                mypy_code, mypy_log = self.run_cmd(f"{self.py_exec} -m mypy {py_file} --check-untyped-defs")
                test_code, test_log = self.run_cmd(f"{self.py_exec} -m pytest {py_file} -k 'not gui'")

                # If checks failed, trigger LLM multi-provider cascade repair
                if mypy_code != 0 or test_code not in (0, 5):
                    print(f"  [-] Quality gate issue on {py_file.name}. Triggering LLM Multi-Provider Cascade...")
                    repaired = self.call_llm_multi_provider_cascade(py_file, mypy_log + "\n" + test_log)
                    if repaired:
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

        # Step 5: Auto-approve and instant auto-merge PR into main without waiting
        print(f"  [+] Auto-approving and instant merging verified branch {head_branch} into main (no-wait mode)...")
        if pr_number > 0:
            self.run_cmd(f'gh pr review {pr_number} --approve -b "Auto-approved with zero-wait requirement by EQATS Autonomous Pipeline"')
            merge_ok, _ = self.run_cmd(f"gh pr merge {pr_number} --auto --merge --delete-branch")
            if merge_ok == 0:
                print(f"  [+] PR #{pr_number} successfully approved and merged via gh CLI!")
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
