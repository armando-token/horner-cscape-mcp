import ctypes
import json
from pathlib import Path
import time
import comtypes
import comtypes.client
import comtypes.automation

comtypes.client.GetModule("oleacc.dll")
from comtypes.gen.Accessibility import IAccessible

user32 = ctypes.windll.user32
oleacc = ctypes.windll.oleacc

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = Path("artifacts/.cscape_live_gate.json")
with open(gate_path) as f:
    gate = json.load(f)
hwnd = int(gate["hwnd"], 16)

ribbon_hwnd = None
def cb(h, _):
    global ribbon_hwnd
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "ribbonbar" in c.value.lower():
        ribbon_hwnd = h
        return 0
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(hwnd, WNDENUM(cb), 0)

pacc = ctypes.POINTER(IAccessible)()
oleacc.AccessibleObjectFromWindow(ribbon_hwnd, 0, ctypes.byref(IAccessible._iid_), ctypes.byref(pacc))

def find_element(acc, target_name):
    cnt = acc.accChildCount
    var_children = (comtypes.automation.VARIANT * cnt)()
    obtained = ctypes.c_long()
    oleacc.AccessibleChildren(acc, 0, cnt, var_children, ctypes.byref(obtained))
    for i in range(obtained.value):
        v = var_children[i]
        val = v.value
        if isinstance(val, int):
            try:
                name = acc.accName(val)
                if name and target_name.lower() in name.lower():
                    return acc, val, name
            except Exception:
                pass
        elif hasattr(val, "QueryInterface"):
            try:
                child_acc = val.QueryInterface(IAccessible)
                name = child_acc.accName(0)
                if name and target_name.lower() in name.lower():
                    return child_acc, 0, name
                res = find_element(child_acc, target_name)
                if res:
                    return res
            except Exception:
                pass
    return None

res = find_element(pacc, "View Thumbnails")
print("Found 'View Thumbnails':", res)
if res:
    parent, child_id, name = res
    print(f"Invoking '{name}' (child_id={child_id})...")
    parent.accDoDefaultAction(child_id)
    time.sleep(2.0)

# Check all top-level / child windows now to see what opened!
def list_wins():
    wins = []
    def wcb(h, _):
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, t, 512)
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        vis = bool(user32.IsWindowVisible(h))
        if vis and t.value:
            wins.append((h, c.value, t.value))
        return 1
    user32.EnumWindows(WNDENUM(wcb), 0)
    return wins

for h, c, t in list_wins():
    if "cscape" in t.lower() or "screen" in t.lower() or "thumbnail" in t.lower() or "#32770" in c:
        print(f"Window: HWND=0x{h:X} Class='{c}' Title='{t}'")
