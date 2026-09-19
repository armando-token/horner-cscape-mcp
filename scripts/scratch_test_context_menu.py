import ctypes
import ctypes.wintypes
import json
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

editor_hwnd = 0xA508C2

r = ctypes.wintypes.RECT()
user32.GetClientRect(editor_hwnd, ctypes.byref(r))
cx = (r.left + r.right) // 2
cy = (r.top + r.bottom) // 2
print(f"Editor client rect: ({r.left}, {r.top}, {r.right}, {r.bottom}), center=({cx}, {cy})")

lparam = (cy << 16) | (cx & 0xFFFF)
print("Sending WM_RBUTTONDOWN / UP...")
user32.SendMessageW(editor_hwnd, 0x0204, 2, lparam) # WM_RBUTTONDOWN
user32.SendMessageW(editor_hwnd, 0x0205, 0, lparam) # WM_RBUTTONUP

time.sleep(1.0)

menu_hwnd = user32.FindWindowW("#32768", None)
print(f"Popup menu HWND: {hex(menu_hwnd) if menu_hwnd else 'None'}")

if menu_hwnd:
    import comtypes
    import comtypes.client
    comtypes.client.GetModule("oleacc.dll")
    from comtypes.gen.Accessibility import IAccessible

    pacc = ctypes.POINTER(IAccessible)()
    oleacc = ctypes.windll.oleacc
    oleacc.AccessibleObjectFromWindow(menu_hwnd, 0, ctypes.byref(IAccessible._iid_), ctypes.byref(pacc))
    if pacc:
        cnt = pacc.accChildCount
        print(f"Menu item count: {cnt}")
        for i in range(1, cnt + 1):
            try:
                name = pacc.accName(i)
                print(f"  Menu Item {i}: '{name}'")
            except Exception as e:
                pass
    user32.PostMessageW(menu_hwnd, 0x0100, 0x1B, 0)
