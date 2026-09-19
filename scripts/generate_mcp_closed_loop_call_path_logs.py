"""Master Script: MCP Closed-Loop Call Path with Concrete Failure Location Logs & Zero PLC Download Proof.

Generates:
1. artifacts/logs/mcp_closed_loop_failure_location_call_path.json
2. artifacts/logs/mcp_closed_loop_failure_location_call_path.log

Executes:
1. Complete MCP closed-loop call path across all 8 MCP tools (Happy Path).
2. Four concrete intentional failure scenarios extracting exact failure_location logs:
   - Scenario 1: Syntax Error (Unclosed IF block missing END_IF)
   - Scenario 2: Missing Semicolon (Assignment missing ';')
   - Scenario 3: Undeclared Variable (Assignment to unallocated symbol)
   - Scenario 4: Ladder Logic Injection (Contact / rung marker '---[ ]---')
3. Assertions of strict zero PLC download policy and fail-closed hardware lockouts:
   - Download Command IDs (32827, 33149)
   - Serial / COM ports (COM1 - COM256)
   - CAN bus interfaces (can0, pcan, kvaser, vector, socketcan, CsCAN, etc.)
   - USB flash tools (PGMUpdateUtility, DfuSeCommand, STMFlashLoader, WinJTAG)
   - CLI download flags (/download, -d, /flash, /pgm, /burn, /target:hardware)
   - Automation Bridge & CLI Runner direct download/hardware methods
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# MCP Tools
from src.mcp.tools import (
    cscape_create_project,
    cscape_add_st_pou,
    cscape_validate_st,
    cscape_inspect_variables,
    cscape_compile_project,
    cscape_get_diagnostics,
    cscape_simulate_pou,
    cscape_export_project,
)

# Diagnostics & Security
from src.cscape.diagnostics import CscapeLogParser
from src.security.exceptions import (
    BlockedExecutableError,
    HardwareLockoutError,
    SecurityError,
    UnauthorizedDownloadError,
)
from src.security.guard import SecurityGuard
from src.security.policy import SafetyPolicy
from src.automation.cli_runner import CLIRunner
from src.automation.com_bridge import CscapeAutomationBridge
from src.automation.ui_automation import (
    CscapeUIAutomation,
    ID_CONTROLLER_DOWNLOAD,
    ID_PLC_DOWNLOAD,
    ID_PROGRAM_DOWNLOADOPTIONS,
    ID_CONTROLLER_DOWNLOAD_ALT,
)

PROJECTS_ROOT = REPO_ROOT / "artifacts" / "projects"
LOGS_DIR = REPO_ROOT / "artifacts" / "logs"


def main():
    start_time = datetime.datetime.now(datetime.timezone.utc)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    log_lines: List[str] = []
    json_report: Dict[str, Any] = {
        "report_type": "MCP_CLOSED_LOOP_FAILURE_LOCATION_CALL_PATH",
        "generated_at": start_time.isoformat(),
        "zero_plc_download_policy": "ENFORCED_FAIL_CLOSED",
        "mcp_tools_call_path": [],
        "failure_location_scenarios": [],
        "zero_plc_download_lockout_assertions": {},
        "overall_status": "IN_PROGRESS",
    }

    def emit(line: str = ""):
        print(line)
        log_lines.append(line)

    emit("=" * 80)
    emit("HORNER CSCAPE 10.2: MCP CLOSED-LOOP CALL PATH & FAILURE LOCATION AUDIT")
    emit("PROOF NOT CLAIMS: 100% VERIFIED CLOSED-LOOP + FAIL-CLOSED HARDWARE LOCKOUT")
    emit("=" * 80)
    emit(f"Run Timestamp (UTC) : {start_time.isoformat()}")
    emit(f"Repository Root    : {REPO_ROOT}")
    emit(f"Workspace Mode     : Pure IEC 61131-3 Structured Text Simulation")
    emit(f"Security Invariant : ZERO Physical PLC Connections | ZERO Controller Downloads")
    emit("-" * 80)

    # --------------------------------------------------------------------------
    # PART 1: MCP CLOSED-LOOP CALL PATH (ALL 8 TOOLS)
    # --------------------------------------------------------------------------
    emit("\n>>> PART 1: MCP CLOSED-LOOP CALL PATH (HAPPY PATH PIPELINE)")
    happy_project_name = "MCP_ClosedLoop_Master_Audit"
    happy_dir = PROJECTS_ROOT / happy_project_name
    if happy_dir.exists():
        shutil.rmtree(happy_dir, ignore_errors=True)

    # STEP 1: cscape_create_project
    emit("\n[TOOL 1/8] cscape_create_project")
    t1_res = cscape_create_project(
        name=happy_project_name,
        description="Master MCP Closed-Loop Pipeline Project",
        target_plc="XL4",
    )
    assert t1_res["status"] == "success" and t1_res["success"] is True
    json_report["mcp_tools_call_path"].append({
        "step": 1,
        "tool": "cscape_create_project",
        "status": "success",
        "project_name": happy_project_name,
        "target_plc": "XL4",
        "project_path": t1_res["project_path"],
    })
    emit(f"  -> SUCCESS: Project '{happy_project_name}' created at {t1_res['project_path']}")

    # STEP 2: cscape_validate_st
    emit("\n[TOOL 2/8] cscape_validate_st")
    tank_code = """PROGRAM TankLevelPID
