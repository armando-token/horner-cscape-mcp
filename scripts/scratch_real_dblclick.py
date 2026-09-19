import ctypes
import ctypes.wintypes
import json
import time
from pathlib import Path
from PIL import ImageGrab

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

gate = json.loads(Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json").read_text())
hwnd = int(gate["hwnd"], 16)

user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(0.3)

# Coordinates of Screen 1 (1) under TankLevel_P4_REDO:
x, y = 146, 597
print(f"Double clicking at ({x}, {y})...")
user32.SetCursorPos(x, y)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
time.sleep(0.08)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
time.sleep(2.0)

rect = ctypes.wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
out_p = Path(r"C:\HornerAI\horner-cscape-mcp\scratch\after_mouse_dblclick_s1.png")
img.save(str(out_p))
print(f"Saved {out_p}")
