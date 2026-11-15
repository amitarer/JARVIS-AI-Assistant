"""Exact bounded arithmetic. No eval, names, calls, imports or filesystem access."""

import ast
from decimal import Decimal, localcontext
from fractions import Fraction
import operator
import re

from jarvis.core.models import Risk, ToolResult, UserError


def evaluate(expression):
    if not isinstance(expression, str) or not 1 <= len(expression) <= 500:
        raise UserError("Espressione numerica troppo lunga o vuota.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        raise UserError("Usa soltanto numeri e operatori aritmetici, con il punto decimale.") from None
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise UserError("Espressione oltre il limite di operazioni.")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}

    def visit(node, depth=0):
        if depth > 20:
            raise UserError("Espressione troppo annidata.")
        if isinstance(node, ast.Constant) and type(node.value) in {int, float}:
            literal = ast.get_source_segment(expression.strip(), node).replace("_", "")
            if not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,2})?", literal):
                raise UserError("Numero non supportato.")
            value = Fraction(literal)
        elif isinstance(node, ast.UnaryOp) and type(node.op) in {ast.UAdd, ast.USub}:
            value = visit(node.operand, depth+1) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp):
            left, right = visit(node.left, depth+1), visit(node.right, depth+1)
            if isinstance(node.op, ast.Pow):
                if right.denominator != 1 or abs(right.numerator) > 12:
                    raise UserError("Esponente intero richiesto tra -12 e 12.")
                value = left ** right.numerator
            elif type(node.op) in operations:
                value = Fraction(operations[type(node.op)](left, right))
            else:
                raise UserError("Operatore non supportato.")
        else:
            raise UserError("Sono ammessi soltanto numeri: niente nomi, funzioni o codice.")
        if value.numerator.bit_length() + value.denominator.bit_length() > 4096:
            raise UserError("Risultato numerico oltre il limite.")
        return value
    try:
        return visit(tree.body)
    except (ZeroDivisionError, OverflowError, ValueError):
        raise UserError("Calcolo non valido: verifica numeri e divisioni per zero.") from None


class CalculateTool:
    name = "calculate"
    risk = Risk.LOW
    description = ("Calcola esattamente un'espressione aritmetica (+ - * / // % ** e parentesi). "
                   "Usalo per prodotti, percentuali e verifica dei conti. Percentuale: dividi per 100; punto decimale. Nessun codice.")
    parameters = {"type": "object", "properties": {"expression": {"type": "string", "minLength": 1, "maxLength": 500}},
                  "required": ["expression"], "additionalProperties": False}

    def validate(self, arguments):
        if set(arguments) != {"expression"} or not isinstance(arguments["expression"], str):
            raise UserError("Specifica soltanto expression.")
        expression = arguments["expression"].strip()
        evaluate(expression)
        return {"expression": expression}

    def describe(self, arguments):
        return "Verifica il calcolo: " + arguments["expression"]

    def execute(self, arguments, context):
        context.checkpoint()
        value = evaluate(arguments["expression"])
        denominator = value.denominator
        for factor in (2, 5):
            while denominator % factor == 0:
                denominator //= factor
        exact_decimal = denominator == 1
        with localcontext() as ctx:
            ctx.prec = 5000 if exact_decimal else 34
            preview = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
        result = preview if exact_decimal else str(value)
        return ToolResult(f"{arguments['expression']} = {result}",
                          {"source": "bounded_rational_calculator", "exact": True, "result": result,
                           "fraction": str(value), "decimal_preview": preview, "decimal_is_exact": exact_decimal}, observation=True)
