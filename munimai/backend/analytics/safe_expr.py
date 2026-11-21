"""
A tiny, strict formula language for the Math agent.

A model may PROPOSE a formula, but it is only text until this module accepts it. We parse it with
Python's `ast` and allow nothing except: numbers, named series, + - * / **, unary minus, and a short
list of whitelisted functions. No attributes, subscripts, strings, lambdas, comprehensions or keyword
arguments, so there is no way to import, open a file or run code.

It also tracks UNITS (rupees, count) so a nonsense formula such as "rupees + count" is rejected.
Evaluation uses numpy on monthly series. Division by zero gives NaN, never an exception or a silent 0.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Optional

import numpy as np

MAX_CHARS = 200
MAX_NODES = 60
MAX_POW = 4

Unit = tuple  # sorted tuple of (dimension, exponent); () means a plain ratio


class FormulaError(ValueError):
    """The proposed formula is not allowed. The message says why."""


def _u_mul(a: Unit, b: Unit, sign: int = 1) -> Unit:
    d = dict(a)
    for k, v in b:
        d[k] = d.get(k, 0) + sign * v
    return tuple(sorted((k, v) for k, v in d.items() if v != 0))


def unit_label(u: Unit) -> str:
    if not u:
        return "ratio"
    d = dict(u)
    if d == {"rupees": 1}:
        return "rupees"
    if d == {"count": 1}:
        return "count"
    if d == {"rupees": 1, "count": -1}:
        return "rupees per item"
    return " ".join(f"{k}^{v}" for k, v in u)


def _lag(x: np.ndarray, k: float) -> np.ndarray:
    k = int(k)
    if k < 1 or k > 12:
        raise FormulaError("lag(series, k) needs k between 1 and 12")
    out = np.full_like(x, np.nan, dtype=float)
    out[k:] = x[:-k]
    return out


def _roll(x: np.ndarray, k: float) -> np.ndarray:
    k = int(k)
    if k < 2 or k > 12:
        raise FormulaError("roll(series, k) needs k between 2 and 12")
    out = np.full_like(x, np.nan, dtype=float)
    for i in range(k - 1, len(x)):
        out[i] = np.mean(x[i - k + 1:i + 1])
    return out


def _diff(x: np.ndarray) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    out[1:] = x[1:] - x[:-1]
    return out


def _growth(x: np.ndarray) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out[1:] = (x[1:] - x[:-1]) / np.where(x[:-1] == 0, np.nan, x[:-1])
    return out


def _mean(x: np.ndarray) -> float:
    v = x[~np.isnan(x)]
    return float(np.mean(v)) if len(v) else float("nan")


def _bin2(f):
    def g(a, b):
        return f(a, b)
    return g


# name -> (callable, nargs, how the unit changes)
_FUNCS = {
    "log": (lambda x: np.log(np.where(x > 0, x, np.nan)), 1, "ratio"),
    "sqrt": (lambda x: np.sqrt(np.where(x >= 0, x, np.nan)), 1, "sqrt"),
    "abs": (np.abs, 1, "same"),
    "mean": (_mean, 1, "same"),
    "lag": (_lag, 2, "same"),
    "roll": (_roll, 2, "same"),
    "diff": (_diff, 1, "same"),
    "growth": (_growth, 1, "ratio"),
    "minimum": (np.minimum, 2, "same2"),
    "maximum": (np.maximum, 2, "same2"),
}


@dataclass
class Compiled:
    source: str
    tree: ast.Expression
    names: set
    unit: Unit
    units: dict

    def evaluate(self, series: dict) -> np.ndarray:
        """series: name -> array of monthly values. Returns an array (or a 0-d array for scalar results)."""
        env = {k: (np.asarray(series[k], dtype=float), self.units[k]) for k in self.names}
        val, _ = _eval(self.tree.body, env, self.units, with_units=False)
        return np.asarray(val, dtype=float)


def compile_formula(source: str, units: dict[str, Unit]) -> Compiled:
    """Validate and unit-check `source` against the available series names. Raises FormulaError."""
    if not isinstance(source, str) or not source.strip():
        raise FormulaError("empty formula")
    if len(source) > MAX_CHARS:
        raise FormulaError(f"formula longer than {MAX_CHARS} characters")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"not valid syntax: {e.msg}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise FormulaError("formula is too complex")
    names: set = set()
    for n in nodes:
        if isinstance(n, ast.Name) and n.id not in _FUNCS:
            if n.id not in units:
                raise FormulaError(f"unknown series '{n.id}'")
            names.add(n.id)
    # unit check walks the tree once with symbolic values
    _, unit = _eval(tree.body, {k: (None, u) for k, u in units.items()}, units, with_units=True)
    return Compiled(source.strip(), tree, names, unit, dict(units))


def _eval(node, env, units, with_units: bool):
    """Returns (value, unit). With with_units=True the value is ignored and only units are checked."""
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError("only plain numbers are allowed as constants")
        return float(node.value), ()
    if isinstance(node, ast.Name):
        if node.id in _FUNCS:
            raise FormulaError(f"'{node.id}' is a function and must be called")
        return (None if with_units else env[node.id][0]), env[node.id][1]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v, u = _eval(node.operand, env, units, with_units)
        return (None if with_units else (-v if isinstance(node.op, ast.USub) else v)), u
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)):
        a, ua = _eval(node.left, env, units, with_units)
        b, ub = _eval(node.right, env, units, with_units)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            if ua != ub:
                raise FormulaError(f"cannot add or subtract {unit_label(ua)} and {unit_label(ub)}")
            return (None if with_units else (a + b if isinstance(node.op, ast.Add) else a - b)), ua
        if isinstance(node.op, ast.Mult):
            return (None if with_units else a * b), _u_mul(ua, ub)
        if isinstance(node.op, ast.Div):
            if with_units:
                return None, _u_mul(ua, ub, -1)
            with np.errstate(divide="ignore", invalid="ignore"):
                bb = np.where(np.asarray(b, dtype=float) == 0, np.nan, b)
                return a / bb, _u_mul(ua, ub, -1)
        # power: exponent must be a small constant number
        if not (isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float))):
            raise FormulaError("the exponent must be a plain number")
        e = float(node.right.value)
        if not (-MAX_POW <= e <= MAX_POW):
            raise FormulaError(f"exponent must be between -{MAX_POW} and {MAX_POW}")
        if ua and e != int(e):
            raise FormulaError("fractional powers are only allowed on plain ratios")
        newu = tuple(sorted((k, int(v * e)) for k, v in ua)) if ua else ()
        if with_units:
            return None, newu
        with np.errstate(invalid="ignore", divide="ignore"):
            return np.power(np.asarray(a, dtype=float), e), newu
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS or node.keywords:
            raise FormulaError("only the listed functions may be called, without keyword arguments")
        fn, nargs, rule = _FUNCS[node.func.id]
        if len(node.args) != nargs:
            raise FormulaError(f"{node.func.id}() takes {nargs} argument(s)")
        a0, u0 = _eval(node.args[0], env, units, with_units)
        if nargs == 2:
            if rule == "same2":
                a1, u1 = _eval(node.args[1], env, units, with_units)
                if u0 != u1:
                    raise FormulaError("minimum/maximum need matching units")
                return (None if with_units else fn(a0, a1)), u0
            if not (isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, (int, float))):
                raise FormulaError(f"the window in {node.func.id}() must be a plain number")
            k = node.args[1].value
            return (None if with_units else fn(np.asarray(a0, dtype=float), k)), u0
        if rule == "ratio":
            return (None if with_units else fn(np.asarray(a0, dtype=float))), ()
        if rule == "sqrt":
            if any(v % 2 for _, v in u0):
                raise FormulaError("square root of an odd power of a unit")
            return (None if with_units else fn(np.asarray(a0, dtype=float))), tuple((k, v // 2) for k, v in u0)
        return (None if with_units else fn(np.asarray(a0, dtype=float))), u0
    raise FormulaError(f"'{type(node).__name__}' is not allowed in a formula")
