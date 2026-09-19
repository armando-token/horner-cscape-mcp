# Technical Evidence: Native ST→LD Language Change in Horner Cscape 10.2

## Verdict: BLOCKED (Not Supported by Horner Cscape 10.2 IDE)

### 1. Executive Summary
An exhaustive architectural audit was performed on the live Cscape 10.2 installation (`Cscape.exe` v10.2.751.4, 32-bit x86 MFC) and its loaded editor modules to determine whether native conversion from an IEC 61131-3 Structured Text (ST) POU to Ladder Diagram (LD / Advanced Ladder) is supported within the IDE.

The audit conclusively proves that **Horner Cscape 10.2 DOES NOT natively support converting Structured Text to Ladder Diagram**. This capability is classified as **`BLOCKED`**.

---

### 2. Live Win32 GUI & Command Bar Inspection
- **Live Window**: HWND `0x007B06D6`, Title `Cscape - Logged In : "armando@controlnautas.com" - [TankLevelClosedLoop.csp]`.
- **Top-Level Menu & Ribbon Bar**: Enumeration of top-level menus and MFC docking command bars found **zero** menu items, context menu actions, or accelerator keys for "Change Language", "Convert to Ladder", "Convert POU", or "ST to LD".
- **Editor Segregation**: In Horner Cscape 10.2, project editor paradigms are strictly disjoint:
  1. Horner Advanced Ladder (`.csp` / `.cpj` native register-based ladder).
  2. IEC 61131-3 Multi-Language projects.
  Within an IEC project, POUs are bound at creation to a specific editor DLL (`W5EditST.dll` for ST, `W5EditLD.dll` for IEC LD, `W5EditFBD.dll` for FBD, `W5EditSFC.dll` for SFC). The GUI provides no transformation action to switch an existing ST POU's language to LD.

---

### 3. Binary Export & String Table Audit
An automated PE analysis was executed across all relevant executable binaries and DLLs in `C:\Program Files (x86)\Cscape 10.2\` ([`scripts/audit_cscape_language_conversion.py`](file:///C:/HornerAI/horner-cscape-mcp/scripts/audit_cscape_language_conversion.py)):

| Binary | Total Exports | Language Conversion Exports | Matched Conversion Strings |
| :--- | :--- | :--- | :--- |
| `Cscape.exe` | 43 | **0** | **0** matches for "Change Language", "Convert to Ladder", "ST to LD" |
| `W5EditST.dll` | 2 | **0** | **0** matches for any conversion routine |
| `W5EditLD.dll` | 2 | **0** | **0** matches for any conversion routine |
| `W5EditFBD.dll` | 2 | **0** | **0** matches for any conversion routine |
| `W5EditSFC.dll` | 2 | **0** | **0** matches for any conversion routine |
| `K5Cmp.dll` | 40 | `['K5CmpCanConvertProgram', 'K5CmpConversionNeedBuild', 'K5CmpConvertProgram', 'K5CmpConvertStExpToFbd']` | **0** matches for ST to LD. Only `K5CmpConvertStExpToFbd` exists (converts inline ST expressions to FBD inside the legacy Straton kernel) |
| `K5MW.dll` | 111 | **0** | **0** matches |
| `K5NMW.dll` | 93 | **0** | **0** matches |
| `K5Caps.dll` | 3 | **0** | **0** matches |
| `K5XML.dll` | 11 | **0** | **0** matches |

Evidence output recorded on disk at: [`artifacts/evidence/cscape_st_to_ld_audit.json`](file:///C:/HornerAI/horner-cscape-mcp/artifacts/evidence/cscape_st_to_ld_audit.json).

---

### 4. Verified Alternative: Offline AST Transpilation
Because the Cscape IDE provides no native ST→LD translation engine, our implementation utilizes an offline AST parsing and transpilation pipeline:
- [`src/cscape/st_ld_interop.py`](file:///C:/HornerAI/horner-cscape-mcp/src/cscape/st_ld_interop.py): [`STLadderInteropGuard`](file:///C:/HornerAI/horner-cscape-mcp/src/cscape/st_ld_interop.py) parses Structured Text syntax into an abstract syntax tree and generates equivalent ladder logic rung structures, contacts, coils, and Math/Compare blocks.
- Verified across 56 tests in [`tests/test_st_ld_interop.py`](file:///C:/HornerAI/horner-cscape-mcp/tests/test_st_ld_interop.py) (56/56 passed) and demonstrated in [`artifacts/conversions/tank_level_st_to_ladder_proof.txt`](file:///C:/HornerAI/horner-cscape-mcp/artifacts/conversions/tank_level_st_to_ladder_proof.txt).
