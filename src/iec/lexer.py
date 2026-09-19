"""
IEC 61131-3 Structured Text Lexer.
Provides full tokenization of IEC 61131-3 Structured Text (2nd & 3rd Editions):
- Keywords: POU definitions (PROGRAM, FUNCTION_BLOCK, FUNCTION, TYPE, STRUCT, CONFIGURATION, RESOURCE)
- Variable scopes: VAR, VAR_INPUT, VAR_OUTPUT, VAR_IN_OUT, VAR_GLOBAL, VAR_TEMP, VAR_EXTERNAL, VAR_STAT, VAR_CONFIG
- Qualifiers: RETAIN, NON_RETAIN, CONSTANT, AT
- Control flow: IF, THEN, ELSIF, ELSE, END_IF, CASE, OF, END_CASE, FOR, TO, BY, DO, END_FOR, WHILE, END_WHILE, REPEAT, UNTIL, END_REPEAT, EXIT, RETURN, CONTINUE
- Operators: AND, &, OR, XOR, NOT, MOD, **, +, -, *, /, =, <>, <, >, <=, >=, :=, ..
- Literals: Typed and untyped integers (dec, bin 2#.., oct 8#.., hex 16#..), reals, booleans, time (T#..), date (D#..), time-of-day (TOD#..), date-and-time (DT#..), strings ('..', "..")
- Comments: Standard nested block (* ... *), single-line //, and C-style /* ... */
"""
import re
from enum import Enum, auto
from typing import List, Optional, Any, NamedTuple


class LexerError(SyntaxError):
    """Raised when the lexer encounters an unexpected or illegal character."""
    pass


class TokenType(Enum):
    # POU Keywords
    PROGRAM = auto()
    END_PROGRAM = auto()
    FUNCTION_BLOCK = auto()
    END_FUNCTION_BLOCK = auto()
    FUNCTION = auto()
    END_FUNCTION = auto()
    CONFIGURATION = auto()
    END_CONFIGURATION = auto()
    RESOURCE = auto()
    END_RESOURCE = auto()
    TYPE = auto()
    END_TYPE = auto()
    STRUCT = auto()
    END_STRUCT = auto()

    # Variable Scopes
    VAR = auto()
    VAR_INPUT = auto()
    VAR_OUTPUT = auto()
    VAR_IN_OUT = auto()
    VAR_GLOBAL = auto()
    VAR_TEMP = auto()
    VAR_EXTERNAL = auto()
    VAR_STAT = auto()
    VAR_CONFIG = auto()
    END_VAR = auto()

    # Qualifiers & Modifiers
    RETAIN = auto()
    NON_RETAIN = auto()
    CONSTANT = auto()
    AT = auto()

    # Types & Declarations
    ARRAY = auto()
    OF = auto()

    # Control Flow
    IF = auto()
    THEN = auto()
    ELSIF = auto()
    ELSE = auto()
    END_IF = auto()
    CASE = auto()
    END_CASE = auto()
    FOR = auto()
    TO = auto()
    BY = auto()
    DO = auto()
    END_FOR = auto()
    WHILE = auto()
    END_WHILE = auto()
    REPEAT = auto()
    UNTIL = auto()
    END_REPEAT = auto()
    EXIT = auto()
    RETURN = auto()
    CONTINUE = auto()

    # Logical / Arithmetic Keywords
    AND = auto()
    OR = auto()
    XOR = auto()
    NOT = auto()
    MOD = auto()

    # Literals
    BOOL_LITERAL = auto()
    INT_LITERAL = auto()
    REAL_LITERAL = auto()
    TIME_LITERAL = auto()
    DATE_LITERAL = auto()
    TOD_LITERAL = auto()
    DT_LITERAL = auto()
    STRING_LITERAL = auto()
    IDENTIFIER = auto()

    # Operators & Delimiters
    ASSIGN = auto()       # :=
    DOTDOT = auto()       # ..
    DOT = auto()          # .
    COMMA = auto()        # ,
    SEMICOLON = auto()    # ;
    COLON = auto()        # :
    LPAREN = auto()       # (
    RPAREN = auto()       # )
    LBRACKET = auto()     # [
    RBRACKET = auto()     # ]
    PLUS = auto()         # +
    MINUS = auto()        # -
    POWER = auto()        # **
    STAR = auto()         # *
    SLASH = auto()        # /
    EQ = auto()           # =
    NEQ = auto()          # <>
    LE = auto()           # <=
    GE = auto()           # >=
    LT = auto()           # <
    GT = auto()           # >
    AMPERSAND = auto()    # &

    EOF = auto()


