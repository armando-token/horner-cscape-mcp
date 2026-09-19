import os
import pefile
import json

cscape_path = r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"
cscape_dir = r"C:\Program Files (x86)\Cscape 10.2"
syswow64 = r"C:\Windows\SysWOW64"

pe = pefile.PE(cscape_path)

dll_list = []
for entry in pe.DIRECTORY_ENTRY_IMPORT:
    dll_name = entry.dll.decode(errors="ignore") if isinstance(entry.dll, bytes) else str(entry.dll)
    local_p = os.path.join(cscape_dir, dll_name)
    sys_p = os.path.join(syswow64, dll_name)
    
    if os.path.exists(local_p):
        loc = "Local"
        file_path = local_p
        sz = os.path.getsize(local_p)
    elif os.path.exists(sys_p):
        loc = "SysWOW64"
        file_path = sys_p
        sz = os.path.getsize(sys_p)
    else:
        loc = "Missing"
        file_path = ""
        sz = 0
        
    func_names = []
    ordinals = 0
    named = 0
    for imp in entry.imports:
        if imp.name:
            named += 1
            func_names.append(imp.name.decode(errors="ignore") if isinstance(imp.name, bytes) else str(imp.name))
        else:
            ordinals += 1
            func_names.append(f"Ordinal {imp.ordinal}")

    # Description from target file
    desc = ""
    f_ver = ""
    p_name = ""
    if file_path and os.path.exists(file_path):
        try:
            subpe = pefile.PE(file_path, fast_load=True)
            subpe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            if hasattr(subpe, 'FileInfo'):
                for fi in subpe.FileInfo:
                    for ent in fi:
                        if hasattr(ent, 'StringTable'):
                            for st in ent.StringTable:
                                for k, v in st.entries.items():
                                    k_s = k.decode(errors='ignore') if isinstance(k, bytes) else str(k)
                                    v_s = v.decode(errors='ignore') if isinstance(v, bytes) else str(v)
                                    if k_s == "FileDescription":
                                        desc = v_s
                                    elif k_s == "FileVersion":
                                        f_ver = v_s
                                    elif k_s == "ProductName":
                                        p_name = v_s
        except Exception:
            pass

    dll_list.append({
        "name": dll_name,
        "location": loc,
        "size": sz,
        "function_count": len(entry.imports),
        "named_count": named,
        "ordinal_count": ordinals,
        "description": desc,
        "file_version": f_ver,
        "product_name": p_name,
        "sample_funcs": func_names[:5]
    })

print(f"Audited {len(dll_list)} DLLs.")
with open(r"C:\HornerAI\horner-cscape-mcp\scratch\dll_audit_complete.json", "w", encoding="utf-8") as f:
    json.dump(dll_list, f, indent=2)

for i, d in enumerate(dll_list, 1):
    print(f"{i:2d}. {d['name']:<25} | {d['location']:<8} | {d['function_count']:3d} f ({d['named_count']} named, {d['ordinal_count']} ord) | {d['description'][:30]}")
