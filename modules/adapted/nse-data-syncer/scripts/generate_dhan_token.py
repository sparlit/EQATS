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


"""One-shot Dhan TOTP login for the Daily Dhan Sync workflow: mints a single
access token that gets reused across every Dhan-calling step in the job,
instead of each sync script logging in independently.

Independent per-script logins meant two TOTP logins could land too close
together if an earlier step in the job finished quickly (a fast SME sync
with little new data, say) - and Dhan rejects a login outright with
"Invalid TOTP" when that happens, rather than just rate-limiting it. See
dhan_daily_sync.yml for how the resulting single token is passed to each
step as DHAN_TOKEN_FILE.

The token is a live, full-access credential for a real brokerage account in
a public repo, so this deliberately never puts it on stdout, in a step
output, or anywhere else that ends up in Actions logs (log-masking is a
mitigation, not a guarantee - better to just never emit the value). --out
writes it straight to a file on the runner's ephemeral disk instead, mode
0600, which is deleted with the rest of the workspace when the job ends.

Even with a single login per job, this has still failed with "Invalid TOTP"
on the very first (and only) attempt on two separate days, at two unrelated
wall-clock times, with nothing else in this repo touching Dhan credentials
anywhere near either failure - so it isn't an in-job collision. Likely
either a login from outside this repo (a manual Dhan app/web session, some
other local script) landing in Dhan's documented ~2min-per-account login
window, or a one-off TOTP/clock edge case. Retries with a fresh TOTP code
handle the cheap case fast and, on a second failure, wait long enough to
clear an external collision before giving up for real.
"""
import argparse
import os
import stat
import sys
import time

import pyotp
import requests

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID")
DHAN_PIN = os.getenv("DHAN_PIN")
DHAN_TOTP_SECRET = os.getenv("DHAN_TOTP_SECRET")
DHAN_TOKEN_URL = "https://auth.dhan.co/app/generateAccessToken"

# Cheap retry first (catches a one-off TOTP/clock edge case), then a wait
# long enough to clear Dhan's documented ~2min-per-account login window
# (catches a login from outside this job) before giving up.
RETRY_DELAYS_SECONDS = [5, 75]


def request_token():
    totp_code = pyotp.TOTP(DHAN_TOTP_SECRET).now()
    resp = requests.post(
        DHAN_TOKEN_URL,
        params={
            "dhanClientId": DHAN_CLIENT_ID,
            "pin": DHAN_PIN,
            "totp": totp_code,
        },
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "accessToken" not in data:
        raise RuntimeError(data.get("message", data))
    return data["accessToken"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="File path to write the access token to (mode 0600)")
    args = parser.parse_args()

    if not DHAN_CLIENT_ID or not DHAN_PIN or not DHAN_TOTP_SECRET:
        print("DHAN_CLIENT_ID / DHAN_PIN / DHAN_TOTP_SECRET not set", file=sys.stderr)
        sys.exit(1)

    access_token = None
    last_error = None
    for attempt, delay in enumerate([0, *RETRY_DELAYS_SECONDS], start=1):
        if delay:
            print(f"Login attempt {attempt - 1} failed ({last_error}), retrying in {delay}s...", file=sys.stderr)
            time.sleep(delay)
        try:
            access_token = request_token()
            break
        except (RuntimeError, requests.RequestException) as e:
            last_error = e

    if access_token is None:
        print(
            f"Dhan token generation failed after {len(RETRY_DELAYS_SECONDS) + 1} attempts: {last_error}",
            file=sys.stderr,
        )
        sys.exit(1)

    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write(access_token)
    print(f"Access token written to {args.out}")


if __name__ == "__main__":
    main()
