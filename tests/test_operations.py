"""Numerical and tool-contract regression tests, without a model or network."""

import inspect
import math

import pytest

from operations import algebra_operations as algebra
from operations import arithmetic_operations as arithmetic
from operations import geometry_operations as geometry
from tools import algebra_tool, geometry_tool
from tools.catalog import MATH_TOOLS


GEOMETRY_CASES = [
    ("rectangle_area", (3, 4), 12),
    ("rectangle_perimeter", (3, 4), 14),
    ("triangle_area", (6, 4), 12),
    ("triangle_perimeter", (3, 4, 5), 12),
    ("circle_area", (2,), 4 * math.pi),
    ("circle_circumference", (2,), 4 * math.pi),
    ("cuboid_volume", (2, 3, 4), 24),
    ("cuboid_surface_area", (2, 3, 4), 52),
    ("cylinder_volume", (2, 3), 12 * math.pi),
    ("cylinder_surface_area", (2, 3), 20 * math.pi),
    ("sphere_volume", (3,), 36 * math.pi),
    ("sphere_surface_area", (3,), 36 * math.pi),
    ("pythagorean_hypotenuse", (3, 4), 5),
    ("coordinate_distance", (-1, -2, 2, 2), 5),
]


@pytest.mark.parametrize(("name", "args", "expected"), GEOMETRY_CASES)
def test_geometry_formulas(name, args, expected):
    assert getattr(geometry, name)(*args) == pytest.approx(expected)
    result = getattr(geometry_tool, name)(*args)
    assert "=" in result
    assert "units" in result


@pytest.mark.parametrize(("name", "args", "_"), GEOMETRY_CASES[:-1])
@pytest.mark.parametrize("invalid", [0, -1, math.inf, -math.inf, math.nan, True])
def test_geometry_validates_every_dimension(name, args, _, invalid):
    operation = getattr(geometry, name)
    for index in range(len(args)):
        values = list(args)
        values[index] = invalid
        with pytest.raises(ValueError):
            operation(*values)


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf, True])
def test_coordinate_validation(invalid):
    for index in range(4):
        values = [0.0] * 4
        values[index] = invalid
        with pytest.raises(ValueError):
            geometry.coordinate_distance(*values)


def test_geometry_edge_cases():
    assert geometry.coordinate_distance(0, 0, 0, 0) == 0
    assert geometry.pythagorean_hypotenuse(3e200, 4e200) == pytest.approx(5e200)
    with pytest.raises(ValueError, match="triangle inequality"):
        geometry.triangle_perimeter(1, 2, 3)
    with pytest.raises(ValueError, match="numeric range"):
        geometry.sphere_volume(1e308)
    with pytest.raises(ValueError, match="numeric range"):
        geometry.coordinate_distance(-1e308, 0, 1e308, 0)


@pytest.mark.parametrize(
    ("a", "b", "status", "roots"),
    [
        (2, -6, "one_solution", [3]),
        (-2, -6, "one_solution", [-3]),
        (4, 0, "one_solution", [0]),
        (0, 1, "no_solution", []),
        (0, 0, "infinite_solutions", []),
    ],
)
def test_linear(a, b, status, roots):
    result = algebra.solve_linear_equation(a, b)
    assert result["status"] == status
    assert result["solutions"] == pytest.approx(roots)


@pytest.mark.parametrize(
    ("coefficients", "status", "roots"),
    [
        ((1, -5, 6), "two_solutions", [2, 3]),
        ((1, 2, 1), "one_solution", [-1]),
        ((1, 0, 0), "one_solution", [0]),
        ((1, 0, -4), "two_solutions", [-2, 2]),
        ((1, 0, 1), "no_real_solutions", []),
        ((0, 2, -6), "one_solution", [3]),
        ((0, 0, 3), "no_solution", []),
        ((0, 0, 0), "infinite_solutions", []),
        ((1e200, -5e200, 6e200), "two_solutions", [2, 3]),
        ((1e-200, -5e-200, 6e-200), "two_solutions", [2, 3]),
        ((1, 1e16, 1), "two_solutions", [-1e16, -1e-16]),
    ],
)
def test_quadratic(coefficients, status, roots):
    result = algebra.solve_quadratic_equation(*coefficients)
    assert result["status"] == status
    assert len(result["solutions"]) == len(roots)
    for actual, expected in zip(result["solutions"], roots):
        assert actual == pytest.approx(expected, rel=1e-12, abs=0)


@pytest.mark.parametrize("invalid", [math.nan, math.inf, -math.inf, True])
def test_algebra_validation(invalid):
    for operation, count in (
        (algebra.solve_linear_equation, 2), (algebra.solve_quadratic_equation, 3)
    ):
        for index in range(count):
            values = [1.0] * count
            values[index] = invalid
            with pytest.raises(ValueError):
                operation(*values)


def test_algebra_unrepresentable():
    with pytest.raises(ValueError, match="numeric range"):
        algebra.solve_linear_equation(1e-308, 1e308)
    with pytest.raises(ValueError, match="Coefficient range"):
        algebra.solve_quadratic_equation(1e-308, 1e308, 1)
    with pytest.raises(ValueError, match="Coefficient range"):
        algebra.solve_quadratic_equation(1e-200, 0, 1e200)


def test_algebra_tool_outcomes():
    assert "Infinitely many" in algebra_tool.solve_linear_equation(0, 0)
    assert "No solution:" in algebra_tool.solve_linear_equation(0, 2)
    assert "No real solutions:" in algebra_tool.solve_quadratic_equation(1, 0, 1)
    with pytest.raises(ValueError):
        geometry_tool.circle_area(-1)


def test_catalog_contract():
    assert len({tool.__name__ for tool in MATH_TOOLS}) == len(MATH_TOOLS)
    for tool in MATH_TOOLS:
        signature = inspect.signature(tool)
        assert tool.__doc__
        assert signature.return_annotation is str
        for parameter in signature.parameters.values():
            assert parameter.annotation is not inspect.Parameter.empty


def test_arithmetic_regression():
    assert arithmetic.add(2, 3) == 5
    assert arithmetic.subtract(2, 3) == -1
    assert arithmetic.multiply(2, 3) == 6
    assert arithmetic.divide(6, 3) == 2
    assert arithmetic.power(2, 3) == 8
    assert arithmetic.modulo(7, 3) == 1
    assert arithmetic.evaluate_expression("(2 + 3) * 4") == 20
    with pytest.raises(ValueError):
        arithmetic.divide(1, 0)
