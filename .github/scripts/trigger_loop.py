#!/usr/bin/env python3
"""
EQATS Automated Workflow Cascade Dispatcher
Direct HTTP Client Tunneling Core
Dispatches workflow dispatch triggers to continue autonomous integration loop.
"""

import http.client
import json
import os
from pathlib import Path
import ssl
import sys
import time


def _send_workflow_dispatch(repo: str, token: str, wf: str, payload_data: bytes):
    endpoint_path = f"/repos/{repo}/actions/workflows/{wf}/dispatches"
    retry_delay = 3

    for attempt in range(1, 4):
        conn = None
        try:
            ssl_context = ssl.create_default_context()
            conn = http.client.HTTPSConnection(
                host="api.github.com",
                port=443,
                context=ssl_context,
                timeout=10,
            )

            conn.request(
                method="POST",
                url=endpoint_path,
                body=payload_data,
                headers={
                    "Authorization": f"token {token}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                    "User-Agent": "EQATS-Ingestion-Engine",
                },
            )

            response = conn.getresponse()
            status = response.status

            if 200 <= status <= 299:
                print(f"[+] Automation cascade payload successfully processed for {wf}.")
                break
            print(f"[-] Received status code {status} for {wf}.")
        except Exception as net_err:
            print(f"[-] Connection anomaly on attempt {attempt}: {net_err}")
        finally:
            if conn:
                conn.close()

        time.sleep(retry_delay)


def load_and_repair_blueprint(blueprint_path: Path) -> dict:
    """Loads ingestion_blueprint.json with automatic self-healing repair for malformed or conflict-marked JSON files."""
    if not blueprint_path.exists():
        print("[*] Blueprint file missing. Rebuilding state ledger...")
        return repair_blueprint_file(blueprint_path)

    try:
        with blueprint_path.open("r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        # Clean residual conflict markers if present
        if "<<<<<<<" in content or ">>>>>>>" in content:
            lines = content.splitlines()
            cleaned = []
            in_conflict = False
            ours = []
            past = False
            for line in lines:
                if line.startswith("<<<<<<<"):
                    in_conflict = True
                    ours = []
                    past = False
                elif in_conflict and line.startswith("======="):
                    past = True
                elif in_conflict and line.startswith(">>>>>>>"):
                    in_conflict = False
                    cleaned.extend(ours)
                    ours = []
                    past = False
                else:
                    if in_conflict:
                        if not past:
                            ours.append(line)
                    else:
                        cleaned.append(line)
            content = "\n".join(cleaned)

        blueprint = json.loads(content)
        if "current_index" in blueprint and "repositories" in blueprint:
            return blueprint
    except Exception as err:
        print(f"[-] Blueprint JSON parse notice ({err}). Triggering automatic state ledger repair...")

    return repair_blueprint_file(blueprint_path)


def repair_blueprint_file(blueprint_path: Path) -> dict:
    """Rebuilds valid tracking ledger from repositories.txt / repo_list.md and writes clean JSON."""
    source = Path("repositories.txt") if Path("repositories.txt").exists() else Path("repo_list.md")
    repos = []
    if source.exists():
        try:
            with source.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_str = line.strip()
                    if not line_str or line_str.startswith(("#", "| Index")):
                        continue
                    if "|" in line_str:
                        parts = [p.strip() for p in line_str.split("|") if p.strip()]
                        if len(parts) >= 2 and parts[0].isdigit():
                            target = parts[1]
                            repo_name = target.split("/")[-1]
                            repos.append({"name": repo_name, "target": target, "url": f"https://github.com/{target}", "status": "pending", "pr_url": None, "merged": False})
                    else:
                        parts = line_str.split("/")
                        if len(parts) >= 2:
                            repo_name = parts[-1]
                            repos.append({"name": repo_name, "target": line_str, "url": f"https://github.com/{line_str}", "status": "pending", "pr_url": None, "merged": False})
        except Exception:
            pass

    blueprint = {"current_index": 0, "repositories": repos}
    try:
        tmp_path = blueprint_path.with_suffix(".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            json.dump(blueprint, f, indent=2)
        tmp_path.replace(blueprint_path)
        print("[+] Rebuilt clean ingestion_blueprint.json state ledger.")
    except Exception as err:
        print(f"[-] Failed saving repaired blueprint: {err}")

    return blueprint


def dispatch_next_cycle():
    blueprint_path = Path("ingestion_blueprint.json")
    blueprint = load_and_repair_blueprint(blueprint_path)

    current = blueprint.get("current_index", 0)
    total = len(blueprint.get("repositories", []))

    if total == 0:
        print("[-] Warning: Ingestion blueprint contains zero target repositories. Triggering safety cycle.")
        total = 411

    if current < total:
        print(f"[+] Progress Matrix Index: ({current} / {total}). Triggering subsequent pipeline cascade...")

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY")

        if not token or not repo:
            print("[-] Environment variables missing (GITHUB_TOKEN or GITHUB_REPOSITORY). Skipping REST trigger.")
            return

        workflows = [
            "autonomous-repo-integration.yml",
        ]

        payload_data = json.dumps({"ref": "main"}).encode("utf-8")

        for wf in workflows:
            _send_workflow_dispatch(repo, token, wf, payload_data)
    else:
        print(f"[+] SUCCESS: All {total} repositories processed.")


if __name__ == "__main__":
    dispatch_next_cycle()
