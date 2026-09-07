#!/usr/bin/env python3
"""
EQATS Automated Workflow Cascade Dispatcher
Direct HTTP Client Tunneling Core
Dispatches workflow dispatch triggers to continue autonomous integration loop.
"""

import http.client
import json
import os
import ssl
import sys
import time
from pathlib import Path


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


def dispatch_next_cycle():
    blueprint_path = Path("ingestion_blueprint.json")

    if not blueprint_path.exists():
        print("[-] Error: Ingestion blueprint file does not exist.")
        sys.exit(1)

    try:
        with blueprint_path.open("r", encoding="utf-8") as f:
            blueprint = json.load(f)
        current = blueprint.get("current_index", 0)
        total = len(blueprint.get("repositories", []))
    except Exception as e:
        print(f"[-] Error reading blueprint matrix: {e}")
        sys.exit(1)

    if total == 0:
        print("[-] Error: Ingestion blueprint contains zero target repositories.")
        sys.exit(1)

    if current < total:
        print(f"[+] Progress Matrix Index: ({current} / {total}). Triggering subsequent pipeline cascade...")

        token = os.environ.get("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPOSITORY")

        if not token or not repo:
            print("[-] Environment variables missing (GITHUB_TOKEN or GITHUB_REPOSITORY). Skipping REST trigger.")
            return

        workflows = [
            "autonomous-repo-integration.yml",
            "eqats-ingestion-loop.yml",
        ]

        payload_data = json.dumps({"ref": "main"}).encode("utf-8")

        for wf in workflows:
            _send_workflow_dispatch(repo, token, wf, payload_data)
    else:
        print(f"[+] SUCCESS: All {total} repositories processed.")


if __name__ == "__main__":
    dispatch_next_cycle()