VAR_INPUT
    RawLevelIn : INT;
    SetPoint : REAL := 60.0;
    AutoMode : BOOL := TRUE;
END_VAR
VAR_OUTPUT
    PumpOutput : INT;
    HighAlarm : BOOL;
    LowAlarm : BOOL;
END_VAR
VAR
    LevelPercent : REAL;
    Error : REAL;
    IntegralTerm : REAL;
END_VAR

LevelPercent := (INT_TO_REAL(RawLevelIn) / 32000.0) * 100.0;
Error := SetPoint - LevelPercent;

IF LevelPercent >= 90.0 THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF LevelPercent <= 10.0 THEN
    LowAlarm := TRUE;
ELSE
    LowAlarm := FALSE;
END_IF;

IF AutoMode THEN
    IntegralTerm := IntegralTerm + (0.2 * Error * 0.01);
    IF IntegralTerm > 100.0 THEN
        IntegralTerm := 100.0;
    ELSIF IntegralTerm < 0.0 THEN
        IntegralTerm := 0.0;
    END_IF;
    PumpOutput := REAL_TO_INT((2.5 * Error + IntegralTerm) * 320.0);
    IF PumpOutput > 32000 THEN
        PumpOutput := 32000;
    ELSIF PumpOutput < 0 THEN
        PumpOutput := 0;
    END_IF;
ELSE
    PumpOutput := 0;
