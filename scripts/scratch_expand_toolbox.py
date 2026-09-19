import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

toolbox_hwnd = 0x19D052C
toolbox_wnd = 0x250053A

print("Expanding Project Toolbox...")
# SWP_SHOWWINDOW = 0x0040, SWP_NOZORDER = 0x0004
user32.SetWindowPos(toolbox_hwnd, 0, 168, 186, 220, 460, 0x0040)
user32.SetWindowPos(toolbox_wnd, 0, 0, 0, 220, 440, 0x0040)

time.sleep(1.0)

# Check rects now
r = ctypes.wintypes.RECT()
user32.GetWindowRect(toolbox_hwnd, ctypes.byref(r))
print("Toolbox rect:", (r.left, r.top, r.right, r.bottom))

# Check child controls of toolbox_wnd
def enum_direct(p):
    res = []
    def cb(h, _):
        if user32.GetParent(h) == p:
            res.append(h)
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(p, WNDENUM(cb), 0)
    return res

for ch in enum_direct(toolbox_wnd):
    tc = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(ch, tc, 256)
    tt = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(ch, tt, 512)
    vis = bool(user32.IsWindowVisible(ch))
    cid = user32.GetDlgCtrlID(ch)
    print(f"  Child: 0x{ch:X} Class='{tc.value}' Title='{tt.value}' ID={cid} Vis={vis}")
