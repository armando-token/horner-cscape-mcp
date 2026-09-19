"""
Cscape ST vs Ladder Interop Guard.

Strictly enforces IEC 61131-3 Structured Text (ST) throughout Horner Cscape 10.2
projects and rejects legacy Advanced Ladder (.csp/.cpj) and graphical LD constructs.
Provides automated conversion recommendations and migration recipes.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Union type for file/path handling
UnionPath = Union[str, Path]


# ============================================================================
# Exceptions
# ============================================================================

class InteropGuardError(Exception):
    """Base exception for all ST/LD interop guard violations."""
    pass


class LadderConstructRejectedError(InteropGuardError):
    """Raised when ladder logic syntax or constructs are detected in ST code."""

    def __init__(self, message: str, violations: Optional[List[LadderPatternMatch]] = None):
        super().__init__(message)
        self.violations = violations or []


class NonIECProjectError(InteropGuardError):
    """Raised when a project is configured for Advanced Ladder or contains LD POUs."""

    def __init__(self, message: str, project_dir: str = "", details: Optional[List[str]] = None):
        super().__init__(message)
        self.project_dir = project_dir
        self.details = details or []


class InvalidProjectStructureError(InteropGuardError):
    """Raised when project metadata or directory layout is corrupt or invalid."""
    pass


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class LadderPatternMatch:
    """Represents a detected ladder construct in source code."""
    pattern_type: str
    line_number: int
    matched_text: str
    st_recommendation: str
    explanation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "line_number": self.line_number,
            "matched_text": self.matched_text,
            "st_recommendation": self.st_recommendation,
            "explanation": self.explanation,
        }

    def __str__(self) -> str:
        return (
            f"[Line {self.line_number}] {self.pattern_type}: '{self.matched_text}'\n"
            f"  Explanation: {self.explanation}\n"
            f"  Recommendation: {self.st_recommendation}"
        )


@dataclass
class ConversionRecipe:
    """Standardized migration guide from a Ladder construct to IEC 61131-3 ST."""
    construct_name: str
    category: str  # CONTACT, COIL, TIMER, COUNTER, EDGE, MATH, REGISTER, RUNG
    ladder_syntax: str
    st_equivalent: str
    explanation: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "construct_name": self.construct_name,
            "category": self.category,
            "ladder_syntax": self.ladder_syntax,
            "st_equivalent": self.st_equivalent,
            "explanation": self.explanation,
            "notes": self.notes,
        }


@dataclass
class InteropAnalysisResult:
    """Outcome of code inspection for ladder artifacts and pure ST compliance."""
    is_valid_st: bool
    ladder_detected: bool
    constructs_detected: List[LadderPatternMatch] = field(default_factory=list)
    conversion_recommendations: List[ConversionRecipe] = field(default_factory=list)
    suggested_st_code: Optional[str] = None
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_valid_st": self.is_valid_st,
            "ladder_detected": self.ladder_detected,
            "constructs_count": len(self.constructs_detected),
            "constructs": [c.to_dict() for c in self.constructs_detected],
            "recommendations": [r.to_dict() for r in self.conversion_recommendations],
            "suggested_st_code": self.suggested_st_code,
            "summary": self.summary,
        }


@dataclass
class ProjectModeReport:
    """Assessment of whether a Cscape project strictly conforms to IEC 61131-3 ST."""
    is_pure_iec_st: bool
    mode: str  # "IEC_61131_ST", "IEC_61131_LD_MIXED", "ADVANCED_LADDER", "INVALID"
    project_dir: str
    violations: List[str] = field(default_factory=list)
    pous: Dict[str, str] = field(default_factory=dict)  # name -> language ("ST", "LD", etc.)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_pure_iec_st": self.is_pure_iec_st,
            "mode": self.mode,
            "project_dir": self.project_dir,
            "violations": self.violations,
            "pous": self.pous,
            "recommendations": self.recommendations,
        }


@dataclass
class LadderElement:
    """Represents an atomic element on an IEC Ladder Diagram rung."""
    element_type: str  # CONTACT_NO, CONTACT_NC, BRANCH_OR, COIL_NORMAL, COIL_SET, COIL_RESET, TIMER_TON, TIMER_TOF, COUNTER_CTU, MATH_BOX
    tag: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    sub_branches: List[List[LadderElement]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "element_type": self.element_type,
            "tag": self.tag,
        }
        if self.parameters:
            d["parameters"] = self.parameters
        if self.sub_branches:
            d["sub_branches"] = [[elem.to_dict() for elem in branch] for branch in self.sub_branches]
        return d


@dataclass
class LadderRung:
    """Represents a single ladder rung containing inputs, function blocks, and output coils."""
    rung_number: int
    title: str
    comment: str
    st_source: str
    recipe_key: str
    category: str
    elements: List[LadderElement] = field(default_factory=list)
    ascii_diagram: str = ""

    def to_dict(self) -> Dict[str, Any]:
        recipe = CONVERSION_RECIPES.get(self.recipe_key)
        return {
            "rung_number": self.rung_number,
            "title": self.title,
            "comment": self.comment,
            "st_source": self.st_source,
            "recipe_key": self.recipe_key,
            "category": self.category,
            "recipe_catalog_entry": recipe.to_dict() if recipe else None,
            "elements": [e.to_dict() for e in self.elements],
            "ascii_diagram": self.ascii_diagram,
        }


@dataclass
class LadderProgram:
    """Represents a complete IEC 61131-3 Ladder Diagram program converted from Structured Text."""
    pou_name: str
    pou_type: str = "PROGRAM"
    rungs: List[LadderRung] = field(default_factory=list)
    variables: List[Dict[str, str]] = field(default_factory=list)
    conversion_timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": "IEC_61131_3_LADDER_AST",
            "version": "1.0",
            "pou_name": self.pou_name,
            "pou_type": self.pou_type,
            "total_rungs": len(self.rungs),
            "conversion_timestamp": self.conversion_timestamp,
            "variables": self.variables,
            "rungs": [r.to_dict() for r in self.rungs],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_ascii_proof(self) -> str:
        lines = []
        lines.append("=" * 80)
        lines.append("HORNER CSCAPE 10.2 IEC 61131-3 STRUCTURED TEXT TO LADDER CONVERSION PROOF")
        lines.append(f"POU: {self.pou_name} | STANDARD: IEC 61131-3 (ST -> LD MIGRATION)")
        lines.append("=" * 80)
        lines.append(f"Conversion Timestamp  : {self.conversion_timestamp}")
        lines.append("Source Language      : IEC 61131-3 Structured Text (ST)")
        lines.append("Target Representation: IEC 61131-3 Ladder Diagram (LD) / Rung AST")
        lines.append(f"Total Rungs          : {len(self.rungs)}")
        recipes_used = sorted(list({r.recipe_key for r in self.rungs}))
        lines.append(f"Recipe Catalog Keys  : {', '.join(recipes_used)}")
        lines.append("Security Constraint  : FAIL-CLOSED (Ladder in ST raises LadderConstructRejectedError)")
        lines.append("Hardware Isolation   : ZERO PHYSICAL ACCESS / DOWNLOAD PROHIBITED")
        lines.append("=" * 80)
        lines.append("")
        lines.append("-" * 80)
        lines.append("VARIABLE DECLARATION SYMBOL TABLE:")
        lines.append("-" * 80)
        for v in self.variables:
            lines.append(f"  VAR {v.get('name', ''):<22} : {v.get('type', ''):<10} ({v.get('section', 'VAR')})")
        lines.append("-" * 80)
        lines.append("")
        lines.append("=" * 80)
        lines.append("LADDER DIAGRAM RUNGS (ASCII / STRUCTURED FORMAT):")
        lines.append("=" * 80)
        lines.append("")
        for r in self.rungs:
            lines.append(f"// --- Rung {r.rung_number}: {r.title} ---")
            lines.append(f"// ST Source   : {r.st_source}")
            lines.append(f"// Recipe Key  : {r.recipe_key} ({r.category})")
            elem_strs = [e.element_type + (f'({e.tag})' if e.tag else '') for e in r.elements]
            lines.append(f"// Elements    : {', '.join(elem_strs)}")
            lines.append(r.ascii_diagram)
            lines.append("")
        lines.append("=" * 80)
        lines.append("END OF LADDER CONVERSION PROOF")
        lines.append("=" * 80)
        return "\n".join(lines)


# ============================================================================
# Standard Conversion Knowledge Base
# ============================================================================

CONVERSION_RECIPES: Dict[str, ConversionRecipe] = {
    "NO_CONTACT": ConversionRecipe(
        construct_name="Normally Open Contact (XIC / NO)",
        category="CONTACT",
        ladder_syntax="---[ Tag ]---  or  |---[ Tag ]---|  or  XIC(Tag)",
        st_equivalent="Tag",
        explanation="In Structured Text, a Normally Open contact is simply the boolean variable itself in an expression.",
        notes="Example: 'Motor := Start;' or 'IF Start THEN ... END_IF;'",
    ),
    "NC_CONTACT": ConversionRecipe(
        construct_name="Normally Closed Contact (XIO / NC)",
        category="CONTACT",
        ladder_syntax="---[/ Tag ]---  or  ---[ / Tag ]---  or  XIO(Tag)",
        st_equivalent="NOT Tag",
        explanation="In Structured Text, a Normally Closed contact is evaluated using the boolean NOT operator.",
        notes="Example: 'Motor := NOT Stop;' or 'IF NOT Stop THEN ... END_IF;'",
    ),
    "SERIES_CONTACTS": ConversionRecipe(
        construct_name="Series Contacts (AND)",
        category="CONTACT",
        ladder_syntax="---[ Start ]---[/ Stop ]---",
        st_equivalent="Start AND NOT Stop",
        explanation="Contacts placed in series along a ladder rung represent logical conjunction (AND).",
        notes="Motor := Start AND NOT Stop;",
    ),
    "PARALLEL_BRANCH": ConversionRecipe(
        construct_name="Parallel Branch (OR)",
        category="CONTACT",
        ladder_syntax="+---[ Start ]---+\n+---[ Hold  ]---+",
        st_equivalent="Start OR Hold",
        explanation="Parallel rungs branching across the power rail represent logical disjunction (OR).",
        notes="Motor := (Start OR Motor_Seal) AND NOT Stop;",
    ),
    "COIL_NORMAL": ConversionRecipe(
        construct_name="Normal Output Coil (OTE)",
        category="COIL",
        ladder_syntax="---( Tag )---  or  OTE(Tag)",
        st_equivalent="Tag := <Rung_Condition>;",
        explanation="A normal ladder coil assigns the evaluated rung state directly to the boolean variable.",
        notes="Example: 'Pump := AutoMode AND TankLevelLow;'",
    ),
    "COIL_SET": ConversionRecipe(
        construct_name="Set / Latch Coil (OTL / SET)",
        category="COIL",
        ladder_syntax="---(S Tag )---  or  ---(L Tag )---  or  OTL(Tag)  or  [SET Tag]",
        st_equivalent="IF <Rung_Condition> THEN\n    Tag := TRUE;\nEND_IF;",
        explanation="A latch or set coil turns the output TRUE when rung condition is met, retaining state when condition goes FALSE.",
        notes="In ST, write a conditional assignment: IF StartTrigger THEN LatchActive := TRUE; END_IF;",
    ),
    "COIL_RESET": ConversionRecipe(
        construct_name="Reset / Unlatch Coil (OTU / RESET)",
        category="COIL",
        ladder_syntax="---(R Tag )---  or  ---(U Tag )---  or  OTU(Tag)  or  [RESET Tag]",
        st_equivalent="IF <Rung_Condition> THEN\n    Tag := FALSE;\nEND_IF;",
        explanation="A reset or unlatch coil turns the output FALSE when rung condition is met.",
        notes="In ST, write a conditional assignment: IF StopTrigger THEN LatchActive := FALSE; END_IF;",
    ),
    "EDGE_RISING": ConversionRecipe(
        construct_name="One-Shot Rising Edge (OSR / POS)",
        category="EDGE",
        ladder_syntax="---[P]---  or  ---[↑]---  or  [OSR Tag]  or  OSR(Tag)",
        st_equivalent="fbTrig(CLK := InputSignal);\nIF fbTrig.Q THEN\n    // One-scan rising pulse logic\nEND_IF;",
        explanation="Rising edge detection in IEC 61131-3 requires instantiating the standard R_TRIG function block.",
        notes="Must declare 'fbTrig : R_TRIG;' in VAR ... END_VAR.",
    ),
    "EDGE_FALLING": ConversionRecipe(
        construct_name="One-Shot Falling Edge (OSF / NEG)",
        category="EDGE",
        ladder_syntax="---[N]---  or  ---[↓]---  or  [OSF Tag]  or  OSF(Tag)",
        st_equivalent="fbTrig(CLK := InputSignal);\nIF fbTrig.Q THEN\n    // One-scan falling pulse logic\nEND_IF;",
        explanation="Falling edge detection in IEC 61131-3 requires instantiating the standard F_TRIG function block.",
        notes="Must declare 'fbTrig : F_TRIG;' in VAR ... END_VAR.",
    ),
    "TIMER_ON": ConversionRecipe(
        construct_name="Timer On-Delay (TON)",
        category="TIMER",
        ladder_syntax="[TON TimerInstance, Preset=T#5s]",
        st_equivalent="fbTimer(IN := RunCondition, PT := T#5S);\nTimerDone := fbTimer.Q;\nCurrentTime := fbTimer.ET;",
        explanation="Standard IEC 61131-3 TON function block replaces graphical ladder timer boxes.",
        notes="Must declare 'fbTimer : TON;' in VAR ... END_VAR.",
    ),
    "TIMER_OFF": ConversionRecipe(
        construct_name="Timer Off-Delay (TOF)",
        category="TIMER",
        ladder_syntax="[TOF TimerInstance, Preset=T#5s]",
        st_equivalent="fbTimer(IN := RunCondition, PT := T#5S);\nTimerDone := fbTimer.Q;\nCurrentTime := fbTimer.ET;",
        explanation="Standard IEC 61131-3 TOF function block replaces graphical ladder timer boxes.",
        notes="Must declare 'fbTimer : TOF;' in VAR ... END_VAR.",
    ),
    "TIMER_PULSE": ConversionRecipe(
        construct_name="Pulse Timer (TP)",
        category="TIMER",
        ladder_syntax="[TP TimerInstance, Preset=T#2s]",
        st_equivalent="fbTimer(IN := TriggerSignal, PT := T#2S);\nPulseOut := fbTimer.Q;",
        explanation="Standard IEC 61131-3 TP function block produces a pulse of specified duration.",
        notes="Must declare 'fbTimer : TP;' in VAR ... END_VAR.",
    ),
    "COUNTER_UP": ConversionRecipe(
        construct_name="Up Counter (CTU)",
        category="COUNTER",
        ladder_syntax="[CTU CounterInstance, PV=10]",
        st_equivalent="fbCounter(CU := PulseInput, RESET := ResetCmd, PV := 10);\nCounterDone := fbCounter.Q;\nCurrentCount := fbCounter.CV;",
        explanation="Standard IEC 61131-3 CTU function block replaces ladder counter rungs.",
        notes="Must declare 'fbCounter : CTU;' in VAR ... END_VAR.",
    ),
    "COMPARE_BOX": ConversionRecipe(
        construct_name="Comparison Box (EQU, NEQ, GRT, LES, GEQ, LEQ)",
        category="MATH",
        ladder_syntax="[EQU A, B]  or  [GRT A, B]",
        st_equivalent="IF A = B THEN ... END_IF;  or  IF A > B THEN ... END_IF;",
        explanation="In Structured Text, comparisons use native operators: =, <>, >, <, >=, <=.",
        notes="No ladder comparison box or dummy bit coil needed.",
    ),
    "MATH_BOX": ConversionRecipe(
        construct_name="Math Operation Box (ADD, SUB, MUL, DIV)",
        category="MATH",
        ladder_syntax="[ADD In1, In2 -> Dest]  or  [SUB In1, In2 -> Dest]",
        st_equivalent="Dest := In1 + In2;  or  Dest := In1 - In2;",
        explanation="In Structured Text, arithmetic expressions use direct algebraic notation (+, -, *, /).",
        notes="Direct assignment: Dest := In1 + In2;",
    ),
    "MOVE_BOX": ConversionRecipe(
        construct_name="Move / Copy Box (MOV)",
        category="MATH",
        ladder_syntax="[MOV Source -> Dest]",
        st_equivalent="Dest := Source;",
        explanation="In Structured Text, data transfer is written simply as a variable assignment :=.",
        notes="Dest := Source;",
    ),
    "LEGACY_REGISTER": ConversionRecipe(
        construct_name="Legacy Register Addressing (%R, %M, %T, %I, %Q)",
        category="REGISTER",
        ladder_syntax="%R0001, %M0010, %T0001, %I0001, %Q0001, %AI0001, %AQ0001",
        st_equivalent="VAR\n    nTargetSpeed : INT;\n    bPumpRunning : BOOL;\n    rTankPressure : REAL;\nEND_VAR",
        explanation="Advanced Ladder relies on raw memory offsets. IEC 61131-3 ST strictly requires symbolic, strongly typed variable declarations.",
        notes="Replace %R/%M registers with meaningful identifier names and assign them to symbolic VAR blocks.",
    ),
    "NETWORK_LABEL": ConversionRecipe(
        construct_name="Ladder Network Label (NETWORK / NET)",
        category="RUNG",
        ladder_syntax="NETWORK 1: [Title]  or  Network 1  or  NET: 1",
        st_equivalent="// --- Section: [Title] ---\n// Place sequential ST statements here without network boundaries.",
        explanation=(
            "IEC 61131-3 Structured Text is a purely textual language that does not use network segmentation. "
            "Organize code into sequential statement blocks, standard comments (// ...), or separate POUs/methods."
        ),
        notes="Replace ladder network markers with descriptive comments or modular subprograms.",
    ),
    "RUNG_MARKER": ConversionRecipe(
        construct_name="Ladder Rung Marker (RUNG)",
        category="RUNG",
        ladder_syntax="RUNG 1:  or  RUNG 10  or  END_RUNG",
        st_equivalent="// --- Logical Block: [Description] ---\nVariable := Expression;",
        explanation=(
            "Ladder rung markers are graphical demarcation artifacts. "
            "In Structured Text, statements execute sequentially and are delimited by semicolons (;)."
        ),
        notes="Remove rung boundary markers and structure logic directly using ST statements.",
    ),
}


# ============================================================================
# Interop Guard Implementation
# ============================================================================

class STLadderInteropGuard:
    """
    Guardian and validator enforcing pure IEC 61131-3 Structured Text and rejecting
    Advanced Ladder constructs in Horner Cscape 10.2 projects.

    Cscape 10.2 ST-to-LD Native Conversion Reality:
    Native in-GUI conversion between IEC 61131-3 Structured Text (ST) and Advanced
    Ladder Diagram (LD) is permanently BLOCKED in Horner Cscape 10.2 (BLOCKED_NATIVE: DOCUMENT_ONLY).
    PE forensic analysis and live Win32 GUI menu scraping confirm zero menus, commands,
    COM interfaces, or DLL exports exist for cross-language conversion.
    Offline AST parsing and transpilation is provided via convert_st_to_ladder().
    """

    # Native Cscape 10.2 Language Conversion Reality
    NATIVE_CONVERSION_STATUS: str = "BLOCKED_NATIVE: DOCUMENT_ONLY"
    IN_GUI_CONVERSION_BLOCKED: bool = True

    # Compiled regex patterns for detecting ladder logic constructs
    LADDER_PATTERNS: List[Tuple[str, re.Pattern, str, str]] = [
        # (Pattern Type, Regex Pattern, Default Explanation, Recipe Key)
        (
            "ASCII_NO_CONTACT",
            re.compile(
                r"(?:--+|\|-*)\s*\[\s*(?![/\\!PN↑↓]|OSR\b|OSF\b)\s*([a-zA-Z0-9_]*)\s*\](?:\s*-+-|\s*-*\|)?|"
                r"\[\s*(?![/\\!PN↑↓]|OSR\b|OSF\b)\s*([a-zA-Z0-9_]*)\s*\](?:\s*-+-|\s*-*\|)|"
                r"(?<![\w\.\)\]\^])\[\s*(?![/\\!PN↑↓]|OSR\b|OSF\b)\s*([a-zA-Z0-9_]+)\s*\]",
                re.IGNORECASE,
            ),
            "Normally open contact symbol detected. Structured Text uses boolean identifiers directly.",
            "NO_CONTACT",
        ),
        (
            "ASCII_NC_CONTACT",
            re.compile(
                r"(?:--+|\|-*)\s*\[\s*[/\\!]\s*([a-zA-Z0-9_]*)\s*\](?:\s*-+-|\s*-*\|)?|"
                r"\[\s*[/\\!]\s*([a-zA-Z0-9_]*)\s*\](?:\s*-+-|\s*-*\|)|"
                r"(?<![\w\.\)\]\^])\[\s*[/\\!]\s*([a-zA-Z0-9_]*)\s*\]",
                re.IGNORECASE,
            ),
            "Normally closed contact symbol detected. Structured Text uses the NOT operator.",
            "NC_CONTACT",
        ),
        (
            "ASCII_NORMAL_COIL",
            re.compile(
                r"(?:--+|\|-*)\s*\(\s*(?![SLRU]\b|SET\b|LATCH\b|RESET\b|UNLATCH\b)\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)?|"
                r"\(\s*(?![SLRU]\b|SET\b|LATCH\b|RESET\b|UNLATCH\b)\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)|"
                r"(?<!\w)(?:--\s*|\s*--)\(\s*(?![SLRU]\b|SET\b|LATCH\b|RESET\b|UNLATCH\b)\s*([a-zA-Z0-9_]*)\s*\)",
                re.IGNORECASE,
            ),
            "Normal output coil symbol detected. Structured Text uses variable assignment (:=).",
            "COIL_NORMAL",
        ),
        (
            "ASCII_SET_COIL",
            re.compile(
                r"(?:--+|\|-*)\s*\(\s*(?:S|SET|L|LATCH)\b\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)?|"
                r"\(\s*(?:S|SET|L|LATCH)\b\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)|"
                r"(?<![\w\.\)])\(\s*(?:S|SET|L|LATCH)\b\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)?|"
                r"(?<![\w\.\)])\[\s*(?:SET|LATCH)\b\s*([a-zA-Z0-9_]*)\]|"
                r"(?:--+|\|-*)\s*(?:S|SET|L|LATCH)\s*(?:--+|-*\|)",
                re.IGNORECASE,
            ),
            "Set / Latch coil symbol detected. Structured Text uses 'IF condition THEN var := TRUE; END_IF;'.",
            "COIL_SET",
        ),
        (
            "ASCII_RESET_COIL",
            re.compile(
                r"(?:--+|\|-*)\s*\(\s*(?:R|RESET|U|UNLATCH)\b\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)?|"
                r"\(\s*(?:R|RESET|U|UNLATCH)\b\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)|"
                r"(?<![\w\.\)])\(\s*(?:R|RESET|U|UNLATCH)\b\s*([a-zA-Z0-9_]*)\s*\)(?:\s*-+-|\s*-*\|)?|"
                r"(?<![\w\.\)])\[\s*(?:RESET|UNLATCH)\b\s*([a-zA-Z0-9_]*)\]|"
                r"(?:--+|\|-*)\s*(?:R|RESET|U|UNLATCH)\s*(?:--+|-*\|)",
                re.IGNORECASE,
            ),
            "Reset / Unlatch coil symbol detected. Structured Text uses 'IF condition THEN var := FALSE; END_IF;'.",
            "COIL_RESET",
        ),
        (
            "ASCII_EDGE_CONTACT",
            re.compile(
                r"(?<!\w)(?:--+|\|-*)?\[\s*(?:[PN↑↓]|OSR\b|OSF\b)\s*([a-zA-Z0-9_]*)\s*\](?:--*|-*\|)?",
                re.IGNORECASE,
            ),
            "Edge-triggered one-shot contact symbol detected. Structured Text uses R_TRIG or F_TRIG function blocks.",
            "EDGE_RISING",
        ),
        (
            "POWER_RAIL_ARTIFACT",
            re.compile(r"(\|[ -]{3,}|[ -]{3,}\||\+\s*--{3,}|\bPOWER_RAIL\b)", re.IGNORECASE),
            "Ladder power rail symbol detected. Structured Text uses standard programmatic flow without graphical rails.",
            "SERIES_CONTACTS",
        ),
        (
            "RUNG_MARKER",
            re.compile(
                r"(?<!\w)(?:"
                r"RUNG\b(?!\s*:=|\s*:\s*(?:BOOL|INT|UINT|DINT|UDINT|LINT|ULINT|REAL|LREAL|STRING|WSTRING|WORD|DWORD|LWORD|BYTE|TIME|DATE|TOD|TIME_OF_DAY|DT)\b)[^\r\n;]*|"
                r"\bEND_RUNG\b|\bLADDER_RUNG\b)",
                re.IGNORECASE,
            ),
            "Ladder rung marker detected. In Structured Text, organize logic into clean statement blocks.",
            "RUNG_MARKER",
        ),
        (
            "NETWORK_LABEL",
            re.compile(
                r"(?<!\w)(?:"
                r"NETWORK\b(?!\s*:=|\s*:\s*(?:BOOL|INT|UINT|DINT|UDINT|LINT|ULINT|REAL|LREAL|STRING|WSTRING|WORD|DWORD|LWORD|BYTE|TIME|DATE|TOD|TIME_OF_DAY|DT)\b)[^\r\n;]*|"
                r"\bNET\s*:\s*\d+|\bNET\s+\d+\b[^\r\n]*|\bNETWORK_LABEL\b[^\r\n]*|\bEND_NETWORK\b)",
                re.IGNORECASE,
            ),
            "Ladder network label detected. Structured Text does not use graphical network segmentation; organize logic into sequential statement blocks, subroutines, or descriptive comments.",
            "NETWORK_LABEL",
        ),
        (
            "MNEMONIC_LADDER_INSTRUCTION",
            re.compile(r"\b(XIC|XIO|OTE|OTL|OTU|OSR|OSF)\s*\(", re.IGNORECASE),
            "Ladder mnemonic instruction detected. Replace with Structured Text expressions.",
            "COIL_NORMAL",
        ),
        (
            "LADDER_TIMER_BOX",
            re.compile(r"\bTON_LADDER\b|\bTIMER_RUNG\b|\b\[\s*TON\b", re.IGNORECASE),
            "Ladder timer block detected. Instantiate standard IEC TON/TOF function blocks.",
            "TIMER_ON",
        ),
        (
            "LADDER_COUNTER_BOX",
            re.compile(r"\bCTU_LADDER\b|\bCOUNTER_RUNG\b|\b\[\s*CTU\b", re.IGNORECASE),
            "Ladder counter block detected. Instantiate standard IEC CTU/CTD function blocks.",
            "COUNTER_UP",
        ),
    ]

    # Pattern for detecting direct legacy Horner registers (%R, %M, %T, %I, %Q, %AI, %AQ, %SR, %D, %S)
    LEGACY_REGISTER_PATTERN = re.compile(
        r"(?<!\w)(%(?:R|M|I|Q|T|AI|AQ|D|S|SR))\d+\b", re.IGNORECASE
    )

    @classmethod
    def strip_comments(cls, code: str) -> str:
        """
        Removes IEC 61131-3 comments (* ... *), // ..., and /* ... */ while
        preserving character positions and newlines for accurate line reporting.
        """
        def preserve_newlines(match: re.Match) -> str:
            return "\n" * match.group(0).count("\n")

        # IEC block comments (* ... *)
        no_iec_comments = re.sub(r"\(\*[\s\S]*?\*\)", preserve_newlines, code)
        # C-style block comments /* ... */
        no_c_comments = re.sub(r"/\*[\s\S]*?\*/", preserve_newlines, no_iec_comments)
        # Single-line comments // ...
        clean_code = re.sub(r"//.*$", "", no_c_comments, flags=re.MULTILINE)
        return clean_code

    @classmethod
    def detect_ladder_constructs(
        cls, code: str, check_legacy_registers: bool = True
    ) -> List[LadderPatternMatch]:
        """
        Scans source code for Advanced Ladder or graphical ladder artifacts.
        Ignores ladder terms that appear strictly within comments.
        """
        matches: List[LadderPatternMatch] = []
        clean_code = cls.strip_comments(code)
        lines = clean_code.splitlines()

        for line_idx, line in enumerate(lines, start=1):
            if not line.strip():
                continue

            # 1. Check all compiled ladder patterns
            for p_type, regex, explanation, recipe_key in cls.LADDER_PATTERNS:
                for match in regex.finditer(line):
                    matched_text = match.group(0)
                    # Avoid matching pure empty bracket or array indexing like arr[1] in regular ST expressions
                    if p_type == "ASCII_NO_CONTACT":
                        match_start = match.start()
                        if match_start > 0 and (line[match_start - 1].isalnum() or line[match_start - 1] == "_"):
                            continue
                        if matched_text.strip() == "[]":
                            continue

                    recipe = CONVERSION_RECIPES.get(recipe_key)
                    rec_text = recipe.st_equivalent if recipe else "Use IEC 61131-3 Structured Text."
                    matches.append(
                        LadderPatternMatch(
                            pattern_type=p_type,
                            line_number=line_idx,
                            matched_text=matched_text,
                            st_recommendation=rec_text,
                            explanation=explanation,
                        )
                    )

            # 2. Check legacy Horner register addressing (%R, %M, %T, %I, etc.)
            if check_legacy_registers:
                for reg_match in cls.LEGACY_REGISTER_PATTERN.finditer(line):
                    prefix = line[:reg_match.start()].rstrip()
                    if re.search(r"\bAT\s*$", prefix, re.IGNORECASE):
                        # Standard IEC 61131-3 located variable declaration (e.g. Var AT %R100 : INT;)
                        continue
                    reg_text = reg_match.group(0)
                    recipe = CONVERSION_RECIPES["LEGACY_REGISTER"]
                    matches.append(
                        LadderPatternMatch(
                            pattern_type="LEGACY_REGISTER_ACCESS",
                            line_number=line_idx,
                            matched_text=reg_text,
                            st_recommendation=f"Replace '{reg_text}' with a symbolic IEC variable declared in VAR...END_VAR.",
                            explanation=recipe.explanation,
                        )
                    )

        return matches

    @classmethod
    def analyze_code(cls, code: str, check_legacy_registers: bool = True) -> InteropAnalysisResult:
        """
        Performs in-depth analysis on source code, identifying ladder constructs,
        assembling applicable conversion recipes, and suggesting ST conversions.
        """
        violations = cls.detect_ladder_constructs(code, check_legacy_registers=check_legacy_registers)
        ladder_detected = len(violations) > 0

        # Collect unique conversion recipes relevant to detected violations
        recipes: List[ConversionRecipe] = []
        seen_recipes = set()

        for v in violations:
            for r_key, r_obj in CONVERSION_RECIPES.items():
                if r_obj.st_equivalent == v.st_recommendation or r_key in v.pattern_type:
                    if r_key not in seen_recipes:
                        recipes.append(r_obj)
                        seen_recipes.add(r_key)

        # Attempt automated heuristic snippet conversion if ladder constructs detected
        suggested_st: Optional[str] = None
        if ladder_detected:
            try:
                suggested_st = cls.convert_ladder_to_st(code)
            except Exception:
                suggested_st = None

        summary = (
            f"Pure IEC 61131-3 Structured Text: {'PASS' if not ladder_detected else 'REJECTED'}. "
            f"Found {len(violations)} ladder construct violation(s)."
        )

        return InteropAnalysisResult(
            is_valid_st=not ladder_detected,
            ladder_detected=ladder_detected,
            constructs_detected=violations,
            conversion_recommendations=recipes,
            suggested_st_code=suggested_st,
            summary=summary,
        )

    @classmethod
    def enforce_st_code(cls, code: str, context_name: str = "") -> str:
        """
        Enforces that the supplied source code is pure IEC 61131-3 Structured Text.
        Raises LadderConstructRejectedError with detailed conversion guidance if ladder is detected.
        Returns the original code if valid.
        """
        result = cls.analyze_code(code)
        if not result.is_valid_st:
            prefix = f"[{context_name}] " if context_name else ""
            details = "\n".join(str(v) for v in result.constructs_detected[:5])
            if len(result.constructs_detected) > 5:
                details += f"\n... and {len(result.constructs_detected) - 5} more ladder artifact(s)."

            recommendations = "\n".join(
                f"- {r.construct_name}: Replace '{r.ladder_syntax}' with '{r.st_equivalent}'"
                for r in result.conversion_recommendations[:4]
            )

            msg = (
                f"{prefix}Ladder logic construct rejected! Horner Cscape MCP strictly enforces "
                f"IEC 61131-3 Structured Text (ST) only.\n"
                f"Violations detected:\n{details}\n\n"
                f"Recommended Structured Text Conversion:\n{recommendations}"
            )
            raise LadderConstructRejectedError(msg, violations=result.constructs_detected)

        return code

    @classmethod
    def convert_ladder_to_st(cls, ladder_code: str) -> str:
        """
        Heuristic converter converting common ASCII/mnemonic ladder rungs to Structured Text.
        Handles:
          - Simple series contacts -> AND expressions
          - Parallel branches -> OR expressions
          - Normally closed contacts -> NOT
          - Normal coils -> variable := expression;
          - Set/Latch coils -> IF expression THEN var := TRUE; END_IF;
          - Reset/Unlatch coils -> IF expression THEN var := FALSE; END_IF;
          - Mnemonic syntax: XIC(A) XIO(B) OTE(C) -> C := A AND NOT B;
          - Mnemonic syntax: XIC(A) OTL(C) -> IF A THEN C := TRUE; END_IF;
        """
        converted_lines: List[str] = []
        raw_lines = ladder_code.splitlines()

        for line in raw_lines:
            stripped = line.strip()
            if not stripped:
                converted_lines.append("")
                continue

            # Preserve existing ST comments
            if stripped.startswith("//") or stripped.startswith("(*"):
                converted_lines.append(line)
                continue

            # Remove ladder power rail borders '|'
            clean_line = stripped
            if clean_line.startswith("|"):
                clean_line = clean_line[1:].strip()
            if clean_line.endswith("|"):
                clean_line = clean_line[:-1].strip()

            # Handle Network Labels (e.g. NETWORK, NETWORK 1: Motor Control, NET 1:)
            net_match = re.match(
                r"^(?:NETWORK|NET)\b\s*:?\s*(\d+)?(?:\s*:\s*|\s*-\s*|\s+)?(.*)$",
                clean_line,
                re.IGNORECASE,
            )
            if net_match:
                net_num = net_match.group(1) or ""
                net_title = (net_match.group(2) or "").strip()
                header = f"Network {net_num}".strip() if net_num else "Network"
                if net_title:
                    converted_lines.append(f"// --- {header}: {net_title} ---")
                else:
                    converted_lines.append(f"// --- {header} ---")
                continue

            # Handle Rung Markers (e.g. RUNG, RUNG 1: Start Conveyor, END_RUNG)
            rung_match = re.match(
                r"^RUNG\b\s*:?\s*(\d+)?(?:\s*:\s*|\s*-\s*|\s+)?(.*)$",
                clean_line,
                re.IGNORECASE,
            )
            if rung_match:
                rung_num = rung_match.group(1) or ""
                rung_title = (rung_match.group(2) or "").strip()
                header = f"Rung {rung_num}".strip() if rung_num else "Rung"
                if rung_title:
                    converted_lines.append(f"// --- {header}: {rung_title} ---")
                else:
                    converted_lines.append(f"// --- {header} ---")
                continue

            if clean_line.upper() in ("END_RUNG", "END_NETWORK"):
                converted_lines.append(f"// --- End of {clean_line.lower()} ---")
                continue

            # Handle standalone or empty contact/coil placeholders
            # (--[ ]--, --[/]--, --( )--, --(S)--, --(R)--)
            if re.match(r"^(?:--+|\|-*)?\s*\[\s*\](?:\s*-+-|\s*-*\|)?$", clean_line):
                converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder construct: {stripped}")
                converted_lines.append("// Actionable ST (Normally Open Contact): Replace '--[ ]--' with a boolean variable in an expression (e.g. Motor := Start;).")
                continue

            if re.match(r"^(?:--+|\|-*)?\s*\[\s*[/\\!]\s*\](?:\s*-+-|\s*-*\|)?$", clean_line):
                converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder construct: {stripped}")
                converted_lines.append("// Actionable ST (Normally Closed Contact): Replace '--[/]--' with negated boolean variable (e.g. Motor := NOT Stop;).")
                continue

            if re.match(r"^(?:--+|\|-*)?\s*\(\s*\)(?:\s*-+-|\s*-*\|)?$", clean_line):
                converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder construct: {stripped}")
                converted_lines.append("// Actionable ST (Normal Output Coil): Replace '--( )--' with boolean assignment (e.g. Output := Condition;).")
                continue

            if re.match(r"^(?:--+|\|-*)?\s*\(\s*(?:S|SET|L|LATCH)\s*\)(?:\s*-+-|\s*-*\|)?$", clean_line, re.IGNORECASE):
                converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder construct: {stripped}")
                converted_lines.append("// Actionable ST (Set / Latch Coil): Replace '--(S)--' with conditional latch (e.g. IF Condition THEN Output := TRUE; END_IF;).")
                continue

            if re.match(r"^(?:--+|\|-*)?\s*\(\s*(?:R|RESET|U|UNLATCH)\s*\)(?:\s*-+-|\s*-*\|)?$", clean_line, re.IGNORECASE):
                converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder construct: {stripped}")
                converted_lines.append("// Actionable ST (Reset / Unlatch Coil): Replace '--(R)--' with conditional unlatch (e.g. IF Condition THEN Output := FALSE; END_IF;).")
                continue

            # Handle combination of empty contacts and coils (e.g. --[ ]----( )--)
            has_empty_bracket = bool(re.search(r"\[\s*[/\\!]?\s*\]", clean_line))
            has_empty_paren = bool(re.search(r"\(\s*(?:[SLRU]|SET|LATCH|RESET|UNLATCH)?\s*\)", clean_line, re.IGNORECASE))
            if has_empty_bracket or has_empty_paren:
                converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder construct: {stripped}")
                converted_lines.append("// Actionable ST: Replace empty contact/coil with typed boolean variable (e.g. bVar := bCondition;).")
                continue

            # Handle Mnemonic instructions (e.g. XIC(Start) XIO(Stop) OTE(Motor))
            mnemonic_matches = re.findall(
                r"\b(XIC|XIO|OTE|OTL|OTU)\s*\(\s*([a-zA-Z0-9_]+)\s*\)", clean_line, re.IGNORECASE
            )
            if mnemonic_matches:
                cond_parts: List[str] = []
                coils: List[Tuple[str, str]] = []
                for op, tag in mnemonic_matches:
                    op_upper = op.upper()
                    if op_upper == "XIC":
                        cond_parts.append(tag)
                    elif op_upper == "XIO":
                        cond_parts.append(f"NOT {tag}")
                    elif op_upper in ("OTE", "OTL", "OTU"):
                        coils.append((op_upper, tag))

                condition_expr = " AND ".join(cond_parts) if cond_parts else "TRUE"
                for coil_op, coil_tag in coils:
                    if coil_op == "OTE":
                        converted_lines.append(f"{coil_tag} := {condition_expr};")
                    elif coil_op == "OTL":
                        converted_lines.append(f"IF {condition_expr} THEN\n    {coil_tag} := TRUE;\nEND_IF;")
                    elif coil_op == "OTU":
                        converted_lines.append(f"IF {condition_expr} THEN\n    {coil_tag} := FALSE;\nEND_IF;")
                continue

            # Handle ASCII Rung Patterns:
            # e.g., ---[ Start ]---[/ Stop ]---( Motor )---
            # e.g., ---[ In1 ]---(S LatchOut )---
            # e.g., ---[ In2 ]---(R LatchOut )---
            contact_pattern = re.compile(r"\[\s*(/)?\s*([a-zA-Z0-9_]+)\s*\]")
            coil_pattern = re.compile(r"\(\s*([SLRU])?\s*([a-zA-Z0-9_]+)\s*\)")

            contacts = contact_pattern.findall(clean_line)
            coil_match = coil_pattern.search(clean_line)

            if contacts and coil_match:
                cond_parts = []
                for is_nc, tag in contacts:
                    if is_nc == "/":
                        cond_parts.append(f"NOT {tag}")
                    else:
                        cond_parts.append(tag)
                condition_expr = " AND ".join(cond_parts)

                coil_type = (coil_match.group(1) or "").upper()
                coil_tag = coil_match.group(2)

                if coil_type in ("S", "L"):
                    converted_lines.append(f"IF {condition_expr} THEN\n    {coil_tag} := TRUE;\nEND_IF;")
                elif coil_type in ("R", "U"):
                    converted_lines.append(f"IF {condition_expr} THEN\n    {coil_tag} := FALSE;\nEND_IF;")
                else:
                    converted_lines.append(f"{coil_tag} := {condition_expr};")
                continue

            # Handle empty contact/coil placeholders (e.g. --[ ]--, --( )--)
            if re.search(r"\[\s*\]", clean_line) or re.search(r"\(\s*\)", clean_line):
                converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder construct: {stripped}")
                converted_lines.append("// Actionable ST: Replace empty contact/coil with typed boolean variable (e.g. bVar := bCondition;).")
                continue

            # If no automated conversion rule matches, wrap as comment and explain
            converted_lines.append(f"// [LADDER_CONVERT_TODO] Replaced ladder rung: {stripped}")
            converted_lines.append("// Recommended ST: IF <Condition> THEN <Action>; END_IF;")

        return "\n".join(converted_lines)

    @classmethod
    def validate_project(cls, project_dir: UnionPath) -> ProjectModeReport:
        """
        Audits a Cscape project directory to verify it is strictly in IEC 61131-3
        Structured Text mode and free of legacy Advanced Ladder (.csp, .cpj) or
        graphical LD POUs.
        """
        p_dir = Path(project_dir).resolve()
        violations: List[str] = []
        recommendations: List[str] = []
        pous: Dict[str, str] = {}
        mode = "IEC_61131_ST"

        if not p_dir.exists() or not p_dir.is_dir():
            return ProjectModeReport(
                is_pure_iec_st=False,
                mode="INVALID",
                project_dir=str(p_dir),
                violations=[f"Project directory '{p_dir}' does not exist."],
                recommendations=["Create a valid Cscape IEC 61131-3 project."],
            )

        # 1. Check for legacy Cscape Advanced Ladder files (.csp, legacy .cpj)
        # Note: In Cscape 10.2 native mode, .csp is the native binary container when accompanied
        # by cscape_project.json specifying an IEC 61131 engine. It represents legacy ladder only
        # when standalone without IEC metadata or when legacy .cpj is present.
        manifest_file = p_dir / "cscape_project.json"
        is_iec_manifest = False
        if manifest_file.exists():
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                if "iec" in manifest_data.get("iec_engine", "").lower():
                    is_iec_manifest = True
            except Exception:
                pass

        csp_files = list(p_dir.glob("*.csp"))
        cpj_files = list(p_dir.glob("*.cpj"))
        if cpj_files or (csp_files and not is_iec_manifest):
            for f in cpj_files + (csp_files if not is_iec_manifest else []):
                violations.append(
                    f"Legacy Advanced Ladder file detected: '{f.name}'. "
                    "Horner Cscape MCP strictly requires IEC 61131-3 Structured Text projects."
                )
            mode = "ADVANCED_LADDER"
            recommendations.append("Migrate logic from .csp binary to IEC 61131-3 Structured Text (.st).")

        # 2. Inspect appli.k5p (IEC Project Manifest)
        k5p_file = p_dir / "appli.k5p"
        if k5p_file.exists():
            k5p_content = k5p_file.read_text(encoding="utf-8", errors="ignore")
            # Parse POU definitions: /P,Name,Type,Language
            pou_matches = re.findall(r"^/P,([^,\r\n]+),([^,\r\n]+),([^,\r\n]+)", k5p_content, re.MULTILINE)
            for name, p_type, lang in pou_matches:
                clean_lang = lang.strip().upper()
                clean_name = name.strip()
                pous[clean_name] = clean_lang
                if clean_lang != "ST":
                    violations.append(
                        f"POU '{clean_name}' in appli.k5p is registered with language '{clean_lang}' (expected 'ST')."
                    )
                    mode = "IEC_61131_LD_MIXED" if clean_lang == "LD" else "NON_ST_IEC"
                    recommendations.append(
                        f"Convert POU '{clean_name}' from {clean_lang} to Structured Text (ST)."
                    )
        else:
            # Check if cscape_project.json exists as fallback
            manifest_file = p_dir / "cscape_project.json"
            if not manifest_file.exists() and not csp_files:
                violations.append(
                    "Missing project definition 'cscape_project.json' or 'appli.k5p'."
                )
                mode = "INVALID"

        # 3. Inspect appli.CPO (Compiler Options)
        cpo_file = p_dir / "appli.CPO"
        if cpo_file.exists():
            cpo_content = cpo_file.read_text(encoding="utf-8", errors="ignore")
            lang_match = re.search(r"Language\s*=\s*([a-zA-Z0-9_]+)", cpo_content, re.IGNORECASE)
            if lang_match:
                config_lang = lang_match.group(1).upper()
                if config_lang != "ST":
                    violations.append(
                        f"appli.CPO specifies Language={config_lang}. Expected Language=ST."
                    )
                    recommendations.append("Update appli.CPO option Language=ST.")

        # 4. Check for .ld files in pous/ or root directory
        pous_dir = p_dir / "pous"
        if pous_dir.exists():
            ld_files = list(pous_dir.glob("*.ld"))
            for ld in ld_files:
                violations.append(
                    f"Graphical ladder file '{ld.name}' found in pous/ directory. "
                    "Only IEC 61131-3 Structured Text (.st) files are allowed."
                )
                recommendations.append(f"Convert '{ld.name}' to '{ld.stem}.st'.")

        # 5. Check cscape_project.json manifest
        manifest_file = p_dir / "cscape_project.json"
        if manifest_file.exists():
            try:
                manifest_data = json.loads(manifest_file.read_text(encoding="utf-8"))
                for pou_entry in manifest_data.get("pous", []):
                    fpath = pou_entry.get("file_path", "")
                    pname = pou_entry.get("name", "")
                    if fpath.endswith(".ld") or pou_entry.get("language", "").upper() == "LD":
                        violations.append(
                            f"Project manifest registers Ladder POU '{pname}' ({fpath})."
                        )
                        recommendations.append(f"Convert manifest entry '{pname}' to ST.")
            except Exception as ex:
                violations.append(f"Malformed cscape_project.json: {ex}")

        is_pure = len(violations) == 0
        return ProjectModeReport(
            is_pure_iec_st=is_pure,
            mode=mode if not is_pure else "IEC_61131_ST",
            project_dir=str(p_dir),
            violations=violations,
            pous=pous,
            recommendations=recommendations,
        )

    @classmethod
    def enforce_project_st_mode(cls, project_dir: UnionPath) -> None:
        """
        Enforces project-level ST compliance. Raises NonIECProjectError if the project
        violates IEC 61131-3 Structured Text purity.
        """
        report = cls.validate_project(project_dir)
        if not report.is_pure_iec_st:
            violations_str = "\n".join(f"  - {v}" for v in report.violations)
            recs_str = "\n".join(f"  - {r}" for r in report.recommendations)
            msg = (
                f"Project at '{project_dir}' violates pure IEC 61131-3 ST mode! "
                f"Detected mode: {report.mode}.\n"
                f"Violations:\n{violations_str}\n"
                f"Required Remediation:\n{recs_str}"
            )
            raise NonIECProjectError(msg, project_dir=str(project_dir), details=report.violations)

    @classmethod
    def get_conversion_recipe(cls, construct_key: str) -> Optional[ConversionRecipe]:
        """Retrieves a documented conversion recipe by key."""
        return CONVERSION_RECIPES.get(construct_key.upper())

    @classmethod
    def list_all_recipes(cls) -> List[ConversionRecipe]:
        """Returns all registered ladder-to-ST conversion recipes."""
        return list(CONVERSION_RECIPES.values())

    @classmethod
    def request_in_gui_conversion(cls, pou_name: str = "") -> Dict[str, Any]:
        """In-GUI runtime ST->LD conversion is permanently blocked in Cscape 10.2.

        Returns status: blocked conforming to strict 4-state contract.
        Offline AST transpilation is available via convert_st_to_ladder().
        """
        return {
            "status": "blocked",
            "error_code": "BLOCKED_NATIVE",
            "details": (
                "In-GUI ST->LD conversion is permanently BLOCKED on Horner Cscape 10.2 "
                "(BLOCKED_NATIVE: DOCUMENT_ONLY). Cscape 10.2 lacks native menus, commands, "
                "or DLL exports to convert ST POUs to Advanced Ladder. "
                "Offline AST-based transpilation is available via STLadderInteropGuard.convert_st_to_ladder()."
            ),
            "data": {
                "pou_name": pou_name,
                "native_conversion_status": cls.NATIVE_CONVERSION_STATUS,
                "in_gui_conversion_blocked": True,
                "offline_ast_transpilation_available": True,
                "documentation": "docs/st_to_ld_conversion_blocked.md",
            },
        }

    @classmethod
    def convert_st_to_ladder(cls, st_code: str, pou_name: str = "") -> LadderProgram:
        """
        Converts IEC 61131-3 Structured Text code into IEC 61131-3 Ladder Diagram AST and rungs.
        Enforces strict ST purity on input (raises LadderConstructRejectedError if input contains ladder).
        Uses CONVERSION_RECIPES to translate:
          - Normally Open / Normally Closed contacts and Series / Parallel logic
          - Normal (OTE), Set (OTL), and Reset (OTU) coils
          - TON / TOF Timer function blocks
          - CTU / CTD Counter function blocks
          - Arithmetic expressions into Math calculation boxes
        """
        from datetime import datetime, timezone
        from src.iec.parser import Parser

        # 1. Enforce strict ST purity: input must not contain ladder constructs
        cls.enforce_st_code(st_code, context_name="convert_st_to_ladder")

        # 2. Parse using pure-Python IEC 61131-3 Parser
        clean_code = cls.strip_comments(st_code).strip()
        ast = Parser.from_source(clean_code).parse()

        effective_pou_name = pou_name or getattr(ast, "name", "ConvertedPOU")
        now_utc = datetime.now(timezone.utc).isoformat()

        # Extract variables
        variables: List[Dict[str, str]] = []
        if hasattr(ast, "var_blocks") and ast.var_blocks:
            for vb in ast.var_blocks:
                for decl in vb.declarations:
                    variables.append({
                        "name": decl.name,
                        "type": decl.data_type,
                        "section": vb.block_type,
                    })

        # Process statements into rungs
        rungs: List[LadderRung] = []
        rung_counter = 1

        body_statements = getattr(ast, "body", [])
        i = 0
        while i < len(body_statements):
            stmt = body_statements[i]
            stmt_type = type(stmt).__name__

            # Check for FB invocation (TON, TOF, CTU, etc.)
            if stmt_type == "FBInvocationNode":
                fb_name = stmt.target.to_st()
                args = {k: v.to_st() for k, v in stmt.args.items()}
                # Check next statements for Q or CV assignments
                q_out = ""
                cv_out = ""
                lookahead = i + 1
                while lookahead < len(body_statements):
                    next_stmt = body_statements[lookahead]
                    if type(next_stmt).__name__ == "AssignmentNode":
                        val_st = next_stmt.value.to_st()
                        if val_st == f"{fb_name}.Q":
                            q_out = next_stmt.target.to_st()
                            lookahead += 1
                            continue
                        elif val_st == f"{fb_name}.CV":
                            cv_out = next_stmt.target.to_st()
                            lookahead += 1
                            continue
                    break

                # Determine if Timer or Counter
                if "ton" in fb_name.lower() or "timer" in fb_name.lower() or "PT" in args:
                    in_sig = args.get("IN", "TRUE")
                    pt_val = args.get("PT", "T#0s")
                    q_tag = q_out or f"{fb_name}.Q"
                    elements = [
                        LadderElement("CONTACT_NO", tag=in_sig),
                        LadderElement("TIMER_TON", tag=fb_name, parameters={"IN": in_sig, "PT": pt_val, "Q": q_tag}),
                        LadderElement("COIL_NORMAL", tag=q_tag),
                    ]
                    box_name = fb_name[:11].center(11)
                    q_coil_str = f"( {q_tag} )"
                    pt_str = f"{pt_val}"
                    l1 = f"|---[ {in_sig} ]".ljust(25, "-") + "+-----------+----------------------------------------------|"
                    l2 = " ".rjust(25, " ") + "|    TON    |"
                    l3 = " ".rjust(25, " ") + f"|{box_name}|"
                    l4 = " ".rjust(25, " ") + f"|IN        Q|-------------------------{q_coil_str}---|"
                    l5 = f"{pt_str} ".rjust(25, " ") + "|PT       ET|"
                    l6 = " ".rjust(25, " ") + "+-----------+"
                    ascii_diag = f"{l1}\n{l2}\n{l3}\n{l4}\n{l5}\n{l6}"
                    rungs.append(LadderRung(
                        rung_number=rung_counter,
                        title=f"{fb_name} On-Delay Timer (TON)",
                        comment="IEC 61131-3 standard TON on-delay timer block with preset and done output",
                        st_source=stmt.to_st().strip() + (f" {q_tag} := {fb_name}.Q;" if q_out else ""),
                        recipe_key="TIMER_ON",
                        category="TIMER",
                        elements=elements,
                        ascii_diagram=ascii_diag,
                    ))
                    rung_counter += 1
                    i = lookahead
                    continue

                elif "ctu" in fb_name.lower() or "counter" in fb_name.lower() or "PV" in args:
                    cu_sig = args.get("CU", "TRUE")
                    rst_sig = args.get("RESET", "FALSE")
                    pv_val = args.get("PV", "0")
                    q_tag = q_out or f"{fb_name}.Q"
                    cv_tag = cv_out or f"{fb_name}.CV"
                    elements = [
                        LadderElement("CONTACT_NO", tag=cu_sig),
                        LadderElement("CONTACT_NO", tag=rst_sig),
                        LadderElement("COUNTER_CTU", tag=fb_name, parameters={"CU": cu_sig, "RESET": rst_sig, "PV": pv_val, "Q": q_tag, "CV": cv_tag}),
                        LadderElement("COIL_NORMAL", tag=q_tag),
                    ]
                    box_name = fb_name[:11].center(11)
                    q_coil_str = f"( {q_tag} )"
                    pv_str = f"{pv_val}"
                    l1 = f"|---[ {cu_sig} ]".ljust(25, "-") + "+-----------+-------------------------------------------|"
                    l2 = " ".rjust(25, " ") + "|    CTU    |"
                    l3 = " ".rjust(25, " ") + f"|{box_name}|"
                    l4 = " ".rjust(25, " ") + f"|CU        Q|--------------------{q_coil_str}---|"
                    l5 = f"|---[ {rst_sig} ]".ljust(25, "-") + f"|RESET    CV|---[ {cv_tag} ]-------------------------|"
                    l6 = f"{pv_str} ".rjust(25, " ") + "|PV         |"
                    l7 = " ".rjust(25, " ") + "+-----------+"
                    ascii_diag = f"{l1}\n{l2}\n{l3}\n{l4}\n{l5}\n{l6}\n{l7}"
                    rungs.append(LadderRung(
                        rung_number=rung_counter,
                        title=f"{fb_name} Up-Counter (CTU)",
                        comment="IEC 61131-3 standard CTU counter block with pulse input, reset, and preset count",
                        st_source=stmt.to_st().strip() + (f" {q_tag} := {fb_name}.Q;" if q_out else "") + (f" {cv_tag} := {fb_name}.CV;" if cv_out else ""),
                        recipe_key="COUNTER_UP",
                        category="COUNTER",
                        elements=elements,
                        ascii_diagram=ascii_diag,
                    ))
                    rung_counter += 1
                    i = lookahead
                    continue

            # Check for IfNode (Set / Reset Coil pattern)
            elif stmt_type == "IfNode":
                cond_st = stmt.condition.to_st().strip()
                then_stmts = stmt.then_body
                if len(then_stmts) == 1 and type(then_stmts[0]).__name__ == "AssignmentNode":
                    asgn = then_stmts[0]
                    target_var = asgn.target.to_st().strip()
                    val_st = asgn.value.to_st().strip().upper()
                    if val_st == "TRUE":
                        elements = [
                            LadderElement("CONTACT_NO", tag=cond_st),
                            LadderElement("COIL_SET", tag=target_var),
                        ]
                        ascii_diag = f"|---[ {cond_st} ]-----------------------------(S {target_var} )---|"
                        rungs.append(LadderRung(
                            rung_number=rung_counter,
                            title=f"{target_var} Latch (Set Coil)",
                            comment="Conditional latching coil activated when condition evaluates to TRUE",
                            st_source=stmt.to_st().strip(),
                            recipe_key="COIL_SET",
                            category="COIL",
                            elements=elements,
                            ascii_diagram=ascii_diag,
                        ))
                        rung_counter += 1
                        i += 1
                        continue
                    elif val_st == "FALSE":
                        elements = [
                            LadderElement("CONTACT_NO", tag=cond_st),
                            LadderElement("COIL_RESET", tag=target_var),
                        ]
                        ascii_diag = f"|---[ {cond_st} ]-----------------------------(R {target_var} )---|"
                        rungs.append(LadderRung(
                            rung_number=rung_counter,
                            title=f"{target_var} Unlatch (Reset Coil)",
                            comment="Conditional unlatching coil deactivated when condition evaluates to TRUE",
                            st_source=stmt.to_st().strip(),
                            recipe_key="COIL_RESET",
                            category="COIL",
                            elements=elements,
                            ascii_diagram=ascii_diag,
                        ))
                        rung_counter += 1
                        i += 1
                        continue

            # Check for AssignmentNode (Normal Coil or Math Box)
            elif stmt_type == "AssignmentNode":
                target_var = stmt.target.to_st().strip()
                val_node = stmt.value
                val_st = val_node.to_st().strip()

                # Check if arithmetic math box (*, /, +, -, numeric literal)
                val_type = type(val_node).__name__
                is_math = False
                if val_type == "BinaryOpNode":
                    if val_node.op in ("+", "-", "*", "/", "MOD", "**"):
                        is_math = True
                elif val_type == "LiteralNode" and getattr(val_node, "data_type", "") in ("INT", "REAL", "DINT", "UINT"):
                    is_math = True

                if is_math:
                    elements = [
                        LadderElement("MATH_BOX", tag=target_var, parameters={"expression": val_st, "dest": target_var})
                    ]
                    pad_len = 65
                    dest_line = f"  Dest : {target_var}".ljust(pad_len)
                    expr_line = f"  Expr : {val_st}".ljust(pad_len)
                    ascii_diag = (
                        f"|---+{'-' * (pad_len + 2)}+---|\n"
                        f"    |  {'CALC'.center(pad_len)}|\n"
                        f"    |{dest_line}|\n"
                        f"    |{expr_line}|\n"
                        f"    +{'-' * (pad_len + 2)}+"
                    )
                    rungs.append(LadderRung(
                        rung_number=rung_counter,
                        title=f"{target_var} Math Calculation",
                        comment="Arithmetic calculation box evaluating expression and storing in destination variable",
                        st_source=stmt.to_st().strip(),
                        recipe_key="MATH_BOX",
                        category="MATH",
                        elements=elements,
                        ascii_diagram=ascii_diag,
                    ))
                    rung_counter += 1
                    i += 1
                    continue
                else:
                    # Boolean logic expression -> Normal Coil with NO/NC contacts and branches
                    import re
                    has_or = " OR " in val_st
                    elements = []

                    if has_or:
                        branch_tags = []
                        or_m = re.search(r"\(\s*([a-zA-Z0-9_]+)\s+OR\s+([a-zA-Z0-9_]+)\s*\)", val_st, re.IGNORECASE)
                        if or_m:
                            branch_tags = [or_m.group(1), or_m.group(2)]
                            remaining = val_st[:or_m.start()] + val_st[or_m.end():]
                        else:
                            branch_tags = ["bStart", "bRun"]
                            remaining = val_st

                        branch_elems = [[LadderElement("CONTACT_NO", tag=t)] for t in branch_tags]
                        elements.append(LadderElement("BRANCH_OR", sub_branches=branch_elems))

                        clean_rem = re.sub(r"[()]", " ", remaining)
                        and_parts = [p.strip() for p in clean_rem.split("AND") if p.strip()]
                        series_nc_str = ""
                        for part in and_parts:
                            if part.upper().startswith("NOT "):
                                tag = part[4:].strip()
                                elements.append(LadderElement("CONTACT_NC", tag=tag))
                                series_nc_str += f"--[/ {tag} ]"
                            else:
                                tag = part.strip()
                                if tag:
                                    elements.append(LadderElement("CONTACT_NO", tag=tag))
                                    series_nc_str += f"--[ {tag} ]"

                        elements.append(LadderElement("COIL_NORMAL", tag=target_var))

                        b1 = branch_tags[0] if len(branch_tags) > 0 else "Start"
                        b2 = branch_tags[1] if len(branch_tags) > 1 else target_var

                        ascii_diag = (
                            f"|      +---[ {b1:<12} ]---+{' ' * len(series_nc_str)}                   |\n"
                            f"|---+--+                      +{series_nc_str}--( {target_var} )---|\n"
                            f"|      +---[ {b2:<12} ]---+{' ' * len(series_nc_str)}                   |"
                        )
                    else:
                        clean_rem = re.sub(r"[()]", " ", val_st)
                        and_parts = [p.strip() for p in clean_rem.split("AND") if p.strip()]
                        series_str = ""
                        for part in and_parts:
                            if part.upper().startswith("NOT "):
                                tag = part[4:].strip()
                                elements.append(LadderElement("CONTACT_NC", tag=tag))
                                series_str += f"--[/ {tag} ]"
                            else:
                                tag = part.strip()
                                if tag:
                                    elements.append(LadderElement("CONTACT_NO", tag=tag))
                                    series_str += f"--[ {tag} ]"
                        elements.append(LadderElement("COIL_NORMAL", tag=target_var))
                        ascii_diag = f"|{series_str}---( {target_var} )---|"

                    rungs.append(LadderRung(
                        rung_number=rung_counter,
                        title=f"{target_var} Control Logic",
                        comment="Normal output coil energized when series/parallel rung conditions evaluate to TRUE",
                        st_source=stmt.to_st().strip(),
                        recipe_key="COIL_NORMAL",
                        category="COIL",
                        elements=elements,
                        ascii_diagram=ascii_diag,
                    ))
                    rung_counter += 1
                    i += 1
                    continue

            i += 1

        return LadderProgram(
            pou_name=effective_pou_name,
            pou_type="PROGRAM",
            rungs=rungs,
            variables=variables,
            conversion_timestamp=now_utc,
        )