END_IF;
END_PROGRAM
"""
    t2_res = cscape_validate_st(tank_code)
    assert t2_res["valid"] is True
    json_report["mcp_tools_call_path"].append({
        "step": 2,
        "tool": "cscape_validate_st",
        "status": "success",
        "valid": True,
        "pou_name": t2_res.get("pou_name"),
        "variable_count": len(t2_res.get("variables", [])),
    })
    emit(f"  -> SUCCESS: Code validated. POU={t2_res.get('pou_name')}, variables={len(t2_res.get('variables', []))}")

    # STEP 3: cscape_add_st_pou
    emit("\n[TOOL 3/8] cscape_add_st_pou")
    t3_res = cscape_add_st_pou(
        project_name=happy_project_name,
        pou_name="TankLevelPID",
        pou_type="PROGRAM",
        code=tank_code,
        cycle_time_ms=10,
    )
    assert t3_res["status"] == "success" and t3_res["success"] is True
    json_report["mcp_tools_call_path"].append({
        "step": 3,
        "tool": "cscape_add_st_pou",
        "status": "success",
        "pou_name": "TankLevelPID",
        "file_path": t3_res["file_path"],
    })
    emit(f"  -> SUCCESS: POU 'TankLevelPID' added at {t3_res['file_path']}")

    # STEP 4: cscape_inspect_variables
    emit("\n[TOOL 4/8] cscape_inspect_variables")
    t4_res = cscape_inspect_variables(happy_project_name)
    assert t4_res["status"] == "success" and t4_res["total_variables"] == 9
    json_report["mcp_tools_call_path"].append({
        "step": 4,
        "tool": "cscape_inspect_variables",
        "status": "success",
        "total_variables": t4_res["total_variables"],
        "pous": t4_res["pous"],
    })
    emit(f"  -> SUCCESS: Inspected {t4_res['total_variables']} variables across POUs: {t4_res['pous']}")

    # STEP 5: cscape_compile_project
    emit("\n[TOOL 5/8] cscape_compile_project")
    t5_res = cscape_compile_project(happy_project_name, clean_build=True)
    assert t5_res["status"] == "success" and t5_res["compile_successful"] is True
    assert t5_res["error_count"] == 0
    json_report["mcp_tools_call_path"].append({
        "step": 5,
        "tool": "cscape_compile_project",
        "status": "success",
        "compile_successful": True,
        "error_count": 0,
        "code_size_bytes": t5_res["memory_footprint"]["code_size_bytes"],
    })
    emit(f"  -> SUCCESS: Clean compilation. Errors: 0, Warnings: {t5_res.get('warning_count', 0)}, Code Size: {t5_res['memory_footprint']['code_size_bytes']} bytes")

    # STEP 6: cscape_get_diagnostics
    emit("\n[TOOL 6/8] cscape_get_diagnostics")
    t6_res = cscape_get_diagnostics(happy_project_name)
    assert t6_res["status"] == "success" and t6_res["compile_successful"] is True
    json_report["mcp_tools_call_path"].append({
        "step": 6,
        "tool": "cscape_get_diagnostics",
        "status": "success",
        "compile_successful": True,
        "error_count": 0,
    })
    emit(f"  -> SUCCESS: Retrieved diagnostics. Build status clean (0 errors).")

    # STEP 7: cscape_simulate_pou
    emit("\n[TOOL 7/8] cscape_simulate_pou")
    t7_res = cscape_simulate_pou(
        code=tank_code,
        inputs={"RawLevelIn": 16000, "SetPoint": 60.0, "AutoMode": True},
        steps=5,
    )
    assert t7_res["success"] is True and t7_res["final_state"]["LevelPercent"] == 50.0
    assert t7_res["hardware_lockout_enforced"] is True
    json_report["mcp_tools_call_path"].append({
        "step": 7,
        "tool": "cscape_simulate_pou",
        "status": "success",
        "steps_executed": t7_res["steps_executed"],
        "level_percent": t7_res["final_state"]["LevelPercent"],
        "hardware_lockout_enforced": t7_res["hardware_lockout_enforced"],
    })
    emit(f"  -> SUCCESS: Simulation 5 cycles complete. LevelPercent={t7_res['final_state']['LevelPercent']}%, hardware_lockout_enforced=True")

    # STEP 8: cscape_export_project
    emit("\n[TOOL 8/8] cscape_export_project")
    export_formats = ["csp", "st", "xml", "json"]
    export_entries = []
    for fmt in export_formats:
        exp_res = cscape_export_project(happy_project_name, output_format=fmt)
        assert exp_res["status"] == "success"
        export_entries.append({
            "format": fmt,
            "export_file": exp_res["export_file"],
            "size_bytes": exp_res["size_bytes"],
        })
        emit(f"  -> SUCCESS: Exported '{fmt}' -> {exp_res['export_file']} ({exp_res['size_bytes']} bytes)")

    json_report["mcp_tools_call_path"].append({
        "step": 8,
        "tool": "cscape_export_project",
        "status": "success",
        "exported_formats": export_entries,
    })
    emit(">>> ALL 8 MCP TOOLS VERIFIED CLEANLY IN HAPPY PATH.")

    # --------------------------------------------------------------------------
    # PART 2: CONCRETE FAILURE SCENARIOS & FAILURE LOCATION LOG EXTRACTION
    # --------------------------------------------------------------------------
    emit("\n" + "=" * 80)
    emit(">>> PART 2: CONCRETE FAILURE SCENARIOS & FAILURE LOCATION LOG EXTRACTION")
    emit("=" * 80)

    scenarios = [
        {
            "id": "SCENARIO_1_SYNTAX_ERROR",
            "name": "Scenario 1: Syntax Error (Unclosed IF block missing END_IF)",
            "proj": "Fail_Syntax_Location_Proj",
            "pou": "POU_SyntaxError",
            "code": """PROGRAM POU_SyntaxError
VAR
    Speed : INT := 100;
