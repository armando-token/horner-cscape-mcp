import os
import hashlib
import pefile
import json

cscape_dir = r"C:\Program Files (x86)\Cscape 10.2"
exes = []

for f in sorted(os.listdir(cscape_dir)):
    if f.lower().endswith(".exe"):
        p = os.path.join(cscape_dir, f)
        sz = os.path.getsize(p)
        h = hashlib.sha256()
        with open(p, "rb") as ef:
            while chunk := ef.read(65536):
                h.update(chunk)
        
        desc = ""
        ver = ""
        prod = ""
        try:
            pe = pefile.PE(p, fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            if hasattr(pe, 'FileInfo'):
                for fi in pe.FileInfo:
                    for ent in fi:
                        if hasattr(ent, 'StringTable'):
                            for st in ent.StringTable:
                                for k, v in st.entries.items():
                                    k_s = k.decode(errors='ignore') if isinstance(k, bytes) else str(k)
                                    v_s = v.decode(errors='ignore') if isinstance(v, bytes) else str(v)
                                    if k_s == "FileDescription":
                                        desc = v_s
                                    elif k_s == "FileVersion":
                                        ver = v_s
                                    elif k_s == "ProductName":
                                        prod = v_s
        except Exception:
            pass
            
        exes.append({
            "name": f,
            "size": sz,
            "sha256": h.hexdigest(),
            "version": ver,
            "product": prod,
            "description": desc
        })

print(f"Total executables: {len(exes)}")
for e in exes:
    print(f"  {e['name']:<20} | {e['size']:10d} B | {e['version']:<15} | {e['description']}")

with open(r"C:\HornerAI\horner-cscape-mcp\scratch\exes_audit.json", "w", encoding="utf-8") as f:
    json.dump(exes, f, indent=2)
