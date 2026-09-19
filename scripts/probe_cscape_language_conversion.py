"""Probe Cscape 10.2 GUI for native Structured Text to Ladder conversion capabilities."""

import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import psutil

user32 = ctypes.windll.user32

user32.GetMenu.argtypes = [ctypes.c_void_p]
user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [ctypes.c_void_p, wintypes.LPWSTR, ctypes.c_int]


MF_BYPOSITION = 0x00000400
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
user32.EnumWindows.argtypes = [WNDENUMPROC, ctypes.c_void_p]
user32.EnumWindows.restype = ctypes.c_bool

def find_cscape_hwnd():
    found = []
    pids = set()
    for p in psutil.process_iter(["name", "pid"]):
        if "cscape" in (p.info["name"] or "").lower():
            pids.add(p.info["pid"])

    def cb(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, buf, 512)
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            if "tanklevel" in buf.value.lower() or "cscape" in buf.value.lower():
                found.append((hwnd, pid.value, buf.value, cls.value))
        return True

    c_cb = WNDENUMPROC(cb)
    user32.EnumWindows(c_cb, 0)
    return found

def recurse_menu(h_menu, menu_items, path=""):
    if not h_menu:
        return
    count = user32.GetMenuItemCount(h_menu)
    for i in range(count):
        sub = user32.GetSubMenu(h_menu, i)
        cmd_id = user32.GetMenuItemID(h_menu, i)
        buf = ctypes.create_unicode_buffer(256)
        user32.GetMenuStringW(h_menu, i, buf, 256, MF_BYPOSITION)
        label = buf.value.replace("&", "")
        current_path = f"{path} -> {label}" if path else label
        if sub:
            recurse_menu(sub, menu_items, current_path)
        else:
            menu_items.append({
                "path": current_path,
                "cmd_id": cmd_id,
                "text": label,
            })

def main():
    gate_file = Path(r"C:\Users\ArmandoSilva\artifacts\.cscape_live_gate.json")
    target_hwnd = None
    target_pid = None
    if gate_file.exists():
        try:
            gate_data = json.loads(gate_file.read_text(encoding="utf-8"))
            if gate_data.get("hwnd"):
                target_hwnd = int(gate_data["hwnd"], 16)
                target_pid = gate_data.get("pid")
                print(f"Loaded active Cscape target from gate file: HWND=0x{target_hwnd:08X}, PID={target_pid}")
        except Exception as e:
            print(f"Error reading gate file: {e}")

    if not target_hwnd:
        windows = find_cscape_hwnd()
        for h, pid, title, cls in windows:
            print(f"  HWND: 0x{h:08X} | PID: {pid} | Class: {cls} | Title: '{title}'")
            if "tanklevel" in title.lower():
                target_hwnd = h
                target_pid = pid

    if not target_hwnd:
        print("ERROR: Cscape window not found!")
        return 1


    hmenu = user32.GetMenu(target_hwnd)
    print(f"\nMenu Handle for 0x{target_hwnd:08X}: {hex(hmenu) if hmenu else 'None'}")

    menu_items = []
    matches = []
    if hmenu:
        recurse_menu(hmenu, menu_items)
        print(f"Total menu items scraped: {len(menu_items)}")
        
        keywords = ["ladder", "change", "convert", "language", "pou", "structured", "text", "iec", "editor", "view"]
        for item in menu_items:
            t = item["text"].lower()
            p = item["path"].lower()
            if any(k in t or k in p for k in keywords):
                matches.append(item)

        print(f"\nMatching menu items for keywords {keywords}:")
        for m in matches:
            print(f"  [{m['cmd_id']}] {m['path']}")

    exe_path = Path(r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe")
    cscape_bytes = exe_path.read_bytes()
    
    probe_phrases = [
        b"Change Language",
        b"Convert to Ladder",
        b"Convert To Ladder",
        b"Convert to LD",
        b"Convert to ST",
        b"Change POU",
        b"Change Type",
        b"Translate",
        b"Structured Text",
        b"Advanced Ladder",
        b"IEC 61131",
    ]
    print("\nProbing Cscape.exe binary string table for language conversion phrases:")
    binary_counts = {}
    for phrase in probe_phrases:
        count_ascii = cscape_bytes.count(phrase)
        count_wide = cscape_bytes.count(phrase.decode("ascii").encode("utf-16le"))
        total = count_ascii + count_wide
        binary_counts[phrase.decode("ascii")] = total
        print(f"  Phrase '{phrase.decode('ascii')}': ASCII={count_ascii}, UTF-16LE={count_wide} (Total={total})")

    out_file = Path(r"C:\Users\ArmandoSilva\artifacts\evidence\st_to_ld_cscape_probe.json")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_data = {
        "cscape_hwnd": hex(target_hwnd) if target_hwnd else None,
        "menu_items_count": len(menu_items),
        "matching_menu_items": matches,
        "binary_probe": binary_counts,
    }
    out_file.write_text(json.dumps(out_data, indent=2), encoding="utf-8")
    print(f"\nEvidence written to {out_file}")
    return 0

if __name__ == "__main__":
    main()
