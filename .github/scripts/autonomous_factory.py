#!/usr/bin/env python3
"""
EQATS Quantitative Ingestion Factory - Multi-Repository Autonomous Loop
Tech Stack: Python 3.13 / Rust (PyO3) / Postgres
Strict Zero-Stub Standard Enforcement
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path

ZERO_TOLERANCE_FORBIDDEN = ["TODO", "WIP", "pass", "...", "Implement later", "mock", "dummy"]

class IngestionFactory:
    def __init__(self, ledger_path="ingestion_blueprint.json", tasks_path="todo_tasks.md"):
        self.root_dir = Path(os.getcwd())
        self.sandbox_dir = self.root_dir / "_tmp_workspace"
        self.ledger_path = self.root_dir / ledger_path
        self.tasks_path = self.root_dir / tasks_path
        self.sandbox_dir.mkdir(exist_ok=True)
        
        # Ensure modules/adapted folder path exists to prevent Git pathspec fatal errors
        (self.root_dir / "modules" / "adapted").mkdir(parents=True, exist_ok=True)
        self.load_ledgers()

    def load_ledgers(self):
        if self.ledger_path.exists():
            with open(self.ledger_path, "r") as f:
                self.ledger = json.load(f)
        else:
            self.ledger = {"current_index": 0, "repositories": []}
            
    def save_ledgers(self):
        """Writes the tracking ledger atomically to prevent file corruption."""
        temp_path = self.ledger_path.with_suffix(".tmp")
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(self.ledger, f, indent=2)
            # Atomic file replacement operation
            temp_path.replace(self.ledger_path)
        except Exception as e:
            print(f"[-] Failed atomic ledger write: {e}")
            if temp_path.exists():
                temp_path.unlink()

    def execute_cmd(self, cmd, cwd=None):
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)
        if result.returncode != 0:
            print(f"[-] Command Failed: {cmd}\nStderr: {result.stderr}")
            return False, result.stderr
        return True, result.stdout

    def process_next_repository(self):
        if self.ledger["current_index"] >= len(self.ledger["repositories"]):
            print("[+] All repositories analyzed and integrated successfully. Factory loop complete.")
            sys.exit(0)

        target = self.ledger["repositories"][self.ledger["current_index"]]
        repo_name = target["name"]
        repo_url = target["url"]

        print(f"\n[=] STARTING PHASE: Ingesting target [{self.ledger['current_index'] + 1}/{len(self.ledger['repositories'])}]: {repo_name}")
        
        target_space = self.sandbox_dir / repo_name
        if target_space.exists():
            shutil.rmtree(target_space)
            
        success, _ = self.execute_cmd(f"git clone --depth=1 {repo_url} {target_space}")
        if not success:
            print(f"[-] Clone failure for {repo_name}. Skipping to keep engine running...")
            self.mark_failed(target, "Clone failure")
            return

        self.analyze_and_integrate_modules(target_space, repo_name)

        if target_space.exists():
            shutil.rmtree(target_space)
        
        self.ledger["current_index"] += 1
        self.save_ledgers()

    def analyze_and_integrate_modules(self, target_space, repo_name):
        quantitative_files = list(target_space.glob("**/*.py")) + list(target_space.glob("**/*.rs"))
        
        for file_path in quantitative_files:
            if any(part.startswith('.') for part in file_path.parts):
                continue
                
            with open(file_path, "r", errors="ignore") as f:
                content = f.read()

            if "def " in content or "fn " in content:
                if any(forbidden in content for forbidden in ZERO_TOLERANCE_FORBIDDEN):
                    continue
                self.integrate_into_eqats(file_path, repo_name)

    def integrate_into_eqats(self, file_path, repo_name):
        dest_dir = self.root_dir / "modules" / "adapted" / repo_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        dest_file = dest_dir / file_path.name
        shutil.copy2(file_path, dest_file)
        print(f"[+] Operational integration compiled for {file_path.name}")

    def mark_failed(self, target, reason):
        target["status"] = f"Failed: {reason}"
        self.ledger["current_index"] += 1
        self.save_ledgers()

if __name__ == "__main__":
    factory = IngestionFactory()
    factory.process_next_repository()
