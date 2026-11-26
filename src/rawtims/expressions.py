"""Bounded, deterministic diagnostic expressions. No Python execution or export mapping.

References use [exact function key], including duplicate-name suffixes. ``log``
is base ten (Java Log); ``ln`` is natural log. Powers associate to the right.
Invalid/missing operands propagate even through operations such as x^0.
"""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

import numpy as np


class ExpressionError(ValueError):
    """Invalid syntax, reference, dependency, or input shape."""


_TOKEN = re.compile(r'\s*(?:(\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?)|\[([^\]\r\n]+)\]|(log|ln|exp|sqrt)|([+*/^()\-]))')
_UNARY = {'log': np.log10, 'ln': np.log, 'exp': np.exp, 'sqrt': np.sqrt, 'neg': np.negative, 'pos': np.positive}
_BINARY = {'+': np.add, '-': np.subtract, '*': np.multiply, '/': np.divide, '^': np.power}


@dataclass(frozen=True)
class ExpressionSpec:
    key: str
    name: str
    expression: str
    kind: str = 'other'
    unit: str | None = None

    def __post_init__(self):
        if not isinstance(self.key, str) or not re.fullmatch(r'derived:[A-Za-z0-9_.-]{1,80}', self.key):
            raise ExpressionError('Use a stable key derived:<id> (letters, digits, dot, dash or underscore)')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 200:
            raise ExpressionError('An expression needs a name of at most 200 characters')
        if self.kind not in ('other', 'ratio', 'intensity') or (self.unit is not None and not isinstance(self.unit, str)):
            raise ExpressionError('Invalid expression kind or unit')
        parse(self.expression)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Parsed:
    tree: tuple
    references: tuple[str, ...]


def parse(expression: str) -> Parsed:
    """Recursive descent over an allowlist, bounded to 512 tokens and 48 nesting levels."""
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 8192:
        raise ExpressionError('Expression must contain 1–8192 characters')
    expression = expression.strip()
    tokens = []
    position = 0
    while position < len(expression):
        match = _TOKEN.match(expression, position)
        if not match:
            raise ExpressionError(f'Unexpected syntax at character {position + 1}')
        number, reference, function, operator = match.groups()
        tokens.append(('number', number) if number is not None else ('ref', reference) if reference is not None else ('op', function or operator))
        position = match.end()
        if len(tokens) > 512:
            raise ExpressionError('Expression exceeds 512 tokens')
    cursor = 0
    references = set()

    def take(value):
        nonlocal cursor
        if cursor < len(tokens) and tokens[cursor] == ('op', value):
            cursor += 1
            return True
        return False

    def node(minimum=0, depth=0):
        nonlocal cursor
        if depth > 48:
            raise ExpressionError('Expression nesting exceeds 48 levels')
        if cursor == len(tokens):
            raise ExpressionError('Missing operand')
        kind, value = tokens[cursor]
        cursor += 1
        if kind == 'number':
            scalar = float(value)
            if not np.isfinite(scalar):
                raise ExpressionError('Numeric constants must be finite')
            left = ('number', scalar)
        elif kind == 'ref':
            references.add(value)
            left = ('ref', value)
        elif value in ('+', '-'):
            left = ('pos' if value == '+' else 'neg', node(3, depth + 1))
        elif value in ('log', 'ln', 'sqrt', 'exp'):
            if not take('('):
                raise ExpressionError(f'{value} requires parentheses')
            left = (value, node(0, depth + 1))
            if not take(')'):
                raise ExpressionError('Missing closing parenthesis')
        elif value == '(':
            left = node(0, depth + 1)
            if not take(')'):
                raise ExpressionError('Missing closing parenthesis')
        else:
            raise ExpressionError('Expected a number, [reference], or function')
        precedences = {'+': 1, '-': 1, '*': 2, '/': 2, '^': 4}
        while cursor < len(tokens):
            op = tokens[cursor][1]
            precedence = precedences.get(op, -1) if tokens[cursor][0] == 'op' else -1
            if precedence < minimum:
                break
            cursor += 1
            right = node(precedence if op == '^' else precedence + 1, depth + 1)
            left = (op, left, right)
        return left

    tree = node()
    if cursor != len(tokens):
        raise ExpressionError('Unexpected operand or closing parenthesis; use explicit operators')
    return Parsed(tree, tuple(sorted(references)))


@dataclass(frozen=True)
class DerivedColumn:
    spec: ExpressionSpec
    values: np.ndarray
    invalid: np.ndarray
    included: np.ndarray
    issues: tuple[str, ...]


