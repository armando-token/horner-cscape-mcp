import sys
sys.path.insert(0, ".")
from pathlib import Path
from src.cscape.project_manager import CscapeLiveProjectManager

mgr = CscapeLiveProjectManager()
mgr._attach_thread_desktop()

csp_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\projects\TankLevel_P4_REDO\TankLevel_P4_REDO.csp")
print(f"Opening {csp_path} in running Cscape...")
res = mgr.open_project(csp_path, require_live_gui=True, timeout_sec=20.0)
print(f"Open result: success={res.success} project={res.project_name} hwnd={hex(res.main_hwnd) if res.main_hwnd else None}")
