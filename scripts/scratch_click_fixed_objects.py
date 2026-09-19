import ctypes
import ctypes.wintypes
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

toolbox_wnd = 0x250053A

# Click on [+] Fixed Objects: x=20, y=28 relative to CProjectToolboxWnd
cx = 25
cy = 30
lparam = (cy << 16) | (cx & 0xFFFF)
print("Clicking on [+] Fixed Objects...")
user32.SendMessageW(toolbox_wnd, 0x0201, 1, lparam) # WM_LBUTTONDOWN
user32.SendMessageW(toolbox_wnd, 0x0202, 0, lparam) # WM_LBUTTONUP

time.sleep(1.0)
