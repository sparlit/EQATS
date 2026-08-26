"""
Unit tests for system_autotune.py.
Validates hardware auto-detection, performance tier classification,
and dynamic auto-tuning config derivation.
"""

import pytest
from institutional_integrations.system_autotune import (
    auto_tune_system_parameters,
    detect_system_capabilities,
    global_system_caps,
    global_tuned_config,
)


def test_detect_system_capabilities_structure():
    caps = detect_system_capabilities()
    assert isinstance(caps, dict)
    assert "cpu_logical_cores" in caps
    assert "cpu_physical_cores" in caps
    assert "ram_total_gb" in caps
    assert "ram_free_gb" in caps
    assert "disk_total_gb" in caps
    assert "disk_free_gb" in caps
    assert "gpu_available" in caps
    assert "performance_tier" in caps
    assert caps["performance_tier"] in ["LOW", "MEDIUM", "HIGH", "ULTRA"]


def test_auto_tune_system_parameters():
    # Test HIGH Tier
    caps_high = {
        "cpu_logical_cores": 8,
        "cpu_physical_cores": 4,
        "ram_total_gb": 16.0,
        "gpu_available": False,
        "performance_tier": "HIGH",
    }
    tuned_high = auto_tune_system_parameters(caps_high)
    assert tuned_high["process_pool_workers"] >= 4
    assert tuned_high["ml_batch_size"] == 64
    assert "HIGH PERFORMANCE" in tuned_high["auto_tune_status"]

    # Test LOW Tier
    caps_low = {
        "cpu_logical_cores": 2,
        "cpu_physical_cores": 1,
        "ram_total_gb": 4.0,
        "gpu_available": False,
        "performance_tier": "LOW",
    }
    tuned_low = auto_tune_system_parameters(caps_low)
    assert tuned_low["process_pool_workers"] == 2
    assert tuned_low["ml_batch_size"] == 16
    assert "LOW-RESOURCE" in tuned_low["auto_tune_status"]


def test_global_autotune_singletons():
    assert isinstance(global_system_caps, dict)
    assert isinstance(global_tuned_config, dict)
    assert "process_pool_workers" in global_tuned_config
