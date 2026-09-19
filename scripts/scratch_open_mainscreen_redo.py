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

gate_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json")
gate = json.loads(gate_path.read_text(encoding="utf-8"))
main_hwnd = int(gate["hwnd"], 16)

user32.ShowWindow(main_hwnd, 9)
user32.SetForegroundWindow(main_hwnd)
time.sleep(0.3)

trees = []
def cb(h, _):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "systreeview32" in c.value.lower() and user32.IsWindowVisible(h):
        trees.append(h)
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(main_hwnd, WNDENUM(cb), 0)
thwnd = trees[0]

TVM_SELECTITEM = 0x110B
TVM_ENSUREVISIBLE = 0x1114
TVGN_CARET = 0x0009

main_screen_redo = 0x1ee1fc60

print(f"Selecting Main Screen of TankLevel_P4_REDO (0x{main_screen_redo:X})...")
user32.SendMessageW(thwnd, TVM_ENSUREVISIBLE, 0, main_screen_redo)
user32.SendMessageW(thwnd, TVM_SELECTITEM, TVGN_CARET, main_screen_redo)
time.sleep(0.5)
user32.SetFocus(thwnd)
time.sleep(0.2)

print("Sending VK_RETURN to Main Screen...")
user32.SendMessageW(thwnd, 0x0100, 0x0D, 0)
time.sleep(0.05)
user32.SendMessageW(thwnd, 0x0101, 0x0D, 0)
time.sleep(2.0)

rect = ctypes.wintypes.RECT()
user32.GetWindowRect(main_hwnd, ctypes.byref(rect))
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
out_p = Path(r"C:\HornerAI\horner-cscape-mcp\scratch\mainscreen_redo_action.png")
img.save(str(out_p))
print(f"Saved {out_p}")
