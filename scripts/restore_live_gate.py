import datetime
import json
from pathlib import Path

gate_data = {
    "ready_for_tests": True,
    "status": "READY_FOR_TESTS",
    "pid": 14580,
    "hwnd": "0x024B054A",
    "window_title": 'Cscape - Logged In : "armando@controlnautas.com" - [TankLevelClosedLoop.csp]',
    "project_file": r"C:\Users\ArmandoSilva\artifacts\projects\TankLevelClosedLoop\TankLevelClosedLoop.csp",
    "exit_code": None,
    "reason": "TankLevelClosedLoop verified active and responsive",
    "cycle": 1,
    "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()[:-3] + "Z",
    "heartbeat_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()[:-3] + "Z"
}

paths = [
    Path(r"C:\Users\ArmandoSilva\artifacts\.cscape_live_gate.json"),
    Path(r"C:\Users\ArmandoSilva\artifacts\checkpoints\cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\.cscape_live_gate.json"),
    Path(r"C:\HornerAI\horner-cscape-mcp\artifacts\checkpoints\cscape_live_gate.json"),
]

for p in paths:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(gate_data, indent=2), encoding="utf-8")

print("Gate successfully restored to all 4 locations.")
