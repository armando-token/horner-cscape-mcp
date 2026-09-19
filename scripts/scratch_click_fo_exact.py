import ctypes
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

# In screen coordinates:
# window left=40, top=40
# [+] is at window x=150, y=222 -> screen x=190, y=262
x = 190
y = 262
print(f"Clicking at ({x}, {y})...")

user32.SetCursorPos(x, y)
time.sleep(0.1)
user32.mouse_event(0x0002, 0, 0, 0, 0) # LEFTDOWN
time.sleep(0.1)
user32.mouse_event(0x0004, 0, 0, 0, 0) # LEFTUP
time.sleep(0.5)

# Also let's try double click just in case
user32.mouse_event(0x0002, 0, 0, 0, 0)
time.sleep(0.1)
user32.mouse_event(0x0004, 0, 0, 0, 0)

time.sleep(1.0)
