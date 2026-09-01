"""
EQATS Version 11.0.0 Hyper-Autonomous Self-Fixing & Self-Improving Governor.
Exposes global integration handles for the V11 self-healing daemon.
"""

from v11_autonomous_self_healing_engine import (
    V11HyperAutonomousSelfFixingGovernor,
    global_v11_self_healing_governor,
)

__all__ = [
    "V11HyperAutonomousSelfFixingGovernor",
    "global_v11_self_healing_governor",
]
