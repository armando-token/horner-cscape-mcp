import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

r = ctypes.wintypes.RECT()
user32.GetWindowRect(0x250053A, ctypes.byref(r))
print("ToolboxWnd screen rect:", (r.left, r.top, r.right, r.bottom))

# Position mouse over the [+] icon of Fixed Objects:
x = r.left + 15
y = r.top + 12
print(f"Clicking at ({x}, {y})...")

user32.SetCursorPos(x, y)
time.sleep(0.2)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
time.sleep(0.1)
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP

time.sleep(1.0)
