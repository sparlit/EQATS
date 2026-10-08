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


"""Flattrade must report pledged holdings as collateral.

Issue #1936. The Limits response carries several collateral figures and
OpenAlgo read the wrong one. `brkcollamt` is the "pre-valued collateral
amount" and sits at 0.00 on an ordinary account; the pledged value lives in
`collateral`, "Collateral from uploaded holdings" in the API docs, which is
what the Flattrade app labels "Holdings Collateral".

The reported account held 9,385.34 cash and 1,890.30 of pledged NSE
collateral. The app totalled those to 11,275.64 while OpenAlgo showed
collateral 0.00, so a funded position looked like no position at all.

The numbers below are that account's, so the first test fails against the old
mapping rather than passing on a value that was never wrong.

`fetch_data` is patched rather than the HTTP client: that exercises the real
mapping arithmetic while keeping the broker off the network.
"""


import broker.flattrade.api.funds as funds
import pytest

# The reporter's account, from the screenshots on the issue.
CASH = 9385.34
PLEDGED = 1890.30

LIMITS = {
    "stat": "Ok",
    "cash": f"{CASH:.2f}",
    "payin": "0.00",
    "payout": "0.00",
    "marginused": "0.00",
    "brkcollamt": "0.00",
    "collateral": f"{PLEDGED:.2f}",
}


@pytest.fixture(autouse=True)
def _broker_key(monkeypatch):
    """get_margin_data reads the uid out of BROKER_API_KEY."""
    monkeypatch.setenv("BROKER_API_KEY", "FZ00000:::secret")


def _margins(monkeypatch, limits, positions=None):
    def fake_fetch(endpoint, payload, headers, client):
        return limits if endpoint.endswith("/Limits") else (positions or [])

    monkeypatch.setattr(funds, "fetch_data", fake_fetch)
    monkeypatch.setattr(funds, "get_httpx_client", lambda: None)
    return funds.get_margin_data("token")


def test_pledged_holdings_are_reported_as_collateral(monkeypatch):
    result = _margins(monkeypatch, LIMITS)

    assert result["collateral"] == f"{PLEDGED:.2f}", (
        "pledged holdings were dropped; the account shows collateral "
        f"{result['collateral']} against {PLEDGED:.2f} held (issue #1936)"
    )


def test_cash_is_unchanged_and_excludes_collateral(monkeypatch):
    """availablecash stays free cash, matching the Zerodha mapping. The app
    adds the two into "Margin Available"; OpenAlgo shows them as two figures."""
    result = _margins(monkeypatch, LIMITS)

    assert result["availablecash"] == f"{CASH:.2f}"


def test_the_two_figures_reconcile_with_the_app(monkeypatch):
    """cash + collateral is what Flattrade calls Total Credits: 11,275.64."""
    result = _margins(monkeypatch, LIMITS)
    total = float(result["availablecash"]) + float(result["collateral"])

    assert round(total, 2) == 11275.64


def test_pre_valued_collateral_is_still_honoured(monkeypatch):
    """An account that populates only brkcollamt must not regress to zero."""
    limits = dict(LIMITS, collateral="0.00", brkcollamt="2500.00")
    result = _margins(monkeypatch, limits)

    assert result["collateral"] == "2500.00"


def test_the_two_are_not_summed(monkeypatch):
    """They overlap, so adding them would double count."""
    limits = dict(LIMITS, collateral="1890.30", brkcollamt="1890.30")
    result = _margins(monkeypatch, limits)

    assert result["collateral"] == "1890.30"


def test_a_missing_or_blank_collateral_does_not_raise(monkeypatch):
    """The order path calls this; float("") would fail the whole funds read."""
    for limits in (
        dict(LIMITS, collateral="", brkcollamt=""),
        {k: v for k, v in LIMITS.items() if k not in ("collateral", "brkcollamt")},
    ):
        assert _margins(monkeypatch, limits)["collateral"] == "0.00"
