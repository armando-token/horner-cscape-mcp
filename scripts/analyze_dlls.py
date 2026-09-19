import os
import sys
import json
import pefile

raw_json_path = r"C:\HornerAI\horner-cscape-mcp\scratch\cscape_audit_raw.json"
with open(raw_json_path, "r", encoding="utf-8") as f:
    raw = json.load(f)

cscape_dir = r"C:\Program Files (x86)\Cscape 10.2"
syswow64 = r"C:\Windows\SysWOW64"

dll_details = []
for item in raw["imported_dlls"]:
    dll_name = item["dll"]
    func_count = item["function_count"]
    sample_funcs = item["functions"][:5]
    
    local_path = os.path.join(cscape_dir, dll_name)
    sys_path = os.path.join(syswow64, dll_name)
    
    location = "Unknown"
    local_size = 0
    if os.path.exists(local_path):
        location = "Local (Cscape 10.2)"
        local_size = os.path.getsize(local_path)
    elif os.path.exists(sys_path):
        location = "System (SysWOW64)"
        local_size = os.path.getsize(sys_path)
    
    # Categorize
    cat = "Other"
    name_lower = dll_name.lower()
    if name_lower.startswith("mfc") or name_lower.startswith("msvc") or name_lower.startswith("vcruntime") or name_lower.startswith("api-ms-win"):
        cat = "CRT / MFC Runtime"
    elif name_lower in ["kernel32.dll", "user32.dll", "gdi32.dll", "comdlg32.dll", "advapi32.dll", "shell32.dll", "ole32.dll", "oleaut32.dll", "wininet.dll", "wsock32.dll", "ws2_32.dll", "version.dll", "shlwapi.dll", "uxtheme.dll", "setupapi.dll", "comctl32.dll", "winspool.drv"]:
        cat = "Windows Win32 System API"
    elif name_lower.startswith("webview2"):
        cat = "Microsoft WebView2 Runtime"
    elif name_lower in ["ocsmodeldatabase.dll", "prot.dll", "useraccesssettings.dll", "loader.dll", "cb160.dll", "cb230.dll", "csftptest.dll", "csrxtest.dll", "heciotag.dll", "hornerethernet.dll", "ioconfig.dll", "pgmloader.dll", "remotedataread.dll", "rn_cfg.dll", "smartmod.dll", "wlgx160.dll", "wlgx230.dll", "wlgxbase.dll", "wlgxccb.dll", "wlgxdrvr.dll", "wlgxmath.dll", "wlgxobjs.dll", "wlgxprcs.dll", "wlgxserv.dll", "wlgxtrap.dll", "wlgxutil.dll"]:
        cat = "Horner Proprietary Engine / Driver"
    elif "stmicro" in name_lower or name_lower.startswith("dfu") or name_lower.startswith("stlink"):
        cat = "Hardware / Programmer Driver"
    else:
        cat = "Application / Component Library"
        
    dll_details.append({
        "dll": dll_name,
        "category": cat,
        "function_count": func_count,
        "location": location,
        "size_bytes": local_size,
        "sample_functions": sample_funcs
    })

print(f"Total DLLs categorized: {len(dll_details)}")
from collections import Counter
print("Categories:", Counter(d["category"] for d in dll_details))
print("Locations:", Counter(d["location"] for d in dll_details))

with open(r"C:\HornerAI\horner-cscape-mcp\scratch\dll_details.json", "w", encoding="utf-8") as out:
    json.dump(dll_details, out, indent=2)
