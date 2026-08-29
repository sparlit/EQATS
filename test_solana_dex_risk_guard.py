"""
Unit and Integration Tests for Solana DEX Risk Guard Engine.
"""

import pytest

from institutional_integrations.solana_dex_risk_guard import (
    SolanaDEXRiskGuard,
    DEXPoolMetrics,
)


def test_solana_dex_risk_guard_safe_pool():
    guard = SolanaDEXRiskGuard()

    safe_metrics = DEXPoolMetrics(
        mint_address="SAFE_MINT_111",
        lp_supply=1000000.0,
        lp_burned_pct=100.0,
        mint_authority_renounced=True,
        freeze_authority_revoked=True,
        is_metadata_mutable=False,
        has_verified_socials=True,
        pool_size_sol=100.0,
    )

    res = guard.audit_dex_pool(safe_metrics)
    assert res.passed is True
    assert len(res.violations) == 0
    assert res.risk_score == 0.0


def test_solana_dex_risk_guard_honeypot_pool():
    guard = SolanaDEXRiskGuard()

    dangerous_metrics = DEXPoolMetrics(
        mint_address="DANGER_MINT_999",
        lp_supply=1000000.0,
        lp_burned_pct=0.0,  # Unburned LP -> Rugpull risk
        mint_authority_renounced=False,  # Infinite mint risk
        freeze_authority_revoked=False,  # Freeze honeypot risk
        is_metadata_mutable=True,
        has_verified_socials=False,
        pool_size_sol=2.0,  # Low liquidity
    )

    res = guard.audit_dex_pool(dangerous_metrics)
    assert res.passed is False
    assert len(res.violations) >= 4
    assert res.risk_score >= 80.0
