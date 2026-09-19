"""Audit Cscape 10.2 editor DLLs for native ST to LD conversion capabilities."""

import json
from pathlib import Path
import pefile

CSCAPE_DIR = Path(r"C:\Program Files (x86)\Cscape 10.2")
OUTPUT_PATH = Path(r"C:\Users\ArmandoSilva\artifacts\evidence\cscape_st_to_ld_audit.json")

DLLS_TO_CHECK = [
    "Cscape.exe",
    "W5EditST.dll",
    "W5EditLD.dll",
    "W5EditFBD.dll",
    "W5EditSFC.dll",
    "K5Cmp.dll",
    "K5MW.dll",
    "K5NMW.dll",
    "K5Caps.dll",
    "K5XML.dll",
]

SEARCH_STRINGS = [
    "Change Language",
    "Change POU Language",
    "Convert to Ladder",
    "Convert to LD",
    "Convert to ST",
    "Convert to FBD",
    "Structured Text to Ladder",
    "ST to LD",
    "Convert Language",
    "Language Conversion",
]

def audit_dll(dll_path: Path):
    res = {
        "file": dll_path.name,
        "exists": dll_path.exists(),
        "exports": [],
        "conversion_exports": [],
        "string_matches": {},
    }
    if not dll_path.exists():
        return res

    data = dll_path.read_bytes()

    try:
        pe = pefile.PE(str(dll_path))
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                if exp.name:
                    sym = exp.name.decode("ascii", errors="ignore")
                    res["exports"].append(sym)
                    if any(k in sym.lower() for k in ["conv", "lang", "stto", "ldto", "trans"]):
                        res["conversion_exports"].append(sym)
    except Exception as err:
        res["pe_error"] = str(err)

    for term in SEARCH_STRINGS:
        term_bytes_a = term.encode("ascii")
        term_bytes_w = term.encode("utf-16le")
        cnt_a = data.count(term_bytes_a)
        cnt_w = data.count(term_bytes_w)
        if cnt_a + cnt_w > 0:
            res["string_matches"][term] = {"ascii": cnt_a, "utf16": cnt_w, "total": cnt_a + cnt_w}

    return res

def main():
    results = {}
    print("Auditing Cscape 10.2 PE binaries for native ST->LD conversion support...")
    for dll_name in DLLS_TO_CHECK:
        p = CSCAPE_DIR / dll_name
        res = audit_dll(p)
        results[dll_name] = res
        print(f"\n--- {dll_name} ---")
        print(f"  Total Exports: {len(res.get('exports', []))}")
        print(f"  Conversion-related exports: {res.get('conversion_exports', [])}")
        if res.get("string_matches"):
            print("  Matched strings:")
            for k, v in res["string_matches"].items():
                print(f"    '{k}': total={v['total']}")
        else:
            print("  No language conversion strings matched.")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nAudit complete. Evidence written to: {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
