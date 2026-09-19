import ctypes

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

# 1. Dismiss Cscape Yes/No dialog safely with IDNO (7)
hwnd_yesno = 0x500CB2
if user32.IsWindow(hwnd_yesno):
    t = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd_yesno, t, 512)
    if "cscape" in t.value.lower():
        print("Dismissing Yes/No dialog safely with IDNO (7)...")
        user32.PostMessageW(hwnd_yesno, 0x0111, 7, 0) # WM_COMMAND IDNO

# 2. Inspect Screen Thumbnails ComboBox
hwnd_thumbs = 0x323020E
if user32.IsWindow(hwnd_thumbs):
    cb_hwnd = 0x313098E
    CB_GETCOUNT = 0x0146
    CB_GETLBTEXT = 0x0148
    CB_GETLBTEXTLEN = 0x0149
    cnt = user32.SendMessageW(cb_hwnd, CB_GETCOUNT, 0, 0)
    print(f"ComboBox item count: {cnt}")
    for i in range(cnt):
        tlen = user32.SendMessageW(cb_hwnd, CB_GETLBTEXTLEN, i, 0)
        buf = ctypes.create_unicode_buffer(tlen + 1)
        user32.SendMessageW(cb_hwnd, CB_GETLBTEXT, i, ctypes.cast(buf, ctypes.c_void_p))
        print(f"  Item {i}: '{buf.value}'")

    edit_hwnd = 0x1DE064E
    ebuf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(edit_hwnd, ebuf, 256)
    print(f"Edit text: '{ebuf.value}'")
