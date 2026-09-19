# Horner Cscape 10.2: Structured Text to Ladder Conversion (BLOCKED_NATIVE)

## 1. Executive Summary & Finding

In Horner APG Cscape 10.2 (Build `10.2.751.4`), **native conversion between IEC 61131-3 Structured Text (ST) and Advanced Ladder Diagram (LD) is BLOCKED_NATIVE**. 

Cscape 10.2 does not provide any GUI menu item, Win32 accelerator command, OLE/COM interface, or DLL export to convert an existing Structured Text POU or project into Advanced Ladder.

The project treats ST→LD conversion within Cscape 10.2 as **`BLOCKED_NATIVE: DOCUMENT_ONLY`**. Any past or future claim of automated in-Cscape native language conversion is inaccurate.

---

## 2. Technical & Binary Dissection Evidence

Comprehensive static PE binary auditing and dynamic Win32 GUI scraping were conducted against the installed Cscape 10.2 toolchain (`C:\Program Files (x86)\Cscape 10.2`):

### 2.1 PE Export & String Audit (`artifacts/evidence/cscape_st_to_ld_audit.json`)

1. **`Cscape.exe` (17.6 MB MFC binary)**:
   - Scanned 42 PE exports.
   - Zero language conversion exports exist.
   - Zero occurrences of strings `"Change Language"`, `"Convert to Ladder"`, `"ST to LD"`, or `"Convert to LD"`.

2. **`W5EditST.dll` & `W5EditLD.dll` (Language Editors)**:
   - Both DLLs export only two functions: `K5ExecuteCommand` and `K5GetClassName`.
   - Neither DLL contains cross-language translation routines or APIs to serialize ST code into ladder rungs.

3. **`K5Cmp.dll` (Straton Compiler Interface)**:
   - Exports `K5CmpCanConvertProgram`, `K5CmpConvertProgram`, and `K5CmpConvertStExpToFbd`.
   - Forensic analysis reveals these routines are internal Copa-Data Straton functions for converting expressions between Straton ST and Straton FBD within the internal Straton database.
   - They have no connection to Horner Advanced Ladder logic (`.csp` rungs, contacts, coils).

### 2.2 Live Win32 GUI Menu Audit (`artifacts/evidence/st_to_ld_cscape_probe.json`)

Dynamic menu tree scraping was executed on the live Cscape 10.2 main window:
- Scraped all top-level menus (`File`, `Edit`, `View`, `Project`, `Program`, `Tools`, `Window`, `Help`) and all submenus.
- Result: **Zero menu items exist for converting POU language or translating ST to Ladder**.
- In Cscape 10.2, project editor mode is selected upon creation (`Advanced Ladder` vs `IEC 61131-3`) and cannot be cross-converted at runtime.

---

## 3. Architectural Division in Cscape 10.2

Horner APG maintains an architectural divide between its two programming environments:

```
┌─────────────────────────────────────────────────────────────┐
│                    Horner Cscape 10.2                       │
├──────────────────────────────┬──────────────────────────────┤
│    Advanced Ladder Mode      │     IEC 61131-3 Mode         │
│  - Native Horner Rung Engine │  - Copa-Data Straton K5 core │
│  - Binary CFBF .csp streams  │  - W5EditST / W5EditLD DLLs  │
│  - Fixed memory %R/%M/%AI    │  - Tagged variables + OCS    │
│  - NO Structured Text        │  - ST, LD, FBD, SFC          │
└──────────────────────────────┴──────────────────────────────┘
               ▲                                ▲
               │                                │
               └──────── NO NATIVE BRIDGE ──────┘
                     (ST ↔ LD BLOCKED)
```

1. **Advanced Ladder Mode**: Uses Horner's proprietary rung solver. Does not support IEC Structured Text syntax.
2. **IEC 61131-3 Mode**: Uses the embedded Copa-Data Straton K5 engine. While Straton supports LD within its own engine, Cscape 10.2 does not expose an automated ST-to-LD converter.

---

## 4. MCP Platform Solution & Mitigations

Because native conversion is blocked in Cscape 10.2, the Horner Cscape MCP server enforces:

1. **`STLadderInteropGuard` AST Decomposition**:
   - Parses IEC 61131-3 Structured Text using pure-Python lexer/parser.
   - Extracts expressions (arithmetic, logic, relational), timers, and alarms into an abstract ladder representation (`LadderProgram`).
   - Generates external ASCII ladder diagrams and JSON AST proofs for engineering verification without modifying Cscape binaries.

2. **Strict Fail-Closed Interop Guardrail**:
   - Rejects any legacy ladder syntax (`--[ ]--`, `--( )--`, rungs, contacts) injected into Structured Text files.
   - Guarantees that Structured Text POUs remain 100% compliant with standard IEC 61131-3 grammar.
