"""Horner Cscape Model Context Protocol (MCP) Prompts.

Exposes engineering prompts for AI coding agents:
- generate_iec_st_controller: Formulate production-grade IEC 61131-3 Structured Text for Horner Cscape
- refactor_ladder_to_st: Convert legacy Horner Advanced Ladder logic into modern Structured Text
- debug_st_diagnostics: Analyze compilation errors and syntax warnings to generate fixes
- simulate_st_logic: Formulate simulation test benches and input sequences for software verification
"""

from typing import Any


def generate_iec_st_controller(
    application_type: str,
    requirements: str,
    target_plc: str = "XL4",
) -> str:
    """Prompt for generating a robust, production-grade IEC 61131-3 Structured Text controller."""
    return f"""You are an expert IEC 61131-3 Structured Text engineer specializing in Horner APG Cscape and modern Horner OCS controllers.

Target PLC Architecture: {target_plc}
Application Type: {application_type}
Requirements:
{requirements}

Strict Design & Safety Rules:
1. PURE STRUCTURED TEXT (ST) ONLY: Do NOT generate ladder logic rungs, contacts, coils, or graphical representations.
2. IEC 61131-3 SYNTAX:
   - Proper POU declaration (PROGRAM, FUNCTION_BLOCK, or FUNCTION).
   - Explicit variable declarations in VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, and internal VAR blocks.
   - Use standard IEC elementary types (BOOL, INT, DINT, REAL, TIME, etc.) and named symbolic variables.
   - Terminate all executable statements with a semicolon (;).
   - Ensure all IF, CASE, FOR, and WHILE blocks are strictly paired with END_IF, END_CASE, END_FOR, and END_WHILE.
3. DETERMINISTIC & CYCLIC EXECUTION:
   - The code will execute cyclically (e.g. 10ms task scan).
   - Avoid infinite loops; use counters or timers (TON, TOF) for time-based sequencing.
   - For state machines, use clean CASE CurrentState OF ... END_CASE; patterns.
4. SAFETY INTERLOCKS:
   - Fail-safe default states on power-up / reset.
   - E-Stop and safety interlock override logic must de-energize outputs immediately.

Generate the complete, validated Structured Text code with comments and variable definitions ready for injection into Cscape.
"""


def refactor_ladder_to_st(
    ladder_logic_description: str,
    registers_used: str = "",
) -> str:
    """Prompt for migrating legacy Horner Advanced Ladder logic to IEC 61131-3 Structured Text."""
    reg_context = f"\nRegisters / I/O Map in Legacy Code:\n{registers_used}\n" if registers_used else ""

    return f"""You are a PLC modernization engineer tasked with migrating legacy Horner Advanced Ladder logic to modern IEC 61131-3 Structured Text (ST).

Legacy Ladder Logic Description:
{ladder_logic_description}
{reg_context}

Refactoring Directives:
1. REPLACE REGISTERS WITH SYMBOLS: Replace raw register addresses (%R, %M, %T, %I, %Q) with descriptive, camel-case symbolic variable names.
2. REPLACE RUNG CONTACTS WITH BOOLEAN LOGIC:
   - Series normally-open contacts -> AND condition.
   - Parallel branches -> OR condition.
   - Normally-closed contacts -> NOT condition.
3. REPLACE COILS & LATCHES:
   - Standard output coils -> Direct assignment (OutVar := Condition;).
   - Set (S) / Reset (R) coils -> Explicit latching/unlatching logic with reset priority:
     IF ResetCondition THEN
         LatchedOutput := FALSE;
     ELSIF SetCondition THEN
         LatchedOutput := TRUE;
     END_IF;
4. REPLACE TIMERS & COUNTERS:
   - Legacy timers -> IEC TON/TOF standard function blocks or scan-counter accumulation.
5. PURE STRUCTURED TEXT: Do not output any ladder ASCII art, network labels, or rung markers.

Provide:
1. Summary of variable mapping (legacy registers -> new IEC symbols).
2. Complete, validated IEC 61131-3 Structured Text POU.
"""


def debug_st_diagnostics(
    code: str,
    diagnostics: str,
) -> str:
    """Prompt for resolving compilation errors and diagnostic warnings in Structured Text."""
    return f"""You are an IEC 61131-3 compiler specialist debugging a Horner Cscape / Straton build failure.

Current Structured Text Code:
```iecst
{code}
```

Compiler Diagnostics / Errors:
{diagnostics}

Task:
1. Pinpoint the exact line and cause of each compilation error or warning.
2. Explain the syntax or type incompatibility according to the IEC 61131-3 specification.
3. Provide the corrected, complete Structured Text code that resolves all issues.
"""


def simulate_st_logic(
    code: str,
    test_scenarios: str,
) -> str:
    """Prompt for formulating software simulation test cases for ST logic."""
    return f"""You are a PLC QA & Verification engineer creating test scenarios for Horner Cscape software simulation.

Structured Text POU Code:
```iecst
{code}
```

Target Verification Scenarios:
{test_scenarios}

Task:
1. Define the input variables and values for each simulation scan cycle.
2. Specify the expected output variable states at each step.
3. Format the test bench as a JSON dictionary ready for the `cscape_simulate_pou` tool:
   - 'code': The ST source code string.
   - 'inputs': Dictionary mapping input variable names to values (or arrays of values for per-step variation).
   - 'steps': Total number of scan cycles to execute.
"""


def register_prompts(server: Any) -> None:
    """Registers all Cscape MCP prompts on the given MCPServer instance."""
    server.prompt()(generate_iec_st_controller)
    server.prompt()(refactor_ladder_to_st)
    server.prompt()(debug_st_diagnostics)
    server.prompt()(simulate_st_logic)
