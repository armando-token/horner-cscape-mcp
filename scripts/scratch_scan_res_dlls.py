import ctypes
from pathlib import Path

kernel32 = ctypes.windll.kernel32
RT_MENU = 4
RT_ACCELERATOR = 9
RT_STRING = 6

def enum_res(hmod, res_type):
    names = []
    def cb(h, rtype, name, _):
        names.append(name)
        return True
    ENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    kernel32.EnumResourceNamesW(hmod, res_type, ENUMPROC(cb), 0)
    return names

cscape_dir = Path(r"C:\Program Files (x86)\Cscape 10.2")
for f in sorted(cscape_dir.glob("*.dll")):
    try:
        h = kernel32.LoadLibraryExW(str(f), None, 0x02)
        if h:
            menus = enum_res(h, RT_MENU)
            accs = enum_res(h, RT_ACCELERATOR)
            if menus or accs:
                print(f"{f.name}: Menus={len(menus)}, Accs={len(accs)}")
            kernel32.FreeLibrary(h)
    except Exception:
        pass
