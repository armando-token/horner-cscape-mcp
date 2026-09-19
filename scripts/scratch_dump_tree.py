import ctypes
import ctypes.wintypes
import json
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

gate_path = Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json")
gate = json.loads(gate_path.read_text(encoding="utf-8"))
main_hwnd = int(gate["hwnd"], 16)
pid = gate["pid"]

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

hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)

TVM_GETNEXTITEM = 0x110A
TVM_GETITEMW = 0x113E
TVM_SELECTITEM = 0x110B
TVM_ENSUREVISIBLE = 0x1114
TVM_EXPAND = 0x1102
TVE_EXPAND = 0x0002
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

all_items = []
def dump_tree(hitem, depth=0):
    if not hitem:
        return
    t = get_text(hitem)
    all_items.append((hitem, depth, t))
    child = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
    dump_tree(child, depth + 1)
    sibling = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
    dump_tree(sibling, depth)

root = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
dump_tree(root)

for hitem, depth, t in all_items:
    print("  " * depth + f"- {t} ({hex(hitem)})")

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)
