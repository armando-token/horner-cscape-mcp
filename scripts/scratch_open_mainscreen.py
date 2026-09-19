import ctypes
import json
import struct
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = "artifacts/.cscape_live_gate.json"
with open(gate_path) as f:
    gate = json.load(f)
pid = gate["pid"]
main_hwnd = int(gate["hwnd"], 16)

trees = []
def cb(h, _):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "systreeview32" in c.value.lower():
        trees.append(h)
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(main_hwnd, WNDENUM(cb), 0)

hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)

TVM_GETNEXTITEM = 0x110A
TVM_GETITEMW = 0x113E
TVM_SELECTITEM = 0x110B
TVM_GETITEMRECT = 0x111F
TVM_ENSUREVISIBLE = 0x1114
TVGN_ROOT = 0x0000
TVGN_NEXT = 0x0001
TVGN_CHILD = 0x0004
TVGN_CARET = 0x0009
TVIF_TEXT = 0x0001

target_tree = None
target_item = None

def find_item_in_tree(thwnd, hitem, target_text):
    global target_tree, target_item
    if not hitem or target_item:
        return
    text_buf = remote_buf + 128
    tvitem = struct.pack("<IIIIII", TVIF_TEXT, hitem, 0, 0, text_buf, 256)
    kernel32.WriteProcessMemory(hproc, remote_buf, tvitem, len(tvitem), None)
    res = user32.SendMessageW(thwnd, TVM_GETITEMW, 0, remote_buf)
    raw = ctypes.create_string_buffer(512)
    kernel32.ReadProcessMemory(hproc, text_buf, raw, 512, None)
    try:
        text = raw.raw.decode("utf-16le", errors="ignore").split("\x00")[0]
    except Exception:
        text = ""
    if target_text.lower() in text.lower():
        print(f"Found match: '{text}' at 0x{hitem:X} in tree 0x{thwnd:X}")
        target_tree = thwnd
        target_item = hitem
        return
    child = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
    find_item_in_tree(thwnd, child, target_text)
    sibling = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
    find_item_in_tree(thwnd, sibling, target_text)

for thwnd in trees:
    root = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    find_item_in_tree(thwnd, root, "Main Screen")
    if target_item:
        break

if target_item and target_tree:
    print(f"Ensuring visible and selecting item 0x{target_item:X}...")
    user32.SendMessageW(target_tree, TVM_ENSUREVISIBLE, 0, target_item)
    user32.SendMessageW(target_tree, TVM_SELECTITEM, TVGN_CARET, target_item)
    time.sleep(0.5)

    # Set focus to tree
    user32.SetForegroundWindow(main_hwnd)
    user32.SetFocus(target_tree)
    time.sleep(0.2)

    # Send VK_RETURN
    print("Sending VK_RETURN to tree...")
    user32.SendMessageW(target_tree, 0x0100, 0x0D, 0) # WM_KEYDOWN VK_RETURN
    user32.SendMessageW(target_tree, 0x0101, 0x0D, 0) # WM_KEYUP VK_RETURN
    time.sleep(2.0)

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)

# Check windows now
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

for ch in find_all_children(main_hwnd):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(ch, c, 256)
    if "mdiclient" in c.value.lower():
        print(f"MDIClient HWND: 0x{ch:X}")
        for mdi_ch in enum_direct_children(ch):
            tc = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(mdi_ch, tc, 256)
            tt = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(mdi_ch, tt, 512)
            vis = bool(user32.IsWindowVisible(mdi_ch))
            print(f"  MDI Child: 0x{mdi_ch:X} Class='{tc.value}' Title='{tt.value}' Vis={vis}")

# Also check top-level windows
def list_top_wins():
    wins = []
    def wcb(h, _):
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, t, 512)
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        vis = bool(user32.IsWindowVisible(h))
        if vis and t.value:
            wins.append((h, c.value, t.value))
        return 1
    user32.EnumWindows(WNDENUM(wcb), 0)
    return wins

print("Top windows:")
for h, c, t in list_top_wins():
    if "screen" in t.lower() or "#32770" in c or "graphics" in t.lower():
        print(f"  HWND=0x{h:X} Class='{c}' Title='{t}'")
