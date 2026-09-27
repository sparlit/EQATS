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


import pytest
from src.company_intelligence.models import CompanyDossier, EvidenceItem


def test_verified_evidence_item() -> None:
    item = EvidenceItem(
        source_id="nse-announcement-1",
        category="CORPORATE_ANNOUNCEMENT",
        as_of_date="2026-08-01",
        status="VERIFIED",
        payload={"headline": "Quarterly result filed"},
        source_reference="NSE",
    )
    assert item.status == "VERIFIED"


def test_invalid_evidence_status_is_rejected() -> None:
    with pytest.raises(ValueError):
        EvidenceItem(
            source_id="bad",
            category="NEWS",
            as_of_date="2026-08-01",
            status="ASSUMED",
        )


def test_company_dossier_count_contract() -> None:
    with pytest.raises(ValueError):
        CompanyDossier(
            symbol="TCS",
            generated_date="2026-08-01",
            status="READY",
            evidence_count=1,
            verified_evidence_count=2,
        )


def test_partial_company_dossier() -> None:
    dossier = CompanyDossier(
        symbol="INFY",
        generated_date="2026-08-01",
        status="PARTIAL",
        evidence_count=3,
        verified_evidence_count=2,
        limitations=("Management evidence not supplied",),
    )
    assert dossier.symbol == "INFY"
