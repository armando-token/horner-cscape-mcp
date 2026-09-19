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

x, y = 1100, 342
print(f"Double-clicking badge at screen coords ({x}, {y})...")
user32.SetCursorPos(x, y)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0)
user32.mouse_event(0x0004, 0, 0, 0, 0)
time.sleep(0.08)
user32.mouse_event(0x0002, 0, 0, 0, 0)
user32.mouse_event(0x0004, 0, 0, 0, 0)
time.sleep(1.5)

dialogs = []
def cb(h, _):
    c = ctypes.create_unicode_buffer(256)
    t = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    user32.GetWindowTextW(h, t, 256)
    if "#32770" in c.value and user32.IsWindowVisible(h):
        dialogs.append((h, t.value))
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows(WNDENUM(cb), 0)
print("Visible dialogs:", [(hex(h), t) for h, t in dialogs])

rect = ctypes.wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
out_p = Path(r"C:\HornerAI\horner-cscape-mcp\scratch\after_badge_dblclick.png")
img.save(str(out_p))
print(f"Saved {out_p}")
