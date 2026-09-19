"""Keep Cscape visible with C6_Native_Run.csp on winsta0\\Default and suppress About dialog."""

import ctypes
import ctypes.wintypes
import os
from pathlib import Path
import sys
import time

import psutil

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
sys.path.insert(0, str(HORNER_ROOT))

from scripts.execute_c6_mcp_client_native_pipeline import (
    ensure_desktop,
    get_all_windows,
    dismiss_modal_dialogs,
    spawn_cscape_visible_c6,
    configure_registry_for_project,
)

C6_CSP = HORNER_ROOT / "artifacts" / "projects" / "C6_Native_Run" / "C6_Native_Run.csp"
user32 = ctypes.windll.user32

WM_COMMAND = 0x0111
WM_CLOSE = 0x0010


def suppress_about_dialog():
    ensure_desktop()
    dismiss_modal_dialogs()
    wins = get_all_windows()
    for w in wins:
        if w["class"] == "#32770":
            title = w["title"].lower()
            if "about cscape" in title or "about" in title:
                user32.PostMessageW(w["hwnd"], WM_COMMAND, 1, 0)
                user32.PostMessageW(w["hwnd"], WM_CLOSE, 0, 0)


def main():
    ensure_desktop()
    configure_registry_for_project(C6_CSP)
    suppress_about_dialog()

    # Check if already running with project
    running = False
    for w in get_all_windows():
        if "cscape" in w["title"].lower() and "c6_native_run" in w["title"].lower() and w["visible"]:
            running = True
            break

    if not running:
        # Check if process is running
        for p in psutil.process_iter(["pid", "name"]):
            if "cscape" in p.info["name"].lower():
                try:
                    p.kill()
                except Exception:
                    pass
        time.sleep(1.0)
        spawn_cscape_visible_c6()
        time.sleep(3.0)

    # Keepalive loop
    for _ in range(3600):  # 1 hour
        suppress_about_dialog()
        time.sleep(2.0)


if __name__ == "__main__":
    main()
