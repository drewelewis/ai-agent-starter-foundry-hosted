"""Typed algebra tools with equation and real-solution descriptions."""

from typing import Annotated

from operations import algebra_operations as algebra


def _describe(result: algebra.EquationResult) -> str:
    if result["status"] == "infinite_solutions":
        return "Infinitely many solutions: every real number satisfies the equation."
    if result["status"] == "no_solution":
        return "No solution: the equation reduces to a nonzero constant equal to zero."
    if result["status"] == "no_real_solutions":
        return "No real solutions: the quadratic discriminant is negative."
    return "Real solutions: " + ", ".join(f"x = {root}" for root in result["solutions"])


def solve_linear_equation(
    a: Annotated[float, "Coefficient a in a*x + b = 0"],
    b: Annotated[float, "Constant b in a*x + b = 0"],
) -> str:
    """Solve a*x + b = 0 over the reals, including zero coefficients."""
    result = algebra.solve_linear_equation(a, b)
    return f"{a}*x + ({b}) = 0. {_describe(result)}"


def solve_quadratic_equation(
    a: Annotated[float, "Coefficient of x squared in a*x^2 + b*x + c = 0"],
    b: Annotated[float, "Coefficient of x in a*x^2 + b*x + c = 0"],
    c: Annotated[float, "Constant in a*x^2 + b*x + c = 0"],
) -> str:
    """Solve a quadratic over the reals; a=0 is treated as a linear equation."""
    result = algebra.solve_quadratic_equation(a, b, c)
    return f"{a}*x^2 + ({b})*x + ({c}) = 0. {_describe(result)}"
