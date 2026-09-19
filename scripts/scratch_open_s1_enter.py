import ctypes
import ctypes.wintypes
import json
import time
from pathlib import Path
from PIL import ImageGrab

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

gate_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json")
gate = json.loads(gate_path.read_text(encoding="utf-8"))
main_hwnd = int(gate["hwnd"], 16)
pid = gate["pid"]

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

# Let's find s1_item
hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)

TVM_GETNEXTITEM = 0x110A
TVM_GETITEMW = 0x113E
TVM_SELECTITEM = 0x110B
TVM_ENSUREVISIBLE = 0x1114
TVGN_ROOT = 0x0000
TVGN_NEXT = 0x0001
TVGN_CHILD = 0x0004
TVGN_CARET = 0x0009
TVIF_TEXT = 0x0001

def get_text(hitem):
    if not hitem:
        return ""
    text_buf = remote_buf + 256
    import struct
    tvitem = struct.pack("<IIIIIIiiii", TVIF_TEXT, hitem, 0, 0, text_buf, 256, 0, 0, 0, 0)
    kernel32.WriteProcessMemory(hproc, remote_buf, tvitem, len(tvitem), None)
    user32.SendMessageW(thwnd, TVM_GETITEMW, 0, remote_buf)
    raw = ctypes.create_string_buffer(512)
    kernel32.ReadProcessMemory(hproc, text_buf, raw, 512, None)
    return raw.raw.decode("utf-16le", errors="ignore").split("\x00")[0]

s1_item = None
def search_tree(hitem):
    global s1_item
    if not hitem or s1_item:
        return
    t = get_text(hitem)
    if "screen 1" in t.lower():
        s1_item = hitem
        return
    child = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
    search_tree(child)
    sibling = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
    search_tree(sibling)

root = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
search_tree(root)

print(f"Found s1_item: {hex(s1_item) if s1_item else None}")
if s1_item:
    user32.SendMessageW(thwnd, TVM_ENSUREVISIBLE, 0, s1_item)
    user32.SendMessageW(thwnd, TVM_SELECTITEM, TVGN_CARET, s1_item)
    time.sleep(0.3)
    user32.SetFocus(thwnd)
    time.sleep(0.2)
    
    # Send Enter key (VK_RETURN = 0x0D) to tree control
    print("Sending VK_RETURN to tree control...")
    user32.SendMessageW(thwnd, 0x0100, 0x0D, 0)
    time.sleep(0.1)
    user32.SendMessageW(thwnd, 0x0101, 0x0D, 0)
    time.sleep(1.5)

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)

rect = ctypes.wintypes.RECT()
user32.GetWindowRect(main_hwnd, ctypes.byref(rect))
img = ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
img.save(r"C:\HornerAI\horner-cscape-mcp\scratch\s1_after_enter.png")
print("Saved s1_after_enter.png")
