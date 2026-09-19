import json

with open(r"C:\HornerAI\horner-cscape-mcp\scratch\cscape_audit_raw.json", "r", encoding="utf-8") as f:
    raw = json.load(f)

for item in raw["imported_dlls"]:
    dll_name = item["dll"]
    if dll_name.startswith("K5") or dll_name in ["CSCAN.dll", "TagDatabase.dll", "OcsModelDatabase.dll", "Prot.dll", "IO_CFG.dll", "MqttManager.dll", "ssh.dll"]:
        print(f"=== {dll_name} ({item['function_count']} funcs) ===")
        for fn in item["functions"]:
            print(f"   {fn}")
        print()