KEYWORDS = {
    # POU
    "PROGRAM": TokenType.PROGRAM,
    "END_PROGRAM": TokenType.END_PROGRAM,
    "FUNCTION_BLOCK": TokenType.FUNCTION_BLOCK,
    "END_FUNCTION_BLOCK": TokenType.END_FUNCTION_BLOCK,
    "FUNCTION": TokenType.FUNCTION,
    "END_FUNCTION": TokenType.END_FUNCTION,
    "CONFIGURATION": TokenType.CONFIGURATION,
    "END_CONFIGURATION": TokenType.END_CONFIGURATION,
    "RESOURCE": TokenType.RESOURCE,
    "END_RESOURCE": TokenType.END_RESOURCE,
    "TYPE": TokenType.TYPE,
    "END_TYPE": TokenType.END_TYPE,
    "STRUCT": TokenType.STRUCT,
    "END_STRUCT": TokenType.END_STRUCT,

    # Scopes
    "VAR": TokenType.VAR,
    "VAR_INPUT": TokenType.VAR_INPUT,
    "VAR_OUTPUT": TokenType.VAR_OUTPUT,
    "VAR_IN_OUT": TokenType.VAR_IN_OUT,
    "VAR_GLOBAL": TokenType.VAR_GLOBAL,
    "VAR_TEMP": TokenType.VAR_TEMP,
    "VAR_EXTERNAL": TokenType.VAR_EXTERNAL,
    "VAR_STAT": TokenType.VAR_STAT,
    "VAR_CONFIG": TokenType.VAR_CONFIG,
    "END_VAR": TokenType.END_VAR,

    # Qualifiers
    "RETAIN": TokenType.RETAIN,
    "NON_RETAIN": TokenType.NON_RETAIN,
    "CONSTANT": TokenType.CONSTANT,
    "AT": TokenType.AT,

    # Types & Declarations
    "ARRAY": TokenType.ARRAY,
    "OF": TokenType.OF,

    # Control flow
    "IF": TokenType.IF,
    "THEN": TokenType.THEN,
    "ELSIF": TokenType.ELSIF,
    "ELSE": TokenType.ELSE,
    "END_IF": TokenType.END_IF,
    "CASE": TokenType.CASE,
    "END_CASE": TokenType.END_CASE,
    "FOR": TokenType.FOR,
    "TO": TokenType.TO,
    "BY": TokenType.BY,
    "DO": TokenType.DO,
    "END_FOR": TokenType.END_FOR,
    "WHILE": TokenType.WHILE,
    "END_WHILE": TokenType.END_WHILE,
    "REPEAT": TokenType.REPEAT,
    "UNTIL": TokenType.UNTIL,
    "END_REPEAT": TokenType.END_REPEAT,
    "EXIT": TokenType.EXIT,
    "RETURN": TokenType.RETURN,
    "CONTINUE": TokenType.CONTINUE,

    # Logical / Arithmetic
    "AND": TokenType.AND,
    "OR": TokenType.OR,
    "XOR": TokenType.XOR,
    "NOT": TokenType.NOT,
    "MOD": TokenType.MOD,
    "TRUE": TokenType.BOOL_LITERAL,
    "FALSE": TokenType.BOOL_LITERAL,
}

INTEGER_TYPE_NAMES = {
    "SINT", "INT", "DINT", "LINT",
    "USINT", "UINT", "UDINT", "ULINT",
    "BYTE", "WORD", "DWORD", "LWORD",
}

REAL_TYPE_NAMES = {"REAL", "LREAL"}


class Token(NamedTuple):
    type: TokenType
    value: Any
    line: int
    col: int


