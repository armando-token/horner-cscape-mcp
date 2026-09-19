import ctypes
import json

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = "artifacts/.cscape_live_gate.json"
with open(gate_path) as f:
    gate = json.load(f)
main_hwnd = int(gate["hwnd"], 16)

# Find Toolbox
toolbox_hwnd = None
def cb(h, _):
    global toolbox_hwnd
    t = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(h, t, 512)
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "toolbox" in t.value.lower():
        toolbox_hwnd = h
        return 0
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(main_hwnd, WNDENUM(cb), 0)
print(f"Toolbox HWND: 0x{toolbox_hwnd:X}")

def dump_all(parent, depth=0):
    def ccb(h, _):
        if user32.GetParent(h) == parent:
            c = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(h, c, 256)
            t = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, t, 512)
            cid = user32.GetDlgCtrlID(h)
            vis = bool(user32.IsWindowVisible(h))
            print("  " * depth + f"0x{h:X}: class='{c.value}', title='{t.value}', id={cid}, vis={vis}")
            dump_all(h, depth + 1)
        return 1
    user32.EnumChildWindows(parent, WNDENUM(ccb), 0)

dump_all(toolbox_hwnd)
