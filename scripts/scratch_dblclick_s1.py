import ctypes
import ctypes.wintypes
import json
import struct
import time
from pathlib import Path
from PIL import ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.restype = ctypes.c_void_p

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

gate = json.loads(Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json").read_text())
hwnd = int(gate["hwnd"], 16)
pid = gate["pid"]

user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(0.3)

thwnd = 0x500438 # Project Navigator SysTreeView32

TVM_SELECTITEM = 0x110B
TVM_ENSUREVISIBLE = 0x1114
TVM_GETITEMRECT = 0x1104
TVGN_CARET = 0x0009

hitem = 0x1EE1FCC0 # Screen 1 (1) under TankLevel_P4_REDO

# Ensure visible and select
user32.SendMessageW(thwnd, TVM_ENSUREVISIBLE, 0, hitem)
time.sleep(0.2)
user32.SendMessageW(thwnd, TVM_SELECTITEM, TVGN_CARET, hitem)
time.sleep(0.2)

# Get rect
hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)

# Put hitem into first 4 bytes of remote_buf
kernel32.WriteProcessMemory(hproc, remote_buf, struct.pack("<I", hitem), 4, None)
res = user32.SendMessageW(thwnd, TVM_GETITEMRECT, 1, remote_buf) # 1 = text rect
raw_rect = ctypes.create_string_buffer(16)
kernel32.ReadProcessMemory(hproc, remote_buf, raw_rect, 16, None)
left, top, right, bottom = struct.unpack("<iiii", raw_rect.raw)
print(f"Item rect: ({left}, {top}, {right}, {bottom}), res={res}")

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)

# Convert client coords to screen coords
pt = ctypes.wintypes.POINT((left + right) // 2, (top + bottom) // 2)
user32.ClientToScreen(thwnd, ctypes.byref(pt))
print(f"Screen coords: ({pt.x}, {pt.y})")

# Double click at tree item
lparam = ((top + bottom) // 2 << 16) | ((left + right) // 2 & 0xFFFF)
user32.SetFocus(thwnd)
time.sleep(0.1)
user32.PostMessageW(thwnd, 0x0201, 1, lparam) # WM_LBUTTONDOWN
user32.PostMessageW(thwnd, 0x0202, 0, lparam) # WM_LBUTTONUP
time.sleep(0.05)
user32.PostMessageW(thwnd, 0x0203, 1, lparam) # WM_LBUTTONDBLCLK
user32.PostMessageW(thwnd, 0x0202, 0, lparam) # WM_LBUTTONUP
time.sleep(1.5)

# Also try sending Enter key just in case
user32.SendMessageW(thwnd, 0x0100, 0x0D, 0) # WM_KEYDOWN VK_RETURN
time.sleep(0.05)
user32.SendMessageW(thwnd, 0x0101, 0x0D, 0) # WM_KEYUP VK_RETURN
time.sleep(1.5)

rect = ctypes.wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
out_p = Path(r"C:\HornerAI\horner-cscape-mcp\scratch\after_dblclick_s1.png")
img.save(str(out_p))
print(f"Saved {out_p}")
