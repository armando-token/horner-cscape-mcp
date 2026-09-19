import asyncio
import ctypes
import json
import sys
import time
from pathlib import Path
import psutil

WORKSPACE = Path(r"C:\Users\ArmandoSilva").resolve()
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from src.mcp.server import server

WORKSPACE = Path(r"C:\Users\ArmandoSilva").resolve()
PROJECT_DIR = WORKSPACE / "artifacts" / "projects" / "TankLevelClosedLoop"
CSP_PATH = PROJECT_DIR / "TankLevelClosedLoop.csp"
VARS_CSV = PROJECT_DIR / "variables.csv"

user32 = ctypes.windll.user32
h_default = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if h_default:
    user32.SetThreadDesktop(h_default)

def check_cscape():
    pid = 12684
    if not psutil.pid_exists(pid):
        return None, False, "Process does not exist"
    proc = psutil.Process(pid)
    hwnd = 17367438
    hung = user32.IsHungAppWindow(hwnd)
    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    return pid, hung == 0, title_buf.value

async def run_e2e_suite():
    pid, responsive, title = check_cscape()
    print(f"[PRE-CHECK] Cscape PID: {pid} | Responsive: {responsive} | Title: {title}")
    assert responsive, "Cscape is not responsive before starting suite!"

    tools_to_test = [
        ("cscape_launch_ide", {"timeout_seconds": 15.0}),
        ("cscape_open_project", {"file_path": str(CSP_PATH)}),
        ("cscape_validate_st", {
            "st_code": (
                "PROGRAM TankLevelControl\n"
                "VAR\n"
                "    bPumpRun : BOOL;\n"
                "    bStartSwitch : BOOL;\n"
                "    bStopSwitch : BOOL;\n"
                "END_VAR\n"
                "bPumpRun := (bStartSwitch OR bPumpRun) AND NOT bStopSwitch;\n"
                "END_PROGRAM"
            )
        }),
        ("cscape_inspect_variables", {"project_name": "TankLevelClosedLoop"}),
        ("cscape_read_variables", {"file_path": str(VARS_CSV)}),
        ("cscape_compile", {
            "project_path": str(CSP_PATH),
            "clean_build": True,
            "cscape_hwnd": 17367438
        }),
        ("cscape_compile_project", {"project_name": "TankLevelClosedLoop", "clean_build": True}),
        ("cscape_get_build_output", {"project_name": "TankLevelClosedLoop"}),
        ("cscape_get_diagnostics", {"project_name": "TankLevelClosedLoop"}),
        ("cscape_simulate_cycle", {
            "st_code": (
                "PROGRAM TankCycle\n"
                "VAR_INPUT RawLevelIn : INT; END_VAR\n"
                "VAR_OUTPUT TankPV : REAL; AlarmHighHigh : BOOL; END_VAR\n"
                "TankPV := (INT_TO_REAL(RawLevelIn) / 32000.0) * 100.0;\n"
                "AlarmHighHigh := TankPV >= 90.0;\n"
                "END_PROGRAM"
            ),
            "inputs": {"RawLevelIn": 30400}
        }),
        ("cscape_simulate_pou", {
            "st_code": (
                "PROGRAM SafetyInterlock\n"
                "VAR_INPUT Level : REAL; END_VAR\n"
                "VAR_OUTPUT EvacuationPump : BOOL; END_VAR\n"
                "EvacuationPump := Level >= 90.0;\n"
                "END_PROGRAM"
            ),
            "inputs": {"Level": 95.0}
        }),
        ("cscape_run_simulation", {"cycles": 3, "initial_inputs": {"RawLevelIn": 16000}}),
        ("cscape_read_register", {"address": "%R100"}),
        ("cscape_write_register", {"address": "%R100", "value": 28800}),
        ("cscape_export_variables", {
            "output_path": str(PROJECT_DIR / "exported_vars.csv"),
            "format": "CSV"
        }),
        ("cscape_import_variables", {"file_path": str(VARS_CSV)}),
        ("cscape_export_project", {"project_name": "TankLevelClosedLoop", "output_format": "JSON"}),
        ("cscape_insert_st", {
            "pou_name": "SafetyInterlockST",
            "pou_type": "PROGRAM",
            "st_code": "PROGRAM SafetyInterlockST\nVAR x : INT; END_VAR\nx := 1;\nEND_PROGRAM",
            "target_project_path": str(PROJECT_DIR)
        }),
        ("cscape_insert_st_pou", {
            "pou_name": "AuxPumpControl",
            "st_code": "PROGRAM AuxPumpControl\nVAR cmd : BOOL; END_VAR\ncmd := TRUE;\nEND_PROGRAM",
            "target_project_path": str(PROJECT_DIR)
        }),
        ("cscape_add_st_pou", {
            "project_name": "TankLevelClosedLoop",
            "pou_name": "AlarmMonitor",
            "st_code": "PROGRAM AlarmMonitor\nVAR trip : BOOL; END_VAR\ntrip := FALSE;\nEND_PROGRAM"
        }),
    ]

    results = []
    print("\n" + "=" * 80)
    print("EXECUTING MCP TOOL CALL E2E SUITE VIA SERVER AGAINST LIVE GUI")
    print("=" * 80)

    for idx, (name, args) in enumerate(tools_to_test, 1):
        t0 = time.time()
        try:
            tool_res = await server.call_tool(name, args)
            dur_ms = (time.time() - t0) * 1000.0
            is_err = tool_res.is_error
            text = tool_res.content[0].text if tool_res.content else ""
            data = json.loads(text) if text.startswith("{") else {"raw": text}
            success = not is_err and data.get("success", True) is not False

            summary = (
                data.get("message")
                or data.get("status")
                or f"Success ({len(text)} bytes)"
            )
            print(f"[{idx:02d}/20] {name:<26} | Status: {'SUCCESS' if success else 'ERROR'} | {dur_ms:6.1f}ms | {summary[:60]}")
            results.append({
                "index": idx,
                "tool_name": name,
                "success": success,
                "duration_ms": round(dur_ms, 1),
                "summary": str(summary)[:120],
                "error": is_err
            })
        except Exception as e:
            dur_ms = (time.time() - t0) * 1000.0
            print(f"[{idx:02d}/20] {name:<26} | Status: EXCEPTION | {dur_ms:6.1f}ms | {str(e)[:60]}")
            results.append({
                "index": idx,
                "tool_name": name,
                "success": False,
                "duration_ms": round(dur_ms, 1),
                "summary": str(e)[:120],
                "error": True
            })

    # Post-check Cscape
    pid_post, responsive_post, title_post = check_cscape()
    print("\n" + "=" * 80)
    print(f"[POST-CHECK] Cscape PID: {pid_post} | Responsive: {responsive_post} | Title: {title_post}")
    print("=" * 80)

    # Write execution log
    log_file = WORKSPACE / "artifacts" / "logs" / "mcp_live_gui_e2e_results.json"
    log_file.write_text(json.dumps({
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cscape_pid": pid_post,
        "cscape_responsive": responsive_post,
        "cscape_title": title_post,
        "total_tools_called": len(results),
        "successful_tools": sum(1 for r in results if r["success"]),
        "results": results
    }, indent=2), encoding="utf-8")
    print(f"Results saved to {log_file}")

if __name__ == "__main__":
    asyncio.run(run_e2e_suite())