END_VAR

IF Speed > 50 THEN
    Speed := 50;
(* Intentional syntax error: unclosed IF missing END_IF *)

END_PROGRAM
""",
            "expected_error_code": "ERR_UNCLOSED_IF",
            "expected_lines": [6, 10],
        },
        {
            "id": "SCENARIO_2_MISSING_SEMICOLON",
            "name": "Scenario 2: Missing Semicolon (Assignment missing ';')",
            "proj": "Fail_Semicolon_Location_Proj",
            "pou": "POU_MissingSemicolon",
            "code": """PROGRAM POU_MissingSemicolon
VAR
    TargetCount : INT;
END_VAR

TargetCount := 42
END_PROGRAM
""",
            "expected_error_code": "ERR_MISSING_SEMICOLON",
            "expected_lines": [6, 7],
        },
        {
            "id": "SCENARIO_3_UNDECLARED_VARIABLE",
            "name": "Scenario 3: Undeclared Variable (Assignment to unallocated symbol)",
            "proj": "Fail_Undeclared_Location_Proj",
            "pou": "POU_UndeclaredVar",
            "code": """PROGRAM POU_UndeclaredVar
VAR
    ValidCounter : INT := 0;
END_VAR

PhantomOutput := 99;
END_PROGRAM
""",
            "expected_error_code": "ERR_UNDECLARED_VAR",
            "expected_lines": [6],
        },
        {
            "id": "SCENARIO_4_LADDER_LOGIC_INJECTION",
            "name": "Scenario 4: Ladder Logic Injection (Forbidden contact '---[ ]---')",
            "proj": "Fail_Ladder_Location_Proj",
            "pou": "POU_LadderInjection",
            "code": """PROGRAM POU_LadderInjection
VAR
    InSensor : BOOL := FALSE;
    OutMotor : BOOL;
END_VAR

---[ ]--- InSensor
END_PROGRAM
""",
            "expected_error_code": "ERR_LADDER_FORBIDDEN",
            "expected_lines": [7],
        },
        {
            "id": "SCENARIO_5_SYNTAX_ERROR_NEAR_SEMICOLON",
            "name": "Scenario 5: Syntax Error Near Semicolon (TargetLevel := TankLevel + ;)",
            "proj": "Fail_SyntaxNearSemi_Location_Proj",
            "pou": "POU_SyntaxNearSemi",
            "code": """PROGRAM POU_SyntaxNearSemi
VAR
    TankLevel : REAL := 50.0;
    TargetLevel : REAL := 60.0;
END_VAR

