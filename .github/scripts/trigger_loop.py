#!/usr/bin/env python3
"""
EQATS Automated Workflow Cascade Dispatcher
Fault-Tolerant Network Resiliency Engine - Zero Unattended Failures
"""

import os
import json
import urllib.request
import sys
import time

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
        
        # 4. Transmit payload with fault-tolerant infinite retry loop
        retry_delay = 5  # Base sleep interval in seconds
        attempt = 1
        
        while True:
            try:
                print(f"[*] Dispatching REST trigger API payload (Attempt {attempt})...")
                with urllib.request.urlopen(req, timeout=15) as response:
                    status = response.getcode()
                    if 200 <= status <= 299:
                        print("[+] Automation cascade payload successfully processed by GitHub REST core.")
                        return  # Break loop on clean delivery success
                    else:
                        print(f"[-] Received unexpected status code: {status}. Retrying in {retry_delay}s...")
            except Exception as net_err:
                # Catch Errno -2 DNS dropouts or any momentary network timeouts
                print(f"[-] Network connection anomaly detected: {net_err}")
                print(f"[*] Retrying cascade sequence automatically in {retry_delay} seconds...")
            
            time.sleep(retry_delay)
            # Apply linear increments to delay capped at 60 seconds to optimize loop recovery profiles
            retry_delay = min(retry_delay + 5, 60)
            attempt += 1
            
    else:
        print(f"[+] SUCCESS: The factory has processed all {total} repositories with zero stubs remaining.")

if __name__ == "__main__":
    dispatch_next_cycle()