def parse_time_literal_ms(raw: str) -> float:
    """
    Parse an IEC 61131-3 time literal (e.g., T#1h2m3s400ms, TIME#500ms, t#2.5s, -t#100ms) to milliseconds.
    """
    s = raw.strip().upper()
    is_negative = False
    if s.startswith("-"):
        is_negative = True
        s = s[1:]
    elif s.startswith("+"):
        s = s[1:]

    if s.startswith("TIME#"):
        s = s[5:]
    elif s.startswith("T#"):
        s = s[2:]

    total_ms = 0.0
    pattern = re.compile(r'([\d\.]+)\s*(MS|US|NS|D|H|M|S)', re.IGNORECASE)
    matches = pattern.findall(s)
    if not matches:
        try:
            val = float(s)
            return -val if is_negative else val
        except ValueError:
            return 0.0

    for val_str, unit in matches:
        val = float(val_str)
        u = unit.upper()
        if u == "D":
            total_ms += val * 86400000.0
        elif u == "H":
            total_ms += val * 3600000.0
        elif u == "M":
            total_ms += val * 60000.0
        elif u == "S":
            total_ms += val * 1000.0
        elif u == "MS":
            total_ms += val
        elif u == "US":
            total_ms += val * 0.001
        elif u == "NS":
            total_ms += val * 0.000001

    return -total_ms if is_negative else total_ms


