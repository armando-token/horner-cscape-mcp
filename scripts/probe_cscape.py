import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import time
import win32gui
import win32process
from src.automation.process_manager import kill_process_tree

cscape_exe = r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"
print("Starting Cscape...")
proc = subprocess.Popen([cscape_exe])
pid = proc.pid
print(f"Cscape PID: {pid}")

seen = set()
try:
    for i in range(12):
        time.sleep(1)
        def enum_cb(hwnd, extra):
            try:
                _, w_pid = win32process.GetWindowThreadProcessId(hwnd)
                if w_pid == pid and hwnd not in seen:
                    seen.add(hwnd)
                    title = win32gui.GetWindowText(hwnd)
                    cls = win32gui.GetClassName(hwnd)
                    vis = win32gui.IsWindowVisible(hwnd)
                    print(f"Window [hwnd={hwnd}, vis={vis}]: title='{title}', class='{cls}'")
            except Exception:
                pass
            return True
        win32gui.EnumWindows(enum_cb, None)
finally:
    print("Terminating Cscape...")
    kill_process_tree(pid)
    print("Done.")
