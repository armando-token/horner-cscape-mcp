"""Pure-Software IEC 61131-3 and Horner OCS Simulator.

Verification Classification: TESTED_MOCK [offline/DEV only]
Execution Mode: Pure Software (EMULATED)
Safety: Zero physical PLC interaction, hardware download lockout enforced. Zero Straton runtime dependencies.
"""

from __future__ import annotations

# Strict taxonomy classification
CLASSIFICATION = "TESTED_MOCK [offline/DEV only]"
VERIFICATION_CLASSIFICATION = "TESTED_MOCK [offline/DEV only]"

from .simulation import (
    CscapeSimulator,
    SimulationBackend,
    SimulationState,
    RegisterType,
    CycleSnapshot,
    create_cscape_simulation,
    simulate_pou_with_registers,
)
from ..simulation.simulator import (
    STSimulator,
    SimulationError,
)

__all__ = [
    "CLASSIFICATION",
    "VERIFICATION_CLASSIFICATION",
    "CscapeSimulator",
    "SimulationBackend",
    "SimulationState",
    "RegisterType",
    "CycleSnapshot",
    "create_cscape_simulation",
    "simulate_pou_with_registers",
    "STSimulator",
    "SimulationError",
]
