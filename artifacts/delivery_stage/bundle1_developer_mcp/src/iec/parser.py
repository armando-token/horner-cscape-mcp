"""
IEC 61131-3 Structured Text Recursive Descent Parser.
Enforces 100% adherence to IEC 61131-3 specifications:
- POU constructs: PROGRAM, FUNCTION_BLOCK, FUNCTION (with return types)
- Variable declaration blocks: VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_GLOBAL, VAR_TEMP, VAR_EXTERNAL, VAR_STAT, VAR_CONFIG
- Qualifiers: RETAIN, NON_RETAIN, CONSTANT, AT direct address binding
- Control structures: IF-THEN-ELSIF-ELSE-END_IF, CASE-OF-ELSE-END_CASE (supporting subranges, comma-separated labels, signed numbers), FOR-TO-BY-DO-END_FOR, WHILE-DO-END_WHILE, REPEAT-UNTIL-END_REPEAT, EXIT, RETURN, CONTINUE
- Expression hierarchy: full operator precedence (OR, XOR, AND/&, =, <>, <, >, <=, >=, +, -, *, /, MOD, **, unary +, -, NOT)
- Statements: assignments (including array indexing and member access), FB invocations, function calls
- Pure Python implementation with zero third-party/legacy compiler dependencies.
"""
from typing import List, Optional, Tuple, Dict, Union, Any
from .lexer import Lexer, Token, TokenType, LexerError
from .ast_nodes import (
    ASTNode, SourceLocation, ProgramNode, VarBlockNode, VarDeclNode,
    StatementNode, AssignmentNode, FBInvocationNode, IfNode, CaseNode,
    CaseRange, ForNode, WhileNode, RepeatNode, ExitNode, ReturnNode,
    ContinueNode, EmptyStatementNode, ExpressionNode, LiteralNode,
    VariableNode, MemberAccessNode, ArrayAccessNode, BinaryOpNode,
    UnaryOpNode, FunctionCallNode, TypeDefNode, StructTypeNode,
    EnumTypeNode, SubrangeTypeNode, AliasTypeNode, TypeDeclNode,
    TypeBlockNode
)


class ParseError(Exception):
    def __init__(self, message: str, token: Optional[Token] = None):
        if token:
            super().__init__(f"Syntax error at line {token.line}, col {token.col}: {message}")
            self.line = token.line
            self.col = token.col
        else:
            super().__init__(message)
            self.line = 0
            self.col = 0


class Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.pos = 0

    @classmethod
    def from_source(cls, source: str) -> "Parser":
        tokens = Lexer(source).tokenize()
        return cls(tokens)

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx < len(self.tokens):
            return self.tokens[idx]
        return self.tokens[-1]

    def _match(self, *expected_types: TokenType) -> bool:
        if self._peek().type in expected_types:
            self.pos += 1
            return True
        return False

    def _expect(self, expected_type: TokenType, err_msg: str = "") -> Token:
        tok = self._peek()
        if tok.type != expected_type:
            msg = err_msg or f"Expected {expected_type.name}, got {tok.type.name} ('{tok.value}')"
            raise ParseError(msg, tok)
        self.pos += 1
        return tok

    def parse_program(self) -> ProgramNode:
        """
        Parses a full IEC 61131-3 POU program into an AST ProgramNode.
        """
        return self.parse()

    def parse(self) -> ProgramNode:
        """
        Parses either a full POU (PROGRAM / FUNCTION_BLOCK / FUNCTION)
        or a sequence of type declarations, variable declarations, and statements.
        """
        type_blocks: List[TypeBlockNode] = []
        while self._peek().type == TokenType.TYPE:
            type_blocks.append(self._parse_type_block())

        tok = self._peek()
        # If the source code only consists of TYPE declarations
        if tok.type == TokenType.EOF and type_blocks:
            return ProgramNode(
                name="Types",
                pou_type="TYPE",
                type_blocks=type_blocks,
                loc=SourceLocation(type_blocks[0].loc.line, type_blocks[0].loc.col)
            )

        pou_type = "PROGRAM"
        pou_name = "Main"
        return_type = None

        pou_opened = False
        if tok.type in (TokenType.PROGRAM, TokenType.FUNCTION_BLOCK, TokenType.FUNCTION):
            pou_opened = True
            self.pos += 1
            pou_type = tok.value.upper()
            name_tok = self._expect(TokenType.IDENTIFIER, "Expected POU identifier")
            pou_name = name_tok.value

            if pou_type == "FUNCTION":
                if self._match(TokenType.COLON):
                    ret_tok = self._expect(TokenType.IDENTIFIER, "Expected function return type")
                    return_type = ret_tok.value.upper()

            # Strictly enforce IEC 61131-3: POU headers must not have a trailing semicolon
            if self._peek().type == TokenType.SEMICOLON:
                semi_tok = self._peek()
                raise ParseError(
                    f"IEC 61131-3 syntax error: {pou_type} header '{pou_name}' must not have a trailing semicolon",
                    semi_tok
                )

        # Parse variable blocks and nested type blocks
        var_blocks: List[VarBlockNode] = []
        while self._peek().type in (
            TokenType.VAR, TokenType.VAR_INPUT, TokenType.VAR_OUTPUT,
            TokenType.VAR_IN_OUT, TokenType.VAR_GLOBAL, TokenType.VAR_TEMP,
            TokenType.VAR_EXTERNAL, TokenType.VAR_STAT, TokenType.VAR_CONFIG,
            TokenType.TYPE
        ):
            if self._peek().type == TokenType.TYPE:
                type_blocks.append(self._parse_type_block())
            else:
                var_blocks.append(self._parse_var_block())

        # Parse body statements
        body: List[StatementNode] = []
        end_token_types = (
            TokenType.END_PROGRAM, TokenType.END_FUNCTION_BLOCK,
            TokenType.END_FUNCTION, TokenType.EOF
        )
        while self._peek().type not in end_token_types:
            stmt = self._parse_statement()
            if stmt:
                body.append(stmt)

        # Match closing POU keyword if opened
        if pou_opened:
            expected_end = {
                "PROGRAM": TokenType.END_PROGRAM,
                "FUNCTION_BLOCK": TokenType.END_FUNCTION_BLOCK,
                "FUNCTION": TokenType.END_FUNCTION,
            }.get(pou_type, TokenType.END_PROGRAM)
            self._expect(expected_end, f"Expected {expected_end.name} to close {pou_type} '{pou_name}'")
        elif self._peek().type in (TokenType.END_PROGRAM, TokenType.END_FUNCTION_BLOCK, TokenType.END_FUNCTION):
            self.pos += 1

        return ProgramNode(
            name=pou_name,
            pou_type=pou_type,
            return_type=return_type,
            var_blocks=var_blocks,
            body=body,
            type_blocks=type_blocks,
            loc=SourceLocation(tok.line, tok.col)
        )

    def _parse_type_block(self) -> TypeBlockNode:
        type_tok = self._expect(TokenType.TYPE, "Expected 'TYPE'")
        decls: List[TypeDeclNode] = []

        while self._peek().type != TokenType.END_TYPE and self._peek().type != TokenType.EOF:
            name_tok = self._expect(TokenType.IDENTIFIER, "Expected type identifier name in TYPE block")
            self._expect(TokenType.COLON, f"Expected ':' after type name '{name_tok.value}'")

            next_tok = self._peek()
            type_def: TypeDefNode

            if next_tok.type == TokenType.STRUCT:
                self.pos += 1
                members: List[VarDeclNode] = []
                while self._peek().type != TokenType.END_STRUCT and self._peek().type != TokenType.EOF:
                    m_name_tok = self._expect(TokenType.IDENTIFIER, "Expected member name in STRUCT")
                    self._expect(TokenType.COLON, f"Expected ':' after member name '{m_name_tok.value}'")
                    m_type_tok = self._expect(TokenType.IDENTIFIER, "Expected member type in STRUCT")
                    m_type = m_type_tok.value
                    m_init = None
                    if self._match(TokenType.ASSIGN):
                        m_init = self._parse_expression()
                    if self._peek().type == TokenType.SEMICOLON:
                        self.pos += 1
                    members.append(VarDeclNode(
                        name=m_name_tok.value,
                        data_type=m_type,
                        initial_value=m_init,
                        loc=SourceLocation(m_name_tok.line, m_name_tok.col)
                    ))
                self._expect(TokenType.END_STRUCT, "Expected 'END_STRUCT' to close STRUCT definition")
                type_def = StructTypeNode(members=members, loc=SourceLocation(next_tok.line, next_tok.col))
                if self._peek().type == TokenType.SEMICOLON:
                    self.pos += 1
            elif next_tok.type == TokenType.LPAREN:
                # Enum definition: (VAL1, VAL2, ...)
                self.pos += 1
                enum_vals: List[str] = []
                while True:
                    v_tok = self._expect(TokenType.IDENTIFIER, "Expected enum value identifier")
                    enum_vals.append(v_tok.value)
                    if self._match(TokenType.COMMA):
                        continue
                    break
                self._expect(TokenType.RPAREN, "Expected ')' to close enum value list")
                init_val = None
                if self._match(TokenType.ASSIGN):
                    init_tok = self._expect(TokenType.IDENTIFIER, "Expected default enum value")
                    init_val = init_tok.value
                type_def = EnumTypeNode(values=enum_vals, initial_value=init_val, loc=SourceLocation(next_tok.line, next_tok.col))
                if self._peek().type == TokenType.SEMICOLON:
                    self.pos += 1
            else:
                base_tok = self._expect(TokenType.IDENTIFIER, "Expected base type name")
                base_type = base_tok.value
                if self._peek().type == TokenType.LPAREN:
                    self.pos += 1
                    min_expr = self._parse_expression()
                    self._expect(TokenType.DOTDOT, "Expected '..' in subrange type definition")
                    max_expr = self._parse_expression()
                    self._expect(TokenType.RPAREN, "Expected ')' to close subrange definition")
                    sub_init = None
                    if self._match(TokenType.ASSIGN):
                        sub_init = self._parse_expression()
                    type_def = SubrangeTypeNode(
                        base_type=base_type,
                        min_val=min_expr,
                        max_val=max_expr,
                        initial_value=sub_init,
                        loc=SourceLocation(base_tok.line, base_tok.col)
                    )
                else:
                    alias_init = None
                    if self._match(TokenType.ASSIGN):
                        alias_init = self._parse_expression()
                    type_def = AliasTypeNode(
                        target_type=base_type,
                        initial_value=alias_init,
                        loc=SourceLocation(base_tok.line, base_tok.col)
                    )
                if self._peek().type == TokenType.SEMICOLON:
                    self.pos += 1

            decls.append(TypeDeclNode(
                name=name_tok.value,
                type_def=type_def,
                loc=SourceLocation(name_tok.line, name_tok.col)
            ))

        self._expect(TokenType.END_TYPE, "Expected 'END_TYPE' to close TYPE block")
        if self._peek().type == TokenType.SEMICOLON:
            self.pos += 1

        return TypeBlockNode(declarations=decls, loc=SourceLocation(type_tok.line, type_tok.col))

    def _parse_var_block(self) -> VarBlockNode:
        start_tok = self._peek()
        block_type = self.tokens[self.pos].value.upper()
        self.pos += 1

        retain = False
        non_retain = False
        constant = False

        while self._peek().type in (TokenType.RETAIN, TokenType.NON_RETAIN, TokenType.CONSTANT):
            mod_tok = self.tokens[self.pos]
            self.pos += 1
            if mod_tok.type == TokenType.RETAIN:
                retain = True
            elif mod_tok.type == TokenType.NON_RETAIN:
                non_retain = True
            elif mod_tok.type == TokenType.CONSTANT:
                constant = True

        decls: List[VarDeclNode] = []
        while self._peek().type != TokenType.END_VAR and self._peek().type != TokenType.EOF:
            names: List[str] = []
            loc = SourceLocation(self._peek().line, self._peek().col)

            name_tok = self._expect(TokenType.IDENTIFIER, "Expected variable name in VAR block")
            names.append(name_tok.value)

            while self._match(TokenType.COMMA):
                next_name = self._expect(TokenType.IDENTIFIER, "Expected identifier after comma")
                names.append(next_name.value)

            address = None
            if self._match(TokenType.AT):
                addr_tok = self._expect(TokenType.IDENTIFIER, "Expected memory location after AT")
                address = addr_tok.value

            self._expect(TokenType.COLON, "Expected ':' after variable name(s)")

            array_bounds = None
            if self._match(TokenType.ARRAY):
                self._expect(TokenType.LBRACKET, "Expected '[' after ARRAY")
                dims = []
                while True:
                    low_sign = -1 if self._match(TokenType.MINUS) else 1
                    low_tok = self._expect(TokenType.INT_LITERAL, "Expected array lower bound")
                    low_val = low_sign * int(low_tok.value)

                    self._expect(TokenType.DOTDOT, "Expected '..' in array range")

                    high_sign = -1 if self._match(TokenType.MINUS) else 1
                    high_tok = self._expect(TokenType.INT_LITERAL, "Expected array upper bound")
                    high_val = high_sign * int(high_tok.value)

                    dims.append((low_val, high_val))
                    if self._match(TokenType.COMMA):
                        continue
                    break

                self._expect(TokenType.RBRACKET, "Expected ']' after array bounds")
                self._expect(TokenType.OF, "Expected 'OF' after array definition")
                array_bounds = dims[0] if len(dims) == 1 else dims

            type_tok = self._expect(TokenType.IDENTIFIER, "Expected variable data type")
            data_type = type_tok.value.upper()

            init_val: Optional[ExpressionNode] = None
            if self._match(TokenType.ASSIGN):
                init_val = self._parse_expression()

            self._expect(TokenType.SEMICOLON, "Expected ';' after variable declaration")

            for name in names:
                decls.append(VarDeclNode(
                    name=name,
                    data_type=data_type,
                    initial_value=init_val,
                    array_bounds=array_bounds,
                    address=address,
                    loc=loc
                ))

        self._expect(TokenType.END_VAR, "Expected END_VAR to close variable block")
        return VarBlockNode(
            block_type=block_type,
            retain=retain,
            constant=constant,
            non_retain=non_retain,
            declarations=decls,
            loc=SourceLocation(start_tok.line, start_tok.col)
        )

    def _parse_statement(self) -> Optional[StatementNode]:
        tok = self._peek()
        if tok.type == TokenType.SEMICOLON:
            self.pos += 1
            return EmptyStatementNode(loc=SourceLocation(tok.line, tok.col))

        if tok.type == TokenType.IF:
            return self._parse_if_statement()
        elif tok.type == TokenType.CASE:
            return self._parse_case_statement()
        elif tok.type == TokenType.FOR:
            return self._parse_for_statement()
        elif tok.type == TokenType.WHILE:
            return self._parse_while_statement()
        elif tok.type == TokenType.REPEAT:
            return self._parse_repeat_statement()
        elif tok.type == TokenType.EXIT:
            self.pos += 1
            self._expect(TokenType.SEMICOLON, "Expected ';' after EXIT")
            return ExitNode(loc=SourceLocation(tok.line, tok.col))
        elif tok.type == TokenType.RETURN:
            self.pos += 1
            self._expect(TokenType.SEMICOLON, "Expected ';' after RETURN")
            return ReturnNode(loc=SourceLocation(tok.line, tok.col))
        elif tok.type == TokenType.CONTINUE:
            self.pos += 1
            self._expect(TokenType.SEMICOLON, "Expected ';' after CONTINUE")
            return ContinueNode(loc=SourceLocation(tok.line, tok.col))
        elif tok.type == TokenType.IDENTIFIER:
            loc = SourceLocation(tok.line, tok.col)
            expr = self._parse_primary()
            expr = self._parse_postfix(expr)

            if self._match(TokenType.ASSIGN):
                val_expr = self._parse_expression()
                self._expect(TokenType.SEMICOLON, "Expected ';' after assignment")
                return AssignmentNode(target=expr, value=val_expr, loc=loc)

            if isinstance(expr, FunctionCallNode):
                self._expect(TokenType.SEMICOLON, "Expected ';' after function/FB call")
                fb_target = VariableNode(expr.name, loc=expr.loc)
                args_dict: Dict[str, ExpressionNode] = {}
                for arg in expr.args:
                    if isinstance(arg, AssignmentNode):
                        if isinstance(arg.target, VariableNode):
                            args_dict[arg.target.name.upper()] = arg.value
                return FBInvocationNode(target=fb_target, args=args_dict, loc=loc)

            if isinstance(expr, VariableNode) and self._peek().type == TokenType.LPAREN:
                self.pos += 1  # consume '('
                args: Dict[str, ExpressionNode] = {}
                if self._peek().type != TokenType.RPAREN:
                    while True:
                        param_tok = self._expect(TokenType.IDENTIFIER, "Expected parameter name in FB invocation")
                        param_name = param_tok.value.upper()
                        self._expect(TokenType.ASSIGN, "Expected ':=' in parameter assignment")
                        val = self._parse_expression()
                        args[param_name] = val
                        if self._match(TokenType.COMMA):
                            continue
                        break
                self._expect(TokenType.RPAREN, "Expected ')' after FB parameters")
                self._expect(TokenType.SEMICOLON, "Expected ';' after FB invocation")
                return FBInvocationNode(target=expr, args=args, loc=loc)

            if self._match(TokenType.SEMICOLON):
                return EmptyStatementNode(loc=loc)

            raise ParseError(f"Unexpected statement syntax near '{tok.value}'", tok)

        raise ParseError(f"Unexpected token in statement: {tok.type.name} ('{tok.value}')", tok)

    def _parse_if_statement(self) -> IfNode:
        start_tok = self._expect(TokenType.IF)
        cond = self._parse_expression()
        self._expect(TokenType.THEN, "Expected 'THEN' after IF condition")

        then_body: List[StatementNode] = []
        while self._peek().type not in (TokenType.ELSIF, TokenType.ELSE, TokenType.END_IF, TokenType.EOF):
            stmt = self._parse_statement()
            if stmt:
                then_body.append(stmt)

        elsif_blocks: List[Tuple[ExpressionNode, List[StatementNode]]] = []
        while self._match(TokenType.ELSIF):
            elif_cond = self._parse_expression()
            self._expect(TokenType.THEN, "Expected 'THEN' after ELSIF condition")
            elif_body: List[StatementNode] = []
            while self._peek().type not in (TokenType.ELSIF, TokenType.ELSE, TokenType.END_IF, TokenType.EOF):
                stmt = self._parse_statement()
                if stmt:
                    elif_body.append(stmt)
            elsif_blocks.append((elif_cond, elif_body))

        else_body: Optional[List[StatementNode]] = None
        if self._match(TokenType.ELSE):
            else_body = []
            while self._peek().type not in (TokenType.END_IF, TokenType.EOF):
                stmt = self._parse_statement()
                if stmt:
                    else_body.append(stmt)

        self._expect(TokenType.END_IF, "Expected 'END_IF'")
        self._expect(TokenType.SEMICOLON, "Expected ';' after END_IF")
        return IfNode(
            condition=cond,
            then_body=then_body,
            elsif_blocks=elsif_blocks,
            else_body=else_body,
            loc=SourceLocation(start_tok.line, start_tok.col)
        )

    def _parse_case_statement(self) -> CaseNode:
        start_tok = self._expect(TokenType.CASE)
        selector = self._parse_expression()
        self._expect(TokenType.OF, "Expected 'OF' after CASE selector")

        cases: List[Tuple[List[Union[ExpressionNode, CaseRange]], List[StatementNode]]] = []
        else_body: Optional[List[StatementNode]] = None

        while self._peek().type not in (TokenType.END_CASE, TokenType.ELSE, TokenType.EOF):
            labels: List[Union[ExpressionNode, CaseRange]] = []
            while True:
                expr = self._parse_expression()
                if self._match(TokenType.DOTDOT):
                    end_expr = self._parse_expression()
                    labels.append(CaseRange(expr, end_expr))
                else:
                    labels.append(expr)

                if self._match(TokenType.COMMA):
                    continue
                break

            self._expect(TokenType.COLON, "Expected ':' after case label(s)")

            case_body: List[StatementNode] = []
            while self._peek().type not in (TokenType.END_CASE, TokenType.ELSE, TokenType.EOF):
                if self._is_case_label_start():
                    break
                stmt = self._parse_statement()
                if stmt:
                    case_body.append(stmt)
            cases.append((labels, case_body))

        if self._match(TokenType.ELSE):
            else_body = []
            while self._peek().type not in (TokenType.END_CASE, TokenType.EOF):
                stmt = self._parse_statement()
                if stmt:
                    else_body.append(stmt)

        self._expect(TokenType.END_CASE, "Expected 'END_CASE'")
        self._expect(TokenType.SEMICOLON, "Expected ';' after END_CASE")
        return CaseNode(
            selector=selector,
            cases=cases,
            else_body=else_body,
            loc=SourceLocation(start_tok.line, start_tok.col)
        )

    def _is_case_label_start(self) -> bool:
        t = self._peek().type
        if t in (TokenType.INT_LITERAL, TokenType.BOOL_LITERAL, TokenType.STRING_LITERAL):
            return True
        if t in (TokenType.MINUS, TokenType.PLUS):
            next_t = self._peek(1).type
            if next_t in (TokenType.INT_LITERAL, TokenType.REAL_LITERAL, TokenType.IDENTIFIER):
                return True
        if t == TokenType.IDENTIFIER:
            p1 = self._peek(1).type
            if p1 in (TokenType.COLON, TokenType.COMMA, TokenType.DOTDOT):
                return True
        return False

    def _parse_for_statement(self) -> ForNode:
        start_tok = self._expect(TokenType.FOR)
        var_tok = self._expect(TokenType.IDENTIFIER, "Expected loop variable in FOR")
        self._expect(TokenType.ASSIGN, "Expected ':=' after loop variable")
        start_expr = self._parse_expression()
        self._expect(TokenType.TO, "Expected 'TO' in FOR loop")
        end_expr = self._parse_expression()

        step_expr = None
        if self._match(TokenType.BY):
            step_expr = self._parse_expression()

        self._expect(TokenType.DO, "Expected 'DO' in FOR loop")

        body: List[StatementNode] = []
        while self._peek().type not in (TokenType.END_FOR, TokenType.EOF):
            stmt = self._parse_statement()
            if stmt:
                body.append(stmt)

        self._expect(TokenType.END_FOR, "Expected 'END_FOR'")
        self._expect(TokenType.SEMICOLON, "Expected ';' after END_FOR")
        return ForNode(
            var_name=var_tok.value,
            start_expr=start_expr,
            end_expr=end_expr,
            step_expr=step_expr,
            body=body,
            loc=SourceLocation(start_tok.line, start_tok.col)
        )

    def _parse_while_statement(self) -> WhileNode:
        start_tok = self._expect(TokenType.WHILE)
        cond = self._parse_expression()
        self._expect(TokenType.DO, "Expected 'DO' in WHILE loop")
        body: List[StatementNode] = []
        while self._peek().type not in (TokenType.END_WHILE, TokenType.EOF):
            stmt = self._parse_statement()
            if stmt:
                body.append(stmt)
        self._expect(TokenType.END_WHILE, "Expected 'END_WHILE'")
        self._expect(TokenType.SEMICOLON, "Expected ';' after END_WHILE")
        return WhileNode(condition=cond, body=body, loc=SourceLocation(start_tok.line, start_tok.col))

    def _parse_repeat_statement(self) -> RepeatNode:
        start_tok = self._expect(TokenType.REPEAT)
        body: List[StatementNode] = []
        while self._peek().type not in (TokenType.UNTIL, TokenType.EOF):
            stmt = self._parse_statement()
            if stmt:
                body.append(stmt)
        self._expect(TokenType.UNTIL, "Expected 'UNTIL' in REPEAT loop")
        cond = self._parse_expression()
        self._expect(TokenType.END_REPEAT, "Expected 'END_REPEAT'")
        self._expect(TokenType.SEMICOLON, "Expected ';' after END_REPEAT")
        return RepeatNode(condition=cond, body=body, loc=SourceLocation(start_tok.line, start_tok.col))

    # --- Expressions Parsing with Full Precedence ---

    def _parse_expression(self) -> ExpressionNode:
        return self._parse_or()

    def _parse_or(self) -> ExpressionNode:
        left = self._parse_xor()
        while self._peek().type == TokenType.OR:
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_xor()
            left = BinaryOpNode(op="OR", left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_xor(self) -> ExpressionNode:
        left = self._parse_and()
        while self._peek().type == TokenType.XOR:
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_and()
            left = BinaryOpNode(op="XOR", left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_and(self) -> ExpressionNode:
        left = self._parse_equality()
        while self._peek().type in (TokenType.AND, TokenType.AMPERSAND):
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_equality()
            left = BinaryOpNode(op="AND", left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_equality(self) -> ExpressionNode:
        left = self._parse_relational()
        while self._peek().type in (TokenType.EQ, TokenType.NEQ):
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_relational()
            op = "=" if op_tok.type == TokenType.EQ else "<>"
            left = BinaryOpNode(op=op, left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_relational(self) -> ExpressionNode:
        left = self._parse_additive()
        while self._peek().type in (TokenType.LT, TokenType.GT, TokenType.LE, TokenType.GE):
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_additive()
            left = BinaryOpNode(op=op_tok.value, left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_additive(self) -> ExpressionNode:
        left = self._parse_multiplicative()
        while self._peek().type in (TokenType.PLUS, TokenType.MINUS):
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_multiplicative()
            left = BinaryOpNode(op=op_tok.value, left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_multiplicative(self) -> ExpressionNode:
        left = self._parse_power()
        while self._peek().type in (TokenType.STAR, TokenType.SLASH, TokenType.MOD):
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_power()
            left = BinaryOpNode(op=op_tok.value.upper(), left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_power(self) -> ExpressionNode:
        left = self._parse_unary()
        while self._peek().type == TokenType.POWER:
            op_tok = self.tokens[self.pos]; self.pos += 1
            right = self._parse_unary()
            left = BinaryOpNode(op="**", left=left, right=right, loc=SourceLocation(op_tok.line, op_tok.col))
        return left

    def _parse_unary(self) -> ExpressionNode:
        tok = self._peek()
        if tok.type in (TokenType.NOT, TokenType.MINUS, TokenType.PLUS):
            self.pos += 1
            operand = self._parse_unary()
            return UnaryOpNode(op=tok.value.upper(), operand=operand, loc=SourceLocation(tok.line, tok.col))
        expr = self._parse_primary()
        return self._parse_postfix(expr)

    def _parse_postfix(self, expr: ExpressionNode) -> ExpressionNode:
        while True:
            if self._match(TokenType.DOT):
                mem_tok = self._expect(TokenType.IDENTIFIER, "Expected identifier after '.'")
                expr = MemberAccessNode(target=expr, member=mem_tok.value, loc=SourceLocation(mem_tok.line, mem_tok.col))
                continue
            if self._match(TokenType.LBRACKET):
                indices = [self._parse_expression()]
                while self._match(TokenType.COMMA):
                    indices.append(self._parse_expression())
                self._expect(TokenType.RBRACKET, "Expected ']' after array index")
                if len(indices) == 1:
                    expr = ArrayAccessNode(target=expr, index=indices[0], loc=expr.loc)
                else:
                    expr = ArrayAccessNode(target=expr, index=indices[0], indices=indices, loc=expr.loc)
                continue
            break
        return expr

    def _parse_primary(self) -> ExpressionNode:
        tok = self._peek()
        loc = SourceLocation(tok.line, tok.col)

        if self._match(TokenType.LPAREN):
            expr = self._parse_expression()
            self._expect(TokenType.RPAREN, "Expected ')' after expression")
            return expr

        if self._match(TokenType.BOOL_LITERAL):
            return LiteralNode(value=bool(tok.value), data_type="BOOL", loc=loc)
        if self._match(TokenType.INT_LITERAL):
            return LiteralNode(value=int(tok.value), data_type="INT", loc=loc)
        if self._match(TokenType.REAL_LITERAL):
            return LiteralNode(value=float(tok.value), data_type="REAL", loc=loc)
        if self._match(TokenType.TIME_LITERAL):
            return LiteralNode(value=float(tok.value), data_type="TIME", loc=loc)
        if self._match(TokenType.DATE_LITERAL):
            return LiteralNode(value=str(tok.value), data_type="DATE", loc=loc)
        if self._match(TokenType.TOD_LITERAL):
            return LiteralNode(value=str(tok.value), data_type="TOD", loc=loc)
        if self._match(TokenType.DT_LITERAL):
            return LiteralNode(value=str(tok.value), data_type="DT", loc=loc)
        if self._match(TokenType.STRING_LITERAL):
            return LiteralNode(value=str(tok.value), data_type="STRING", loc=loc)

        if self._match(TokenType.IDENTIFIER):
            name = tok.value
            if self._match(TokenType.LPAREN):
                args: List[ExpressionNode] = []
                if self._peek().type != TokenType.RPAREN:
                    while True:
                        if self._peek().type == TokenType.IDENTIFIER and self._peek(1).type == TokenType.ASSIGN:
                            p_tok = self._expect(TokenType.IDENTIFIER)
                            self._expect(TokenType.ASSIGN)
                            val = self._parse_expression()
                            args.append(AssignmentNode(
                                target=VariableNode(p_tok.value, loc=SourceLocation(p_tok.line, p_tok.col)),
                                value=val,
                                loc=SourceLocation(p_tok.line, p_tok.col)
                            ))
                        else:
                            args.append(self._parse_expression())

                        if self._match(TokenType.COMMA):
                            continue
                        break
                self._expect(TokenType.RPAREN, "Expected ')' after function arguments")
                return FunctionCallNode(name=name, args=args, loc=loc)

            return VariableNode(name=name, loc=loc)

        raise ParseError(f"Unexpected token in expression: {tok.type.name} ('{tok.value}')", tok)
