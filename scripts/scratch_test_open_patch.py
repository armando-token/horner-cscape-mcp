import sys
sys.path.insert(0, ".")
from pathlib import Path
from src.cscape.project_manager import CscapeLiveProjectManager

mgr = CscapeLiveProjectManager()
mgr._attach_thread_desktop()

test_csp = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\test_patch.csp")
print(f"Opening {test_csp} in Cscape...")
res = mgr.open_project(test_csp, require_live_gui=True, timeout_sec=15.0)
print(f"Open result: success={res.success} message={res.message}")
