"""IEC 61131-3 Structured Text package.
Provides 100% adherence to IEC 61131-3 Structured Text specification:
- Lexer: Pure Python regex lexer with full tokenization and typed literals.
- Parser: Recursive descent AST parser for POUs, variables, and control structures.
- AST Nodes: Complete typed abstract syntax tree node hierarchy.
- Validator: IECValidator and STParser for syntax, semantic, safety, and block nesting validation.
- Pure Python implementation with zero third-party/legacy compiler dependencies.
"""
from .ast_nodes import (
    ASTNode, SourceLocation, ProgramNode, VarBlockNode, VarDeclNode,
    StatementNode, AssignmentNode, FBInvocationNode, IfNode, CaseNode,
    CaseRange, ForNode, WhileNode, RepeatNode, ExitNode, ReturnNode,
    ContinueNode, EmptyStatementNode, ExpressionNode, LiteralNode,
    VariableNode, MemberAccessNode, ArrayAccessNode, BinaryOpNode,
    UnaryOpNode, FunctionCallNode
)
from .lexer import Lexer, Token, TokenType, LexerError, parse_time_literal_ms
from .parser import Parser, ParseError
from .validator import IECValidator
from .simulator import STSimulator
from .templates import (
    TEMPLATES,
    get_template_catalog,
    get_template,
    get_template_code,
)
from .st_parser import (
    STParser,
    STPOU,
    STVariable,
    POUKind,
    VarScope,
    IssueSeverity,
    STIssue,
    STValidationResult,
)
from .st_generator import STGenerator

__all__ = [
    "Lexer",
    "LexerError",
    "Token",
    "TokenType",
    "parse_time_literal_ms",
    "Parser",
    "ParseError",
    "ASTNode",
    "SourceLocation",
    "ProgramNode",
    "VarBlockNode",
    "VarDeclNode",
    "StatementNode",
    "AssignmentNode",
    "FBInvocationNode",
    "IfNode",
    "CaseNode",
    "CaseRange",
    "ForNode",
    "WhileNode",
    "RepeatNode",
    "ExitNode",
    "ReturnNode",
    "ContinueNode",
    "EmptyStatementNode",
    "ExpressionNode",
    "LiteralNode",
    "VariableNode",
    "MemberAccessNode",
    "ArrayAccessNode",
    "BinaryOpNode",
    "UnaryOpNode",
    "FunctionCallNode",
    "IECValidator",
    "STSimulator",
    "TEMPLATES",
    "get_template_catalog",
    "get_template",
    "get_template_code",
    "STParser",
    "STPOU",
    "STVariable",
    "POUKind",
    "VarScope",
    "IssueSeverity",
    "STIssue",
    "STValidationResult",
    "STGenerator",
]
