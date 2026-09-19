import ctypes
import ctypes.wintypes
import json
import comtypes
import comtypes.client

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

r = ctypes.wintypes.RECT()
user32.GetWindowRect(main_hwnd, ctypes.byref(r))
print(f"Main window rect: ({r.left}, {r.top}, {r.right}, {r.bottom})")

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

oleacc.AccessibleObjectFromPoint.argtypes = [
    POINT,
    ctypes.POINTER(ctypes.POINTER(IAccessible)),
    ctypes.POINTER(comtypes.automation.VARIANT),
]
oleacc.AccessibleObjectFromPoint.restype = ctypes.c_long

pacc = ctypes.POINTER(IAccessible)()
var_child = comtypes.automation.VARIANT()

for x_off in range(10, 650, 15):
    pt = POINT(r.left + x_off, r.top + 22)
    res = oleacc.AccessibleObjectFromPoint(pt, ctypes.byref(pacc), ctypes.byref(var_child))
    if res == 0 and pacc:
        try:
            name = pacc.accName(var_child.value)
            role = pacc.accRole(var_child.value)
            if name:
                print(f"x_off={x_off}: Name='{name}', ChildID={var_child.value}, Role={role}")
        except Exception:
            pass
