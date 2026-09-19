"""
IEC 61131-3 Structured Text Syntax, Semantic & Safety Validator.
Enforces ST-only grammar, variable scope integrity, and hardware safety constraints.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Any
import re

from src.parser.lexer import Lexer, TokenType
from src.parser.parser import Parser, ParseError
from src.parser.ast_nodes import (
    ProgramNode, VarBlockNode, VarDeclNode, StatementNode, AssignmentNode,
    FBInvocationNode, IfNode, CaseNode, ForNode, WhileNode, RepeatNode,
    VariableNode, MemberAccessNode, ArrayAccessNode, BinaryOpNode,
    UnaryOpNode, FunctionCallNode, LiteralNode
)
from src.simulation.function_blocks import STANDARD_FB_CLASSES, STANDARD_FUNCTIONS

# Blocked hardware primitives according to AGENTS.md safety lock
FORBIDDEN_HARDWARE_PATTERNS = [
    r'\bPGMUpdateUtility\b',
    r'\bDfuSeCommand\b',
    r'\bSTMFlashLoader\b',
    r'\bWinJTAG\b',
    r'\bDIRECT_IO\b',
    r'\bCAN_SEND\b',
    r'\bCAN_RECEIVE\b',
    r'\bSERIAL_PORT_WRITE\b',
    r'\bFLASH_ERASE\b',
    r'\bFLASH_WRITE\b',
    r'\bCONTROLLER_DOWNLOAD\b'
]

VALID_STANDARD_TYPES = {
    "BOOL", "BYTE", "WORD", "DWORD", "LWORD",
    "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT",
    "REAL", "LREAL", "TIME", "STRING"
}

@dataclass
class DiagnosticIssue:
    severity: str  # ERROR, WARNING
    line: int
    col: int
    message: str

    def __str__(self) -> str:
        return f"[{self.severity}] (Line {self.line}, Col {self.col}): {self.message}"

@dataclass
class ValidationResult:
    is_valid: bool
    errors: List[DiagnosticIssue] = field(default_factory=list)
    warnings: List[DiagnosticIssue] = field(default_factory=list)
    declared_variables: Dict[str, str] = field(default_factory=dict)
    used_function_blocks: List[str] = field(default_factory=list)
    pou_name: str = ""
    pou_type: str = "PROGRAM"

    @property
    def summary(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        lines = [f"Validation Result: {status} ({len(self.errors)} errors, {len(self.warnings)} warnings)"]
        for e in self.errors:
            lines.append(f"  {e}")
        for w in self.warnings:
            lines.append(f"  {w}")
        return "\n".join(lines)

class STValidator:
    """
    Validates IEC 61131-3 Structured Text programs.
    Checks syntax, variable type validity, scope usage, and safety directives.
    """
    def __init__(self, allow_undeclared_vars: bool = False):
        self.allow_undeclared_vars = allow_undeclared_vars

    def validate(self, st_code: str) -> ValidationResult:
        errors: List[DiagnosticIssue] = []
        warnings: List[DiagnosticIssue] = []
        declared_vars: Dict[str, str] = {}
        used_fbs: List[str] = []

        # 1. Hardware Safety Directive Scan
        for pattern in FORBIDDEN_HARDWARE_PATTERNS:
            match = re.search(pattern, st_code, re.IGNORECASE)
            if match:
                line_no = st_code[:match.start()].count('\n') + 1
                errors.append(DiagnosticIssue(
                    severity="ERROR",
                    line=line_no,
                    col=1,
                    message=f"Safety Directive Violation: Forbidden hardware operation '{match.group(0)}' detected."
                ))

        # 2. Syntax & Lexical Parsing
        ast: Optional[ProgramNode] = None
        try:
            parser = Parser.from_source(st_code)
            ast = parser.parse()
        except ParseError as pe:
            errors.append(DiagnosticIssue(
                severity="ERROR",
                line=pe.line,
                col=pe.col,
                message=str(pe)
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)
        except Exception as ex:
            errors.append(DiagnosticIssue(
                severity="ERROR",
                line=1,
                col=1,
                message=f"Parser failure: {str(ex)}"
            ))
            return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

        pou_name = ast.name
        pou_type = ast.pou_type

        # 3. Variable Declaration Inspection
        for block in ast.var_blocks:
            for decl in block.declarations:
                name_upper = decl.name.upper()
                type_upper = decl.data_type.upper()

                if name_upper in declared_vars:
                    warnings.append(DiagnosticIssue(
                        severity="WARNING",
                        line=decl.loc.line,
                        col=decl.loc.col,
                        message=f"Duplicate variable declaration '{decl.name}'"
                    ))
                declared_vars[name_upper] = type_upper

                # Check if valid type
                if type_upper in STANDARD_FB_CLASSES:
                    if type_upper not in used_fbs:
                        used_fbs.append(type_upper)
                elif type_upper not in VALID_STANDARD_TYPES:
                    warnings.append(DiagnosticIssue(
                        severity="WARNING",
                        line=decl.loc.line,
                        col=decl.loc.col,
                        message=f"Custom or unrecognized data type '{decl.data_type}' for variable '{decl.name}'"
                    ))

        # 4. Semantic Statement & Scope Check
        referenced_vars: Set[str] = set()

        def collect_var_refs(node: Any):
            if isinstance(node, VariableNode):
                referenced_vars.add(node.name.upper())
            elif isinstance(node, MemberAccessNode):
                collect_var_refs(node.target)
            elif isinstance(node, ArrayAccessNode):
                collect_var_refs(node.target)
                collect_var_refs(node.index)
            elif isinstance(node, BinaryOpNode):
                collect_var_refs(node.left)
                collect_var_refs(node.right)
            elif isinstance(node, UnaryOpNode):
                collect_var_refs(node.operand)
            elif isinstance(node, FunctionCallNode):
                for a in node.args:
                    collect_var_refs(a)
            elif isinstance(node, AssignmentNode):
                collect_var_refs(node.target)
                collect_var_refs(node.value)
            elif isinstance(node, FBInvocationNode):
                collect_var_refs(node.target)
                for a in node.args.values():
                    collect_var_refs(a)
            elif isinstance(node, IfNode):
                collect_var_refs(node.condition)
                for s in node.then_body: collect_var_refs(s)
                for c, b in node.elsif_blocks:
                    collect_var_refs(c)
                    for s in b: collect_var_refs(s)
                if node.else_body:
                    for s in node.else_body: collect_var_refs(s)
            elif isinstance(node, CaseNode):
                collect_var_refs(node.selector)
                for lbls, b in node.cases:
                    for s in b: collect_var_refs(s)
                if node.else_body:
                    for s in node.else_body: collect_var_refs(s)
            elif isinstance(node, ForNode):
                referenced_vars.add(node.var_name.upper())
                collect_var_refs(node.start_expr)
                collect_var_refs(node.end_expr)
                if node.step_expr: collect_var_refs(node.step_expr)
                for s in node.body: collect_var_refs(s)
            elif isinstance(node, WhileNode):
                collect_var_refs(node.condition)
                for s in node.body: collect_var_refs(s)
            elif isinstance(node, RepeatNode):
                collect_var_refs(node.condition)
                for s in node.body: collect_var_refs(s)

        for stmt in ast.body:
            collect_var_refs(stmt)

        # Check for undeclared variable references
        known_identifiers = set(declared_vars.keys()) | set(STANDARD_FUNCTIONS.keys()) | {"TRUE", "FALSE"}
        for var_name in referenced_vars:
            if var_name not in known_identifiers and not self.allow_undeclared_vars:
                # If variable was not declared in VAR blocks
                warnings.append(DiagnosticIssue(
                    severity="WARNING",
                    line=1,
                    col=1,
                    message=f"Variable '{var_name}' referenced without explicit declaration in VAR block."
                ))

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            declared_variables=declared_vars,
            used_function_blocks=used_fbs,
            pou_name=pou_name,
            pou_type=pou_type
        )