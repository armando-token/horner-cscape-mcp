import ctypes
import json
from pathlib import Path

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = Path("artifacts/.cscape_live_gate.json")
with open(gate_path) as f:
    gate = json.load(f)
main_hwnd = int(gate["hwnd"], 16)

def enum_direct_children(parent):
    res = []
    def cb(h, _):
        if user32.GetParent(h) == parent:
            res.append(h)
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(parent, WNDENUM(cb), 0)
    return res

def dump_tree(h, depth=0):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    t = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, t, 512)
    vis = bool(user32.IsWindowVisible(h))
    cid = user32.GetDlgCtrlID(h)
    print("  " * depth + f"0x{h:X}: class='{c.value}', title='{t.value}', id={cid}, vis={vis}")
    for ch in enum_direct_children(h):
        dump_tree(ch, depth + 1)

print("=== MDI CHILDREN OF CSCAPE ===")
# Find MDI client
def find_all_children(p):
    res = []
    def cb(h, _):
        res.append(h)
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(p, WNDENUM(cb), 0)
    return res

for ch in find_all_children(main_hwnd):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(ch, c, 256)
    if "mdiclient" in c.value.lower():
        print(f"MDIClient HWND: 0x{ch:X}")
        dump_tree(ch)
