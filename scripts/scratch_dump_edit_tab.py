import ctypes
import json
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

gate_path = "artifacts/.cscape_live_gate.json"
with open(gate_path) as f:
    gate = json.load(f)
main_hwnd = int(gate["hwnd"], 16)

# Find ribbon
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
user32.EnumChildWindows(main_hwnd, WNDENUM(cb), 0)

pacc = ctypes.POINTER(IAccessible)()
oleacc.AccessibleObjectFromWindow(ribbon_hwnd, 0, ctypes.byref(IAccessible._iid_), ctypes.byref(pacc))

def find_child(acc, target):
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
                if name and target.lower() == name.lower().strip():
                    return acc, val
            except Exception:
                pass
        elif hasattr(val, "QueryInterface"):
            try:
                child_acc = val.QueryInterface(IAccessible)
                name = child_acc.accName(0)
                if name and target.lower() == name.lower().strip():
                    return child_acc, 0
                res = find_child(child_acc, target)
                if res:
                    return res
            except Exception:
                pass
    return None

def dump_tab(tab_name):
    print(f"\n=== TAB: {tab_name} ===")
    res = find_child(pacc, tab_name)
    if res:
        parent, cid = res
        parent.accDoDefaultAction(cid)
        time.sleep(0.5)

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
                        print("  " * depth + f"Child: '{name}'")
                except Exception:
                    pass
            elif hasattr(val, "QueryInterface"):
                try:
                    child_acc = val.QueryInterface(IAccessible)
                    name = child_acc.accName(0)
                    if name:
                        print("  " * depth + f"Group: '{name}'")
                    if depth < 3:
                        dump_acc(child_acc, depth + 1)
                except Exception:
                    pass

    # Find the active tab container
    tab_elem = find_child(pacc, tab_name)
    if tab_elem:
        # dump children under ribbon
        dump_acc(pacc)

dump_tab("Edit")