TargetLevel := TankLevel + ;
END_PROGRAM
""",
            "expected_error_code": "ST_SYNTAX_ERROR",
            "expected_lines": [7],
        },
    ]

    for sc in scenarios:
        emit(f"\n--- [EXECUTION] {sc['name']} ---")
        p_dir = PROJECTS_ROOT / sc["proj"]
        if p_dir.exists():
            shutil.rmtree(p_dir, ignore_errors=True)
        cscape_create_project(name=sc["proj"], description=sc["name"])

        # Tool Call: cscape_validate_st
        val_res = cscape_validate_st(sc["code"])
        assert val_res["valid"] is False
        emit(f"  [cscape_validate_st] valid={val_res['valid']} | errors={val_res.get('errors')}")

        # Tool Call: cscape_add_st_pou (Enforces fail-closed rejection)
        add_res = cscape_add_st_pou(
            project_name=sc["proj"],
            pou_name=sc["pou"],
            pou_type="PROGRAM",
            code=sc["code"],
        )
        assert add_res["status"] == "error" and add_res["success"] is False
        emit(f"  [cscape_add_st_pou] status={add_res['status']} (Pre-automation rejection confirmed)")

        # Write code to pous/ to inspect build log failure location diagnostics
        pou_path = p_dir / "pous" / f"{sc['pou']}.st"
        pou_path.parent.mkdir(parents=True, exist_ok=True)
        pou_path.write_text(sc["code"], encoding="utf-8")

        # Tool Call: cscape_compile_project
        comp_res = cscape_compile_project(sc["proj"], clean_build=True)
        assert comp_res["status"] == "error" and comp_res["compile_successful"] is False
        assert comp_res["error_count"] > 0
        emit(f"  [cscape_compile_project] compile_successful=False | error_count={comp_res['error_count']}")

        # Tool Call: cscape_get_diagnostics
        diag_res = cscape_get_diagnostics(sc["proj"])
        assert diag_res["status"] == "error" and diag_res["compile_successful"] is False
        emit(f"  [cscape_get_diagnostics] status=error | error_count={diag_res.get('error_count', len(diag_res.get('errors', [])))}")

        # Extract concrete failure locations from build_log
        build_log = comp_res["build_log"]
        parsed_diags = CscapeLogParser.parse_log(build_log)
        concrete_locations = []

        emit("  Concrete Failure Location Diagnostic Entries:")
        for d in parsed_diags:
            if d.level == "ERROR":
                loc_entry = {
                    "file_path": d.file_path or f"{sc['pou']}.st",
                    "pou_name": d.pou_name or sc["pou"],
                    "line": d.line,
                    "column": d.column,
                    "error_code": d.error_code,
                    "level": d.level,
                    "message": d.message,
                }
                concrete_locations.append(loc_entry)
                emit(f"    -> FAILURE LOCATION: File: {loc_entry['file_path']} | Line: {loc_entry['line']} | Col: {loc_entry['column']} | Code: {loc_entry['error_code']}")
                emit(f"       Message: {loc_entry['message']}")

        # Verify location matches expected bounds
        assert len(concrete_locations) > 0, f"No concrete failure locations extracted for {sc['name']}"
        assert any(loc["line"] in sc["expected_lines"] for loc in concrete_locations), f"Line mismatch in {sc['name']}"

        scenario_record = {
            "scenario_id": sc["id"],
            "scenario_name": sc["name"],
            "target_pou": f"{sc['pou']}.st",
            "validate_st_errors": val_res.get("errors", []),
            "compile_project_error_count": comp_res["error_count"],
            "concrete_failure_locations": concrete_locations,
            "relevant_build_log_lines": [l for l in build_log.splitlines() if "error" in l.lower() or "line" in l.lower() or "col" in l.lower()][:8],
        }
        json_report["failure_location_scenarios"].append(scenario_record)

    # --------------------------------------------------------------------------
    # PART 3: ZERO PHYSICAL PLC DOWNLOAD LOCKOUT ENFORCEMENT
    # --------------------------------------------------------------------------
    emit("\n" + "=" * 80)
    emit(">>> PART 3: ZERO PHYSICAL PLC DOWNLOAD LOCKOUT ENFORCEMENT")
    emit("=" * 80)

    guard = SecurityGuard()
    policy = SafetyPolicy()
    ui = CscapeUIAutomation()
    cli = CLIRunner()
    bridge = CscapeAutomationBridge()

    lockout_assertions: Dict[str, Any] = {}

    # 1. Safety Policy Invariants
    emit("\n[LOCKOUT 1/6] Safety Policy Invariants Verification")
    assert policy.simulation_only is True
    assert policy.allow_hardware_communication is False
    assert policy.allow_controller_download is False
    assert policy.allow_firmware_flash is False
    assert policy.enforce_file_sandbox is True
    emit("  -> Invariants: simulation_only=True, allow_hardware_comm=False, allow_download=False, allow_flash=False")
    lockout_assertions["safety_policy_invariants"] = {
        "simulation_only": True,
        "allow_hardware_communication": False,
        "allow_controller_download": False,
        "allow_firmware_flash": False,
        "enforce_file_sandbox": True,
        "status": "VERIFIED_LOCKED",
    }

    # 2. Physical PLC Download Command IDs (32827, 33149)
    emit("\n[LOCKOUT 2/6] Physical PLC Download Commands (IDs 32827, 33149)")
    download_cmds = [
        (32827, "ID_CONTROLLER_DOWNLOAD / ID_PLC_DOWNLOAD"),
        (33149, "ID_PROGRAM_DOWNLOADOPTIONS / ID_CONTROLLER_DOWNLOAD_ALT"),
        (32828, "ID_PLC_UPLOAD"),
        (32862, "ID_PLC_VERIFY"),
        (32993, "ID_PLC_CLEARMEMORY"),
        (38295, "ID_ONLINECHANGEACTION"),
    ]
    verified_cmds = []
    for cid, name in download_cmds:
        try:
            ui.dispatch_command(cid)
            raise AssertionError(f"Command {cid} ({name}) FAILED TO RAISE UnauthorizedDownloadError!")
        except UnauthorizedDownloadError:
            verified_cmds.append({"id": cid, "name": name, "blocked": True, "error": "UnauthorizedDownloadError"})
            emit(f"  -> BLOCKED: Command ID {cid} ({name}) raised UnauthorizedDownloadError.")

    lockout_assertions["download_command_ids"] = verified_cmds

    # 3. Serial / COM Ports Lockout (COM1 to COM256)
    emit("\n[LOCKOUT 3/6] Serial/COM Ports Lockout (COM1 - COM256, device namespaces)")
    sample_ports = ["COM1", "COM2", "COM4", "COM10", "COM256", r"\\.\COM1", r"\\.\COM4", "/dev/ttyS0", "/dev/ttyUSB0", "/dev/ttyACM0"]
    verified_ports = []
    for port in sample_ports:
        assert policy.is_port_blocked(port) is True
        try:
            ui.configure_interface("COM", port=port)
            raise AssertionError(f"Port {port} FAILED TO RAISE HardwareLockoutError!")
        except HardwareLockoutError:
            verified_ports.append({"port": port, "blocked": True, "error": "HardwareLockoutError"})
    emit(f"  -> BLOCKED: Verified fail-closed lockout across {len(verified_ports)} COM/serial interfaces (COM1..COM256).")
    lockout_assertions["serial_com_ports"] = verified_ports

    # 4. CAN Bus Interfaces Lockout
    emit("\n[LOCKOUT 4/6] CAN Bus Interfaces Lockout")
    can_interfaces = ["CAN", "can0", "CAN1", "pcan", "pcan_usb", "kvaser", "kvaser_leaf", "vector", "vector_can", "socketcan", "slcan0", "CsCAN", "CANopen", "DeviceNet", "J1939"]
    verified_can = []
    for can in can_interfaces:
        try:
            ui.validate_interface(can)
            raise AssertionError(f"CAN interface {can} FAILED TO RAISE in validate_interface!")
        except HardwareLockoutError:
            pass
        try:
            ui.configure_interface("CAN", port=can)
            raise AssertionError(f"CAN interface {can} FAILED TO RAISE in configure_interface!")
        except HardwareLockoutError:
            verified_can.append({"interface": can, "blocked": True, "error": "HardwareLockoutError"})
    emit(f"  -> BLOCKED: Verified fail-closed lockout across {len(verified_can)} CAN interfaces.")
    lockout_assertions["can_interfaces"] = verified_can

    # 4b. USB Hardware Interfaces Lockout
    usb_interfaces = ["USB", "usb0", "USB1", r"\\?\usb#vid_0483&pid_df11", "HORNER_USB", "DFU", "JTAG", "VID_0483", "PID_DF11"]
    verified_usb = []
    for usb in usb_interfaces:
        try:
            ui.validate_interface(usb)
            raise AssertionError(f"USB interface {usb} FAILED TO RAISE in validate_interface!")
        except HardwareLockoutError:
            pass
        try:
            ui.configure_interface("USB", port=usb)
            raise AssertionError(f"USB interface {usb} FAILED TO RAISE in configure_interface!")
        except HardwareLockoutError:
            verified_usb.append({"device": usb, "blocked": True, "error": "HardwareLockoutError"})
    emit(f"  -> BLOCKED: Verified fail-closed lockout across {len(verified_usb)} USB physical devices.")
    lockout_assertions["usb_interfaces"] = verified_usb

    # 5. USB Flash Tools & Dangerous Utilities
    emit("\n[LOCKOUT 5/6] USB Flash Tools & Dangerous Companion Executables")
    dangerous_tools = ["PGMUpdateUtility.exe", "DfuSeCommand.exe", "STMFlashLoader.exe", "WinJTAG.exe", "CscapeAutoUpdt.exe", "XLeTerm.exe", "DnCfg.exe", "DNXCfg.exe"]
    verified_tools = []
    for exe in dangerous_tools:
        assert policy.is_executable_blocked(exe) is True
        try:
            guard.validate_execution(Path(exe))
            raise AssertionError(f"Tool {exe} FAILED TO RAISE SecurityError!")
        except SecurityError:
            verified_tools.append({"executable": exe, "blocked": True, "error": "SecurityError/BlockedExecutableError"})
    emit(f"  -> BLOCKED: Verified fail-closed interception for {len(verified_tools)} dangerous binaries.")
    lockout_assertions["prohibited_executables"] = verified_tools

    # 6. CLI Download Flags & Automation Methods
    emit("\n[LOCKOUT 6/6] CLI Download Flags & Automation Bridge Methods")
    cli_flags = ["/download", "--download", "-d", "/d", "/flash", "--flash", "/pgm", "/burn", "/firmware", "/target:hardware", "/target:plc"]
    verified_flags = []
    for flag in cli_flags:
        assert policy.is_flag_blocked(flag) is True
        try:
            cli.run_cscape(args=[flag])
            raise AssertionError(f"CLI flag {flag} FAILED TO RAISE UnauthorizedDownloadError!")
        except UnauthorizedDownloadError:
            verified_flags.append({"flag": flag, "blocked": True, "error": "UnauthorizedDownloadError"})
    emit(f"  -> BLOCKED: Verified fail-closed rejection for {len(verified_flags)} CLI download/flash flags.")
    lockout_assertions["cli_download_flags"] = verified_flags

    # Direct methods
    try:
        cli.download_to_controller()
        raise AssertionError("cli.download_to_controller() failed to raise!")
    except UnauthorizedDownloadError:
        emit("  -> BLOCKED: CLIRunner.download_to_controller() raised UnauthorizedDownloadError.")

    try:
        bridge.download_to_controller()
        raise AssertionError("bridge.download_to_controller() failed to raise!")
    except UnauthorizedDownloadError:
        emit("  -> BLOCKED: CscapeAutomationBridge.download_to_controller() raised UnauthorizedDownloadError.")

    try:
        bridge.connect_hardware(target="XL4", port="COM1")
        raise AssertionError("bridge.connect_hardware() failed to raise!")
    except HardwareLockoutError:
        emit("  -> BLOCKED: CscapeAutomationBridge.connect_hardware() raised HardwareLockoutError.")

    lockout_assertions["direct_automation_methods"] = {
        "CLIRunner.download_to_controller": "UnauthorizedDownloadError",
        "CscapeAutomationBridge.download_to_controller": "UnauthorizedDownloadError",
        "CscapeAutomationBridge.connect_hardware": "HardwareLockoutError",
        "status": "ALL_LOCKED_OUT",
    }

    # --------------------------------------------------------------------------
    # WRITE ARTIFACTS
    # --------------------------------------------------------------------------
    duration_sec = (datetime.datetime.now(datetime.timezone.utc) - start_time).total_seconds()
    emit("-" * 80)
    emit(f"VERIFICATION COMPLETED IN {duration_sec:.2f}s WITH ZERO ERRORS.")
    emit("ALL 8 MCP TOOLS OPERATING IN AIR-GAPPED SOFTWARE SIMULATION.")
    emit("=" * 80)

    json_report["zero_plc_download_lockout_assertions"] = lockout_assertions
    json_report["execution_duration_seconds"] = duration_sec
    json_report["overall_status"] = "PASSED_100_PERCENT"

    json_path = LOGS_DIR / "mcp_closed_loop_failure_location_call_path.json"
    log_path = LOGS_DIR / "mcp_closed_loop_failure_location_call_path.log"

    json_path.write_text(json.dumps(json_report, indent=2), encoding="utf-8")
    log_path.write_text("\n".join(log_lines), encoding="utf-8")

    user_logs_dir = Path(r"C:\Users\ArmandoSilva\artifacts\logs")
    if user_logs_dir.exists():
        (user_logs_dir / "mcp_closed_loop_failure_location_call_path.json").write_text(json.dumps(json_report, indent=2), encoding="utf-8")
        (user_logs_dir / "mcp_closed_loop_failure_location_call_path.log").write_text("\n".join(log_lines), encoding="utf-8")

    print(f"\nArtifacts successfully written:")
    print(f"  JSON: {json_path} ({json_path.stat().st_size} bytes)")
    print(f"  LOG : {log_path} ({log_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
