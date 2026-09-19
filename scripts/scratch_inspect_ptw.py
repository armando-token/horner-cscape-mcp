import ctypes
import comtypes
import comtypes.client
import comtypes.automation

comtypes.client.GetModule("oleacc.dll")
from comtypes.gen.Accessibility import IAccessible

user32 = ctypes.windll.user32
oleacc = ctypes.windll.oleacc

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

target_hwnd = 0x250053A
pacc = ctypes.POINTER(IAccessible)()
res = oleacc.AccessibleObjectFromWindow(target_hwnd, 0, ctypes.byref(IAccessible._iid_), ctypes.byref(pacc))
print(f"AccessibleObjectFromWindow res: {res}")

def dump_acc(acc, depth=0):
    cnt = acc.accChildCount
    print("  " * depth + f"Count: {cnt}")
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
                state = acc.accState(val)
                print("  " * depth + f"Child {val}: Name='{name}', Role={role}, State={state}")
            except Exception as e:
                print("  " * depth + f"Child {val}: err {e}")
        elif hasattr(val, "QueryInterface"):
            try:
                child_acc = val.QueryInterface(IAccessible)
                name = child_acc.accName(0)
                print("  " * depth + f"Object: Name='{name}'")
                if depth < 3:
                    dump_acc(child_acc, depth + 1)
            except Exception as e:
                pass

dump_acc(pacc)
