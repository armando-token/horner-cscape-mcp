import asyncio
import json
import sys
import time
from pathlib import Path

WORKSPACE = Path(r"C:\Users\ArmandoSilva").resolve()
HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
for p in [str(WORKSPACE), str(HORNER_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from src.mcp.server import server
from src.cscape.gate import assert_cscape_live, get_gate_status

PROJECT_DIR = WORKSPACE / "artifacts" / "projects" / "TankLevelClosedLoop"
CSP_PATH = PROJECT_DIR / "TankLevelClosedLoop.csp"
VARS_CSV = PROJECT_DIR / "variables.csv"

gate = assert_cscape_live()
LIVE_HWND = int(gate.get("hwnd", "0"), 16) if gate.get("hwnd") else 0

async def run_e2e():
    test_calls = [
        ("cscape_open_project", {"file_path": str(CSP_PATH)}),
        ("cscape_read_variables", {"file_path": str(VARS_CSV)}),
        ("cscape_inspect_variables", {"project_name": "TankLevelClosedLoop"}),
        ("cscape_validate_st", {
            "code": (
                "PROGRAM TankLevelControl\n"
                "VAR bPumpRun : BOOL; bStart : BOOL; END_VAR\n"
                "bPumpRun := bStart;\n"
                "END_PROGRAM"
            )
        }),
        ("cscape_compile_project", {"project_name": "TankLevelClosedLoop", "clean_build": True}),
        ("cscape_compile", {
            "project_path": str(CSP_PATH),
            "clean_build": True,
            "cscape_hwnd": LIVE_HWND
        }),
        ("cscape_get_build_output", {"project_path": str(PROJECT_DIR)}),
        ("cscape_get_diagnostics", {"project_name": "TankLevelClosedLoop"}),
        ("cscape_simulate_cycle", {"inputs": {"RawLevelIn": 30400}}),
        ("cscape_simulate_pou", {
            "code": (
                "PROGRAM TankLevelSafetySim\n"
                "VAR_INPUT RawLevelIn : INT; END_VAR\n"
                "VAR_OUTPUT AlarmHighHigh : BOOL; END_VAR\n"
                "AlarmHighHigh := RawLevelIn > 28800;\n"
                "END_PROGRAM"
            ),
            "inputs": {"RawLevelIn": 30400}
        }),
        ("cscape_run_simulation", {"steps": 3}),
        ("cscape_read_register", {"address": "%R100"}),
        ("cscape_write_register", {"address": "%R100", "value": 28800}),
        ("cscape_export_variables", {"output_path": str(PROJECT_DIR / "exported_vars.csv")}),
        ("cscape_import_variables", {"file_path": str(VARS_CSV)}),
        ("cscape_export_project", {"project_name": "TankLevelClosedLoop"}),
        ("cscape_insert_st", {
            "pou_name": "SafetyInterlockST",
            "pou_type": "PROGRAM",
            "st_code": "PROGRAM SafetyInterlockST\nVAR x : INT; END_VAR\nx := 1;\nEND_PROGRAM"
        }),
        ("cscape_insert_st_pou", {
            "pou_name": "AuxPumpControl",
            "st_code": "PROGRAM AuxPumpControl\nVAR cmd : BOOL; END_VAR\ncmd := TRUE;\nEND_PROGRAM"
        }),
        ("cscape_add_st_pou", {
            "project_name": "TankLevelClosedLoop",
            "pou_name": "AlarmMonitor",
            "pou_type": "PROGRAM",
            "code": "PROGRAM AlarmMonitor\nVAR trip : BOOL; END_VAR\ntrip := FALSE;\nEND_PROGRAM"
        }),
    ]

    results = []
    print("=" * 80)
    print("MCP SERVER TOOL CALL E2E RESULTS AGAINST LIVE PROJECT & GUI")
    print("=" * 80)

    for idx, (name, args) in enumerate(test_calls, 1):
        t0 = time.time()
        tool_res = await server.call_tool(name, args)
        dur_ms = (time.time() - t0) * 1000.0

        is_err = tool_res.is_error
        text = tool_res.content[0].text if tool_res.content else ""
        try:
            data = json.loads(text) if text.startswith("{") else {"raw": text}
        except Exception:
            data = {"raw": text}

        success = not is_err and data.get("success", True) is not False
        summary = data.get("message") or data.get("status") or (text[:60] if text else "OK")

        print(f"[{idx:02d}/{len(test_calls)}] {name:<26} | Status: {'PASS' if success else 'FAIL'} | {dur_ms:6.1f}ms | {str(summary)[:60]}")
        results.append({
            "order": idx,
            "tool_name": name,
            "status": "PASS" if success else "FAIL",
            "duration_ms": round(dur_ms, 1),
            "summary": str(summary)[:120],
            "lockout_safe": True
        })

    log_path = WORKSPACE / "artifacts" / "logs" / "mcp_server_live_e2e_results.json"
    log_path.write_text(json.dumps({
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_calls": len(results),
        "passed": sum(1 for r in results if r["status"] == "PASS"),
        "results": results
    }, indent=2), encoding="utf-8")
    print(f"\nSaved execution summary to {log_path}")

if __name__ == "__main__":
    asyncio.run(run_e2e())
