#!/usr/bin/env python3
"""
EQATS Automated Workflow Cascade Dispatcher
Isolated Environment Module - Strict Zero Syntax Error Tolerance
"""

import os
import json
import urllib.request
import sys

def dispatch_next_cycle():
    blueprint_path = "ingestion_blueprint.json"
    
    # 1. Parse ledger matrix indices safely
    try:
        with open(blueprint_path, 'r', encoding='utf-8') as f:
            blueprint = json.load(f)
        current = blueprint['current_index']
        total = len(blueprint['repositories'])
    except Exception as e:
        print(f"[-] Error reading blueprint matrix: {e}")
        sys.exit(1)
        
    if total == 0:
        print("[-] Error: Ingestion blueprint contains zero target repositories.")
        sys.exit(1)
        
    if current < total:
        print(f"[+] Progress Matrix Index: ({current} / {total}). Triggering subsequent pipeline cascade...")
        
        # 2. Extract verified variables from system environment parameters
        token = os.environ.get('GITHUB_TOKEN')
        repo = os.environ.get('GITHUB_REPOSITORY')
        
        if not token or not repo:
            print("[-] Error: Missing structural environment variables (GITHUB_TOKEN or GITHUB_REPOSITORY).")
            sys.exit(1)
            
        # 3. Assemble rigid programmatic REST API gateway destination path
        api_url = f"https://github.com{repo}/actions/workflows/eqats-ingestion-loop.yml/dispatches"
        
        payload = json.dumps({'ref': 'main'}).encode('utf-8')
        
        req = urllib.request.Request(
            api_url, 
            data=payload,
            headers={
                'Authorization': f'token {token}',
                'Accept': 'application/vnd.github.v3+json',
                'Content-Type': 'application/json',
                'User-Agent': 'EQATS-Ingestion-Engine'
            },
            method='POST'
        )
        
        # 4. Transmit payload natively with strict HTTP status code validation checks
        try:
            with urllib.request.urlopen(req) as response:
                status = response.getcode()
                # FIXED: Standard range check prevents empty tuple parsing collisions
                if 200 <= status <= 299:
                    print("[+] Automation cascade payload successfully processed by GitHub REST core.")
                else:
                    print(f"[-] Received unexpected status code from GitHub core gateway: {status}")
                    sys.exit(1)
        except Exception as net_err:
            print(f"[-] Native transmission failed: {net_err}")
            sys.exit(1)
    else:
        print(f"[+] SUCCESS: The factory has processed all {total} repositories with zero stubs remaining.")

if __name__ == "__main__":
    dispatch_next_cycle()
