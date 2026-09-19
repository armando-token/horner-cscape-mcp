import os
import sys
import hashlib
import datetime
import json
import pefile

cscape_dir = r"C:\Program Files (x86)\Cscape 10.2"
exe_path = os.path.join(cscape_dir, "Cscape.exe")

result = {
    "cscape_dir_exists": os.path.isdir(cscape_dir),
    "exe_path": exe_path,
    "exe_exists": os.path.exists(exe_path)
}

if os.path.exists(exe_path):
    # Size
    size = os.path.getsize(exe_path)
    result["size_bytes"] = size
    result["size_mb"] = round(size / (1024 * 1024), 2)
    
    # SHA256
    sha256 = hashlib.sha256()
    with open(exe_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    result["sha256"] = sha256.hexdigest()

    # PE analysis
    pe = pefile.PE(exe_path)
    result["pe_machine"] = hex(pe.FILE_HEADER.Machine)
    result["pe_machine_desc"] = "IMAGE_FILE_MACHINE_I386 (32-bit x86)" if pe.FILE_HEADER.Machine == 0x14c else hex(pe.FILE_HEADER.Machine)
    
    timestamp = pe.FILE_HEADER.TimeDateStamp
    dt = datetime.datetime.fromtimestamp(timestamp, tz=datetime.timezone.utc)
    result["pe_timestamp_raw"] = timestamp
    result["pe_timestamp_utc"] = dt.isoformat()
    result["pe_timestamp_str"] = dt.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Version Info
    version_info = {}
    if hasattr(pe, "FileInfo"):
        for finfo in pe.FileInfo:
            for entry in finfo:
                if hasattr(entry, "StringTable"):
                    for st in entry.StringTable:
                        for k, v in st.entries.items():
                            k_str = k.decode(errors="ignore") if isinstance(k, bytes) else str(k)
                            v_str = v.decode(errors="ignore") if isinstance(v, bytes) else str(v)
                            version_info[k_str] = v_str
    result["version_info"] = version_info
    
    # FixedFileInfo
    if hasattr(pe, "VS_FIXEDFILEINFO"):
        ffi = pe.VS_FIXEDFILEINFO[0]
        result["fixed_file_version"] = f"{(ffi.FileVersionMS >> 16) & 0xffff}.{ffi.FileVersionMS & 0xffff}.{(ffi.FileVersionLS >> 16) & 0xffff}.{ffi.FileVersionLS & 0xffff}"
        result["fixed_product_version"] = f"{(ffi.ProductVersionMS >> 16) & 0xffff}.{ffi.ProductVersionMS & 0xffff}.{(ffi.ProductVersionLS >> 16) & 0xffff}.{ffi.ProductVersionLS & 0xffff}"

    # Imports
    imports = []
    if hasattr(pe, "DIRECTORY_ENTRY_IMPORT"):
        for entry in pe.DIRECTORY_ENTRY_IMPORT:
            dll_name = entry.dll.decode(errors="ignore") if isinstance(entry.dll, bytes) else str(entry.dll)
            func_names = []
            for imp in entry.imports:
                if imp.name:
                    func_names.append(imp.name.decode(errors="ignore") if isinstance(imp.name, bytes) else str(imp.name))
                else:
                    func_names.append(f"Ordinal({imp.ordinal})")
            imports.append({
                "dll": dll_name,
                "function_count": len(entry.imports),
                "functions": func_names
            })
    result["imported_dll_count"] = len(imports)
    result["imported_dlls"] = imports

# Directory contents analysis
dir_files = []
dir_subdirs = []
extension_counts = {}
total_dir_size = 0

if os.path.isdir(cscape_dir):
    for root, dirs, files in os.walk(cscape_dir):
        rel_root = os.path.relpath(root, cscape_dir)
        if rel_root != ".":
            dir_subdirs.append(rel_root)
        for f in files:
            full_f = os.path.join(root, f)
            try:
                f_sz = os.path.getsize(full_f)
                total_dir_size += f_sz
                ext = os.path.splitext(f)[1].lower()
                extension_counts[ext] = extension_counts.get(ext, 0) + 1
                if rel_root == ".":
                    dir_files.append({
                        "name": f,
                        "size": f_sz,
                        "ext": ext
                    })
            except Exception as e:
                pass

result["dir_stats"] = {
    "total_files": sum(extension_counts.values()),
    "root_file_count": len(dir_files),
    "subdir_count": len(dir_subdirs),
    "total_size_bytes": total_dir_size,
    "total_size_mb": round(total_dir_size / (1024 * 1024), 2),
    "extension_counts": extension_counts,
    "subdirectories": dir_subdirs,
    "root_files": sorted(dir_files, key=lambda x: x["name"].lower())
}

scratch_dir = r"C:\HornerAI\horner-cscape-mcp\scratch"
os.makedirs(scratch_dir, exist_ok=True)
with open(os.path.join(scratch_dir, "cscape_audit_raw.json"), "w", encoding="utf-8") as out:
    json.dump(result, out, indent=2)

print(f"Audit completed successfully. Imported DLLs: {result.get('imported_dll_count')}")
print(f"FileVersion: {result.get('version_info', {}).get('FileVersion')}")
print(f"ProductName: {result.get('version_info', {}).get('ProductName')}")
print(f"Size: {result.get('size_bytes')} bytes")
print(f"SHA256: {result.get('sha256')}")
print(f"PE Timestamp: {result.get('pe_timestamp_str')} (raw: {result.get('pe_timestamp_raw')})")
