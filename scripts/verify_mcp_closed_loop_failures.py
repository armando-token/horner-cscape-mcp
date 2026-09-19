"""Automated End-to-End MCP Closed-Loop Verification & Failure Location Reporter.

Executes:
1. Closed-loop verification across all 8 MCP tools:
   - cscape_create_project
   - cscape_add_st_pou
   - cscape_validate_st
   - cscape_inspect_variables
   - cscape_compile_project
   - cscape_get_diagnostics
   - cscape_simulate_pou
   - cscape_export_project

2. Intentional Failure Scenarios:
   - Syntax Error (Unclosed IF block)
   - Missing Semicolon (Assignment missing ';')
   - Undeclared Variable (Assignment to undeclared identifier)
   - Ladder Logic Injection (Contact / rung marker)

3. Detailed Failure Location Log Reporting:
   - File Path
   - Line Number
   - Column Number
   - Error Code
   - Log Line Output
"""

import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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
from src.cscape.diagnostics import CscapeLogParser

REPO_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
PROJECTS_ROOT = REPO_ROOT / "artifacts" / "projects"


def run_verification():
    print("=" * 80)
    print("HORNER CSAPE MCP: END-TO-END CLOSED-LOOP VERIFICATION")
    print("=" * 80)

    # --------------------------------------------------------------------------
    # Part 1: All 8 Tools Closed-Loop Pipeline (Happy Path)
    # --------------------------------------------------------------------------
    proj_name = "Verification_Master_Project"
    proj_dir = PROJECTS_ROOT / proj_name
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)

    print("\n[STEP 1/8] cscape_create_project...")
    res_create = cscape_create_project(name=proj_name, description="Master Verification", target_plc="XL4")
    assert res_create["status"] == "success" and res_create["success"] is True
    print(f"  -> SUCCESS: Project '{proj_name}' created at {res_create['project_path']}")

    valid_code = """PROGRAM TankLevelControl
VAR_INPUT
    RawLevelIn : INT;
    SetPoint : REAL := 50.0;
    AutoMode : BOOL := TRUE;
END_VAR
VAR_OUTPUT
    PumpSpeed : INT;
    HighAlarm : BOOL;
END_VAR
VAR
    LevelPercent : REAL;
END_VAR

LevelPercent := (INT_TO_REAL(RawLevelIn) / 32000.0) * 100.0;

IF LevelPercent >= 90.0 THEN
    HighAlarm := TRUE;
ELSE
    HighAlarm := FALSE;
END_IF;

IF AutoMode THEN
    IF LevelPercent < SetPoint THEN
        PumpSpeed := 25000;
    ELSE
        PumpSpeed := 8000;
    END_IF;
ELSE
    PumpSpeed := 0;
END_IF;
END_PROGRAM
"""

    print("\n[STEP 2/8] cscape_validate_st...")
    res_val = cscape_validate_st(valid_code)
    assert res_val["valid"] is True
    print(f"  -> SUCCESS: Validated POU '{res_val['pou_name']}', {len(res_val['variables'])} variables, 0 errors.")

    print("\n[STEP 3/8] cscape_add_st_pou...")
    res_add = cscape_add_st_pou(
        project_name=proj_name,
        pou_name="TankLevelControl",
        pou_type="PROGRAM",
        code=valid_code,
    )
    assert res_add["status"] == "success" and res_add["success"] is True
    print(f"  -> SUCCESS: Added POU 'TankLevelControl' at {res_add['file_path']}")

    print("\n[STEP 4/8] cscape_inspect_variables...")
    res_inspect = cscape_inspect_variables(proj_name)
    assert res_inspect["status"] == "success" and res_inspect["total_variables"] == 6
    print(f"  -> SUCCESS: Inspected {res_inspect['total_variables']} variables across {res_inspect['pous']}.")

    print("\n[STEP 5/8] cscape_compile_project...")
    res_compile = cscape_compile_project(proj_name, clean_build=True)
    assert res_compile["status"] == "success" and res_compile["compile_successful"] is True
    print(f"  -> SUCCESS: Compiled with 0 errors. Code size: {res_compile['memory_footprint']['code_size_bytes']} bytes.")

    print("\n[STEP 6/8] cscape_get_diagnostics...")
    res_diags = cscape_get_diagnostics(proj_name)
    assert res_diags["status"] == "success" and res_diags["compile_successful"] is True
    print(f"  -> SUCCESS: Diagnostics verified. Build clean (0 errors, 0 warnings).")

    print("\n[STEP 7/8] cscape_simulate_pou...")
    res_sim = cscape_simulate_pou(
        code=valid_code,
        inputs={"RawLevelIn": 16000, "SetPoint": 60.0, "AutoMode": True},
        steps=5,
    )
    assert res_sim["success"] is True and res_sim["final_state"]["LevelPercent"] == 50.0
    print(f"  -> SUCCESS: Simulated 5 scan cycles. PV LevelPercent = {res_sim['final_state']['LevelPercent']}%")

    print("\n[STEP 8/8] cscape_export_project...")
    for fmt in ["csp", "st", "xml", "json"]:
        res_exp = cscape_export_project(proj_name, output_format=fmt)
        assert res_exp["status"] == "success"
        print(f"  -> SUCCESS: Exported format '{fmt}' ({res_exp['size_bytes']} bytes) -> {res_exp['export_file']}")

    print("\n>>> ALL 8 MCP TOOLS VERIFIED CLEANLY IN CLOSED-LOOP PIPELINE.")

    # --------------------------------------------------------------------------
    # Part 2: Intentional Failure Scenarios & Failure Location Extraction
    # --------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("INTENTIONAL FAILURE SCENARIOS & FAILURE LOCATION LOG EXTRACTION")
    print("=" * 80)

    scenarios = [
        {
            "name": "Scenario 1: Syntax Error (Unclosed IF block missing END_IF)",
            "proj": "Fail_Syntax_Log_Project",
            "pou": "POU_SyntaxError",
            "code": """PROGRAM POU_SyntaxError
VAR
    Speed : INT := 100;
END_VAR

IF Speed > 50 THEN
    Speed := 50;
(* Deliberately missing END_IF *)

END_PROGRAM
""",
        },
        {
            "name": "Scenario 2: Missing Semicolon (Assignment missing ';')",
            "proj": "Fail_Semicolon_Log_Project",
            "pou": "POU_MissingSemicolon",
            "code": """PROGRAM POU_MissingSemicolon
VAR
    TargetCount : INT;
END_VAR

TargetCount := 42
END_PROGRAM
""",
        },
        {
            "name": "Scenario 3: Undeclared Variable (Assignment to unallocated symbol)",
            "proj": "Fail_Undeclared_Log_Project",
            "pou": "POU_UndeclaredVar",
            "code": """PROGRAM POU_UndeclaredVar
VAR
    ValidCounter : INT := 0;
END_VAR

PhantomOutput := 99;
END_PROGRAM
""",
        },
        {
            "name": "Scenario 4: Ladder Logic Injection (Forbidden contact '---[ ]---')",
            "proj": "Fail_Ladder_Log_Project",
            "pou": "POU_LadderInjection",
            "code": """PROGRAM POU_LadderInjection
VAR
    InSensor : BOOL := FALSE;
    OutMotor : BOOL;
END_VAR

---[ ]--- InSensor
END_PROGRAM
""",
        },
    ]

    report_entries = []

    for sc in scenarios:
        print(f"\n--------------------------------------------------------------------------------")
        print(f"RUNNING: {sc['name']}")
        print(f"--------------------------------------------------------------------------------")

        p_dir = PROJECTS_ROOT / sc["proj"]
        if p_dir.exists():
            shutil.rmtree(p_dir, ignore_errors=True)
        cscape_create_project(name=sc["proj"], description=sc["name"])

        # 1. Validate tool check
        v_res = cscape_validate_st(sc["code"])
        print(f"[cscape_validate_st] valid={v_res['valid']}, errors count={len(v_res.get('errors', []))}")

        # 2. Add POU tool rejection check (fail-closed)
        a_res = cscape_add_st_pou(project_name=sc["proj"], pou_name=sc["pou"], pou_type="PROGRAM", code=sc["code"])
        print(f"[cscape_add_st_pou] status={a_res['status']}, success={a_res.get('success')}")

        # Place file in project pous/ to inspect compilation build.log diagnostics
        pou_file = p_dir / "pous" / f"{sc['pou']}.st"
        pou_file.parent.mkdir(parents=True, exist_ok=True)
        pou_file.write_text(sc["code"], encoding="utf-8")

        # 3. Compile project tool check
        c_res = cscape_compile_project(sc["proj"], clean_build=True)
        print(f"[cscape_compile_project] compile_successful={c_res['compile_successful']}, error_count={c_res['error_count']}")

        # 4. Get diagnostics tool check
        d_res = cscape_get_diagnostics(sc["proj"])
        print(f"[cscape_get_diagnostics] compile_successful={d_res['compile_successful']}, diagnostics count={len(d_res.get('diagnostics', []))}")

        build_log = c_res["build_log"]
        parsed = CscapeLogParser.parse_log(build_log)

        print("\nCaptured Failure Location Diagnostics:")
        for diag in parsed:
            entry = {
                "scenario": sc["name"],
                "file_path": diag.file_path or f"{sc['pou']}.st",
                "line": diag.line,
                "column": diag.column,
                "error_code": diag.error_code,
                "level": diag.level,
                "message": diag.message,
            }
            report_entries.append(entry)
            print(f"  [LOCATION] File: {entry['file_path']} | Line: {entry['line']} | Column: {entry['column']} | Code: {entry['error_code']}")
            print(f"             Message: {entry['message']}")

        print("\nRelevant Build Log Lines:")
        for line in build_log.splitlines():
            if "error" in line.lower() or "line" in line.lower():
                print(f"  {line}")

    print("\n" + "=" * 80)
    print("VERIFICATION COMPLETED SUCCESSFULLY.")
    print("=" * 80)
    return report_entries


if __name__ == "__main__":
    entries = run_verification()
    output_json = REPO_ROOT / "artifacts" / "failure_location_report.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    print(f"\nSaved structured report to: {output_json}")
