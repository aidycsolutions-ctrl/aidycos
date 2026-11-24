"""Expression engine for the AidyCOS calculator.

Accepts both ``.`` and ``,`` as the decimal separator, ``× ÷ − √`` and the
usual ASCII operators. A trailing ``%`` is a percent of the value on the
left of ``+`` or ``−`` (so ``200+10%`` is 220) and a fraction in any other
position (so ``50%`` is 0.5).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    localcontext,
)

PI = Decimal("3.1415926535897932384626433832795")
E = Decimal("2.7182818284590452353602874713527")

_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?|\d*[.,]\d+(?:[eE][+-]?\d+)?")
_OP_MAP = {"×": "*", "÷": "/", "−": "-", ":": "/", "–": "-"}
_MAX_LEN = 1000


class CalcError(Exception):
    """A user-facing calculator error.

    ``incomplete`` is true while the expression is still being typed
    (trailing operator, open parenthesis, function without an argument).
    """

    def __init__(self, message: str, *, incomplete: bool = False) -> None:
        super().__init__(message)
        self.incomplete = incomplete


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int


@dataclass(frozen=True)
class Num:
    value: Decimal
    start: int
    end: int


@dataclass(frozen=True)
class Const:
    name: str
    start: int
    end: int


@dataclass(frozen=True)
class Unary:
    op: str
    inner: object
    start: int
    end: int


@dataclass(frozen=True)
class Percent:
    inner: object
    start: int
    end: int


@dataclass(frozen=True)
class Group:
    inner: object
    start: int
    end: int


@dataclass(frozen=True)
class Bin:
    op: str
    left: object
    right: object
    start: int
    end: int


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple
    start: int
    end: int


Node = Num | Const | Unary | Percent | Group | Bin | Call

_ALIASES = {
    "sen": "sin",
    "tg": "tan",
    "arcsin": "asin",
    "arcsen": "asin",
    "arccos": "acos",
    "arctan": "atan",
    "arctg": "atan",
    "raiz": "sqrt",
    "raíz": "sqrt",
    "factorial": "fact",
}

_FUNCTIONS = frozenset(
    {
        "sin",
        "cos",
        "tan",
        "asin",
        "acos",
        "atan",
        "sinh",
        "cosh",
        "tanh",
        "sqrt",
        "cbrt",
        "ln",
        "log",
        "log10",
        "log2",
        "abs",
        "fact",
        "exp",
        "floor",
        "ceil",
        "round",
        "mod",
    }
)


def _canonicalize(name: str) -> str:
    key = name.casefold()
    mapped = _ALIASES.get(key, key)
    return mapped if mapped in _FUNCTIONS else key


@dataclass
class Context:
    angle: str = "deg"
    ans: Decimal | None = None
    memory: Decimal = Decimal(0)


def tokenize(source: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char in "()":
            kind = "lparen" if char == "(" else "rparen"
            tokens.append(_Token(kind, char, index, index + 1))
            index += 1
            continue
        if char == ";":
            tokens.append(_Token("semi", char, index, index + 1))
            index += 1
            continue
        if char == "*" and index + 1 < length and source[index + 1] == "*":
            tokens.append(_Token("op", "^", index, index + 2))
            index += 2
            continue
        if char in "+-*/^%!×÷−–:√":
            tokens.append(_Token("op", _OP_MAP.get(char, char), index, index + 1))
            index += 1
            continue
        if char.isdigit() or (
            char in ".," and index + 1 < length and source[index + 1].isdigit()
        ):
            match = _NUM_RE.match(source, index)
            if match is None:
                raise CalcError(f"No entiendo «{char}»")
            tokens.append(
                _Token("num", match.group().replace(",", "."), index, match.end())
            )
            index = match.end()
            continue
        if char.isalpha() or char in "_π":
            end = index + 1
            while end < length and (source[end].isalnum() or source[end] in "_π"):
                end += 1
            tokens.append(_Token("id", source[index:end], index, end))
            index = end
            continue
        raise CalcError(f"No entiendo «{char}»")
    return tokens


class _Parser:
    def __init__(self, source: str, tokens: list[_Token]) -> None:
        self.source = source
        self.tokens = tokens
        self.index = 0

    def peek(self) -> _Token | None:
        if self.index >= len(self.tokens):
            return None
        return self.tokens[self.index]

    def advance(self) -> _Token:
        token = self.peek()
        if token is None:
            raise CalcError("Expresión incompleta", incomplete=True)
        self.index += 1
        return token

    def parse(self) -> Node:
        if not self.tokens:
            raise CalcError("Escribe una operación", incomplete=True)
        node = self.parse_expr()
        extra = self.peek()
        if extra is not None:
            raise CalcError(f"No entiendo «{self.source[extra.start:extra.end]}»")
        return node

    def parse_expr(self) -> Node:
        node = self.parse_term()
        while True:
            token = self.peek()
            if token is None or token.kind != "op" or token.value not in {"+", "-"}:
                return node
            self.advance()
            right = self.parse_term()
            node = Bin(token.value, node, right, node.start, right.end)

    def parse_term(self) -> Node:
        node = self.parse_factor()
        while True:
            token = self.peek()
            if token is not None and token.kind == "op" and token.value in {"*", "/"}:
                self.advance()
                right = self.parse_factor()
                node = Bin(token.value, node, right, node.start, right.end)
                continue
            if _starts_primary(token):
                right = self.parse_factor()
                node = Bin("*", node, right, node.start, right.end)
                continue
            return node

    def parse_factor(self) -> Node:
        token = self.peek()
        if token is not None and token.kind == "op" and token.value in {"+", "-"}:
            self.advance()
            inner = self.parse_factor()
            if token.value == "+":
                return inner
            return Unary("-", inner, token.start, inner.end)
        if token is not None and token.kind == "op" and token.value == "√":
            self.advance()
            inner = self.parse_factor()
            return Call("sqrt", (inner,), token.start, inner.end)
        return self.parse_power()

    def parse_power(self) -> Node:
        base = self.parse_postfix()
        token = self.peek()
        if token is not None and token.kind == "op" and token.value == "^":
            self.advance()
            exponent = self.parse_factor()
            return Bin("^", base, exponent, base.start, exponent.end)
        return base

    def parse_postfix(self) -> Node:
        node = self.parse_primary()
        while True:
            token = self.peek()
            if token is not None and token.kind == "op" and token.value == "%":
                self.advance()
                node = Percent(node, node.start, token.end)
                continue
            if token is not None and token.kind == "op" and token.value == "!":
                self.advance()
                node = Call("fact", (node,), node.start, token.end)
                continue
            return node

    def parse_primary(self) -> Node:
        token = self.peek()
        if token is None:
            raise CalcError("Expresión incompleta", incomplete=True)
        if token.kind == "num":
            self.advance()
            return Num(Decimal(token.value), token.start, token.end)
        if token.kind == "id":
            return self.parse_name()
        if token.kind == "lparen":
            start = token.start
            self.advance()
            inner = self.parse_expr()
            closing = self.peek()
            if closing is None or closing.kind != "rparen":
                raise CalcError("Falta cerrar el paréntesis", incomplete=True)
            self.advance()
            return Group(inner, start, closing.end)
        raise CalcError(f"No entiendo «{self.source[token.start:token.end]}»")

    def parse_name(self) -> Node:
        token = self.advance()
        name = _canonicalize(token.value)
        if name not in _FUNCTIONS:
            return Const(name, token.start, token.end)
        nxt = self.peek()
        if nxt is not None and nxt.kind == "lparen":
            self.advance()
            args = [self.parse_expr()]
            while self.peek() is not None and self.peek().kind == "semi":
                self.advance()
                args.append(self.parse_expr())
            closing = self.peek()
            if closing is None or closing.kind != "rparen":
                raise CalcError("Falta cerrar el paréntesis", incomplete=True)
            self.advance()
            return Call(name, tuple(args), token.start, closing.end)
        if _starts_primary(nxt):
            arg = self.parse_factor()
            return Call(name, (arg,), token.start, arg.end)
        if nxt is None:
            raise CalcError(f"Falta el argumento de {token.value}", incomplete=True)
        raise CalcError(f"Falta el argumento de {token.value}")


def _starts_primary(token: _Token | None) -> bool:
    return token is not None and token.kind in {"num", "id", "lparen"}


def parse(expression: str) -> Node:
    if len(expression) > _MAX_LEN:
        raise CalcError("Expresión demasiado larga")
    if not expression.strip():
        raise CalcError("Escribe una operación", incomplete=True)
    return _Parser(expression, tokenize(expression)).parse()


def repeat_suffix(expression: str) -> tuple[str, str] | None:
    """Return ``(op, rhs_source)`` when the expression is a top-level operation."""
    node = parse(expression)
    if isinstance(node, Bin):
        return node.op, expression[node.right.start : node.right.end]
    return None


def evaluate(
    expression: str,
    *,
    angle: str = "deg",
    ans: Decimal | str | None = None,
    memory: Decimal | str | None = None,
) -> Decimal:
    if angle not in {"deg", "rad"}:
        raise CalcError("Unidad de ángulo desconocida")
    context = Context(
        angle=angle,
        ans=_optional_decimal(ans),
        memory=_optional_decimal(memory) or Decimal(0),
    )
    node = parse(expression)
    with localcontext() as decimal_ctx:
        decimal_ctx.prec = 50
        decimal_ctx.traps[DivisionByZero] = True
        decimal_ctx.traps[InvalidOperation] = True
        decimal_ctx.traps[Overflow] = True
        try:
            return _eval(node, context)
        except DivisionByZero as exc:
            raise CalcError("División por cero") from exc
        except (InvalidOperation, Overflow) as exc:
            raise CalcError("Número demasiado grande") from exc


def format_number(value: Decimal) -> str:
    if not isinstance(value, Decimal):
        value = Decimal(value)
    if not value.is_finite():
        raise CalcError("Resultado no numérico")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    magnitude = abs(value)
    exponent = magnitude.adjusted()
    if exponent >= 12 or exponent <= -7:
        mantissa, exp_text = f"{magnitude:.10e}".split("e")
        mantissa = mantissa.rstrip("0").rstrip(".")
        return f"{sign}{mantissa}e{int(exp_text)}"
    quantized = magnitude.quantize(Decimal("1e-12"), rounding=ROUND_HALF_EVEN)
    text = format(quantized, "f").rstrip("0").rstrip(".")
    return f"{sign}{text or '0'}"


def toggle_sign(expression: str) -> str:
    """Negate the last number already typed."""
    text = expression.strip()
    if not text:
        return "-"
    match = None
    for match in re.finditer(r"\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?", text):
        pass
    if match is None:
        if text.endswith("-") or text.endswith("−"):
            return text[:-1]
        return text + "-"
    prefix = text[: match.start()]
    number = match.group()
    suffix = text[match.end() :]
    if prefix.endswith("(-") or prefix.endswith("(−"):
        if suffix.startswith(")"):
            suffix = suffix[1:]
        return prefix[:-2] + number + suffix
    if prefix.endswith(("-", "−")) and (
        len(prefix) == 1 or prefix[-2] in "+-*/^(×÷−–"
    ):
        return prefix[:-1] + number + suffix
    if prefix == "" or prefix.endswith("("):
        return prefix + "-" + number + suffix
    return prefix + "(-" + number + ")" + suffix


def _optional_decimal(value: Decimal | str | None) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value).replace(",", "."))


def _eval(node: Node, ctx: Context) -> Decimal:
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Const):
        return _const(node.name, ctx)
    if isinstance(node, Group):
        return _eval(node.inner, ctx)  # type: ignore[arg-type]
    if isinstance(node, Percent):
        return _eval(node.inner, ctx) / Decimal(100)  # type: ignore[arg-type]
    if isinstance(node, Unary):
        value = _eval(node.inner, ctx)  # type: ignore[arg-type]
        return -value if node.op == "-" else value
    if isinstance(node, Bin):
        return _binop(node, ctx)
    if isinstance(node, Call):
        args = tuple(_eval(arg, ctx) for arg in node.args)  # type: ignore[arg-type]
        return _call(node.name, args, ctx)
    raise CalcError("Operación no válida")


def _binop(node: Bin, ctx: Context) -> Decimal:
    left = _eval(node.left, ctx)  # type: ignore[arg-type]
    if isinstance(node.right, Percent) and node.op in {"+", "-", "*", "/", "^"}:
        percent = _eval(node.right.inner, ctx)  # type: ignore[arg-type]
        hundred = Decimal(100)
        if node.op == "+":
            return left + (left * percent / hundred)
        if node.op == "-":
            return left - (left * percent / hundred)
        if node.op == "*":
            return left * percent / hundred
        if node.op == "/":
            if percent == 0:
                raise CalcError("División por cero")
            return left / (percent / hundred)
        return _pow(left, percent / hundred)
    right = _eval(node.right, ctx)  # type: ignore[arg-type]
    if node.op == "+":
        return left + right
    if node.op == "-":
        return left - right
    if node.op == "*":
        return left * right
    if node.op == "/":
        if right == 0:
            raise CalcError("División por cero")
        return left / right
    if node.op == "^":
        return _pow(left, right)
    raise CalcError("Operador desconocido")


def _pow(base: Decimal, exponent: Decimal) -> Decimal:
    if base == 0 and exponent == 0:
        return Decimal(1)
    if exponent == exponent.to_integral_value():
        power = int(exponent)
        if abs(power) > 10000:
            raise CalcError("Potencia demasiado grande")
        return base**power
    try:
        return _from_float(math.pow(float(base), float(exponent)))
    except (ValueError, OverflowError) as exc:
        raise CalcError("Potencia no real") from exc


def _const(name: str, ctx: Context) -> Decimal:
    if name in {"pi", "π"}:
        return PI
    if name == "e":
        return E
    if name in {"ans", "respuesta"}:
        if ctx.ans is None:
            raise CalcError("Todavía no hay un resultado anterior")
        return ctx.ans
    if name in {"mem", "m"}:
        return ctx.memory
    raise CalcError(f"No conozco «{name}»")


def _call(name: str, args: tuple[Decimal, ...], ctx: Context) -> Decimal:
    if name == "mod":
        if len(args) != 2:
            raise CalcError("mod necesita dos argumentos: mod(a;b)")
        return _mod(args[0], args[1])
    if name == "log" and len(args) == 2:
        return _log(args[0], args[1])
    if name == "round" and len(args) == 2:
        return _round(args[0], args[1])
    if len(args) != 1:
        raise CalcError(f"{name} necesita un argumento")
    value = args[0]
    if name == "sqrt":
        if value < 0:
            raise CalcError("Raíz de un número negativo")
        return value.sqrt()
    if name == "cbrt":
        if value < 0:
            return -((-value) ** (Decimal(1) / Decimal(3)))
        return value ** (Decimal(1) / Decimal(3))
    if name == "abs":
        return abs(value)
    if name == "fact":
        return _factorial(value)
    if name == "floor":
        return value.to_integral_value(rounding=ROUND_FLOOR)
    if name == "ceil":
        return value.to_integral_value(rounding=ROUND_CEILING)
    if name == "round":
        return _round(value, Decimal(0))
    if name == "exp":
        return _from_float(math.exp(float(value)))
    if name == "ln":
        return _log(value, E)
    if name == "log":
        return _log(value, Decimal(10))
    if name == "log10":
        return _log(value, Decimal(10))
    if name == "log2":
        return _log(value, Decimal(2))
    if name in {"sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh"}:
        return _trig(name, value, ctx.angle)
    raise CalcError(f"No conozco «{name}»")


def _trig(name: str, value: Decimal, angle: str) -> Decimal:
    number = float(value)
    if name in {"sinh", "cosh", "tanh"}:
        try:
            return _from_float(getattr(math, name)(number))
        except (ValueError, OverflowError) as exc:
            raise CalcError("Resultado no numérico") from exc
    if name == "tan":
        degrees = number if angle == "deg" else math.degrees(number)
        folded = degrees % 180
        if abs(folded - 90) < 1e-9:
            raise CalcError("Tangente indefinida")
    if name in {"sin", "cos", "tan"}:
        radians = math.radians(number) if angle == "deg" else number
        return _from_float(getattr(math, name)(radians))
    if name == "asin" and abs(number) > 1:
        raise CalcError("asin solo acepta valores entre -1 y 1")
    if name == "acos" and abs(number) > 1:
        raise CalcError("acos solo acepta valores entre -1 y 1")
    radians = getattr(math, name)(number)
    if angle == "deg":
        radians = math.degrees(radians)
    return _from_float(radians)


def _log(value: Decimal, base: Decimal) -> Decimal:
    if value <= 0 or base <= 0 or base == 1:
        raise CalcError("Logaritmo no definido")
    return _from_float(math.log(float(value), float(base)))


def _mod(left: Decimal, right: Decimal) -> Decimal:
    if right == 0:
        raise CalcError("División por cero")
    quotient = (left / right).to_integral_value(rounding=ROUND_FLOOR)
    return left - (right * quotient)


def _round(value: Decimal, digits: Decimal) -> Decimal:
    if digits != digits.to_integral_value():
        raise CalcError("Los decimales de round tienen que ser enteros")
    places = int(digits)
    if places < 0 or places > 12:
        raise CalcError("round admite entre 0 y 12 decimales")
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _factorial(value: Decimal) -> Decimal:
    if value < 0:
        raise CalcError("El factorial no admite negativos")
    if value == value.to_integral_value() and value <= 1000:
        result = Decimal(1)
        for step in range(2, int(value) + 1):
            result *= step
        return result
    if value > 170:
        raise CalcError("Factorial demasiado grande")
    try:
        return _from_float(math.gamma(float(value) + 1))
    except (ValueError, OverflowError) as exc:
        raise CalcError("Factorial no definido") from exc


def _from_float(value: float) -> Decimal:
    if not math.isfinite(value):
        raise CalcError("Resultado no numérico")
    decimal_value = Decimal(f"{value:.12g}")
    if not decimal_value.is_finite():
        raise CalcError("Resultado no numérico")
    nearest = decimal_value.to_integral_value(rounding=ROUND_HALF_EVEN)
    if abs(decimal_value - nearest) <= Decimal("1e-9"):
        return nearest
    return decimal_value
