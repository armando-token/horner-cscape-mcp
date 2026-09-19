import ctypes
import ctypes.wintypes
import struct
import sys

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

main_hwnd = 0x02E301BA
pid = 12184
thwnd = 0x00520438

TVM_GETITEMA = 0x110C
TVM_GETITEMSTATE = 0x1127
TVM_EXPAND = 0x1102
TVE_EXPAND = 0x0002
TVIS_EXPANDED = 0x0020
TVIF_STATE = 0x0008

# Node handles from previous run:
# TankLevel_P5_Dedicated: 0x1DC64368
# Networking: 0x1DC641B8
# Protocols: 0x1DC64AE8

for name, hitem in [("TankLevel_P5_Dedicated", 0x1DC64368), ("Networking", 0x1DC641B8), ("Protocols", 0x1DC64AE8)]:
    state = user32.SendMessageW(thwnd, TVM_GETITEMSTATE, hitem, 0xFFFF)
    is_expanded = bool(state & TVIS_EXPANDED)
    print(f"{name} (0x{hitem:08X}): state=0x{state:04X}, is_expanded={is_expanded}")
