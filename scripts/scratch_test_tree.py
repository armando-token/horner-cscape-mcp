import ctypes
import json
import struct

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
user32.SetThreadDesktop(hd)

gate_path = "artifacts/.cscape_live_gate.json"
with open(gate_path) as f:
    gate = json.load(f)
pid = gate["pid"]
main_hwnd = int(gate["hwnd"], 16)

# Find all TreeView handles
trees = []
def cb(h, _):
    c = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, c, 256)
    if "systreeview32" in c.value.lower():
        trees.append(h)
    return 1

WNDENUM = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumChildWindows(main_hwnd, WNDENUM(cb), 0)
print(f"Found trees: {[hex(t) for t in trees]}")

hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)
print(f"Remote buffer: 0x{remote_buf:X}")

TVM_GETNEXTITEM = 0x110A
TVM_GETITEMA = 0x110C
TVM_GETITEMW = 0x113E
TVGN_ROOT = 0x0000
TVGN_NEXT = 0x0001
TVGN_CHILD = 0x0004
TVIF_TEXT = 0x0001

for thwnd in trees:
    print(f"\n--- Tree HWND 0x{thwnd:X} ---")
    root = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
    print(f"Root: 0x{root:X}" if root else "Root: None")

    def dump_node(hitem, depth=0):
        if not hitem:
            return
        # Test Unicode
        text_buf = remote_buf + 128
        tvitem_w = struct.pack("<IIIIII", TVIF_TEXT, hitem, 0, 0, text_buf, 256)
        kernel32.WriteProcessMemory(hproc, remote_buf, tvitem_w, len(tvitem_w), None)
        res_w = user32.SendMessageW(thwnd, TVM_GETITEMW, 0, remote_buf)
        raw_w = ctypes.create_string_buffer(512)
        kernel32.ReadProcessMemory(hproc, text_buf, raw_w, 512, None)
        
        # Test ANSI
        tvitem_a = struct.pack("<IIIIII", TVIF_TEXT, hitem, 0, 0, text_buf, 256)
        kernel32.WriteProcessMemory(hproc, remote_buf, tvitem_a, len(tvitem_a), None)
        res_a = user32.SendMessageW(thwnd, TVM_GETITEMA, 0, remote_buf)
        raw_a = ctypes.create_string_buffer(512)
        kernel32.ReadProcessMemory(hproc, text_buf, raw_a, 512, None)

        print("  " * depth + f"Item 0x{hitem:X}: res_w={res_w} w='{raw_w.raw[:40]}' res_a={res_a} a='{raw_a.raw[:40]}'")

        child = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
        dump_node(child, depth + 1)
        sibling = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_NEXT, hitem)
        dump_node(sibling, depth)

    dump_node(root)

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)
