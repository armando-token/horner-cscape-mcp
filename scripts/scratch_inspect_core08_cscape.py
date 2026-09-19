import ctypes
import ctypes.wintypes
import json
import struct
import sys
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

main_hwnd = 0x02E301BA
pid = 12184
thwnd = 0x00520438

TVM_GETNEXTITEM = 0x110A
TVM_GETITEMW = 0x113E
TVM_GETITEMA = 0x110C
TVGN_ROOT = 0x0000
TVGN_NEXT = 0x0001
TVGN_CHILD = 0x0004
TVIF_TEXT = 0x0001
TVIF_CHILDREN = 0x0040

hproc = kernel32.OpenProcess(0x001F0FFF, False, pid)
if not hproc:
    print(f"Failed to open process {pid}")
    sys.exit(1)

remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)
text_buf = remote_buf + 256

def get_node_info(hitem):
    # Read ANSI and Unicode
    # struct TVITEM: mask(4), hItem(4), state(4), stateMask(4), pszText(4), cchTextMax(4), iImage(4), iSelectedImage(4), cChildren(4), lParam(4)
    # total 40 bytes on 32-bit
    tvitem = struct.pack("<IIIIIIIIII", TVIF_TEXT | TVIF_CHILDREN, hitem, 0, 0, text_buf, 256, 0, 0, 0, 0)
    kernel32.WriteProcessMemory(hproc, remote_buf, tvitem, len(tvitem), None)
    
    # Try ANSI first (many MFC apps use ANSI)
    res_a = user32.SendMessageW(thwnd, TVM_GETITEMA, 0, remote_buf)
    raw_a = ctypes.create_string_buffer(256)
    kernel32.ReadProcessMemory(hproc, text_buf, raw_a, 256, None)
    
    # Also read returned TVITEM to inspect cChildren
    tvitem_out = ctypes.create_string_buffer(40)
    kernel32.ReadProcessMemory(hproc, remote_buf, tvitem_out, 40, None)
    _, _, _, _, _, _, _, _, c_children, _ = struct.unpack("<IIIIIIIIII", tvitem_out.raw)
    
    name_a = raw_a.value.decode('latin1', errors='replace').strip()
    
    # If ANSI is empty or strange, try Unicode
    kernel32.WriteProcessMemory(hproc, remote_buf, tvitem, len(tvitem), None)
    res_w = user32.SendMessageW(thwnd, TVM_GETITEMW, 0, remote_buf)
    raw_w = (ctypes.c_wchar * 256)()
    kernel32.ReadProcessMemory(hproc, text_buf, raw_w, 512, None)
    name_w = raw_w.value.strip()
    
    # Count actual children via TVGN_CHILD / TVGN_NEXT
    actual_children = []
    child = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
    while child:
        actual_children.append(child)
        child = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_NEXT, child)
        
    return {
        "hitem": hitem,
        "name_a": name_a,
        "name_w": name_w,
        "c_children_flag": c_children,
        "children_count": len(actual_children),
        "children_handles": actual_children
    }

tree_nodes = []

def dump_tree(hitem, depth=0, parent_name=""):
    if not hitem:
        return
    info = get_node_info(hitem)
    name = info["name_a"] or info["name_w"] or f"<unnamed 0x{hitem:X}>"
    info["depth"] = depth
    info["resolved_name"] = name
    info["parent"] = parent_name
    tree_nodes.append(info)
    
    indent = "  " * depth
    print(f"{indent}[0x{hitem:08X}] '{name}' (cChildren_flag={info['c_children_flag']}, actual_children={info['children_count']})")
    
    for ch in info["children_handles"]:
        dump_tree(ch, depth + 1, name)

root = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)
print(f"=== Project Navigator Tree (Root: 0x{root:08X}) ===")
cur = root
while cur:
    dump_tree(cur, depth=0)
    cur = user32.SendMessageW(thwnd, TVM_GETNEXTITEM, TVGN_NEXT, cur)

kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
kernel32.CloseHandle(hproc)
