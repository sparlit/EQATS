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


"""Caching of the /trading chart's custom indicator modules.

A folder of hundreds of user indicators made every page reload fetch every
module again. The chart asks for each module at ``?v=<mtime>``, so the bytes
behind a versioned URL never change and the browser may keep them for good,
while the index that lists the files must always be revalidated or a new or
edited indicator would stay hidden.
"""

import sys

import pytest


@pytest.fixture
def indicators_client(monkeypatch, tmp_path):
    """The blueprint alone, with the session check lifted and a temporary folder."""
    import utils.session as us

    monkeypatch.setattr(us, "check_session_validity", lambda f: f)
    for module in list(sys.modules):
        if module == "blueprints.custom_indicators":
            del sys.modules[module]

    import blueprints.custom_indicators as bp_module
    from flask import Flask

    folder = tmp_path / "indicators"
    folder.mkdir()
    (folder / "demo.js").write_text("export default () => {}\n", encoding="utf-8")
    monkeypatch.setattr(bp_module, "INDICATORS_DIR", folder)

    app = Flask(__name__)
    app.register_blueprint(bp_module.custom_indicators_bp)
    yield app.test_client()
    for module in list(sys.modules):
        if module == "blueprints.custom_indicators":
            del sys.modules[module]


def test_a_versioned_module_is_cacheable_for_good(indicators_client):
    res = indicators_client.get("/custom-indicators/demo.js?v=1700000000")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "private, max-age=31536000, immutable"
    assert res.mimetype == "text/javascript"


def test_an_unversioned_module_is_revalidated(indicators_client):
    res = indicators_client.get("/custom-indicators/demo.js")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "no-cache"


def test_the_index_is_always_revalidated(indicators_client):
    res = indicators_client.get("/custom-indicators/index.json")
    assert res.status_code == 200
    assert res.headers["Cache-Control"] == "no-cache"
    assert [m["file"] for m in res.get_json()] == ["demo.js"]
