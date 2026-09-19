import os
import json

raw_json_path = r"C:\HornerAI\horner-cscape-mcp\scratch\cscape_audit_raw.json"
dll_json_path = r"C:\HornerAI\horner-cscape-mcp\scratch\dll_audit_complete.json"
exes_json_path = r"C:\HornerAI\horner-cscape-mcp\scratch\exes_audit.json"

with open(raw_json_path, "r", encoding="utf-8") as f:
    raw = json.load(f)
with open(dll_json_path, "r", encoding="utf-8") as f:
    dlls = json.load(f)
with open(exes_json_path, "r", encoding="utf-8") as f:
    exes = json.load(f)

# Sort DLLs by name
dlls_sorted = sorted(dlls, key=lambda x: x["name"].lower())

print(f"Loaded {len(dlls)} DLLs, {len(exes)} EXEs.")