class Lexer:
    """IEC 61131-3 Structured Text Lexer."""

    def __init__(self, source: str):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.length = len(source)

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        if idx < self.length:
            return self.source[idx]
        return '\0'

    def _advance(self) -> str:
        ch = self._peek()
        self.pos += 1
        if ch == '\n':
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _skip_whitespace_and_comments(self):
        while self.pos < self.length:
            ch = self._peek()
            if ch.isspace():
                self._advance()
                continue

            if ch == '/' and self._peek(1) == '/':
                self._advance()
                self._advance()
                while self._peek() not in ('\n', '\0'):
                    self._advance()
                continue

            if ch == '/' and self._peek(1) == '*':
                self._advance()
                self._advance()
                while self.pos < self.length:
                    if self._peek() == '*' and self._peek(1) == '/':
                        self._advance()
                        self._advance()
                        break
                    self._advance()
                continue

            if ch == '(' and self._peek(1) == '*':
                self._advance()
                self._advance()
                depth = 1
                while depth > 0 and self._peek() != '\0':
                    if self._peek() == '(' and self._peek(1) == '*':
                        depth += 1
                        self._advance()
                        self._advance()
                    elif self._peek() == '*' and self._peek(1) == ')':
                        depth -= 1
                        self._advance()
                        self._advance()
                    else:
                        self._advance()
                continue

            break

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []
        while True:
            self._skip_whitespace_and_comments()
            if self.pos >= self.length:
                tokens.append(Token(TokenType.EOF, None, self.line, self.col))
                break

            start_line = self.line
            start_col = self.col
            ch = self._peek()

            # Time literal starting with T# or TIME#
            if (ch in ('T', 't') and self._peek(1) == '#') or \
               (self.source[self.pos:self.pos+5].upper() == "TIME#"):
                time_str = ""
                while self.pos < self.length and not (self._peek() in (';', ')', ',', ' ', '\t', '\r', '\n')):
                    time_str += self._advance()
                ms_val = parse_time_literal_ms(time_str)
                tokens.append(Token(TokenType.TIME_LITERAL, ms_val, start_line, start_col))
                continue

            # Two-character symbols
            two_ch = ch + self._peek(1)
            if two_ch == ':=':
                self._advance(); self._advance()
                tokens.append(Token(TokenType.ASSIGN, ':=', start_line, start_col))
                continue
            elif two_ch == '..':
                self._advance(); self._advance()
                tokens.append(Token(TokenType.DOTDOT, '..', start_line, start_col))
                continue
            elif two_ch == '<=':
                self._advance(); self._advance()
                tokens.append(Token(TokenType.LE, '<=', start_line, start_col))
                continue
            elif two_ch == '>=':
                self._advance(); self._advance()
                tokens.append(Token(TokenType.GE, '>=', start_line, start_col))
                continue
            elif two_ch == '<>':
                self._advance(); self._advance()
                tokens.append(Token(TokenType.NEQ, '<>', start_line, start_col))
                continue
            elif two_ch == '**':
                self._advance(); self._advance()
                tokens.append(Token(TokenType.POWER, '**', start_line, start_col))
                continue

            # Single-character symbols
            if ch == '=':
                self._advance()
                tokens.append(Token(TokenType.EQ, '=', start_line, start_col))
                continue
            elif ch == '<':
                self._advance()
                tokens.append(Token(TokenType.LT, '<', start_line, start_col))
                continue
            elif ch == '>':
                self._advance()
                tokens.append(Token(TokenType.GT, '>', start_line, start_col))
                continue
            elif ch == '+':
                self._advance()
                tokens.append(Token(TokenType.PLUS, '+', start_line, start_col))
                continue
            elif ch == '-':
                self._advance()
                tokens.append(Token(TokenType.MINUS, '-', start_line, start_col))
                continue
            elif ch == '*':
                self._advance()
                tokens.append(Token(TokenType.STAR, '*', start_line, start_col))
                continue
            elif ch == '/':
                self._advance()
                tokens.append(Token(TokenType.SLASH, '/', start_line, start_col))
                continue
            elif ch == ':':
                self._advance()
                tokens.append(Token(TokenType.COLON, ':', start_line, start_col))
                continue
            elif ch == ';':
                self._advance()
                tokens.append(Token(TokenType.SEMICOLON, ';', start_line, start_col))
                continue
            elif ch == ',':
                self._advance()
                tokens.append(Token(TokenType.COMMA, ',', start_line, start_col))
                continue
            elif ch == '.':
                self._advance()
                tokens.append(Token(TokenType.DOT, '.', start_line, start_col))
                continue
            elif ch == '(':
                self._advance()
                tokens.append(Token(TokenType.LPAREN, '(', start_line, start_col))
                continue
            elif ch == ')':
                self._advance()
                tokens.append(Token(TokenType.RPAREN, ')', start_line, start_col))
                continue
            elif ch == '[':
                self._advance()
                tokens.append(Token(TokenType.LBRACKET, '[', start_line, start_col))
                continue
            elif ch == ']':
                self._advance()
                tokens.append(Token(TokenType.RBRACKET, ']', start_line, start_col))
                continue
            elif ch == '&':
                self._advance()
                tokens.append(Token(TokenType.AND, 'AND', start_line, start_col))
                continue

            # Strings: '...' (standard IEC STRING) or "..." (WSTRING)
            if ch in ("'", '"'):
                quote = ch
                self._advance()
                str_val = ""
                while self.pos < self.length and self._peek() != quote:
                    if self._peek() == '$':
                        self._advance()
                        next_ch = self._peek()
                        if next_ch == '$':
                            str_val += '$'; self._advance()
                        elif next_ch == "'":
                            str_val += "'"; self._advance()
                        elif next_ch == '"':
                            str_val += '"'; self._advance()
                        elif next_ch in ('L', 'l'):
                            str_val += '\n'; self._advance()
                        elif next_ch in ('N', 'n'):
                            str_val += '\n'; self._advance()
                        elif next_ch in ('P', 'p'):
                            str_val += '\f'; self._advance()
                        elif next_ch in ('R', 'r'):
                            str_val += '\r'; self._advance()
                        elif next_ch in ('T', 't'):
                            str_val += '\t'; self._advance()
                        else:
                            str_val += '$'
                    elif self._peek() == '\\' and self._peek(1) != '\0':
                        self._advance()
                        str_val += self._advance()
                    else:
                        str_val += self._advance()
                if self.pos < self.length and self._peek() == quote:
                    self._advance()
                tokens.append(Token(TokenType.STRING_LITERAL, str_val, start_line, start_col))
                continue

            # Direct address literal: %IX0.0, %QX0.0, %MW100, %R100 etc.
            if ch == '%':
                addr_str = self._advance()
                while self.pos < self.length and (self._peek().isalnum() or self._peek() in ('.', '_', '*')):
                    addr_str += self._advance()
                tokens.append(Token(TokenType.IDENTIFIER, addr_str, start_line, start_col))
                continue

            # Numbers (Hex 16#..., Binary 2#..., Octal 8#..., Float, or Integer)
            if ch.isdigit():
                num_str = ""
                while self.pos < self.length and (self._peek().isalnum() or self._peek() in ('#', '_', '.')):
                    if self._peek() == '.' and self._peek(1) == '.':
                        break
                    num_str += self._advance()

                clean = num_str.replace('_', '')
                if '#' in clean:
                    base_str, val_str = clean.split('#', 1)
                    base = int(base_str)
                    val = int(val_str, base)
                    tokens.append(Token(TokenType.INT_LITERAL, val, start_line, start_col))
                elif '.' in clean or ('e' in clean.lower() and not clean.startswith('0x')):
                    val = float(clean)
                    tokens.append(Token(TokenType.REAL_LITERAL, val, start_line, start_col))
                else:
                    val = int(clean)
                    tokens.append(Token(TokenType.INT_LITERAL, val, start_line, start_col))
                continue

            # Identifiers, Keywords, and Typed Literals
            if ch.isalpha() or ch == '_':
                ident = ""
                while self.pos < self.length and (self._peek().isalnum() or self._peek() == '_'):
                    ident += self._advance()

                upper_ident = ident.upper()

                if self._peek() == '#':
                    self._advance()
                    prefix = upper_ident

                    if prefix in ("TIME", "T"):
                        time_body = ""
                        while self.pos < self.length and not (self._peek() in (';', ')', ',', ' ', '\t', '\r', '\n')):
                            time_body += self._advance()
                        ms_val = parse_time_literal_ms(prefix + "#" + time_body)
                        tokens.append(Token(TokenType.TIME_LITERAL, ms_val, start_line, start_col))
                        continue
                    elif prefix in ("DATE", "D"):
                        date_body = ""
                        while self.pos < self.length and not (self._peek() in (';', ')', ',', ' ', '\t', '\r', '\n')):
                            date_body += self._advance()
                        tokens.append(Token(TokenType.DATE_LITERAL, date_body, start_line, start_col))
                        continue
                    elif prefix in ("TIME_OF_DAY", "TOD"):
                        tod_body = ""
                        while self.pos < self.length and not (self._peek() in (';', ')', ',', ' ', '\t', '\r', '\n')):
                            tod_body += self._advance()
                        tokens.append(Token(TokenType.TOD_LITERAL, tod_body, start_line, start_col))
                        continue
                    elif prefix in ("DATE_AND_TIME", "DT"):
                        dt_body = ""
                        while self.pos < self.length and not (self._peek() in (';', ')', ',', ' ', '\t', '\r', '\n')):
                            dt_body += self._advance()
                        tokens.append(Token(TokenType.DT_LITERAL, dt_body, start_line, start_col))
                        continue
                    elif prefix == "BOOL":
                        bool_body = ""
                        while self.pos < self.length and (self._peek().isalnum() or self._peek() == '_'):
                            bool_body += self._advance()
                        b_val = (bool_body.upper() in ("1", "TRUE"))
                        tokens.append(Token(TokenType.BOOL_LITERAL, b_val, start_line, start_col))
                        continue
                    elif prefix in REAL_TYPE_NAMES:
                        num_str = ""
                        while self.pos < self.length and (self._peek().isalnum() or self._peek() in ('.', '+', '-', '_')):
                            num_str += self._advance()
                        tokens.append(Token(TokenType.REAL_LITERAL, float(num_str.replace('_', '')), start_line, start_col))
                        continue
                    elif prefix in INTEGER_TYPE_NAMES:
                        num_str = ""
                        while self.pos < self.length and (self._peek().isalnum() or self._peek() in ('#', '_', '+', '-')):
                            num_str += self._advance()
                        clean_val = num_str.replace('_', '')
                        if '#' in clean_val:
                            base_str, val_str = clean_val.split('#', 1)
                            val = int(val_str, int(base_str))
                        else:
                            val = int(clean_val)
                        tokens.append(Token(TokenType.INT_LITERAL, val, start_line, start_col))
                        continue
                    elif prefix in ("STRING", "WSTRING"):
                        quote = self._peek()
                        if quote in ("'", '"'):
                            self._advance()
                            str_val = ""
                            while self.pos < self.length and self._peek() != quote:
                                str_val += self._advance()
                            if self.pos < self.length and self._peek() == quote:
                                self._advance()
                            tokens.append(Token(TokenType.STRING_LITERAL, str_val, start_line, start_col))
                            continue

                if upper_ident in KEYWORDS:
                    ttype = KEYWORDS[upper_ident]
                    if ttype == TokenType.BOOL_LITERAL:
                        tokens.append(Token(ttype, upper_ident == "TRUE", start_line, start_col))
                    else:
                        tokens.append(Token(ttype, upper_ident, start_line, start_col))
                else:
                    tokens.append(Token(TokenType.IDENTIFIER, ident, start_line, start_col))
                continue

            unknown_ch = self._advance()
            raise LexerError(f"Unexpected character '{unknown_ch}' at line {start_line}, col {start_col}")

        return tokens
