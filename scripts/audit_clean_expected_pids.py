import re
from pathlib import Path

scripts_dir = Path(r"C:\HornerAI\horner-cscape-mcp\scripts")

for step in range(156, 171):
    file_path = scripts_dir / f"execute_step{step}_visible_cscape_gui_driver.py"
    if not file_path.exists():
        print(f"Not found: {file_path}")
        continue
    content = file_path.read_text(encoding="utf-8")
    
    # Remove EXPECTED_PID, EXPECTED_HWND_HEX, EXPECTED_HWND_INT definitions
    content = re.sub(r'EXPECTED_PID\s*=\s*\d+\r?\n', '', content)
    content = re.sub(r'EXPECTED_HWND_HEX\s*=\s*"[^"]+"\r?\n', '', content)
    content = re.sub(r'EXPECTED_HWND_INT\s*=\s*int\([^)]+\)\r?\n', '', content)
    
    # Replace (expected {EXPECTED_PID}) and (expected {EXPECTED_HWND_HEX}) in print
    content = content.replace(" (expected {EXPECTED_PID})", "")
    content = content.replace(" (expected {EXPECTED_HWND_HEX})", "")
    
    file_path.write_text(content, encoding="utf-8")
    print(f"Cleaned {file_path.name}")
