import ctypes
import comtypes
import comtypes.client

comtypes.client.GetModule("oleacc.dll")
from comtypes.gen.Accessibility import IAccessible

user32 = ctypes.windll.user32
oleacc = ctypes.windll.oleacc

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

m = user32.FindWindowW("#32768", None)
print(f"Popup menu HWND: {hex(m) if m else 'None'}")
if m:
    pacc = ctypes.POINTER(IAccessible)()
    oleacc.AccessibleObjectFromWindow(m, 0, ctypes.byref(IAccessible._iid_), ctypes.byref(pacc))
    cnt = pacc.accChildCount
    print(f"Menu item count: {cnt}")
    for i in range(1, cnt + 1):
        try:
            name = pacc.accName(i)
            print(f"  Item {i}: '{name}'")
        except Exception as e:
            print(f"  Item {i}: err {e}")
