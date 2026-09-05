#!/usr/bin/env python3
"""
EQATS Automated Workflow Cascade Dispatcher
Direct HTTP Client Tunneling Core - Absolute Invalidation of Urllib Verification Constraints
"""

import os
import json
import http.client
import sys
import time
import socket
import ssl

def resolve_via_public_dns(hostname="://github.com"):
    """Queries public Anycast DNS servers over raw UDP to bypass dead system resolvers."""
    public_dns_ips = ["1.1.1.1", "8.8.8.8", "9.9.9.9"]
    dns_query_packet = (
        b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
        b"\x03api\x06github\x03com\x00\x00\x01\x00\x01"
    )
    
    for dns_server in public_dns_ips:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2.0)
            sock.sendto(dns_query_packet, (dns_server, 53))
            data, _ = sock.recvfrom(512)
            sock.close()
            
            if len(data) >= 16:
                ip_bytes = data[-4:]
                resolved_ip = f"{ip_bytes[0]}.{ip_bytes[1]}.{ip_bytes[2]}.{ip_bytes[3]}"
                socket.inet_aton(resolved_ip)
                print(f"[+] Application-Level DNS Success via {dns_server}: {resolved_ip}")
                return resolved_ip
        except Exception:
            continue
            
    print("[*] Public resolvers timed out. Deploying default hardcoded operational Anycast route...")
    return "140.82.113.6"

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

        # Structure endpoint and payload properties explicitly
        endpoint_path = f"/repos/{repo}/actions/workflows/eqats-ingestion-loop.yml/dispatches"
        payload_data = json.dumps({'ref': 'main'}).encode('utf-8')
        
        retry_delay = 5
        attempt = 1
        
        while True:
            conn = None
            try:
                # 1. Resolve domain endpoint without touching system nameservers
                target_ip = resolve_via_public_dns("://github.com")
                print(f"[*] Tunneling request directly to Anycast IP Destination: {target_ip}")
                
                # 2. Set up secure context explicitly avoiding any broken structural defaults
                ssl_context = ssl.create_default_context()
                
                # 3. Initialize low-level HTTP Connection directly to the resolved target IP address
                # Passing ://github.com as the host name keeps SNI validation rules valid
                conn = http.client.HTTPSConnection(
                    host="://github.com",
                    port=443,
                    context=ssl_context,
                    timeout=10
                )
                
                # Intercept socket creation and force connectivity to our target IP address
                original_connect = conn.connect
                def forced_ip_connect():
                    conn.sock = socket.create_connection((target_ip, 443), conn.timeout, conn.source_address)
                    conn.sock = ssl_context.wrap_socket(conn.sock, server_hostname="://github.com")
                conn.connect = forced_ip_connect

                print(f"[*] Dispatching REST trigger API payload via low-level connection core (Attempt {attempt})...")
                
                # 4. Transmit payload natively
                conn.request(
                    method="POST",
                    url=endpoint_path,
                    body=payload_data,
                    headers={
                        'Authorization': f'token {token}',
                        'Accept': 'application/vnd.github.v3+json',
                        'Content-Type': 'application/json',
                        'User-Agent': 'EQATS-Ingestion-Engine'
                    }
                )
                
                response = conn.getresponse()
                status = response.status
                
                if 200 <= status <= 299:
                    print("[+] Automation cascade payload successfully processed by GitHub REST core.")
                    return
                else:
                    print(f"[-] Received unexpected status code: {status}. Retrying...")
            except Exception as net_err:
                print(f"[-] Network connection anomaly detected: {net_err}")
                print(f"[*] Retrying cascade sequence automatically in {retry_delay} seconds...")
            finally:
                if conn:
                    conn.close()
            
            time.sleep(retry_delay)
            retry_delay = min(retry_delay + 2, 15)
            attempt += 1
    else:
        print(f"[+] SUCCESS: The factory has processed all {total} repositories with zero stubs remaining.")

if __name__ == "__main__":
    dispatch_next_cycle()
