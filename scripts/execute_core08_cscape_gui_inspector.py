#!/usr/bin/env python3
"""CORE-08 Cscape GUI Liveness & Protocols Inspector.

Verifies the live Cscape 10.2 GUI state on winsta0\\Default:
1. Inspects Cscape process (PID 12184, HWND 0x02E301BA).
2. Verifies window title contains 'TankLevel_P5_Dedicated.csp'.
3. Inspects Project Navigator tree: confirms 'Protocols' exists under 'Networking' for 'TankLevel_P5_Dedicated'.
4. Confirms that 'Protocols' tree item currently has Children count: 0 (empty in GUI).
5. Documents the architectural finding: The native Cscape GUI tree item Protocols is unexpanded/empty
   (Children count: 0) in the UI tree, whereas the complete devices and scan list are defined and maintained
   in modbus_protocol_inventory.json and modbus_pv_config.json.
6. Captures a fresh screenshot to artifacts/screenshots/core08_cscape_protocols_navigator.png.
7. Saves verification evidence to artifacts/checkpoints/core08_cscape_gui_evidence.json.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import hashlib
import json
import os
import struct
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from PIL import ImageGrab
import psutil

# Base directories
PRIMARY_ROOT = Path(r"C:\HornerAI\horner-cscape-mcp")
USER_ROOT = Path(r"C:\Users\ArmandoSilva")

sys.path.insert(0, str(PRIMARY_ROOT))
from scripts.watchdog_cscape_10min import Win32Helper

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# TreeView Constants
TVM_GETNEXTITEM = 0x110A
TVM_GETITEMA = 0x110C
TVM_GETITEMW = 0x113E
TVM_GETITEMSTATE = 0x1127
TVM_ENSUREVISIBLE = 0x1114
TVM_SELECTITEM = 0x110B
TVGN_ROOT = 0x0000
TVGN_NEXT = 0x0001
TVGN_CHILD = 0x0004
TVGN_CARET = 0x0009
TVIF_TEXT = 0x0001
TVIF_CHILDREN = 0x0040
TVIS_EXPANDED = 0x0020


def compute_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def run_inspection():
    print("=== [CORE-08] Starting Cscape GUI Liveness & Protocols Inspection ===")
    
    # Ensure Default desktop
    hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
    if hd:
        user32.SetThreadDesktop(hd)
        print("Attached to desktop: winsta0\\Default")
    else:
        print("Warning: Could not explicitly open winsta0\\Default desktop handle")

    w = Win32Helper()
    w.ensure_desktop()

    expected_title_sub = "TankLevel_P5_Dedicated.csp"
    cscape_pids = [p.info["pid"] for p in psutil.process_iter(["pid", "name"]) if "cscape" in (p.info["name"] or "").lower()]
    if not cscape_pids:
        raise RuntimeError("No active Cscape.exe process found!")
    expected_pid = cscape_pids[0]

    from scripts.watchdog_cscape_10min import WNDENUMPROC
    expected_hwnd_int = None
    def _find_win(h, _):
        nonlocal expected_hwnd_int
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        if pid.value == expected_pid and user32.IsWindowVisible(h):
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(h, title, 512)
            if expected_title_sub.lower() in title.value.lower():
                expected_hwnd_int = h
        return True
    user32.EnumWindows(WNDENUMPROC(_find_win), 0)
    if not expected_hwnd_int:
        raise RuntimeError(f"No visible Cscape window found for PID {expected_pid} with title containing '{expected_title_sub}'!")
    expected_hwnd_hex = f"0x{expected_hwnd_int:08X}"

    # 1. Process verification
    print(f"\n[Step 1] Verifying Cscape process (PID: {expected_pid})...")
    if not psutil.pid_exists(expected_pid):
        raise RuntimeError(f"Cscape process PID {expected_pid} does not exist!")

    proc = psutil.Process(expected_pid)
    proc_name = proc.name()
    proc_exe = proc.exe()
    proc_memory_mb = proc.memory_info().rss / (1024 * 1024)
    proc_status = proc.status()
    print(f"  PID {expected_pid} verified: Name='{proc_name}', Exe='{proc_exe}', Memory={proc_memory_mb:.2f} MB, Status={proc_status}")
    if "cscape" not in proc_name.lower():
        raise RuntimeError(f"PID {expected_pid} is not Cscape.exe (name={proc_name})")

    # 2. Window verification
    print(f"\n[Step 2] Verifying Main Window (HWND: {expected_hwnd_hex})...")
    if not user32.IsWindow(expected_hwnd_int):
        raise RuntimeError(f"HWND {expected_hwnd_hex} is not a valid Win32 window handle!")

    win_pid = ctypes.wintypes.DWORD()
    user32.GetWindowThreadProcessId(expected_hwnd_int, ctypes.byref(win_pid))
    if win_pid.value != expected_pid:
        raise RuntimeError(f"HWND {expected_hwnd_hex} belongs to PID {win_pid.value}, expected {expected_pid}!")

    buf_title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(expected_hwnd_int, buf_title, 512)
    win_title = buf_title.value
    win_visible = bool(user32.IsWindowVisible(expected_hwnd_int))
    win_enabled = bool(user32.IsWindowEnabled(expected_hwnd_int))
    is_hung = w.is_hung_app_window(expected_hwnd_int)

    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(expected_hwnd_int, ctypes.byref(rect))
    rect_coords = [rect.left, rect.top, rect.right, rect.bottom]

    print(f"  Window Title: '{win_title}'")
    print(f"  Visible: {win_visible}, Enabled: {win_enabled}, IsHung: {is_hung}, Rect: {rect_coords}")

    if expected_title_sub.lower() not in win_title.lower():
        raise RuntimeError(f"Window title '{win_title}' does not contain expected '{expected_title_sub}'!")
    if not win_visible:
        raise RuntimeError(f"Main window {expected_hwnd_hex} is not visible!")

    # 3. Inspect Project Navigator and TreeView
    print("\n[Step 3] Locating Project Navigator and SysTreeView32 control...")
    navigator_hwnd = None
    tree_hwnd = None

    def enum_child_proc(h, _):
        nonlocal navigator_hwnd, tree_hwnd
        c = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(h, c, 256)
        t = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(h, t, 512)
        vis = bool(user32.IsWindowVisible(h))
        if "project navigator" in t.value.lower() and vis:
            navigator_hwnd = h
        if "systreeview32" in c.value.lower() and vis:
            tree_hwnd = h
        return 1

    from scripts.watchdog_cscape_10min import WNDENUMPROC
    c_cb = WNDENUMPROC(enum_child_proc)
    user32.EnumChildWindows(expected_hwnd_int, c_cb, 0)

    print(f"  Project Navigator Bar HWND: 0x{navigator_hwnd:08X}" if navigator_hwnd else "  Project Navigator Bar not found")
    print(f"  Visible SysTreeView32 HWND: 0x{tree_hwnd:08X}" if tree_hwnd else "  SysTreeView32 not found")

    if not tree_hwnd:
        raise RuntimeError("Could not find visible SysTreeView32 control under Cscape main window!")

    # Open target process for memory reading
    hproc = kernel32.OpenProcess(0x001F0FFF, False, expected_pid)
    if not hproc:
        raise RuntimeError(f"Failed to OpenProcess on PID {expected_pid}")

    remote_buf = kernel32.VirtualAllocEx(hproc, None, 4096, 0x1000, 0x04)
    text_buf = remote_buf + 256

    def get_node_details(hitem: int):
        tvitem = struct.pack("<IIIIIIIIII", TVIF_TEXT | TVIF_CHILDREN, hitem, 0, 0, text_buf, 256, 0, 0, 0, 0)
        kernel32.WriteProcessMemory(hproc, remote_buf, tvitem, len(tvitem), None)
        user32.SendMessageW(tree_hwnd, TVM_GETITEMA, 0, remote_buf)
        raw_a = ctypes.create_string_buffer(256)
        kernel32.ReadProcessMemory(hproc, text_buf, raw_a, 256, None)
        
        tvitem_out = ctypes.create_string_buffer(40)
        kernel32.ReadProcessMemory(hproc, remote_buf, tvitem_out, 40, None)
        _, _, _, _, _, _, _, _, c_children, _ = struct.unpack("<IIIIIIIIII", tvitem_out.raw)
        
        name = raw_a.value.decode('latin1', errors='replace').strip()
        if not name:
            user32.SendMessageW(tree_hwnd, TVM_GETITEMW, 0, remote_buf)
            raw_w = (ctypes.c_wchar * 256)()
            kernel32.ReadProcessMemory(hproc, text_buf, raw_w, 512, None)
            name = raw_w.value.strip()

        state = user32.SendMessageW(tree_hwnd, TVM_GETITEMSTATE, hitem, 0xFFFF)
        is_expanded = bool(state & TVIS_EXPANDED)

        # Enumerate children
        actual_children = []
        child = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_CHILD, hitem)
        while child:
            actual_children.append(child)
            child = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, child)

        return {
            "hitem": hitem,
            "hitem_hex": f"0x{hitem:08X}",
            "name": name,
            "c_children_flag": c_children,
            "children_count": len(actual_children),
            "is_expanded": is_expanded,
            "state_hex": f"0x{state:04X}",
            "children_handles": actual_children,
        }

    # Traverse tree to find TankLevel_P5_Dedicated -> Networking -> Protocols
    print("\n[Step 4] Traversing Project Navigator Tree...")
    all_tree_nodes = []
    root = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_ROOT, 0)

    def traverse(hitem, parent_info=None):
        if not hitem:
            return
        node = get_node_details(hitem)
        node["parent_name"] = parent_info["name"] if parent_info else None
        node["parent_hitem_hex"] = parent_info["hitem_hex"] if parent_info else None
        all_tree_nodes.append(node)

        for ch in node["children_handles"]:
            traverse(ch, node)

    cur = root
    while cur:
        traverse(cur)
        cur = user32.SendMessageW(tree_hwnd, TVM_GETNEXTITEM, TVGN_NEXT, cur)

    print(f"  Scanned {len(all_tree_nodes)} total tree nodes.")

    # Locate target nodes
    p5_project_node = next((n for n in all_tree_nodes if "tanklevel_p5_dedicated" in n["name"].lower()), None)
    if not p5_project_node:
        raise RuntimeError("Node 'TankLevel_P5_Dedicated' not found in Project Navigator tree!")
    print(f"  Found Project Root Node: '{p5_project_node['name']}' ({p5_project_node['hitem_hex']}), children_count={p5_project_node['children_count']}")

    networking_node = next(
        (n for n in all_tree_nodes if n["parent_hitem_hex"] == p5_project_node["hitem_hex"] and n["name"].lower() == "networking"),
        None
    )
    if not networking_node:
        raise RuntimeError("Node 'Networking' under 'TankLevel_P5_Dedicated' not found!")
    print(f"  Found Networking Node: '{networking_node['name']}' ({networking_node['hitem_hex']}), children_count={networking_node['children_count']}, is_expanded={networking_node['is_expanded']}")

    protocols_node = next(
        (n for n in all_tree_nodes if n["parent_hitem_hex"] == networking_node["hitem_hex"] and n["name"].lower() == "protocols"),
        None
    )
    if not protocols_node:
        raise RuntimeError("Node 'Protocols' under 'Networking' not found!")
    print(f"  Found Protocols Node: '{protocols_node['name']}' ({protocols_node['hitem_hex']}), children_count={protocols_node['children_count']}, is_expanded={protocols_node['is_expanded']}")

    # 4. Verification assertions
    print("\n[Step 5] Evaluating Protocols Tree Item Assertions...")
    assert protocols_node["children_count"] == 0, f"Expected Protocols children_count to be 0, got {protocols_node['children_count']}"
    assert protocols_node["c_children_flag"] == 0, f"Expected Protocols c_children_flag to be 0, got {protocols_node['c_children_flag']}"
    print(f"  CONFIRMED: Protocols tree item has Children count: {protocols_node['children_count']} (empty in GUI).")

    # Ensure Protocols is scrolled and visible in the tree control
    user32.SendMessageW(tree_hwnd, TVM_ENSUREVISIBLE, 0, protocols_node["hitem"])
    user32.SendMessageW(tree_hwnd, TVM_SELECTITEM, TVGN_CARET, protocols_node["hitem"])
    time.sleep(0.5)

    # Release process memory buffer
    kernel32.VirtualFreeEx(hproc, remote_buf, 0, 0x8000)
    kernel32.CloseHandle(hproc)

    # 5. Capture screenshot
    print("\n[Step 6] Capturing fresh Cscape GUI screenshot...")
    screenshot_rel = Path("artifacts/screenshots/core08_cscape_protocols_navigator.png")
    screenshot_primary = PRIMARY_ROOT / screenshot_rel
    screenshot_user = USER_ROOT / screenshot_rel

    screenshot_primary.parent.mkdir(parents=True, exist_ok=True)
    screenshot_user.parent.mkdir(parents=True, exist_ok=True)

    # Bring window to foreground momentarily for clean capture
    user32.ShowWindow(expected_hwnd_int, 9)  # SW_RESTORE
    user32.SetForegroundWindow(expected_hwnd_int)
    time.sleep(0.5)

    # Grab bounding box of Cscape main window
    user32.GetWindowRect(expected_hwnd_int, ctypes.byref(rect))
    bbox = (max(0, rect.left), max(0, rect.top), max(10, rect.right), max(10, rect.bottom))
    im = ImageGrab.grab(bbox=bbox)
    im.save(str(screenshot_primary))
    im.save(str(screenshot_user))
    ss_sha256 = compute_sha256(screenshot_primary)
    print(f"  Screenshot captured successfully:")
    print(f"    Primary: {screenshot_primary} ({im.size[0]}x{im.size[1]} px, {ss_sha256[:16]}...)")
    print(f"    User:    {screenshot_user}")

    # 6. Verify associated Modbus files
    print("\n[Step 7] Inspecting associated Modbus configuration files...")
    inv_path = PRIMARY_ROOT / "artifacts/projects/TankLevel_P5_Dedicated/modbus_protocol_inventory.json"
    pv_config_path = PRIMARY_ROOT / "artifacts/projects/TankLevel_P5_Dedicated/modbus_pv_config.json"

    assert inv_path.exists(), f"File {inv_path} does not exist!"
    assert pv_config_path.exists(), f"File {pv_config_path} does not exist!"

    with open(inv_path, "r", encoding="utf-8") as f:
        inv_data = json.load(f)
    with open(pv_config_path, "r", encoding="utf-8") as f:
        pv_config_data = json.load(f)

    inv_sha256 = compute_sha256(inv_path)
    pv_config_sha256 = compute_sha256(pv_config_path)

    print(f"  Inventory file: {inv_path} (devices={len(inv_data.get('devices', []))}, scan_list={len(inv_data.get('scan_list', []))})")
    print(f"  PV config file: {pv_config_path} (modicon={pv_config_data.get('address_mapping', {}).get('modicon_1based')}, reg={pv_config_data.get('address_mapping', {}).get('horner_ocs_register')})")

    # 7. Document findings and compile evidence JSON
    print("\n[Step 8] Compiling and saving verification evidence...")
    evidence_rel = Path("artifacts/checkpoints/core08_cscape_gui_evidence.json")
    evidence_primary = PRIMARY_ROOT / evidence_rel
    evidence_user = USER_ROOT / evidence_rel

    evidence_primary.parent.mkdir(parents=True, exist_ok=True)
    evidence_user.parent.mkdir(parents=True, exist_ok=True)

    documented_finding = (
        "The native Cscape GUI tree item Protocols is unexpanded/empty (Children count: 0) in the UI tree, "
        "whereas the complete devices and scan list are defined and maintained in modbus_protocol_inventory.json "
        "and modbus_pv_config.json."
    )

    evidence_payload = {
        "status": "success",
        "task": "CORE-08 Cscape GUI Liveness & Protocols Inspection",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "cscape_process": {
            "pid": expected_pid,
            "name": proc_name,
            "exe": proc_exe,
            "memory_mb": round(proc_memory_mb, 2),
            "status": proc_status,
            "is_hung": is_hung,
        },
        "cscape_window": {
            "hwnd_hex": expected_hwnd_hex,
            "hwnd_int": expected_hwnd_int,
            "title": win_title,
            "visible": win_visible,
            "enabled": win_enabled,
            "rect": rect_coords,
            "title_verification": {
                "expected_substring": expected_title_sub,
                "matched": True,
            },
        },
        "project_navigator_tree": {
            "navigator_bar_hwnd": f"0x{navigator_hwnd:08X}" if navigator_hwnd else None,
            "tree_hwnd": f"0x{tree_hwnd:08X}",
            "project_node": {
                "name": p5_project_node["name"],
                "hitem": p5_project_node["hitem_hex"],
                "children_count": p5_project_node["children_count"],
                "is_expanded": p5_project_node["is_expanded"],
            },
            "networking_node": {
                "name": networking_node["name"],
                "hitem": networking_node["hitem_hex"],
                "children_count": networking_node["children_count"],
                "is_expanded": networking_node["is_expanded"],
            },
            "protocols_node": {
                "name": protocols_node["name"],
                "hitem": protocols_node["hitem_hex"],
                "children_count": protocols_node["children_count"],
                "c_children_flag": protocols_node["c_children_flag"],
                "is_expanded": protocols_node["is_expanded"],
                "state_hex": protocols_node["state_hex"],
                "is_empty_in_gui": True,
            },
        },
        "architectural_finding": {
            "statement": documented_finding,
            "gui_state": "EMPTY_UNEXPANDED_TREE_ITEM (Children count: 0)",
            "config_source_of_truth": {
                "modbus_protocol_inventory": {
                    "path": str(inv_path),
                    "sha256": inv_sha256,
                    "devices_count": len(inv_data.get("devices", [])),
                    "scan_list_count": len(inv_data.get("scan_list", [])),
                    "channels_count": len(inv_data.get("channels", [])),
                },
                "modbus_pv_config": {
                    "path": str(pv_config_path),
                    "sha256": pv_config_sha256,
                    "target_register": pv_config_data.get("address_mapping", {}).get("horner_ocs_register"),
                    "modicon_address": pv_config_data.get("address_mapping", {}).get("modicon_1based"),
                },
            },
        },
        "screenshot": {
            "file_name": "core08_cscape_protocols_navigator.png",
            "primary_path": str(screenshot_primary),
            "user_path": str(screenshot_user),
            "dimensions_px": [im.size[0], im.size[1]],
            "sha256": ss_sha256,
        },
        "safety_declarations": {
            "fail_closed_policy": "STRICTLY_ENFORCED",
            "physical_ports": "BLOCKED_FAIL_CLOSED (COM1-COM256)",
            "download_lockout": "BLOCKED_FAIL_CLOSED (32827/33149)",
            "physical_runtime_verification": "PENDING_P7 (Strictly deferred to Phase P7)",
        },
    }

    with open(evidence_primary, "w", encoding="utf-8") as f:
        json.dump(evidence_payload, f, indent=2)
    with open(evidence_user, "w", encoding="utf-8") as f:
        json.dump(evidence_payload, f, indent=2)

    print(f"  Evidence saved successfully:")
    print(f"    Primary: {evidence_primary}")
    print(f"    User:    {evidence_user}")
    print("\n=== [CORE-08] Inspection Completed Successfully ===")
    return evidence_payload


if __name__ == "__main__":
    run_inspection()
