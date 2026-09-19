import sys
sys.path.insert(0, ".")
from pathlib import Path
from src.cscape.lifecycle import CscapeLifecycleManager, CscapeLifecycleState
from src.cscape.project_manager import CscapeLiveProjectManager

print("Launching Cscape...")
l_mgr = CscapeLifecycleManager()
state = l_mgr.launch(timeout=30.0, headless=False, enter_iec_mode=True)
print(f"Launch state: {state}, pid: {l_mgr.pid}, hwnd: {hex(l_mgr.main_hwnd) if l_mgr.main_hwnd else None}")

assert state == CscapeLifecycleState.READY, f"Cscape failed to launch: {state}"

test_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\test_clean_patch.csp")
p_mgr = CscapeLiveProjectManager()
p_mgr._attach_thread_desktop()
print(f"Opening {test_csp}...")
res = p_mgr.open_project(test_csp, require_live_gui=True, timeout_sec=20.0)
print(f"Open result: success={res.success} message={res.message}")
