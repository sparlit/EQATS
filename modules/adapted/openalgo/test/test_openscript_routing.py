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


"""Which blueprint answers an OpenScript URL, resolved against the real rule map.

This file exists because a browser asking for ``/openscript/runner/status`` was
answered ``Invalid script name 'runner/status'``, a 400 from the blueprint that
serves scripts by name. The runner looked registered and not one of its routes
could be reached.

**The cause was a stale server**, started before the runner blueprint existed,
and not a collision between the two: with both registered, the rule map resolves
every runner route to the runner, which the first group below asserts.

What the investigation did turn up is that ``/<path:filename>`` was the wrong
converter for a script name. ``path`` matches a slash and a script name can
never hold one (``_SAFE_NAME`` requires letters, digits, dot, dash or underscore
and an ``.oscript`` ending), so the rule claimed a shape it never serves. That is
why a missing blueprint came back as a confusing 400 about a script name instead
of a plain 404, and it is why the last two tests here are about the converter
rather than about the collision.
"""

import pytest
from blueprints.openscript import openscript_bp
from blueprints.openscript_runner import openscript_runner_bp
from flask import Flask


@pytest.fixture
def adapter():
    """The two blueprints on one app, bound the way a request binds them."""
    app = Flask(__name__)
    app.register_blueprint(openscript_bp)
    app.register_blueprint(openscript_runner_bp)
    return app.url_map.bind("127.0.0.1")


def owner_of(adapter, url: str, method: str) -> str:
    """Which blueprint answers this URL, by name."""
    endpoint, _ = adapter.match(url, method=method)
    return endpoint.split(".")[0]


@pytest.mark.parametrize(
    ("url", "method"),
    [
        ("/openscript/runner/status", "GET"),
        ("/openscript/runner/status/a.oscript", "GET"),
        ("/openscript/runner/start/a.oscript", "POST"),
        ("/openscript/runner/stop/a.oscript", "POST"),
        ("/openscript/runner/config", "GET"),
        ("/openscript/runner/config/a.oscript", "POST"),
        ("/openscript/runner/config/a.oscript", "DELETE"),
        ("/openscript/runner/schedule/a.oscript", "POST"),
        ("/openscript/runner/schedule/a.oscript", "DELETE"),
    ],
)
def test_every_runner_route_reaches_the_runner(adapter, url, method):
    # Catches the source blueprint's name route swallowing anything registered
    # under it. Answered by the wrong blueprint, each of these is a 400 about an
    # invalid script name, and the runner is unreachable while looking wired.
    assert owner_of(adapter, url, method) == "openscript_runner_bp"


@pytest.mark.parametrize(
    ("url", "method"),
    [
        ("/openscript/index.json", "GET"),
        ("/openscript/a.oscript", "GET"),
        ("/openscript/a.oscript", "POST"),
        ("/openscript/a.oscript", "DELETE"),
        ("/openscript/program/a.oscript", "GET"),
    ],
)
def test_the_source_routes_still_reach_the_source_blueprint(adapter, url, method):
    # The other side. Narrowing the converter must not cost the routes it was
    # widened for: a script is still served, saved and deleted by name.
    assert owner_of(adapter, url, method) == "openscript_bp"


def test_a_name_holding_a_slash_is_not_a_name_this_serves():
    # A script name cannot hold a slash, so a URL carrying one names no script.
    from blueprints.openscript import _SAFE_NAME

    assert _SAFE_NAME.match("a.oscript")
    assert not _SAFE_NAME.match("runner/status")
    assert not _SAFE_NAME.match("../secrets.oscript")


def test_a_url_with_a_slash_in_the_name_position_matches_no_route(adapter):
    # The converter itself, which is the thing that actually changed. With
    # ``path`` these resolved to the route that serves a script and were
    # answered 400 about an invalid name; with the default converter they match
    # nothing, which is a 404 and the truthful answer for a URL naming nothing.
    from werkzeug.exceptions import NotFound

    for url in ("/openscript/deeper/name.oscript", "/openscript/a/b/c"):
        with pytest.raises(NotFound):
            adapter.match(url, method="GET")
