"""Legacy parser module re-exporting canonical src.iec parser components."""
from src.iec.lexer import Lexer, Token, TokenType, parse_time_literal_ms
from src.iec.ast_nodes import (
    ASTNode, SourceLocation, ProgramNode, VarBlockNode, VarDeclNode,
    StatementNode, AssignmentNode, FBInvocationNode, IfNode, CaseNode,
    CaseRange, ForNode, WhileNode, RepeatNode, ExitNode, ReturnNode,
    ContinueNode, EmptyStatementNode, ExpressionNode, LiteralNode,
    VariableNode, MemberAccessNode, ArrayAccessNode, BinaryOpNode,
    UnaryOpNode, FunctionCallNode
)
from src.iec.parser import Parser, ParseError

__all__ = [
    "Lexer", "Token", "TokenType", "parse_time_literal_ms",
    "ASTNode", "SourceLocation", "ProgramNode", "VarBlockNode", "VarDeclNode",
    "StatementNode", "AssignmentNode", "FBInvocationNode", "IfNode", "CaseNode",
    "CaseRange", "ForNode", "WhileNode", "RepeatNode", "ExitNode", "ReturnNode",
    "ContinueNode", "EmptyStatementNode", "ExpressionNode", "LiteralNode",
    "VariableNode", "MemberAccessNode", "ArrayAccessNode", "BinaryOpNode",
    "UnaryOpNode", "FunctionCallNode", "Parser", "ParseError"
]
