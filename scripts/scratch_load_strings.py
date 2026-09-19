import ctypes
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

dll_path = r"C:\Program Files (x86)\Cscape 10.2\GrEdit.dll"
hmod = kernel32.LoadLibraryExW(dll_path, None, 0x02) # LOAD_LIBRARY_AS_DATAFILE

cmd_ids = [2787, 2825, 57635, 57634, 57637, 57643, 57644, 2857, 2859, 2788, 2789, 1006, 2841, 2869, 2870, 7803, 38477, 38478, 38570]

buf = ctypes.create_unicode_buffer(512)
for cid in cmd_ids:
    length = user32.LoadStringW(hmod, cid, buf, 512)
    print(f"GrEdit Command {cid}: length={length}, text='{buf.value}'")

exe_path = r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"
hmod_exe = kernel32.LoadLibraryExW(exe_path, None, 0x02)
for cid in cmd_ids:
    length = user32.LoadStringW(hmod_exe, cid, buf, 512)
    if length:
        print(f"Cscape Command {cid}: length={length}, text='{buf.value}'")
