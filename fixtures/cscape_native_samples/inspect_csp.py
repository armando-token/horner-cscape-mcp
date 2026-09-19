"""
Cscape Native Project (.csp) Binary Inspector

Inspects native Horner Cscape binary project files (.csp), which use the
Microsoft Compound File Binary Format (CFBF / OLE2) and Horner's internal
'Contents' stream serialization.
"""

import argparse
import os
import re
import struct
import sys
from typing import Dict, List, Optional, Any

try:
    import olefile
except ImportError:
    olefile = None


def parse_csp_header(data: bytes) -> Dict[str, Any]:
    """
    Parse the header of the 'Contents' stream from a Cscape .csp file.
    
    Header structure:
      0x00 - 0x03: Magic Number (0x78563412, little-endian: 12 34 56 78)
      0x04 - 0x07: File Format Version (uint32, e.g. 38, 48, 54, 62, 69, 79)
      0x08:        Cscape Major Version (uint8, e.g. 3, 5)
      0x09:        Cscape Minor Version (uint8, e.g. 40, 80)
      0x0A - 0x0B: Cscape Build Number (uint16, e.g. 1, 20, 250, 253)
    """
    if len(data) < 12:
        return {"valid": False, "error": "Stream too short (<12 bytes)"}
    
    magic, file_ver, c_maj, c_min, c_bld = struct.unpack("<IIBBH", data[:12])
    
    is_magic_valid = (magic == 0x78563412)
    return {
        "valid": is_magic_valid,
        "magic": hex(magic),
        "magic_bytes": data[:4].hex(" "),
        "file_format_version": file_ver,
        "cscape_version": f"{c_maj}.{c_min:02d}",
        "cscape_build": c_bld,
        "cscape_version_full": f"v{c_maj}.{c_min:02d} (build {c_bld})"
    }


def inspect_csp_file(fpath: str) -> Dict[str, Any]:
    """Thoroughly inspect a .csp file."""
    if not os.path.isfile(fpath):
        return {"error": f"File not found: {fpath}"}
    
    file_size = os.path.getsize(fpath)
    with open(fpath, "rb") as f:
        cfbf_magic = f.read(8)
    
    is_cfbf = (cfbf_magic == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    result: Dict[str, Any] = {
        "file_name": os.path.basename(fpath),
        "file_path": os.path.abspath(fpath),
        "file_size": file_size,
        "is_cfbf": is_cfbf,
        "cfbf_magic_hex": cfbf_magic.hex(" ")
    }
    
    if not is_cfbf:
        result["error"] = "Not a valid OLE Compound Document (missing CFBF signature)"
        return result
    
    if olefile is None:
        result["error"] = "olefile python package is required for full stream parsing"
        return result
        
    try:
        ole = olefile.OleFileIO(fpath)
        streams = ["/".join(s) for s in ole.listdir()]
        result["streams"] = streams
        
        if ole.exists("Contents"):
            data = ole.openstream("Contents").read()
            result["contents_size"] = len(data)
            hdr = parse_csp_header(data)
            result["header"] = hdr
            
            # Detect subroutines
            subroutines = []
            for m in re.finditer(rb'(?:main|[A-Za-z][A-Za-z0-9_]{3,30})', data[:2048]):
                s = m.group().decode("latin1")
                if s in ["main", "Main", "Receive_Q_AQ", "Transmit_I_AI"] or re.match(r'^(Sub_\w+|Task_\w+)$', s):
                    if s not in subroutines:
                        subroutines.append(s)
            if not subroutines and b"main" in data:
                subroutines.append("main")
            result["subroutines"] = subroutines
            
            # Detect registers
            reg_patterns = re.findall(r'%?[RQIAMSTK][A-Z]?\d+', data.decode("latin1", errors="replace"))
            result["registers"] = sorted(list(set(reg_patterns)))[:15]
            
            # Detect strings / comments
            raw_strings = [m.group().decode("latin1", errors="replace").strip() for m in re.finditer(rb'[\x20-\x7e]{15,}', data)]
            comments = [s for s in raw_strings if " " in s and not re.match(r'^[0-9A-Fa-f\s,.-]+$', s)]
            result["sample_comments"] = comments[:5]
        else:
            result["contents_size"] = 0
            result["error"] = "'Contents' stream not found"
            
        ole.close()
    except Exception as exc:
        result["error"] = f"OLE extraction failed: {str(exc)}"
        
    return result


def main():
    parser = argparse.ArgumentParser(description="Inspect Horner Cscape .csp binary files.")
    parser.add_argument("path", help="Path to .csp file or directory of .csp files")
    args = parser.parse_args()
    
    target = args.path
    if os.path.isdir(target):
        csp_files = sorted([os.path.join(target, f) for f in os.listdir(target) if f.endswith(".csp")])
        print(f"Found {len(csp_files)} .csp files in {target}\n")
        print(f"{'Filename':<30} | {'Size':>8} | {'Ver':>4} | {'Cscape Version':<18} | {'Subroutines'}")
        print("-" * 85)
        for cf in csp_files:
            info = inspect_csp_file(cf)
            hdr = info.get("header", {})
            sub_str = ", ".join(info.get("subroutines", []))
            print(f"{info['file_name']:<30} | {info['file_size']:>8} | {hdr.get('file_format_version', '-'):>4} | {hdr.get('cscape_version_full', '-'):<18} | {sub_str}")
    else:
        info = inspect_csp_file(target)
        import json
        print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
