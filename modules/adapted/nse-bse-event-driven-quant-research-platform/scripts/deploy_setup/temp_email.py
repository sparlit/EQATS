from __future__ import annotations

import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


"""Temporary email utility using mail.tm API.

Creates disposable email addresses and polls for verification messages.
No API key required — fully free.
"""


import random
import re
import string
import time

import httpx

API_BASE = "https://api.mail.tm"


def _get_domain(client: httpx.Client) -> str:
    """Get the first available domain."""
    r = client.get(f"{API_BASE}/domains")
    r.raise_for_status()
    domains = r.json()["hydra:member"]
    return domains[0]["domain"]


def create_email(
    prefix: str | None = None,
    password: str = "QuantDeploy2026!",
) -> tuple[str, str]:
    """Create a temp email address.

    Args:
        prefix: Custom prefix (e.g. "quantsetup"). If None, generates random.
        password: Password for the temp email account.

    Returns:
        (email_address, auth_token)
    """
    client = httpx.Client(timeout=15)

    domain = _get_domain(client)
    if prefix is None:
        prefix = f"quant{int(time.time())}"
    elif not any(c.isdigit() for c in prefix):
        # Add random suffix to avoid collisions
        suffix = "".join(random.choices(string.digits, k=4))
        prefix = f"{prefix}{suffix}"

    address = f"{prefix}@{domain}"

    # Create account
    r = client.post(
        f"{API_BASE}/accounts",
        json={"address": address, "password": password},
    )
    r.raise_for_status()

    # Get token
    r = client.post(
        f"{API_BASE}/token",
        json={"address": address, "password": password},
    )
    r.raise_for_status()
    token = r.json()["token"]

    return address, token


def wait_for_verification(
    token: str,
    timeout: int = 300,
    poll_interval: int = 5,
    subject_contains: str = "verif",
    sender_contains: str = "",
) -> str | None:
    """Poll for a verification email and extract the link.

    Args:
        token: Auth token from create_email()
        timeout: Max seconds to wait
        poll_interval: Seconds between polls
        subject_contains: Case-insensitive substring to match in subject
        sender_contains: Case-insensitive substring to match in sender

    Returns:
        Verification URL or None if timed out
    """
    client = httpx.Client(timeout=15)
    headers = {"Authorization": f"Bearer {token}"}

    start = time.time()
    while time.time() - start < timeout:
        r = client.get(f"{API_BASE}/messages", headers=headers)
        if r.status_code == 200:
            messages = r.json().get("hydra:member", [])
            for msg in messages:
                subj = msg.get("subject", "").lower()
                sender = msg.get("from", {}).get("address", "").lower()

                if subject_contains.lower() in subj:
                    if sender_contains and sender_contains.lower() not in sender:
                        continue

                    # Fetch full message body
                    msg_id = msg.get("id")
                    if msg_id:
                        body = _get_message_body(client, headers, msg_id)
                        link = _extract_verification_link(body)
                        if link:
                            return link

                        # Try extracting OTP code
                        code = _extract_otp(body)
                        if code:
                            return code

        time.sleep(poll_interval)

    return None


def wait_for_code(
    token: str,
    timeout: int = 300,
    poll_interval: int = 5,
    subject_contains: str = "code",
    sender_contains: str = "",
) -> str | None:
    """Poll for a verification code (OTP)."""
    client = httpx.Client(timeout=15)
    headers = {"Authorization": f"Bearer {token}"}

    start = time.time()
    while time.time() - start < timeout:
        r = client.get(f"{API_BASE}/messages", headers=headers)
        if r.status_code == 200:
            messages = r.json().get("hydra:member", [])
            for msg in messages:
                subj = msg.get("subject", "").lower()
                sender = msg.get("from", {}).get("address", "").lower()

                if subject_contains.lower() in subj:
                    if sender_contains and sender_contains.lower() not in sender:
                        continue

                    msg_id = msg.get("id")
                    if msg_id:
                        body = _get_message_body(client, headers, msg_id)
                        code = _extract_otp(body)
                        if code:
                            return code

        time.sleep(poll_interval)

    return None


def _get_message_body(client: httpx.Client, headers: dict, msg_id: str) -> str:
    """Fetch full message body."""
    r = client.get(f"{API_BASE}/messages/{msg_id}", headers=headers)
    if r.status_code == 200:
        data = r.json()
        return data.get("text", "") or data.get("html", [""])[0]
    return ""


def _extract_verification_link(body: str) -> str | None:
    """Extract a verification URL from email body."""
    # Common verification link patterns
    patterns = [
        r'(https?://[^\s"<>\']+(?:verif|confirm|activate)[^\s"<>\']*)',
        r'(https?://[^\s"<>\']+(?:token|key|code)=[^\s"<>\']*)',
        r'(https?://[^\s"<>\']*email[^\s"<>\']*verify[^\s"<>\']*)',
        r'(https?://[^\s"<>\']*confirm[^\s"<>\']*)',
        r'(https?://[^\s"<>\']*activate[^\s"<>\']*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            link = match.group(1)
            # Clean trailing punctuation
            link = link.rstrip(".,;:!?)")
            return link
    return None


def _extract_otp(body: str) -> str | None:
    """Extract OTP/verification code from email body."""
    # Look for 4-8 digit codes
    patterns = [
        r"(?:code|OTP|pin|verification)\s*(?:is|:)\s*(\d{4,8})",
        r"(?:code|OTP|pin|verification)\s*(\d{4,8})",
        r"\b(\d{6})\b",  # 6-digit code (most common)
        r"\b(\d{4})\b",  # 4-digit code
    ]
    for pattern in patterns:
        match = re.search(pattern, body, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def delete_email(token: str) -> None:
    """Delete the temp email account."""
    client = httpx.Client(timeout=15)
    client.delete(f"{API_BASE}/accounts/me", headers={"Authorization": f"Bearer {token}"})


if __name__ == "__main__":
    print("Creating temp email...")
    addr, tok = create_email("quanttest")
    print(f"  Email: {addr}")
    print(f"  Token: {tok[:20]}...")
    print("  Waiting for verification email (will timeout in 10s)...")
    result = wait_for_verification(tok, timeout=10, poll_interval=3)
    if result:
        print(f"  Got: {result}")
    else:
        print("  No email received (expected — this is a test)")
