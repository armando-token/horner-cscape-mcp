import ctypes
import json
from pathlib import Path
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

def inspect_hwnd(target_hwnd, title):
    print(f"=== Inspecting {title} (HWND 0x{target_hwnd:X}) ===")
    pacc = ctypes.POINTER(IAccessible)()
    res = oleacc.AccessibleObjectFromWindow(target_hwnd, 0, ctypes.byref(IAccessible._iid_), ctypes.byref(pacc))
    if res != 0 or not pacc:
        print("  AccessibleObjectFromWindow failed")
        return

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
                    role = acc.accRole(val)
                    val_str = acc.accValue(val)
                    state = acc.accState(val)
                    if name:
                        print("  " * depth + f"Child {val}: Name='{name}', Role={role}, Value='{val_str}'")
                except Exception:
                    pass
            elif hasattr(val, "QueryInterface"):
                try:
                    child_acc = val.QueryInterface(IAccessible)
                    name = child_acc.accName(0)
                    role = child_acc.accRole(0)
                    if name:
                        print("  " * depth + f"Object: Name='{name}', Role={role}")
                    if depth < 5:
                        dump_acc(child_acc, depth + 1)
                except Exception:
                    pass

    dump_acc(pacc)

# Inspect Project Navigator tree
def find_ctrl(parent, class_sub):
    found = []
    def cb(h, _):
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, t, 512)
        if class_sub.lower() in c.value.lower() or class_sub.lower() in t.value.lower():
            found.append((h, c.value, t.value))
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(parent, WNDENUM(cb), 0)
    return found

for h, c, t in find_ctrl(hwnd, "Navigator"):
    inspect_hwnd(h, f"Navigator Bar {t}")
for h, c, t in find_ctrl(hwnd, "SysTreeView32"):
    inspect_hwnd(h, f"SysTreeView32 {t}")
for h, c, t in find_ctrl(hwnd, "Toolbox"):
    inspect_hwnd(h, f"Toolbox Bar {t}")
