import pefile

cscape_path = r"C:\Program Files (x86)\Cscape 10.2\Cscape.exe"
pe = pefile.PE(cscape_path)

if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
    print(f"Export Name: {pe.DIRECTORY_ENTRY_EXPORT.name}")
    print(f"Number of exports: {len(pe.DIRECTORY_ENTRY_EXPORT.symbols)}")
    for sym in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        name = sym.name.decode(errors="ignore") if sym.name else f"Ordinal({sym.ordinal})"
        print(f"  {sym.ordinal}: {name} (RVA: {hex(sym.address)})")
else:
    print("No export directory found.")
