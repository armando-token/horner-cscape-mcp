import os
import sys
import json
import hashlib
import datetime
import pefile

raw_json_path = r"C:\HornerAI\horner-cscape-mcp\scratch\cscape_audit_raw.json"
with open(raw_json_path, "r", encoding="utf-8") as f:
    raw = json.load(f)

cscape_dir = r"C:\Program Files (x86)\Cscape 10.2"

# Find all executables in the Cscape directory
exes = []
for f in os.listdir(cscape_dir):
    full_p = os.path.join(cscape_dir, f)
    if os.path.isfile(full_p) and f.lower().endswith(".exe"):
        sz = os.path.getsize(full_p)
        h = hashlib.sha256()
        with open(full_p, "rb") as ef:
            while c := ef.read(65536):
                h.update(c)
        exes.append({
            "name": f,
            "size": sz,
            "sha256": h.hexdigest()
        })

print("Found EXEs:", len(exes))
for e in exes:
    print(f"  {e['name']}: {e['size']} bytes, {e['sha256'][:16]}...")

print("\nImported DLLs count:", len(raw["imported_dlls"]))
