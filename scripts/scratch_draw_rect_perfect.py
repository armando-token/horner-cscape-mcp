import ctypes
import json
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = "artifacts/.cscape_live_gate.json"
with open(gate_path) as f:
    gate = json.load(f)
main_hwnd = int(gate["hwnd"], 16)

# 1. Bring Cscape to foreground
user32.SetForegroundWindow(main_hwnd)
user32.BringWindowToTop(main_hwnd)
time.sleep(0.3)

# 2. Click on 'Rectangle' in ToolboxWnd at (180, 241)
print("Clicking on Rectangle at (180, 241)...")
user32.SetCursorPos(180, 241)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
time.sleep(0.05)
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
time.sleep(0.5)

# 3. Draw on editor canvas at (800, 330) -> (860, 370)
print("Drawing on canvas from (800, 330) to (860, 370)...")
user32.SetCursorPos(800, 330)
time.sleep(0.2)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
time.sleep(0.2)

for step in range(1, 11):
    cx = 800 + (860 - 800) * step // 10
    cy = 330 + (370 - 330) * step // 10
    user32.SetCursorPos(cx, cy)
    time.sleep(0.04)

time.sleep(0.2)
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
time.sleep(1.0)

# 4. Check for modal dialogs
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
    if "cscape" not in dtitle.lower() or "properties" in dtitle.lower():
        print(f"Dismissing dialog 0x{dhwnd:X} ('{dtitle}') with IDOK...")
        user32.PostMessageW(dhwnd, 0x0111, 1, 0)
        time.sleep(0.5)
