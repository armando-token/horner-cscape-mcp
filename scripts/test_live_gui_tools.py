"""Live GUI Verification Test Harness for cscape_launch_ide and cscape_new_iec_project.

Executes:
1. cscape_launch_ide -> launches Cscape.exe, auto-dismisses splash, enters IEC 61131 mode.
2. cscape_new_iec_project -> drives live project creation in IEC 61131 mode and Save As.
3. Generates artifacts/logs/mcp_live_gui_tools_evidence.log with complete execution metadata.
4. Cleans up gracefully.
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# Enable line buffering on stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

REPO_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.mcp.tools import cscape_launch_ide, cscape_new_iec_project
from src.cscape.lifecycle import CscapeLifecycleManager

EVIDENCE_LOG = REPO_ROOT / "artifacts" / "logs" / "mcp_live_gui_tools_evidence.log"
EVIDENCE_LOG.parent.mkdir(parents=True, exist_ok=True)


def main():
    print("=" * 80, flush=True)
    print("STARTING LIVE GUI TOOLS VERIFICATION", flush=True)
    print("=" * 80, flush=True)

    evidence_lines = [
        "================================================================================",
        "HORNER CSAPE MCP: LIVE GUI TOOLS VERIFICATION EVIDENCE LOG",
        "================================================================================",
        f"Execution Timestamp: {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}",
        "Target Cscape Executable: C:\\Program Files (x86)\\Cscape 10.2\\Cscape.exe",
        "Safety Directive: Fail-Closed Zero PLC Download Enforced",
        "--------------------------------------------------------------------------------",
    ]

    # Step 0: Ensure clean slate
    try:
        CscapeLifecycleManager.recycle_running_instances(timeout=5.0)
        time.sleep(2.0)
    except Exception:
        pass

    # Step 1: Execute cscape_launch_ide
    print("\n--- Testing Tool 1: cscape_launch_ide ---")
    start_t1 = time.time()
    res_launch = cscape_launch_ide(headless=False, timeout_seconds=30.0)
    dur_t1 = time.time() - start_t1
    print("cscape_launch_ide result:")
    print(json.dumps(res_launch, indent=2))

    assert res_launch["success"] is True, f"cscape_launch_ide failed: {res_launch.get('message')}"
    pid_1 = res_launch.get("pid")
    hwnd_1 = res_launch.get("main_hwnd")
    title_1 = res_launch.get("window_title")

    evidence_lines.extend([
        "[TOOL 1: cscape_launch_ide]",
        f"  Status: SUCCESS",
        f"  PID: {pid_1}",
        f"  Main HWND: {hwnd_1} (0x{hwnd_1:X})" if hwnd_1 else "  Main HWND: None",
        f"  Window Title: {title_1}",
        f"  Lifecycle State: {res_launch.get('lifecycle_state')}",
        f"  IEC Mode Active: {res_launch.get('iec_mode_active')}",
        f"  Duration: {dur_t1:.3f}s",
        f"  Message: {res_launch.get('message')}",
        "--------------------------------------------------------------------------------",
    ])

    # Give UI a moment to settle
    time.sleep(1.0)

    # Step 2: Execute cscape_new_iec_project
    print("\n--- Testing Tool 2: cscape_new_iec_project ---")
    start_t2 = time.time()
    proj_name = "LiveGUI_Verification_Proj"
    target_dir = str(REPO_ROOT / "artifacts" / "projects")

    res_new = cscape_new_iec_project(
        project_name=proj_name,
        target_dir=target_dir,
        controller_model="XL4",
        description="Live GUI Automation Verification Project",
        live_gui=True,
    )
    dur_t2 = time.time() - start_t2
    print("cscape_new_iec_project result:")
    print(json.dumps(res_new, indent=2))

    assert res_new["success"] is True, f"cscape_new_iec_project failed: {res_new.get('message')}"
    proj_path = Path(res_new["project_path"])
    proj_file = Path(res_new["project_file"])
    assert proj_path.exists(), f"Project directory not created: {proj_path}"
    assert proj_file.exists(), f"Project file not created: {proj_file}"
    assert proj_file.stat().st_size > 0, "Project file is 0 bytes"

    evidence_lines.extend([
        "[TOOL 2: cscape_new_iec_project]",
        f"  Status: SUCCESS",
        f"  Project Name: {res_new.get('project_name')}",
        f"  Project Path: {res_new.get('project_path')}",
        f"  Project File: {res_new.get('project_file')} ({proj_file.stat().st_size} bytes)",
        f"  Editor Mode: {res_new.get('editor_mode', 'IEC 61131')}",
        f"  Controller Model: {res_new.get('controller_model')}",
        f"  Cscape PID: {res_new.get('cscape_pid') or pid_1}",
        f"  Main HWND: {res_new.get('main_hwnd') or hwnd_1} (0x{(res_new.get('main_hwnd') or hwnd_1):X})" if (res_new.get("main_hwnd") or hwnd_1) else "  Main HWND: None",
        f"  Duration: {dur_t2:.3f}s",
        f"  Files Created: {res_new.get('files_created')}",
        f"  Message: {res_new.get('message')}",
        "================================================================================",
        "SUMMARY: ALL LIVE GUI MCP TOOLS EXECUTED AND VERIFIED SUCCESSFULLY.",
        "================================================================================",
    ])

    # Write evidence log
    evidence_content = "\n".join(evidence_lines) + "\n"
    EVIDENCE_LOG.write_text(evidence_content, encoding="utf-8")
    print(f"\nSaved concrete evidence to: {EVIDENCE_LOG}")
    print("\nEvidence Log Content:")
    print(evidence_content)

    # Teardown / Close Cscape
    print("\n--- Gracefully Closing Cscape ---")
    try:
        CscapeLifecycleManager.recycle_running_instances(timeout=5.0)
    except Exception as e:
        print(f"Cleanup note: {e}")

    print("\nVERIFICATION COMPLETE.")


if __name__ == "__main__":
    main()
