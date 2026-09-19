import re
from pathlib import Path

dll_path = Path(r"C:\Program Files (x86)\Cscape 10.2\GrEdit.dll")
data = dll_path.read_bytes()

# Find strings related to drawing objects
keywords = [b"Static Text", b"Rectangle", b"Line", b"Button", b"Draw", b"Circle", b"Meter", b"Gauge"]
for kw in keywords:
    matches = [m.start() for m in re.finditer(re.escape(kw), data, re.IGNORECASE)]
    print(f"Keyword '{kw.decode()}': {len(matches)} occurrences")
    for pos in matches[:3]:
        # print surrounding text
        start = max(0, pos - 30)
        end = min(len(data), pos + 50)
        snippet = data[start:end]
        print(f"  at 0x{pos:X}: {snippet!r}")
