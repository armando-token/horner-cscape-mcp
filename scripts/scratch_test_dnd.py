import ctypes
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

# First test: Double click on Text Label at (250, 278)
print("Double clicking on Text Label at (250, 278)...")
user32.SetCursorPos(250, 278)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0004, 0, 0, 0, 0)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0)
time.sleep(0.05)
user32.mouse_event(0x0004, 0, 0, 0, 0)

time.sleep(1.0)

# Check for dialogs
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

d1 = check_dialogs()
print("Dialogs after double click:", [(hex(h), t) for h, t in d1])

# If no dialog, test Drag-and-Drop from (250, 278) to canvas (650, 350)
if not d1:
    print("Testing Drag and Drop from (250, 278) to (650, 350)...")
    user32.SetCursorPos(250, 278)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
    time.sleep(0.3)
    for step in range(1, 21):
        cx = 250 + (650 - 250) * step // 20
        cy = 278 + (350 - 278) * step // 20
        user32.SetCursorPos(cx, cy)
        time.sleep(0.03)
    time.sleep(0.3)
    user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
    time.sleep(1.0)
    d2 = check_dialogs()
    print("Dialogs after drag-and-drop:", [(hex(h), t) for h, t in d2])
