"""
IEC 61131-3 Structured Text Abstract Syntax Tree (AST) Node Definitions.
Provides complete node definitions, JSON-serializable dictionaries (to_dict),
and roundtrippable Structured Text code emission (to_st).
"""
from typing import List, Optional, Any, Tuple, Dict, Union

class SourceLocation:
    def __init__(self, line: int = 1, col: int = 1):
        self.line = line
        self.col = col

    def __str__(self) -> str:
        return f"Line {self.line}, Col {self.col}"

    def __repr__(self) -> str:
        return f"SourceLocation({self.line}, {self.col})"

    def to_dict(self) -> Dict[str, Any]:
        return {"line": self.line, "col": self.col}

class ASTNode:
    def __init__(self, loc: Optional[SourceLocation] = None):
        self.loc = loc or SourceLocation()

    def to_dict(self) -> Dict[str, Any]:
        return {"node_type": self.__class__.__name__, "loc": self.loc.to_dict()}

    def to_st(self, indent: int = 0) -> str:
        raise NotImplementedError(f"to_st() not implemented for {self.__class__.__name__}")

# --- Expressions ---

class ExpressionNode(ASTNode):
    pass

class LiteralNode(ExpressionNode):
    def __init__(self, value: Any, data_type: str = "INT", loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.value = value
        self.data_type = data_type

    def __repr__(self) -> str:
        return f"LiteralNode({self.value!r}, {self.data_type!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "LiteralNode",
            "value": self.value,
            "data_type": self.data_type,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        if self.data_type == "BOOL":
            return "TRUE" if self.value else "FALSE"
        elif self.data_type == "STRING":
            return f"'{self.value}'"
        elif self.data_type == "TIME":
            val = self.value
            if isinstance(val, (int, float)) and val >= 1000 and val % 1000 == 0:
                return f"T#{int(val // 1000)}s"
            elif isinstance(val, (int, float)) and val == int(val):
                return f"T#{int(val)}ms"
            return f"T#{val}ms"
        elif self.data_type in ("DATE", "D"):
            return f"DATE#{self.value}"
        elif self.data_type in ("TOD", "TIME_OF_DAY"):
            return f"TOD#{self.value}"
        elif self.data_type in ("DT", "DATE_AND_TIME"):
            return f"DT#{self.value}"
        elif self.data_type in ("REAL", "LREAL"):
            s = str(self.value)
            return s if "." in s or "e" in s or "E" in s else f"{s}.0"
        return str(self.value)

class VariableNode(ExpressionNode):
    def __init__(self, name: str, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.name = name

    def __repr__(self) -> str:
        return f"VariableNode({self.name!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "VariableNode",
            "name": self.name,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        return self.name

class MemberAccessNode(ExpressionNode):
    def __init__(self, target: ExpressionNode, member: str, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.target = target
        self.member = member

    def __repr__(self) -> str:
        return f"MemberAccessNode({self.target!r}, {self.member!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "MemberAccessNode",
            "target": self.target.to_dict(),
            "member": self.member,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        return f"{self.target.to_st(indent)}.{self.member}"

class ArrayAccessNode(ExpressionNode):
    def __init__(self, target: ExpressionNode, index: ExpressionNode,
                 indices: Optional[List[ExpressionNode]] = None,
                 loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.target = target
        self.index = index
        self.indices = indices or [index]

    def __repr__(self) -> str:
        return f"ArrayAccessNode({self.target!r}, {self.index!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "ArrayAccessNode",
            "target": self.target.to_dict(),
            "index": self.index.to_dict(),
            "indices": [i.to_dict() for i in self.indices],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        idx_strs = [i.to_st(indent) for i in self.indices]
        return f"{self.target.to_st(indent)}[{', '.join(idx_strs)}]"

class BinaryOpNode(ExpressionNode):
    def __init__(self, op: str, left: ExpressionNode, right: ExpressionNode, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self) -> str:
        return f"BinaryOpNode({self.op!r}, {self.left!r}, {self.right!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "BinaryOpNode",
            "op": self.op,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        left_st = self.left.to_st(indent)
        right_st = self.right.to_st(indent)
        if isinstance(self.left, BinaryOpNode):
            left_st = f"({left_st})"
        if isinstance(self.right, BinaryOpNode):
            right_st = f"({right_st})"
        return f"{left_st} {self.op} {right_st}"

class UnaryOpNode(ExpressionNode):
    def __init__(self, op: str, operand: ExpressionNode, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.op = op
        self.operand = operand

    def __repr__(self) -> str:
        return f"UnaryOpNode({self.op!r}, {self.operand!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "UnaryOpNode",
            "op": self.op,
            "operand": self.operand.to_dict(),
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        opnd_st = self.operand.to_st(indent)
        if isinstance(self.operand, (BinaryOpNode, UnaryOpNode)):
            opnd_st = f"({opnd_st})"
        if self.op.upper() == "NOT":
            return f"NOT {opnd_st}"
        return f"{self.op}{opnd_st}"

class FunctionCallNode(ExpressionNode):
    def __init__(self, name: str, args: Optional[List[Any]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.name = name
        self.args = args or []

    def __repr__(self) -> str:
        return f"FunctionCallNode({self.name!r}, {self.args!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "FunctionCallNode",
            "name": self.name,
            "args": [a.to_dict() if hasattr(a, "to_dict") else a for a in self.args],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        args_st = []
        for a in self.args:
            if hasattr(a, "to_st"):
                args_st.append(a.to_st(indent))
            else:
                args_st.append(str(a))
        return f"{self.name}({', '.join(args_st)})"

# --- Statements ---

class StatementNode(ASTNode):
    pass

class AssignmentNode(StatementNode):
    def __init__(self, target: ExpressionNode, value: ExpressionNode, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.target = target
        self.value = value

    def __repr__(self) -> str:
        return f"AssignmentNode({self.target!r}, {self.value!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "AssignmentNode",
            "target": self.target.to_dict(),
            "value": self.value.to_dict(),
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        if indent == 0:
            return f"{self.target.to_st(0)} := {self.value.to_st(0)}"
        return f"{pad}{self.target.to_st(0)} := {self.value.to_st(0)};"

class FBInvocationNode(StatementNode):
    def __init__(self, target: ExpressionNode, args: Optional[Dict[str, ExpressionNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.target = target
        self.args = args or {}

    def __repr__(self) -> str:
        return f"FBInvocationNode({self.target!r}, {self.args!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "FBInvocationNode",
            "target": self.target.to_dict(),
            "args": {k: v.to_dict() for k, v in self.args.items()},
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        arg_strs = [f"{k} := {v.to_st(0)}" for k, v in self.args.items()]
        return f"{pad}{self.target.to_st(0)}({', '.join(arg_strs)});"

class IfNode(StatementNode):
    def __init__(self, condition: ExpressionNode, then_body: List[StatementNode],
                 elsif_blocks: Optional[List[Tuple[ExpressionNode, List[StatementNode]]]] = None,
                 else_body: Optional[List[StatementNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.condition = condition
        self.then_body = then_body
        self.elsif_blocks = elsif_blocks or []
        self.else_body = else_body

    def __repr__(self) -> str:
        return f"IfNode({self.condition!r}, then={len(self.then_body)}, elsifs={len(self.elsif_blocks)})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "IfNode",
            "condition": self.condition.to_dict(),
            "then_body": [s.to_dict() for s in self.then_body],
            "elsif_blocks": [
                (c.to_dict(), [s.to_dict() for s in b]) for c, b in self.elsif_blocks
            ],
            "else_body": [s.to_dict() for s in self.else_body] if self.else_body is not None else None,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        lines = [f"{pad}IF {self.condition.to_st(0)} THEN"]
        for s in self.then_body:
            lines.append(s.to_st(indent + 1))
        for cond, body in self.elsif_blocks:
            lines.append(f"{pad}ELSIF {cond.to_st(0)} THEN")
            for s in body:
                lines.append(s.to_st(indent + 1))
        if self.else_body is not None:
            lines.append(f"{pad}ELSE")
            for s in self.else_body:
                lines.append(s.to_st(indent + 1))
        lines.append(f"{pad}END_IF;")
        return "\n".join(lines)

class CaseRange:
    def __init__(self, start: ExpressionNode, end: ExpressionNode):
        self.start = start
        self.end = end

    def __repr__(self) -> str:
        return f"CaseRange({self.start!r}..{self.end!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "CaseRange",
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        return f"{self.start.to_st(0)}..{self.end.to_st(0)}"

class CaseNode(StatementNode):
    def __init__(self, selector: ExpressionNode,
                 cases: Optional[List[Tuple[List[Union[ExpressionNode, CaseRange]], List[StatementNode]]]] = None,
                 else_body: Optional[List[StatementNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.selector = selector
        self.cases = cases or []
        self.else_body = else_body

    def __repr__(self) -> str:
        return f"CaseNode({self.selector!r}, cases={len(self.cases)})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "CaseNode",
            "selector": self.selector.to_dict(),
            "cases": [
                ([lbl.to_dict() for lbl in labels], [s.to_dict() for s in body])
                for labels, body in self.cases
            ],
            "else_body": [s.to_dict() for s in self.else_body] if self.else_body is not None else None,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        lines = [f"{pad}CASE {self.selector.to_st(0)} OF"]
        for labels, body in self.cases:
            lbl_str = ", ".join(lbl.to_st(0) for lbl in labels)
            lines.append(f"{pad}    {lbl_str}:")
            for s in body:
                lines.append(s.to_st(indent + 2))
        if self.else_body is not None:
            lines.append(f"{pad}    ELSE")
            for s in self.else_body:
                lines.append(s.to_st(indent + 2))
        lines.append(f"{pad}END_CASE;")
        return "\n".join(lines)

class ForNode(StatementNode):
    def __init__(self, var_name: str, start_expr: ExpressionNode, end_expr: ExpressionNode,
                 step_expr: Optional[ExpressionNode] = None, body: Optional[List[StatementNode]] = None,
                 loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.var_name = var_name
        self.start_expr = start_expr
        self.end_expr = end_expr
        self.step_expr = step_expr
        self.body = body or []

    def __repr__(self) -> str:
        return f"ForNode({self.var_name!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "ForNode",
            "var_name": self.var_name,
            "start_expr": self.start_expr.to_dict(),
            "end_expr": self.end_expr.to_dict(),
            "step_expr": self.step_expr.to_dict() if self.step_expr is not None else None,
            "body": [s.to_dict() for s in self.body],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        step_part = f" BY {self.step_expr.to_st(0)}" if self.step_expr is not None else ""
        lines = [f"{pad}FOR {self.var_name} := {self.start_expr.to_st(0)} TO {self.end_expr.to_st(0)}{step_part} DO"]
        for s in self.body:
            lines.append(s.to_st(indent + 1))
        lines.append(f"{pad}END_FOR;")
        return "\n".join(lines)

class WhileNode(StatementNode):
    def __init__(self, condition: ExpressionNode, body: Optional[List[StatementNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.condition = condition
        self.body = body or []

    def __repr__(self) -> str:
        return f"WhileNode({self.condition!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "WhileNode",
            "condition": self.condition.to_dict(),
            "body": [s.to_dict() for s in self.body],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        lines = [f"{pad}WHILE {self.condition.to_st(0)} DO"]
        for s in self.body:
            lines.append(s.to_st(indent + 1))
        lines.append(f"{pad}END_WHILE;")
        return "\n".join(lines)

class RepeatNode(StatementNode):
    def __init__(self, condition: ExpressionNode, body: Optional[List[StatementNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.condition = condition
        self.body = body or []

    def __repr__(self) -> str:
        return f"RepeatNode({self.condition!r})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "RepeatNode",
            "condition": self.condition.to_dict(),
            "body": [s.to_dict() for s in self.body],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        lines = [f"{pad}REPEAT"]
        for s in self.body:
            lines.append(s.to_st(indent + 1))
        lines.append(f"{pad}UNTIL {self.condition.to_st(0)}")
        lines.append(f"{pad}END_REPEAT;")
        return "\n".join(lines)

class ExitNode(StatementNode):
    def __init__(self, loc: Optional[SourceLocation] = None):
        super().__init__(loc)

    def __repr__(self) -> str:
        return "ExitNode()"

    def to_dict(self) -> Dict[str, Any]:
        return {"node_type": "ExitNode", "loc": self.loc.to_dict()}

    def to_st(self, indent: int = 0) -> str:
        return f"{'    ' * indent}EXIT;"

class ReturnNode(StatementNode):
    def __init__(self, loc: Optional[SourceLocation] = None):
        super().__init__(loc)

    def __repr__(self) -> str:
        return "ReturnNode()"

    def to_dict(self) -> Dict[str, Any]:
        return {"node_type": "ReturnNode", "loc": self.loc.to_dict()}

    def to_st(self, indent: int = 0) -> str:
        return f"{'    ' * indent}RETURN;"

class ContinueNode(StatementNode):
    def __init__(self, loc: Optional[SourceLocation] = None):
        super().__init__(loc)

    def __repr__(self) -> str:
        return "ContinueNode()"

    def to_dict(self) -> Dict[str, Any]:
        return {"node_type": "ContinueNode", "loc": self.loc.to_dict()}

    def to_st(self, indent: int = 0) -> str:
        return f"{'    ' * indent}CONTINUE;"

class EmptyStatementNode(StatementNode):
    def __init__(self, loc: Optional[SourceLocation] = None):
        super().__init__(loc)

    def __repr__(self) -> str:
        return "EmptyStatementNode()"

    def to_dict(self) -> Dict[str, Any]:
        return {"node_type": "EmptyStatementNode", "loc": self.loc.to_dict()}

    def to_st(self, indent: int = 0) -> str:
        return f"{'    ' * indent};"

# --- Declarations & Top-level ---

class VarDeclNode(ASTNode):
    def __init__(self, name: str, data_type: str = "INT", initial_value: Optional[ExpressionNode] = None,
                 array_bounds: Optional[Any] = None, address: Optional[str] = None,
                 loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.name = name
        self.data_type = data_type
        self.initial_value = initial_value
        self.array_bounds = array_bounds
        self.address = address

    def __repr__(self) -> str:
        return f"VarDeclNode({self.name}: {self.data_type})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "VarDeclNode",
            "name": self.name,
            "data_type": self.data_type,
            "initial_value": self.initial_value.to_dict() if self.initial_value is not None else None,
            "array_bounds": self.array_bounds,
            "address": self.address,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        decl = f"{pad}{self.name}"
        if self.address:
            decl += f" AT {self.address}"
        decl += " : "
        if self.array_bounds:
            if isinstance(self.array_bounds, tuple):
                decl += f"ARRAY [{self.array_bounds[0]}..{self.array_bounds[1]}] OF "
            elif isinstance(self.array_bounds, list):
                dims = [f"{d[0]}..{d[1]}" if isinstance(d, tuple) else str(d) for d in self.array_bounds]
                decl += f"ARRAY [{', '.join(dims)}] OF "
            else:
                decl += f"ARRAY [{self.array_bounds}] OF "
        decl += self.data_type
        if self.initial_value is not None:
            decl += f" := {self.initial_value.to_st(0)}"
        decl += ";"
        return decl

class VarBlockNode(ASTNode):
    def __init__(self, block_type: str = "VAR", retain: bool = False, constant: bool = False,
                 non_retain: bool = False,
                 declarations: Optional[List[VarDeclNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.block_type = block_type
        self.retain = retain
        self.constant = constant
        self.non_retain = non_retain
        self.declarations = declarations or []

    def __repr__(self) -> str:
        return f"VarBlockNode({self.block_type}, decls={len(self.declarations)})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "VarBlockNode",
            "block_type": self.block_type,
            "retain": self.retain,
            "constant": self.constant,
            "non_retain": self.non_retain,
            "declarations": [d.to_dict() for d in self.declarations],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        header = f"{pad}{self.block_type}"
        if self.retain:
            header += " RETAIN"
        elif self.non_retain:
            header += " NON_RETAIN"
        if self.constant:
            header += " CONSTANT"
        lines = [header]
        for decl in self.declarations:
            lines.append(decl.to_st(indent + 1))
        lines.append(f"{pad}END_VAR")
        return "\n".join(lines)

# --- User-Defined Types (IEC 61131-3 TYPE ... END_TYPE) ---

class TypeDefNode(ASTNode):
    """Base class for type definitions (STRUCT, ENUM, subrange, alias)."""
    pass

class StructTypeNode(TypeDefNode):
    def __init__(self, members: Optional[List[VarDeclNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.members = members or []

    def __repr__(self) -> str:
        return f"StructTypeNode(members={len(self.members)})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "StructTypeNode",
            "members": [m.to_dict() for m in self.members],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        lines = [f"{pad}STRUCT"]
        for m in self.members:
            lines.append(m.to_st(indent + 1))
        lines.append(f"{pad}END_STRUCT")
        return "\n".join(lines)

class EnumTypeNode(TypeDefNode):
    def __init__(self, values: List[str], initial_value: Optional[str] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.values = values
        self.initial_value = initial_value

    def __repr__(self) -> str:
        return f"EnumTypeNode(values={self.values}, init={self.initial_value})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "EnumTypeNode",
            "values": self.values,
            "initial_value": self.initial_value,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        val_str = ", ".join(self.values)
        st = f"{pad}({val_str})"
        if self.initial_value:
            st += f" := {self.initial_value}"
        return st

class SubrangeTypeNode(TypeDefNode):
    def __init__(self, base_type: str, min_val: ExpressionNode, max_val: ExpressionNode,
                 initial_value: Optional[ExpressionNode] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.base_type = base_type
        self.min_val = min_val
        self.max_val = max_val
        self.initial_value = initial_value

    def __repr__(self) -> str:
        return f"SubrangeTypeNode({self.base_type} min={self.min_val} max={self.max_val})"

    @property
    def lower_bound(self) -> Any:
        if hasattr(self.min_val, "value"):
            return self.min_val.value
        return self.min_val

    @property
    def upper_bound(self) -> Any:
        if hasattr(self.max_val, "value"):
            return self.max_val.value
        return self.max_val

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "SubrangeTypeNode",
            "base_type": self.base_type,
            "min_val": self.min_val.to_dict(),
            "max_val": self.max_val.to_dict(),
            "initial_value": self.initial_value.to_dict() if self.initial_value else None,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        st = f"{pad}{self.base_type} ({self.min_val.to_st()}..{self.max_val.to_st()})"
        if self.initial_value:
            st += f" := {self.initial_value.to_st()}"
        return st

class AliasTypeNode(TypeDefNode):
    def __init__(self, target_type: str, initial_value: Optional[ExpressionNode] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.target_type = target_type
        self.initial_value = initial_value

    def __repr__(self) -> str:
        return f"AliasTypeNode({self.target_type})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "AliasTypeNode",
            "target_type": self.target_type,
            "initial_value": self.initial_value.to_dict() if self.initial_value else None,
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        st = f"{pad}{self.target_type}"
        if self.initial_value:
            st += f" := {self.initial_value.to_st()}"
        return st

class TypeDeclNode(ASTNode):
    def __init__(self, name: str, type_def: TypeDefNode, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.name = name
        self.type_def = type_def

    def __repr__(self) -> str:
        return f"TypeDeclNode({self.name}, def={self.type_def})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "TypeDeclNode",
            "name": self.name,
            "type_def": self.type_def.to_dict(),
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        if isinstance(self.type_def, StructTypeNode):
            st_body = self.type_def.to_st(indent)
            return f"{pad}{self.name} : {st_body.strip()};"
        else:
            return f"{pad}{self.name} : {self.type_def.to_st().strip()};"

class TypeBlockNode(ASTNode):
    def __init__(self, declarations: Optional[List[TypeDeclNode]] = None, loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.declarations = declarations or []

    def __repr__(self) -> str:
        return f"TypeBlockNode(decls={len(self.declarations)})"

    @property
    def types(self) -> List[TypeDeclNode]:
        return self.declarations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "TypeBlockNode",
            "declarations": [d.to_dict() for d in self.declarations],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        pad = "    " * indent
        lines = [f"{pad}TYPE"]
        for decl in self.declarations:
            lines.append(decl.to_st(indent + 1))
        lines.append(f"{pad}END_TYPE")
        return "\n".join(lines)

class ProgramNode(ASTNode):
    def __init__(self, name: str = "Main", pou_type: str = "PROGRAM", return_type: Optional[str] = None,
                 var_blocks: Optional[List[VarBlockNode]] = None, body: Optional[List[StatementNode]] = None,
                 type_blocks: Optional[List[TypeBlockNode]] = None,
                 loc: Optional[SourceLocation] = None):
        super().__init__(loc)
        self.name = name
        self.pou_type = pou_type
        self.return_type = return_type
        self.var_blocks = var_blocks or []
        self.body = body or []
        self.type_blocks = type_blocks or []

    def __repr__(self) -> str:
        return f"ProgramNode({self.pou_type} {self.name}, types={len(self.type_blocks)}, blocks={len(self.var_blocks)}, stmts={len(self.body)})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": "ProgramNode",
            "name": self.name,
            "pou_type": self.pou_type,
            "return_type": self.return_type,
            "type_blocks": [tb.to_dict() for tb in self.type_blocks],
            "var_blocks": [vb.to_dict() for vb in self.var_blocks],
            "body": [s.to_dict() for s in self.body],
            "loc": self.loc.to_dict(),
        }

    def to_st(self, indent: int = 0) -> str:
        lines = []
        if self.type_blocks:
            for tb in self.type_blocks:
                lines.append(tb.to_st(indent))
            if self.pou_type == "TYPE":
                return "\n".join(lines)
            lines.append("")

        if self.pou_type == "TYPE":
            return "\n".join(lines)

        # Strictly follow IEC 61131-3: NO trailing semicolon on POU header
        if self.pou_type == "FUNCTION":
            lines.append(f"FUNCTION {self.name} : {self.return_type or 'BOOL'}")
        else:
            lines.append(f"{self.pou_type} {self.name}")

        for vb in self.var_blocks:
            lines.append(vb.to_st(indent + 1))

        if self.var_blocks and self.body:
            lines.append("")

        for stmt in self.body:
            lines.append(stmt.to_st(indent + 1))

        # Strictly follow IEC 61131-3: NO trailing semicolon on POU closer
        lines.append(f"END_{self.pou_type}")
        return "\n".join(lines)
