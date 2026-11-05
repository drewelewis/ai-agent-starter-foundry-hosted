"""Offline polynomial derivative and tool-contract tests."""

import math

import pytest

from operations import calculus_operations as calculus
from tools import calculus_tool
from tools.catalog import MATH_TOOLS


@pytest.mark.parametrize(
    ("coefficients", "expected"),
    [
        ([3, 0, 1], [6, 0]),
        ([4, -3, 2, -7], [12, -6, 2]),
        ([2.5, 0, -1.25, 4], [7.5, 0, -1.25]),
        ([5], [0]),
        ([0], [0]),
        ([0, 0, 0], [0]),
        ([0, 3, 0, 1], [6, 0]),
        ([1, 0], [1]),
        ([-1, 0, 0], [-2, 0]),
    ],
)
def test_polynomial_derivative(coefficients, expected):
    original = coefficients.copy()
    assert calculus.differentiate_polynomial(coefficients) == expected
    assert coefficients == original


@pytest.mark.parametrize("invalid", [[], "sin(x)", "x^-1", None, (3, 0, 1)])
def test_derivative_rejects_invalid_polynomial_input(invalid):
    with pytest.raises(ValueError, match="nonempty list"):
        calculus.differentiate_polynomial(invalid)


@pytest.mark.parametrize("invalid", [True, "3", None, math.inf, -math.inf, math.nan])
def test_derivative_validates_every_coefficient(invalid):
    for index in range(3):
        coefficients = [3, 0, 1]
        coefficients[index] = invalid
        with pytest.raises(ValueError, match="finite real number"):
            calculus.differentiate_polynomial(coefficients)


def test_derivative_rejects_overflow():
    with pytest.raises(ValueError, match="numeric range"):
        calculus.differentiate_polynomial([1e308, 0, 0])


@pytest.mark.parametrize(
    ("coefficients", "expected"),
    [
        ([3, 0, 1], "Derivative with respect to x: 6*x"),
        ([1, 0, -1, 0], "Derivative with respect to x: 3*x^2 - 1"),
        ([-1, 1, 0], "Derivative with respect to x: -2*x + 1"),
        ([0.5, 0, 0, 0], "Derivative with respect to x: 1.5*x^2"),
        ([0, 1, 0, 0], "Derivative with respect to x: 2*x"),
        ([0.5, 0, 0], "Derivative with respect to x: x"),
        ([-0.5, 0, 0], "Derivative with respect to x: -x"),
        ([7], "Derivative with respect to x: 0"),
        ([1, 0], "Derivative with respect to x: 1"),
        ([0.123456789012345, 0], "Derivative with respect to x: 0.123456789012345"),
    ],
)
def test_derivative_tool_output(coefficients, expected):
    assert calculus_tool.differentiate_polynomial(coefficients) == expected


def test_derivative_tool_registered_and_errors_propagate():
    assert calculus_tool.differentiate_polynomial in MATH_TOOLS
    with pytest.raises(ValueError, match="finite real number"):
        calculus_tool.differentiate_polynomial([math.nan])
