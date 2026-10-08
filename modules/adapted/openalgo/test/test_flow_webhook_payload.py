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


"""
What a Flow webhook accepts as a body.

The route used `request.get_json()`, which makes Flask answer 415 before the
handler runs for anything not declared `application/json`. The callers that hit
this endpoint are the ones least able to set a header: a TradingView alert left
on its default plain-text message never reached the workflow at all, and neither
did a form post.

The order below is the whole point. JSON is tried first whatever the sender
declared, because a sender that cannot set a Content-Type still posts JSON far
more often than not.
"""

import pytest
from blueprints.flow import _read_webhook_payload
from flask import Flask


@pytest.fixture
def app():
    return Flask(__name__)


def read(app, body, content_type=None):
    headers = {"Content-Type": content_type} if content_type else {}
    with app.test_request_context("/", method="POST", data=body, headers=headers):
        return _read_webhook_payload()


@pytest.mark.parametrize(
    "content_type",
    ["application/json", "text/plain", "application/octet-stream", None],
    ids=["declared-json", "declared-text", "declared-binary", "undeclared"],
)
def test_json_body_parses_whatever_the_sender_declared(app, content_type):
    """The header is a hint, not the truth. External platforms get it wrong."""
    assert read(app, '{"secret": "s", "qty": 10}', content_type) == {"secret": "s", "qty": 10}


def test_plain_text_lands_under_message(app):
    """A TradingView alert on its default message. Readable as {{webhook.message}}."""
    assert read(app, "BUY RELIANCE 10", "text/plain") == {"message": "BUY RELIANCE 10"}


def test_form_encoded_body_becomes_fields(app):
    assert read(app, "secret=s&qty=10", "application/x-www-form-urlencoded") == {
        "secret": "s",
        "qty": "10",
    }


def test_json_that_is_not_an_object_keeps_both_forms(app):
    """A list or bare scalar has no fields to merge, so keep the text and the value."""
    assert read(app, "[1, 2, 3]", "application/json") == {
        "message": "[1, 2, 3]",
        "payload": [1, 2, 3],
    }


@pytest.mark.parametrize("body", ["", "   ", "\n"], ids=["empty", "spaces", "newline"])
def test_empty_body_is_an_empty_dict_not_a_message(app, body):
    """`_execute_webhook` pops 'secret' from this, so it must stay a dict."""
    assert read(app, body, "text/plain") == {}


def test_malformed_json_is_kept_as_text_rather_than_dropped(app):
    """Truncated JSON is still evidence of what was sent; do not silently discard it."""
    assert read(app, '{"secret": "s"', "application/json") == {"message": '{"secret": "s"'}
