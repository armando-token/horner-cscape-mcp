import sys
from pathlib import Path
sys.path.insert(0, r"C:\Users\ArmandoSilva")
from scripts.watchdog_cscape_10min import Win32Helper

w = Win32Helper()
wins = w.enum_windows_for_pids({4444})
for win in wins:
    print(f"HWND: 0x{win.hwnd:08X} ({win.hwnd}) | Vis: {win.visible} | Title: '{win.title}'")
