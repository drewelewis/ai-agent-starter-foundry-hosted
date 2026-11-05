"""Solve linear and quadratic equations over the real numbers."""

import math
from typing import Literal, TypedDict

from operations.validation import finite_number, finite_result


class EquationResult(TypedDict):
    status: Literal[
        "one_solution", "two_solutions", "no_solution",
        "infinite_solutions", "no_real_solutions",
    ]
    solutions: list[float]


def solve_linear_equation(a: float, b: float) -> EquationResult:
    """Solve a*x + b = 0, including zero-coefficient cases."""
    finite_number(a, "a")
    finite_number(b, "b")
    if a == 0:
        return {
            "status": "infinite_solutions" if b == 0 else "no_solution",
            "solutions": [],
        }
    return {"status": "one_solution", "solutions": [finite_result(-b / a)]}


def solve_quadratic_equation(a: float, b: float, c: float) -> EquationResult:
    """Solve a*x*x + b*x + c = 0 for real roots; a=0 reduces to a linear equation."""
    for name, value in (("a", a), ("b", b), ("c", c)):
        finite_number(value, name)
    if a == 0:
        return solve_linear_equation(b, c)

    _, exponent = math.frexp(max(abs(a), abs(b), abs(c)))
    coefficients = tuple(math.ldexp(value, -exponent) for value in (a, b, c))
    if any(old != 0 and new == 0 for old, new in zip((a, b, c), coefficients)):
        raise ValueError("Coefficient range is too large for a reliable quadratic solution.")
    a, b, c = coefficients
    squared_b = b * b
    product_ac = 4 * a * c
    if (b != 0 and squared_b == 0) or (c != 0 and product_ac == 0):
        raise ValueError("Coefficient range is too large for a reliable quadratic solution.")
    discriminant = squared_b - product_ac
    if discriminant < 0:
        return {"status": "no_real_solutions", "solutions": []}
    if discriminant == 0:
        return {
            "status": "one_solution",
            "solutions": [finite_result(-b / (2 * a))],
        }

    # This equivalent form avoids cancellation when one root is much smaller.
    q = -0.5 * (b + math.copysign(math.sqrt(discriminant), b))
    roots = sorted((finite_result(q / a), finite_result(c / q)))
    return {"status": "two_solutions", "solutions": roots}
