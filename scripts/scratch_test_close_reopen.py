import ctypes
import ctypes.wintypes
import json
import os
import struct
import sys
import time
from pathlib import Path
from PIL import ImageGrab

HORNER_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp").resolve()
USER_ROOT = Path(r"C:\Users\ArmandoSilva").resolve()
if str(HORNER_ROOT) not in sys.path:
    sys.path.insert(0, str(HORNER_ROOT))

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.restype = ctypes.c_void_p

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

gate_path = HORNER_ROOT / "artifacts" / ".cscape_live_gate.json"
gate = json.loads(gate_path.read_text(encoding="utf-8"))
main_hwnd = int(gate["hwnd"], 16)
pid = gate["pid"]
project_name = "TankLevel_P4_REDO"
csp_file = HORNER_ROOT / "artifacts" / "projects" / project_name / f"{project_name}.csp"

user32.ShowWindow(main_hwnd, 9)
user32.SetForegroundWindow(main_hwnd)
time.sleep(0.3)

# 1. Find and close MDI child of TankLevel_P4_REDO
mdi_hwnd = None
def cb_find_mdi(h, _):
    global mdi_hwnd
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "mdiclient" in c.value.lower():
        mdi_hwnd = h
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(main_hwnd, WNDENUM(cb_find_mdi), 0)

target_child = None
def cb_find_child(h, _):
    global target_child
    if user32.GetParent(h) == mdi_hwnd:
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, t, 512)
        if project_name.lower() in t.value.lower():
            target_child = h
    return 1

user32.EnumChildWindows(mdi_hwnd, WNDENUM(cb_find_child), 0)
print(f"Target child HWND to close: {hex(target_child) if target_child else 'None'}")

if target_child:
    print(f"Sending WM_CLOSE to {hex(target_child)}...")
    user32.SendMessageW(target_child, 0x0010, 0, 0) # WM_CLOSE
    time.sleep(1.5)

# Dismiss any save/confirm prompts if any
def cb_prompts(h, _):
    if user32.IsWindowVisible(h):
        c = ctypes.create_unicode_buffer(256)
        t = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        user32.GetWindowTextW(h, t, 256)
        if "#32770" in c.value:
            print(f"Found prompt dialog {hex(h)}: '{t.value}'")
            user32.PostMessageW(h, 0x0111, 1, 0) # IDOK
    return 1

user32.EnumWindows(WNDENUM(cb_prompts), 0)
time.sleep(1.0)

# 2. Reopen project via CscapeLiveProjectManager
from src.cscape.project_manager import CscapeLiveProjectManager
mgr = CscapeLiveProjectManager()
print(f"Reopening project via CscapeLiveProjectManager: {csp_file}...")
reopen_res = mgr.open_project(csp_file, require_live_gui=True, timeout_sec=20.0)
print(f"Reopen result: success={reopen_res.success}, mode={reopen_res.open_mode}, title='{reopen_res.window_title}'")
time.sleep(1.5)

# 3. Locate Screen 1 (1) in Project Navigator tree and double-click to open
trees = []
def cb_trees(h, _):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "systreeview32" in c.value.lower() and user32.IsWindowVisible(h):
        trees.append(h)
    return 1

user32.EnumChildWindows(main_hwnd, WNDENUM(cb_trees), 0)
print("Tree controls:", [hex(h) for h in trees])
# Project Navigator tree is typically the one with more items or tree[1]
tree_hwnd = None
for th in trees:
    cnt = user32.SendMessageW(th, 0x110A, 0x0000, 0) # TVGN_ROOT
    if cnt:
        tree_hwnd = th
if len(trees) > 1:
    tree_hwnd = trees[1] # Project Navigator tree

print(f"Using Project Navigator tree: {hex(tree_hwnd)}")

# Find Screen 1 (1) under TankLevel_P4_REDO
hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)

TVM_GETNEXTITEM = 0x110A
TVM_GETITEMW = 0x113E
TVM_SELECTITEM = 0x110B
TVM_ENSUREVISIBLE = 0x1114
TVM_GETITEMRECT = 0x1104
TVGN_ROOT = 0x0000
TVGN_NEXT = 0x0001
TVGN_CHILD = 0x0004
TVGN_CARET = 0x0009
TVIF_TEXT = 0x0001

def get_text(hitem):
    if not hitem: return ""
    text_buf = remote_buf + 256
    tvitem = struct.pack("<IIIIIIiiii", TVIF_TEXT, hitem, 0, 0, text_buf, 256, 0, 0, 0, 0)
    kernel32.WriteProcessMemory(hproc, remote_buf, tvitem, len(tvitem), None)
    user32.SendMessageW(tree_hwnd, TVM_GETITEMW, 0, remote_buf)
    raw = ctypes.create_string_buffer(512)
    kernel32.ReadProcessMemory(hproc, text_buf, raw, 512, None)
    return raw.raw.decode("utf-16le", errors="ignore").split("\x00")[0]

s1_item = None
def find_s1(hitem, in_p4=False):
    global s1_item
    if not hitem or s1_item: return
    t = get_text(hitem)
    is_p4 = in_p4 or (project_name.lower() in t.lower())
    if is_p4 and "screen 1" in t.lower():
        s1_item = hitem
        print(f"Found Screen 1 item in tree: 0x{hitem:X} ('{t}')")
        return
    c = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
    find_s1(c, is_p4)
    s = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
    find_s1(s, in_p4)

root = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
find_s1(root)

if s1_item:
    user32.SendMessageW(tree_hwnd, TVM_ENSUREVISIBLE, 0, s1_item)
    time.sleep(0.2)
    user32.SendMessageW(tree_hwnd, TVM_SELECTITEM, TVGN_CARET, s1_item)
    time.sleep(0.2)

    kernel32.WriteProcessMemory(hproc, remote_buf, struct.pack("<I", s1_item), 4, None)
    user32.SendMessageW(tree_hwnd, TVM_GETITEMRECT, 1, remote_buf)
    raw_rect = ctypes.create_string_buffer(16)
    kernel32.ReadProcessMemory(hproc, remote_buf, raw_rect, 16, None)
    l, top, r, b = struct.unpack("<iiii", raw_rect.raw)
    pt = ctypes.wintypes.POINT((l + r) // 2, (top + b) // 2)
    user32.ClientToScreen(tree_hwnd, ctypes.byref(pt))
    print(f"Double clicking Screen 1 at screen coords ({pt.x}, {pt.y})...")
    user32.SetCursorPos(pt.x, pt.y)
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(2.0)

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)

# Capture reopened screenshot
rect = ctypes.wintypes.RECT()
user32.GetWindowRect(main_hwnd, ctypes.byref(rect))
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))

out_p1 = HORNER_ROOT / "artifacts" / "screenshots" / "p4_redo_cscape_reopened_35_75.png"
out_p2 = USER_ROOT / "artifacts" / "screenshots" / "p4_redo_cscape_reopened_35_75.png"
out_p1.parent.mkdir(parents=True, exist_ok=True)
out_p2.parent.mkdir(parents=True, exist_ok=True)
img.save(str(out_p1))
img.save(str(out_p2))
print(f"Saved reopened screenshots to {out_p1} and {out_p2}")
