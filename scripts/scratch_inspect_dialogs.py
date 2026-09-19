import ctypes

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

def inspect_dialog(hwnd, name):
    print(f"=== Dialog {name} (HWND 0x{hwnd:X}) ===")
    t = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, t, 512)
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, c, 256)
    vis = bool(user32.IsWindowVisible(hwnd))
    print(f"Title: '{t.value}', Class: '{c.value}', Vis: {vis}")

    def ccb(h, _):
        cid = user32.GetDlgCtrlID(h)
        ct = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, ct, 512)
        cc = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, cc, 256)
        cvis = bool(user32.IsWindowVisible(h))
        print(f"  Ctrl 0x{h:X}: id={cid}, class='{cc.value}', text='{ct.value}', vis={cvis}")
        return 1

    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(hwnd, WNDENUM(ccb), 0)

inspect_dialog(0x323020E, "Screen Thumbnails")
inspect_dialog(0x500CB2, "Cscape")
