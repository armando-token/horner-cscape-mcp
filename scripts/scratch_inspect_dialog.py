import ctypes

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

dialogs = []
def cb_top(h, _):
    c = ctypes.create_unicode_buffer(256)
    t = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    user32.GetWindowTextW(h, t, 256)
    if "#32770" in c.value and user32.IsWindowVisible(h):
        dialogs.append((h, t.value))
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows(WNDENUM(cb_top), 0)

for h_dlg, title in dialogs:
    print(f"Dialog {hex(h_dlg)}: '{title}'")
    controls = []
    def cb(h, _):
        c = ctypes.create_unicode_buffer(256)
        t = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        user32.GetWindowTextW(h, t, 256)
        cid = user32.GetDlgCtrlID(h)
        controls.append((hex(h), cid, c.value, t.value))
        return 1
    user32.EnumChildWindows(h_dlg, WNDENUM(cb), 0)
    for h, cid, cls, txt in controls:
        print(f"  {h} id={cid} class={cls} text='{txt}'")
