#!/usr/bin/env python3
"""
EQATS Automated Workflow Cascade Dispatcher
DNS Failover Core - Insulated SSL Anycast IP Routing Engine
"""

import os
import json
import urllib.request
import sys
import time
import ssl

# Hardcoded Anycast IP backup layer targeting official ://github.com operational routes
GITHUB_API_IP_FALLBACKS = [
    "140.82.112.6",
    "140.82.113.6",
    "140.82.114.6"
]

def dispatch_next_cycle():
    blueprint_path = "ingestion_blueprint.json"
    
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
        
        token = os.environ.get('GITHUB_TOKEN')
        repo = os.environ.get('GITHUB_REPOSITORY')
        
        if not token or not repo:
            print("[-] Error: Missing structural environment variables (GITHUB_TOKEN or GITHUB_REPOSITORY).")
            sys.exit(1)

        payload = json.dumps({'ref': 'main'}).encode('utf-8')
        retry_delay = 5
        attempt = 1
        
        while True:
            # Alternate endpoints between standard DNS path and hard-coded Anycast IP paths
            if attempt % 3 == 0 or "Errno -2" in locals().get('last_error_str', ''):
                ip_target = GITHUB_API_IP_FALLBACKS[attempt % len(GITHUB_API_IP_FALLBACKS)]
                api_url = f"https://{ip_target}/repos/{repo}/actions/workflows/eqats-ingestion-loop.yml/dispatches"
                use_ip_fallback = True
                print(f"[*] DNS Anomaly Active. Bypassing nameservers, hard-routing via Anycast IP: {ip_target}")
                
                # FIXED: Call the correct unverified context internal constructor module
                ctx = ssl._create_unverified_context()
            else:
                api_url = f"https://://github.com/repos/{repo}/actions/workflows/eqats-ingestion-loop.yml/dispatches"
                use_ip_fallback = False
                
                # Standard verification context for normal domain operations
                ctx = ssl.create_default_context()

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
            
            # Inject host header explicitly to guide GitHub's Anycast proxy routers
            if use_ip_fallback:
                req.add_header('Host', '://github.com')

            try:
                print(f"[*] Dispatching REST trigger API payload (Attempt {attempt})...")
                with urllib.request.urlopen(req, timeout=8, context=ctx) as response:
                    status = response.getcode()
                    if 200 <= status <= 299:
                        print("[+] Automation cascade payload successfully processed by GitHub REST core.")
                        return
                    else:
                        print(f"[-] Received unexpected status code: {status}. Retrying...")
            except Exception as net_err:
                last_error_str = str(net_err)
                print(f"[-] Network connection anomaly detected: {net_err}")
                print(f"[*] Retrying cascade sequence automatically in {retry_delay} seconds...")
            
            time.sleep(retry_delay)
            retry_delay = min(retry_delay + 2, 15)
            attempt += 1
            
    else:
        print(f"[+] SUCCESS: The factory has processed all {total} repositories with zero stubs remaining.")

if __name__ == "__main__":
    dispatch_next_cycle()
