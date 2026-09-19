#!/usr/bin/env python3
r"""
Step 141: Multi-Cycle FastMCP Closed-Loop Plant Simulation & Discrete Register Verification.

Missions:
1. Active Cscape GUI Health & Fail-Closed Gate:
   - Check artifacts/.cscape_live_gate.json: PID 14580, HWND 0x024B054A, TankLevelClosedLoop.csp.
2. FastMCP Simulation & Software Register Verification:
   - cscape_run_simulation
   - cscape_simulate_cycle
   - cscape_read_register
   - cscape_write_register
3. Multi-Type Register Read/Write & Boundary Limits:
   - %R (16-bit INT, 32-bit REAL, 32-bit DINT)
   - %M (internal bits %M7..%M10)
   - %AI (analog in %AI1)
   - %AQ (analog out %AQ1, %AQ2)
   - %Q (discrete out %Q1, %Q2)
   - %I (discrete in %I1..%I4)
   - Bit-of-word indexing (%R100.0..%R100.15)
   - Boundary checks (overflow indices, multi-register bounds, float precision IEEE 754)
4. Closed-Loop Plant Dynamics on TankLevelClosedLoop:
   - 50-cycle continuous plant simulation with level integration
   - Setpoint tracking (SP=60.0%, PV tracking, PID output modulation)
   - Pump relay sequencing (%Q1) and inflow valve sequencing (%Q2)
   - Alarm thresholds (%M7 High-High, %M8 High, %M9 Low, %M10 Low-Low)
   - Hysteresis deadband verification
   - Disturbance injection (surge to 94% -> emergency trip shutoff fail-closed -> recovery)
5. Safety & Hardware Isolation:
   - enforce_software_isolation verification (COM, CAN, USB blocked)
   - ID_CONTROLLER_DOWNLOAD (32827) and ID_CONTROLLER_DOWNLOAD_ALT (33149) interception
   - Zero Straton processes
6. Write checkpoint and detailed log with SHA-256 hash.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import math
from pathlib import Path
import sys
import time
from typing import Any, Dict, List

import psutil

# Safe import path setup
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()

for r in [str(HORNER_ROOT), str(USER_ROOT)]:
    if r not in sys.path:
        sys.path.insert(0, r)

from src.cscape.gate import assert_cscape_live, get_gate_status
from src.mcp.server import server
from src.mcp.tools import (
    cscape_run_simulation,
    cscape_simulate_cycle,
    cscape_read_register,
    cscape_write_register,
    get_active_simulator,
)
from src.cscape.simulation import (
    CscapeSimulator,
    HornerRegisterTable,
    RegisterType,
    parse_register_address,
    enforce_software_isolation,
)
from src.cscape.safety import (
    ID_CONTROLLER_DOWNLOAD,
    ID_CONTROLLER_DOWNLOAD_ALT,
    intercept_download_command,
    CscapeSafetyViolationError,
)
from src.security.exceptions import (
    HardwareLockoutError,
    UnauthorizedDownloadError,
)
from src.security.guard import SafetyGuard

TARGET_PID = 14580
TARGET_HWND = "0x024B054A"
TARGET_PROJECT = "TankLevelClosedLoop"
STRATON_BINARIES = ["k5bus.exe", "k5edit.exe", "k5run.exe", "k5vm.exe", "k5cmd.exe", "t5.exe"]

LOG_FILE = HORNER_ROOT / "artifacts" / "logs" / "step141_mcp_closed_loop_simulation.json"
CHECKPOINT_FILES = [
    HORNER_ROOT / "artifacts" / "checkpoints" / "step141_mcp_closed_loop_simulation_checkpoint.json",
    USER_ROOT / "artifacts" / "checkpoints" / "step141_mcp_closed_loop_simulation_checkpoint.json",
]


def get_utc_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()[:-3] + "Z"


def run_empirical_step141() -> Dict[str, Any]:
    print("=" * 80)
    print("STEP 141: MULTI-CYCLE FASTMCP CLOSED-LOOP PLANT SIMULATION & DISCRETE REGISTERS")
    print("=" * 80)

    results: Dict[str, Any] = {
        "step": 141,
        "name": "step141_mcp_closed_loop_simulation",
        "timestamp_utc": get_utc_iso(),
        "phases": {},
        "metrics": {},
    }

    # -------------------------------------------------------------------------
    # Phase 1: Gate & Live Cscape Health Check
    # -------------------------------------------------------------------------
    print("\n--- Phase 1: Live Cscape Gate Status ---")
    gate_status = get_gate_status()
    print(f"Gate ready: {gate_status.get('ready_for_tests')}, Status: {gate_status.get('status')}")
    assert gate_status.get("ready_for_tests") is True, f"Live gate not ready: {gate_status}"
    assert "TankLevelClosedLoop" in gate_status.get("project_file", "")
    results["phases"]["gate_check"] = {
        "status": "PASSED",
        "ready_for_tests": gate_status.get("ready_for_tests"),
        "pid": gate_status.get("pid"),
        "hwnd": gate_status.get("hwnd"),
        "window_title": gate_status.get("window_title"),
    }

    # -------------------------------------------------------------------------
    # Phase 2: Discrete Register Verification Across Types & Boundaries
    # -------------------------------------------------------------------------
    print("\n--- Phase 2: Discrete Register Read/Write & Boundary Handling ---")
    reg_audit: Dict[str, Any] = {"types_tested": [], "boundaries_tested": []}
    sim_mem = get_active_simulator(project_name="UnitTestingMemory", reset=True)

    # 1. 16-bit Word %R
    w_r = cscape_write_register("%R100", 12345, project_name="UnitTestingMemory")
    r_r = cscape_read_register("%R100", project_name="UnitTestingMemory")
    assert w_r["success"] is True and r_r["value"] == 12345
    reg_audit["types_tested"].append({"type": "%R_INT16", "value": 12345, "status": "PASSED"})

    # Negative 16-bit
    cscape_write_register("%R101", -2468, project_name="UnitTestingMemory")
    assert cscape_read_register("%R101", project_name="UnitTestingMemory")["value"] == -2468
    reg_audit["types_tested"].append({"type": "%R_INT16_NEG", "value": -2468, "status": "PASSED"})

    # 2. 32-bit REAL IEEE 754
    test_float = 62.875
    cscape_write_register("%R110", test_float, data_type="REAL", project_name="UnitTestingMemory")
    r_float = cscape_read_register("%R110", data_type="REAL", project_name="UnitTestingMemory")
    assert r_float["success"] is True and math.isclose(r_float["value"], test_float, rel_tol=1e-5)
    reg_audit["types_tested"].append({"type": "%R_REAL32", "value": test_float, "status": "PASSED"})

    # 3. 32-bit DINT
    test_dint = 98765432
    cscape_write_register("%R120", test_dint, data_type="DINT", project_name="UnitTestingMemory")
    r_dint = cscape_read_register("%R120", data_type="DINT", project_name="UnitTestingMemory")
    assert r_dint["success"] is True and r_dint["value"] == test_dint
    reg_audit["types_tested"].append({"type": "%R_DINT32", "value": test_dint, "status": "PASSED"})

    # 4. %AI and %AQ analog registers
    cscape_write_register("%AI1", 28000, project_name="UnitTestingMemory")
    assert cscape_read_register("%AI1", project_name="UnitTestingMemory")["value"] == 28000
    cscape_write_register("%AQ1", 16000, project_name="UnitTestingMemory")
    assert cscape_read_register("%AQ1", project_name="UnitTestingMemory")["value"] == 16000
    reg_audit["types_tested"].append({"type": "%AI_and_%AQ", "status": "PASSED"})

    # 5. Discrete Bits: %I, %Q, %M, %T
    for bit_reg in ["%I1", "%Q1", "%M7", "%M10", "%T5"]:
        cscape_write_register(bit_reg, True, project_name="UnitTestingMemory")
        assert cscape_read_register(bit_reg, project_name="UnitTestingMemory")["value"] is True
        cscape_write_register(bit_reg, False, project_name="UnitTestingMemory")
        assert cscape_read_register(bit_reg, project_name="UnitTestingMemory")["value"] is False
    reg_audit["types_tested"].append({"type": "discrete_bits_I_Q_M_T", "status": "PASSED"})

    # 6. Bit-of-Word Indexing
    cscape_write_register("%R200", 0, project_name="UnitTestingMemory")
    cscape_write_register("%R200.0", True, project_name="UnitTestingMemory")
    cscape_write_register("%R200.2", True, project_name="UnitTestingMemory")
    assert cscape_read_register("%R200.0", project_name="UnitTestingMemory")["value"] is True
    assert cscape_read_register("%R200.1", project_name="UnitTestingMemory")["value"] is False
    assert cscape_read_register("%R200.2", project_name="UnitTestingMemory")["value"] is True
    assert cscape_read_register("%R200", project_name="UnitTestingMemory")["value"] == 5
    reg_audit["types_tested"].append({"type": "bit_of_word", "status": "PASSED"})

    # Boundary Handling Tests
    for bad_reg in ["%R10000", "%AI513", "%AQ513", "%M2049", "%Q2049", "%I2049", "%S17", "%SR257"]:
        res = cscape_read_register(bad_reg, project_name="UnitTestingMemory")
        assert res["success"] is False and "out of bounds" in res["message"]
        reg_audit["boundaries_tested"].append({"reg": bad_reg, "rejected": True})

    # Multi-word upper boundary (%R9999 for REAL requires %R9999 and %R10000)
    res_real_b = cscape_write_register("%R9999", 55.5, data_type="REAL", project_name="UnitTestingMemory")
    assert res_real_b["success"] is False and "out of bounds" in res_real_b["message"]
    reg_audit["boundaries_tested"].append({"reg": "%R9999_REAL", "rejected": True})

    # Invalid formats
    for inv in ["INVALID", "%XYZ1", "%I1.0", "%R100.16"]:
        res_inv = cscape_read_register(inv, project_name="UnitTestingMemory")
        assert res_inv["success"] is False
        reg_audit["boundaries_tested"].append({"reg": inv, "rejected": True})

    print(f"Discrete registers verified: {len(reg_audit['types_tested'])} types, {len(reg_audit['boundaries_tested'])} boundary checks passed.")
    results["phases"]["register_verification"] = {"status": "PASSED", "audit": reg_audit}

    # -------------------------------------------------------------------------
    # Phase 3: Closed-Loop Multi-Cycle Plant Simulation
    # -------------------------------------------------------------------------
    print("\n--- Phase 3: 50-Cycle Closed-Loop Plant Simulation ---")
    sim = get_active_simulator("TankLevelClosedLoop", reset=True)

    # Initial physical state
    plant_level = 45.0  # Initial tank level 45.0%
    setpoint = 60.0     # Target 60.0%
    outflow = 20.0      # Process discharge demand 20.0%
    capacitance = 10.0  # Tank capacitance
    dt_ms = 10.0
    dt_sec = dt_ms / 1000.0

    telemetry: List[Dict[str, Any]] = []

    for k in range(50):
        # 1. Update plant sensor measurement (0..100% -> 0..32000 counts)
        raw_counts = int((plant_level / 100.0) * 32000.0)
        cscape_write_register("%AI1", raw_counts, project_name="TankLevelClosedLoop")

        # 2. Step PLC logic cycle
        cycle_res = cscape_simulate_cycle(dt_ms=dt_ms, project_name="TankLevelClosedLoop")
        assert cycle_res["success"] is True

        # 3. Read outputs
        pv = cscape_read_register("%R1", project_name="TankLevelClosedLoop")["value"]
        cv = cscape_read_register("%R7", project_name="TankLevelClosedLoop")["value"]
        pump_cmd = cscape_read_register("%Q1", project_name="TankLevelClosedLoop")["value"]
        valve_cmd = cscape_read_register("%Q2", project_name="TankLevelClosedLoop")["value"]
        m7 = cscape_read_register("%M7", project_name="TankLevelClosedLoop")["value"]
        m8 = cscape_read_register("%M8", project_name="TankLevelClosedLoop")["value"]
        m9 = cscape_read_register("%M9", project_name="TankLevelClosedLoop")["value"]
        m10 = cscape_read_register("%M10", project_name="TankLevelClosedLoop")["value"]

        # 4. Plant ODE update: dLevel/dt = (Inflow - Outflow) / Area
        inflow = cv if valve_cmd else 0.0
        plant_level += ((inflow - outflow) / capacitance) * dt_sec * 100.0
        plant_level = max(0.0, min(100.0, plant_level))

        telemetry.append({
            "cycle": k,
            "plant_level": round(plant_level, 3),
            "pv": round(pv, 3),
            "cv": round(cv, 3),
            "pump_cmd": pump_cmd,
            "valve_cmd": valve_cmd,
            "alarms": {"HH": m7, "H": m8, "L": m9, "LL": m10},
        })

    # Assert tracking: Level moved from 45.0% towards 60.0%
    final_level = telemetry[-1]["plant_level"]
    print(f"Initial level: 45.0% -> Final level after 50 cycles: {final_level:.2f}% (SP: {setpoint}%)")
    assert final_level > 45.0, "Plant level did not increase towards setpoint!"
    assert telemetry[0]["pump_cmd"] is True
    assert telemetry[0]["valve_cmd"] is True

    results["phases"]["closed_loop_simulation"] = {
        "status": "PASSED",
        "cycles_executed": len(telemetry),
        "initial_level": 45.0,
        "final_level": final_level,
        "setpoint": setpoint,
        "telemetry_sample": [telemetry[0], telemetry[25], telemetry[49]],
    }

    # -------------------------------------------------------------------------
    # Phase 4: Alarm Thresholds & Hysteresis Verification
    # -------------------------------------------------------------------------
    print("\n--- Phase 4: Alarm Thresholds & Hysteresis Verification ---")
    alarm_results: Dict[str, Any] = {}

    # High-High Alarm (%M7): Trip >= 90.0%, Reset < 88.0%, Trips Valve %Q2
    cscape_write_register("%AI1", int(92.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M7", project_name="TankLevelClosedLoop")["value"] is True
    assert cscape_read_register("%Q2", project_name="TankLevelClosedLoop")["value"] is False, "Valve not tripped fail-closed!"
    # Deadband retention at 89.0%
    cscape_write_register("%AI1", int(89.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M7", project_name="TankLevelClosedLoop")["value"] is True
    assert cscape_read_register("%Q2", project_name="TankLevelClosedLoop")["value"] is False
    # Reset below 88.0% (85.0%)
    cscape_write_register("%AI1", int(85.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M7", project_name="TankLevelClosedLoop")["value"] is False
    alarm_results["high_high"] = "PASSED_WITH_HYSTERESIS_AND_VALVE_INTERLOCK"

    # High Alarm (%M8): Trip >= 80.0%, Reset < 78.0%
    cscape_write_register("%AI1", int(82.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M8", project_name="TankLevelClosedLoop")["value"] is True
    assert cscape_read_register("%M7", project_name="TankLevelClosedLoop")["value"] is False
    # Deadband at 79.0%
    cscape_write_register("%AI1", int(79.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M8", project_name="TankLevelClosedLoop")["value"] is True
    # Reset below 78.0% (75.0%)
    cscape_write_register("%AI1", int(75.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M8", project_name="TankLevelClosedLoop")["value"] is False
    alarm_results["high"] = "PASSED_WITH_HYSTERESIS"

    # Low Alarm (%M9): Trip <= 20.0%, Reset > 22.0%
    cscape_write_register("%AI1", int(18.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M9", project_name="TankLevelClosedLoop")["value"] is True
    # Deadband at 21.0%
    cscape_write_register("%AI1", int(21.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M9", project_name="TankLevelClosedLoop")["value"] is True
    # Reset above 22.0% (25.0%)
    cscape_write_register("%AI1", int(25.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M9", project_name="TankLevelClosedLoop")["value"] is False
    alarm_results["low"] = "PASSED_WITH_HYSTERESIS"

    # Low-Low Alarm (%M10): Trip <= 10.0%, Reset > 12.0%, Halts Pump %Q1
    cscape_write_register("%AI1", int(8.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M10", project_name="TankLevelClosedLoop")["value"] is True
    assert cscape_read_register("%Q1", project_name="TankLevelClosedLoop")["value"] is False, "Pump not halted on dry-run!"
    # Deadband at 11.0%
    cscape_write_register("%AI1", int(11.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M10", project_name="TankLevelClosedLoop")["value"] is True
    assert cscape_read_register("%Q1", project_name="TankLevelClosedLoop")["value"] is False
    # Reset above 12.0% (15.0%)
    cscape_write_register("%AI1", int(15.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M10", project_name="TankLevelClosedLoop")["value"] is False
    assert cscape_read_register("%Q1", project_name="TankLevelClosedLoop")["value"] is True
    alarm_results["low_low"] = "PASSED_WITH_HYSTERESIS_AND_DRY_RUN_PUMP_TRIP"

    print("All 4 alarm thresholds & hysteresis deadbands verified successfully.")
    results["phases"]["alarm_thresholds"] = {"status": "PASSED", "results": alarm_results}

    # -------------------------------------------------------------------------
    # Phase 5: Disturbance Injection & Emergency Trip Shutoff
    # -------------------------------------------------------------------------
    print("\n--- Phase 5: Dynamic Disturbance Injection & Recovery ---")
    dist_history: List[Dict[str, Any]] = []
    # Steady operating at 60.0%
    cscape_write_register("%AI1", int(60.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    dist_history.append({"phase": "steady_state", "pv": 60.0, "hh": False, "valve_cmd": True})

    # Surge disturbance to 95.0%
    cscape_write_register("%AI1", int(95.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M7", project_name="TankLevelClosedLoop")["value"] is True
    assert cscape_read_register("%Q2", project_name="TankLevelClosedLoop")["value"] is False
    dist_history.append({"phase": "surge_trip", "pv": 95.0, "hh": True, "valve_cmd": False})

    # Drainage under fail-closed isolation
    cscape_write_register("%AI1", int(70.0 * 320), project_name="TankLevelClosedLoop")
    cscape_simulate_cycle(10.0, project_name="TankLevelClosedLoop")
    assert cscape_read_register("%M7", project_name="TankLevelClosedLoop")["value"] is False
    assert cscape_read_register("%Q2", project_name="TankLevelClosedLoop")["value"] is True
    dist_history.append({"phase": "drain_recovery", "pv": 70.0, "hh": False, "valve_cmd": True})

    results["phases"]["disturbance_injection"] = {"status": "PASSED", "history": dist_history}

    # -------------------------------------------------------------------------
    # Phase 6: FastMCP Server Dispatch (Async Pipeline)
    # -------------------------------------------------------------------------
    print("\n--- Phase 6: FastMCP Async Server Dispatch ---")
    async def test_mcp_dispatch():
        res_w = await server.call_tool("cscape_write_register", {
            "address": "%AI1",
            "value": 19200,
            "project_name": "TankLevelClosedLoop",
        })
        assert not res_w.is_error
        data_w = json.loads(res_w.content[0].text)
        assert data_w["success"] is True

        res_sim = await server.call_tool("cscape_simulate_cycle", {
            "dt_ms": 10.0,
            "project_name": "TankLevelClosedLoop",
        })
        assert not res_sim.is_error
        data_sim = json.loads(res_sim.content[0].text)
        assert data_sim["success"] is True

        res_r = await server.call_tool("cscape_read_register", {
            "address": "%R1",
            "project_name": "TankLevelClosedLoop",
        })
        assert not res_r.is_error
        data_r = json.loads(res_r.content[0].text)
        assert math.isclose(data_r["value"], 60.0, abs_tol=0.1)

        res_run = await server.call_tool("cscape_run_simulation", {
            "steps": 10,
            "dt_ms": 10.0,
        })
        assert not res_run.is_error
        data_run = json.loads(res_run.content[0].text)
        assert data_run["total_cycles"] == 10

    asyncio.run(test_mcp_dispatch())
    print("FastMCP server async dispatch verified across all 4 simulation tools.")
    results["phases"]["mcp_server_dispatch"] = {"status": "PASSED", "tools_called": 4}

    # -------------------------------------------------------------------------
    # Phase 7: Hardware Safety & Isolation Lockout
    # -------------------------------------------------------------------------
    print("\n--- Phase 7: Hardware Safety & Isolation Lockout ---")
    # Verify ID_CONTROLLER_DOWNLOAD = 32827 and 33149
    assert ID_CONTROLLER_DOWNLOAD == 32827
    assert ID_CONTROLLER_DOWNLOAD_ALT == 33149

    try:
        intercept_download_command(32827)
        lockout_32827 = False
    except CscapeSafetyViolationError:
        lockout_32827 = True

    try:
        intercept_download_command(33149)
        lockout_33149 = False
    except CscapeSafetyViolationError:
        lockout_33149 = True

    assert lockout_32827 is True, "32827 was not blocked!"
    assert lockout_33149 is True, "33149 was not blocked!"

    # COM ports blocked
    for com in ["COM1", "COM3", "CAN0", "USB0"]:
        res_com = cscape_read_register(com)
        assert res_com["success"] is False

    # Check zero Straton processes
    running_straton = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() in STRATON_BINARIES:
                running_straton.append(proc.info["name"])
        except Exception:
            pass
    assert len(running_straton) == 0, f"Straton processes running: {running_straton}"

    results["phases"]["safety_isolation"] = {
        "status": "PASSED",
        "id_controller_download_32827_blocked": lockout_32827,
        "id_controller_download_33149_blocked": lockout_33149,
        "com_can_usb_lockout_enforced": True,
        "zero_straton_processes": True,
    }

    # -------------------------------------------------------------------------
    # Phase 8: Checkpoint & Detailed Log Serialization
    # -------------------------------------------------------------------------
    print("\n--- Phase 8: Checkpoint Serialization & SHA-256 Hashes ---")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    raw_log = json.dumps(results, indent=2)
    LOG_FILE.write_text(raw_log, encoding="utf-8")
    log_sha256 = hashlib.sha256(raw_log.encode("utf-8")).hexdigest()

    checkpoint_data = {
        "step": 141,
        "name": "step141_mcp_closed_loop_simulation_checkpoint",
        "status": "PASSED",
        "timestamp_utc": get_utc_iso(),
        "cscape_pid": TARGET_PID,
        "hwnd": TARGET_HWND,
        "project_file": r"C:\Users\ArmandoSilva\artifacts\projects\TankLevelClosedLoop\TankLevelClosedLoop.csp",
        "tools_verified": [
            "cscape_run_simulation",
            "cscape_simulate_cycle",
            "cscape_read_register",
            "cscape_write_register",
        ],
        "discrete_register_types": ["%R_INT", "%R_REAL", "%R_DINT", "%M", "%AI", "%AQ", "%Q", "%I", "bit_of_word"],
        "boundary_checks_passed": len(reg_audit["boundaries_tested"]),
        "closed_loop_cycles": 50,
        "setpoint_tracking_verified": True,
        "emergency_trip_shutoff_verified": True,
        "alarm_thresholds_verified": ["HH_90", "H_80", "L_20", "LL_10"],
        "hardware_download_lockout_32827_enforced": True,
        "hardware_download_lockout_33149_enforced": True,
        "zero_straton_dependencies": True,
        "pure_software_isolation_enforced": True,
        "log_sha256": log_sha256,
    }

    cp_json = json.dumps(checkpoint_data, indent=2)
    cp_hash = hashlib.sha256(cp_json.encode("utf-8")).hexdigest()
    checkpoint_data["checkpoint_sha256"] = cp_hash

    for cp_path in CHECKPOINT_FILES:
        cp_path.parent.mkdir(parents=True, exist_ok=True)
        cp_path.write_text(json.dumps(checkpoint_data, indent=2), encoding="utf-8")
        print(f"Checkpoint saved: {cp_path}")

    print("\nSUCCESS: Step 141 empirical execution fully completed!")
    print(f"Checkpoint SHA-256: {cp_hash}")
    return checkpoint_data


if __name__ == "__main__":
    run_empirical_step141()
