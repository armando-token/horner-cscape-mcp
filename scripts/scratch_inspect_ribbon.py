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

def find_child_by_name(acc, target_name):
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
                    return acc, val
            except Exception:
                pass
        elif hasattr(val, "QueryInterface"):
            try:
                child_acc = val.QueryInterface(IAccessible)
                name = child_acc.accName(0)
                if name and target_name.lower() in name.lower():
                    return child_acc, 0
                res = find_child_by_name(child_acc, target_name)
                if res:
                    return res
            except Exception:
                pass
    return None

res = find_child_by_name(pacc, "User Interface")
print("Found 'User Interface':", res)
if res:
    parent, child_id = res
    print("Clicking / invoking 'User Interface' tab...")
    parent.accDoDefaultAction(child_id)
    time.sleep(1.0)

# Now dump ribbon elements again
def dump_acc(acc, depth=0):
    cnt = acc.accChildCount
    if cnt == 0:
        return
    var_children = (comtypes.automation.VARIANT * cnt)()
    obtained = ctypes.c_long()
    oleacc.AccessibleChildren(acc, 0, cnt, var_children, ctypes.byref(obtained))
    for i in range(obtained.value):
        v = var_children[i]
        val = v.value
        if isinstance(val, int):
            try:
                name = acc.accName(val)
                if name:
                    print("  " * depth + f"Child {val}: '{name}'")
            except Exception:
                pass
        elif hasattr(val, "QueryInterface"):
            try:
                child_acc = val.QueryInterface(IAccessible)
                name = child_acc.accName(0)
                if name:
                    print("  " * depth + f"Object: '{name}'")
                if depth < 3:
                    dump_acc(child_acc, depth + 1)
            except Exception:
                pass

dump_acc(pacc)
