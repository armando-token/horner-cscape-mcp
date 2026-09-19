import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

# 1. Select Rectangle tool in Project Toolbox
# Rectangle is at x = 250, y = 318
print("Selecting Rectangle tool at (250, 318)...")
user32.SetCursorPos(250, 318)
time.sleep(0.2)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
time.sleep(0.1)
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
time.sleep(0.5)

# 2. Draw rectangle on Screen 1 canvas: drag from (650, 350) to (750, 400)
print("Drawing rectangle on canvas from (650, 350) to (750, 400)...")
user32.SetCursorPos(650, 350)
time.sleep(0.2)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
time.sleep(0.2)

# Move in small steps to simulate smooth drag
for step in range(1, 11):
    cur_x = 650 + (750 - 650) * step // 10
    cur_y = 350 + (400 - 350) * step // 10
    user32.SetCursorPos(cur_x, cur_y)
    time.sleep(0.05)

time.sleep(0.2)
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
time.sleep(1.0)

# 3. Check for any modal dialogs (#32770)
def check_dialogs():
    dialogs = []
    def cb(h, _):
        if user32.IsWindowVisible(h):
            c = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, c, 256)
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, t, 512)
            if c.value == "#32770":
                dialogs.append((h, t.value))
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUM(cb), 0)
    return dialogs

d_list = check_dialogs()
print("Dialogs open:", [(hex(h), t) for h, t in d_list])
for dhwnd, dtitle in d_list:
    # If it's a property dialog, click OK (ID 1)
    if "cscape" not in dtitle.lower() or "properties" in dtitle.lower():
        print(f"Clicking OK on dialog 0x{dhwnd:X} ('{dtitle}')...")
        user32.PostMessageW(dhwnd, 0x0111, 1, 0) # IDOK
        time.sleep(0.5)

# 4. Check status bar text on HornerAPGTabbedGraphicsEditor
statusbar_hwnd = 0x1DF064E
st_buf = ctypes.create_unicode_buffer(512)
user32.GetWindowTextW(statusbar_hwnd, st_buf, 512)
print("Graphics Editor statusbar text:", st_buf.value)
