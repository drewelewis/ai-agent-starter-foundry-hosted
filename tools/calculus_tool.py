"""Typed polynomial derivative tool for the math tutor."""

from typing import Annotated

from operations import calculus_operations as calculus


def differentiate_polynomial(
    coefficients: Annotated[
        list[float],
        "Finite real coefficients in descending powers of x, including zeros for "
        "missing powers. Example: 3*x^2 + 1 is [3, 0, 1]. Constants use [c]. "
        "Only nonnegative integer powers of the single variable x are supported.",
    ],
) -> str:
    """Differentiate a polynomial in x using the power rule; not general expressions."""
    derivative = calculus.differentiate_polynomial(coefficients)
    degree = len(derivative) - 1
    terms: list[str] = []
    for index, coefficient in enumerate(derivative):
        if coefficient == 0:
            continue
        exponent = degree - index
        magnitude = abs(coefficient)
        number = str(int(magnitude)) if magnitude.is_integer() else str(magnitude)
        if exponent == 0:
            term = number
        else:
            variable = "x" if exponent == 1 else f"x^{exponent}"
            term = variable if magnitude == 1 else f"{number}*{variable}"
        if not terms:
            terms.append(f"-{term}" if coefficient < 0 else term)
        else:
            terms.append(f" {'-' if coefficient < 0 else '+'} {term}")
    return "Derivative with respect to x: " + ("".join(terms) or "0")
