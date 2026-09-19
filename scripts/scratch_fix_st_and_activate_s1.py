import ctypes
import ctypes.wintypes
import json
import time
from pathlib import Path
from PIL import ImageGrab
import win32clipboard

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.restype = ctypes.c_void_p

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd: user32.SetThreadDesktop(hd)

gate = json.loads(open(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json").read())
hwnd = int(gate["hwnd"], 16)
user32.ShowWindow(hwnd, 9)
user32.SetForegroundWindow(hwnd)
time.sleep(0.3)

clean_code = (
    "AlwaysOn := TRUE;\r\n"
    "Setpoint_I16 := ANY_TO_INT(Setpoint);\r\n"
    "TankLevelPV_I16 := ANY_TO_INT(TankLevelPV);\r\n"
    "HI := TankLevelPV >= 75.0;\r\n"
    "LO := TankLevelPV <= 35.0;\r\n"
    "Error := Setpoint - TankLevelPV;\r\n"
)

# Put clean_code onto Windows Clipboard via win32clipboard
win32clipboard.OpenClipboard()
win32clipboard.EmptyClipboard()
win32clipboard.SetClipboardText(clean_code, win32clipboard.CF_UNICODETEXT)
win32clipboard.CloseClipboard()

# Find visible W5EditST
w5_edits = []
def cb_w5(h, _):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "w5editst" in c.value.lower() and user32.IsWindowVisible(h):
        w5_edits.append(h)
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(hwnd, WNDENUM(cb_w5), 0)

if w5_edits:
    h_w5 = w5_edits[0]
    user32.SetFocus(h_w5)
    time.sleep(0.1)
    # Select all: EM_SETSEL(0, -1)
    user32.SendMessageW(h_w5, 0x00B1, 0, -1)
    time.sleep(0.1)
    # Paste clean text: WM_PASTE = 0x0302
    user32.SendMessageW(h_w5, 0x0302, 0, 0)
    time.sleep(0.3)
    print("Pasted clean code into W5EditST")

# Trigger compile: ID_PROGRAM_ERRORCHECK = 32826
print("Triggering compile...")
user32.SendMessageW(hwnd, 0x0111, 32826, 0)
time.sleep(2.0)

# Dismiss compile dialog
def cb_dlg(h, _):
    if user32.IsWindowVisible(h):
        c = ctypes.create_unicode_buffer(256)
        t = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        user32.GetWindowTextW(h, t, 256)
        if "#32770" in c.value and any(k in t.value.lower() for k in ["no error", "cscape", "compile"]):
            print("Dismissing compile dialog:", t.value)
            user32.PostMessageW(h, 0x0111, 1, 0) # IDOK
    return 1

user32.EnumWindows(WNDENUM(cb_dlg), 0)
time.sleep(1.0)

# Now switch to Screen 1 by finding the Screen 1 item in Project Navigator and double clicking
trees = []
def cb_trees(h, _):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "systreeview32" in c.value.lower() and user32.IsWindowVisible(h):
        trees.append(h)
    return 1

user32.EnumChildWindows(hwnd, WNDENUM(cb_trees), 0)
tree_hwnd = trees[1] if len(trees) > 1 else (trees[0] if trees else None)

pid = gate["pid"]
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
    import struct
    tvitem = struct.pack("<IIIIIIiiii", TVIF_TEXT, hitem, 0, 0, text_buf, 256, 0, 0, 0, 0)
    kernel32.WriteProcessMemory(hproc, remote_buf, tvitem, len(tvitem), None)
    user32.SendMessageW(tree_hwnd, TVM_GETITEMW, 0, remote_buf)
    raw = ctypes.create_string_buffer(512)
    kernel32.ReadProcessMemory(hproc, text_buf, raw, 512, None)
    return raw.raw.decode("utf-16le", errors="ignore").split("\x00")[0]

s1_item = None
def find_s1(hitem, in_proj=False):
    global s1_item
    if not hitem or s1_item: return
    t = get_text(hitem)
    is_p = in_proj or ("tanklevel_p4_redo" in t.lower())
    if is_p and "screen 1" in t.lower():
        s1_item = hitem
        return
    c = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
    find_s1(c, is_p)
    s = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
    find_s1(s, is_p)

root = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
find_s1(root)

if s1_item:
    import struct
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
    print(f"Double clicking Screen 1 at ({pt.x}, {pt.y})...")
    user32.SetCursorPos(pt.x, pt.y)
    time.sleep(0.1)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(1.5)

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)

# Save project
print("Sending ID_FILE_SAVE (57603)...")
user32.SendMessageW(hwnd, 0x0111, 57603, 0)
time.sleep(1.5)

# Capture screenshots
rect = ctypes.wintypes.RECT()
user32.GetWindowRect(hwnd, ctypes.byref(rect))
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))

p1 = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\screenshots\p4_redo_cscape_ui_35_75.png")
p2 = Path(r"C:\Users\ArmandoSilva\artifacts\screenshots\p4_redo_cscape_ui_35_75.png")
p3 = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\screenshots\p4_redo_cscape_reopened_35_75.png")
p4 = Path(r"C:\Users\ArmandoSilva\artifacts\screenshots\p4_redo_cscape_reopened_35_75.png")
img.save(str(p1))
img.save(str(p2))
img.save(str(p3))
img.save(str(p4))
print("Saved all screenshots")
