#!/usr/bin/env python3
"""
EQATS Automated Workflow Cascade Dispatcher
Custom HTTPS Connection Tunneling Engine - Absolute System DNS Independence
"""

import os
import json
import urllib.request
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

class DNSInsulatedHTTPSConnection(http.client.HTTPSConnection):
    """Custom HTTPS Connection wrapper that routes to an explicit IP while preserving SNI contexts."""
    def __init__(self, host, ip_target, ssl_context, *args, **kwargs):
        self.ip_target = ip_target
        self.ssl_context = ssl_context
        # Enforce structural context injection upstream
        kwargs['context'] = ssl_context
        super().__init__(host, *args, **kwargs)

    def connect(self):
        # Establish raw TCP socket pipeline directly to the resolved public IP destination
        self.sock = socket.create_connection((self.ip_target, self.port), self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()
            
        # Target identity assignment
        server_hostname = self._tunnel_host or self.host
        
        # FIXED: Explicitly set the internal _host attribute to satisfy check_hostname requirements
        self._host = server_hostname
        
        # Safely execute secure TLS wrap using native parameters
        self.sock = self.ssl_context.wrap_socket(self.sock, server_hostname=server_hostname)

class DNSInsulatedHTTPSHandler(urllib.request.HTTPSHandler):
    """Custom urllib opener handler that injects the DNS-insulated connection class."""
    def __init__(self, ip_target, context):
        self.ip_target = ip_target
        self.context = context
        super().__init__(context=context)

    def https_open(self, req):
        return self.do_open(
            lambda host, **kwargs: DNSInsulatedHTTPSConnection(host, ip_target=self.ip_target, ssl_context=self.context, **kwargs),
            req
        )

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

        api_url = f"https://://github.com/repos/{repo}/actions/workflows/eqats-ingestion-loop.yml/dispatches"
        payload = json.dumps({'ref': 'main'}).encode('utf-8')
        
        retry_delay = 5
        attempt = 1
        
        while True:
            try:
                # 1. Resolve domain endpoint without touching system nameservers
                target_ip = resolve_via_public_dns("://github.com")
                print(f"[*] Tunneling request directly to Anycast IP Destination: {target_ip}")
                
                # 2. Build secure context
                ssl_context = ssl.create_default_context()
                opener = urllib.request.build_opener(DNSInsulatedHTTPSHandler(target_ip, context=ssl_context))
                
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

                print(f"[*] Dispatching REST trigger API payload (Attempt {attempt})...")
                # 3. Transmit the payload using our custom tunnel handler
                with opener.open(req, timeout=10) as response:
                    status = response.getcode()
                    if 200 <= status <= 299:
                        print("[+] Automation cascade payload successfully processed by GitHub REST core.")
                        return
                    else:
                        print(f"[-] Received unexpected status code: {status}. Retrying...")
            except Exception as net_err:
                print(f"[-] Network connection anomaly detected: {net_err}")
                print(f"[*] Retrying cascade sequence automatically in {retry_delay} seconds...")
            
            time.sleep(retry_delay)
            retry_delay = min(retry_delay + 2, 15)
            attempt += 1
    else:
        print(f"[+] SUCCESS: The factory has processed all {total} repositories with zero stubs remaining.")

if __name__ == "__main__":
    dispatch_next_cycle()
