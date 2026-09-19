import ctypes
import json
from pathlib import Path
import uiautomation as auto

user32 = ctypes.windll.user32
hd = user32.OpenDesktopW("Default", 0, False, 0x01FF)
if hd:
    user32.SetThreadDesktop(hd)

gate = json.loads(Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json").read_text())
hwnd = int(gate["hwnd"], 16)

cscape = auto.ControlFromHandle(hwnd)
print(f"Cscape window: {cscape.Name}")

for ctrl, depth in auto.WalkTree(cscape, maxDepth=8):
    if ctrl.ControlTypeName == "TreeControl":
        print(f"TreeControl: {ctrl.Name}, HWND={hex(ctrl.NativeWindowHandle)}")
        for item in ctrl.GetChildren():
            print(f"  Item: '{item.Name}'")
            for sub in item.GetChildren():
                print(f"    Sub: '{sub.Name}'")
                for sub2 in sub.GetChildren():
                    print(f"      Sub2: '{sub2.Name}'")