def dependency_order(specs: Sequence[ExpressionSpec], source_keys=None):
    """Validate the dependency graph; an absent source namespace defers missing-input checks."""
    by_key = {spec.key: spec for spec in specs}
    if len(by_key) != len(specs) or (source_keys is not None and set(by_key) & set(source_keys)):
        raise ExpressionError('Duplicate or source-colliding output key')
    parsed = {key: parse(spec.expression) for key, spec in by_key.items()}
    pending, ordered, visiting = set(by_key), [], set()

    def visit(key):
        if key in visiting:
            raise ExpressionError(f'Dependency cycle at {key}')
        if key not in pending:
            return
        visiting.add(key)
        for reference in parsed[key].references:
            if source_keys is not None and reference not in source_keys and reference not in by_key:
                raise ExpressionError(f'{key}: missing reference [{reference}]')
            if reference in by_key:
                visit(reference)
        visiting.remove(key)
        pending.remove(key)
        ordered.append(key)

    for key in sorted(by_key):
        visit(key)

    return parsed, tuple(ordered)


def evaluate(specs: Sequence[ExpressionSpec], columns: Mapping[str, np.ndarray], *,
             masks: Mapping[str, np.ndarray] | None = None,
             invalid: Mapping[str, np.ndarray] | None = None) -> tuple[DerivedColumn, ...]:
    """Topological order uses sorted keys; output keys do not depend on library order.

    Data invalidity is distinct from selection: rejected finite operands retain
    their diagnostic value, but their derived result is excluded. Domain failures
    become NaN with invalid=True. No uncertainty propagation is implied.
    """
    if not columns:
        raise ExpressionError('At least one source column is required')
    if len(specs) > 128:
        raise ExpressionError('At most 128 expressions per object')
    values = {key: np.asarray(value, dtype=float) for key, value in columns.items()}
    shape = next(iter(values.values())).shape
    if len(shape) != 1 or any(value.shape != shape for value in values.values()):
        raise ExpressionError('Source columns must be equally sized vectors')
    selected, bad = {}, {}
    for key, value in values.items():
        selected[key] = np.asarray((masks or {}).get(key, np.ones(shape, dtype=bool)), dtype=bool).copy()
        bad[key] = np.asarray((invalid or {}).get(key, ~np.isfinite(value)), dtype=bool) | ~np.isfinite(value)
        if selected[key].shape != shape or bad[key].shape != shape:
            raise ExpressionError('Mask shape differs from source columns')
    by_key = {spec.key: spec for spec in specs}
    parsed, ordered = dependency_order(specs, set(values))

    def calculate(tree):
        operation = tree[0]
        if operation == 'number':
            return np.full(shape, tree[1]), np.zeros(shape, dtype=bool)
        if operation == 'ref':
            return np.where(bad[tree[1]], np.nan, values[tree[1]]), bad[tree[1]]
        left, left_bad = calculate(tree[1])
        with np.errstate(all='ignore'):
            if operation in _UNARY:
                result = _UNARY[operation](left)
                result_bad = left_bad | ~np.isfinite(result)
            else:
                right, right_bad = calculate(tree[2])
                result = _BINARY[operation](left, right)
                result_bad = left_bad | right_bad | ~np.isfinite(result)
        return np.where(result_bad, np.nan, result), result_bad

    result = []
    for key in ordered:
        spec = by_key[key]
        value, invalid_values = calculate(parsed[key].tree)
        if spec.kind == 'ratio':
            invalid_values = invalid_values | (value <= 0)
            value = np.where(invalid_values, np.nan, value)
        include = np.ones(shape, dtype=bool)
        for reference in parsed[key].references:
            include &= selected[reference] & ~bad[reference]
        values[key], bad[key], selected[key] = value, invalid_values, include
        count = int(invalid_values.sum())
        issues = (f'{count} cycles have missing, domain, nonfinite or nonpositive-ratio values',) if count else ()
        result.append(DerivedColumn(spec, value, invalid_values, include & ~invalid_values, issues))
    return tuple(result)


def ratio_spec(key: str, name: str, numerator: str, denominator: str, *, unit: str | None = None) -> ExpressionSpec:
    """Build an explicit ratio of two existing keys; the caller validates their units."""
    if any(not isinstance(k, str) or not k or ']' in k or '\n' in k for k in (numerator, denominator)):
        raise ExpressionError('Source key cannot be represented in a bracket reference')
    return ExpressionSpec(key, name, f'[{numerator}] / [{denominator}]', 'ratio', unit)
