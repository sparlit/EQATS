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


"""Clear the login so the app asks you to set it up again:

    .venv/bin/python -m app.reset_login          # asks first
    .venv/bin/python -m app.reset_login --yes    # no prompt

For when the password and PIN are both gone and you don't have the recovery code either. Trades,
watchlists, settings - everything else is untouched; only the credentials, sessions, trusted
devices and the recovery code go.

**This is deliberately not an HTTP endpoint.** A reset that needs no credentials would be reachable
by any web page your browser opens: a cross-origin POST is still *sent* whatever CORS says about
reading the reply, and with no cookie required there would be nothing to stop it. A script needs a
shell on the machine, which is the same access that could read the database directly - so it grants
nothing new, and it cannot be triggered from the network at all.
"""
import argparse
import sys

from app.core import auth, db


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m app.reset_login",
        description="Clear the app's login (password, PIN, recovery code, sessions). Trades are kept.",
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args(argv)

    try:
        db.init_schema()
    except Exception as e:  # noqa: BLE001 - the usual cause is "Postgres isn't running"
        print(f"couldn't reach the database: {e}", file=sys.stderr)
        return 1

    if not auth.configured():
        print("No account is configured - open the app and set one up.")
        return 0

    name = auth.username() or "(unnamed)"
    if not args.yes:
        answer = input(f"Clear the login for '{name}'? Trades and settings are kept. [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            print("Left alone.")
            return 0

    auth.clear_credentials()
    print("Login cleared. Open the app on this machine to create a new one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
