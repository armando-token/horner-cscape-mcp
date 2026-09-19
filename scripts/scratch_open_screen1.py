import ctypes
import time

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

hwnd_thumbs = 0x323020E
edit_hwnd = 0x1DE064E
ok_hwnd = 0x342067C

print("Setting Edit text to '1'...")
WM_SETTEXT = 0x000C
user32.SendMessageW(edit_hwnd, WM_SETTEXT, 0, "1")

time.sleep(0.5)

print("Clicking OK button (ID 1)...")
user32.SendMessageW(ok_hwnd, 0x00F5, 0, 0) # BM_CLICK
user32.PostMessageW(hwnd_thumbs, 0x0111, 1, ok_hwnd)

time.sleep(2.0)

# Check all open windows and MDI children
gate_path = "artifacts/.cscape_live_gate.json"
import json
with open(gate_path) as f:
    gate = json.load(f)
main_hwnd = int(gate["hwnd"], 16)

def enum_direct_children(parent):
    res = []
    def ccb(h, _):
        if user32.GetParent(h) == parent:
            res.append(h)
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(parent, WNDENUM(ccb), 0)
    return res

def find_all_children(p):
    res = []
    def ccb(h, _):
        res.append(h)
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumChildWindows(p, WNDENUM(ccb), 0)
    return res

print("=== MDI CHILDREN ===")
for ch in find_all_children(main_hwnd):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(ch, c, 256)
    if "mdiclient" in c.value.lower():
        for mdi_ch in enum_direct_children(ch):
            tc = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(mdi_ch, tc, 256)
            tt = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(mdi_ch, tt, 512)
            vis = bool(user32.IsWindowVisible(mdi_ch))
            print(f"  MDI Child: 0x{mdi_ch:X} Class='{tc.value}' Title='{tt.value}' Vis={vis}")

print("=== TOP WINDOWS ===")
def list_top_wins():
    wins = []
    def wcb(h, _):
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, t, 512)
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        vis = bool(user32.IsWindowVisible(h))
        if vis and (t.value or "#32770" in c.value):
            wins.append((h, c.value, t.value))
        return 1
    WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(WNDENUM(wcb), 0)
    return wins

for h, c, t in list_top_wins():
    if any(k in t.lower() for k in ["cscape", "screen", "graphic", "thumb"]) or "#32770" in c:
        print(f"  Top: 0x{h:X} Class='{c}' Title='{t}'")
