"""Single catalog of calculation tools registered with the hosted agent."""

from collections.abc import Callable

from tools import algebra_tool, arithmetic_tool, calculus_tool, geometry_tool


MATH_TOOLS: tuple[Callable[..., str], ...] = (
    arithmetic_tool.add,
    arithmetic_tool.subtract,
    arithmetic_tool.multiply,
    arithmetic_tool.divide,
    arithmetic_tool.power,
    arithmetic_tool.modulo,
    arithmetic_tool.evaluate_expression,
    geometry_tool.rectangle_area,
    geometry_tool.rectangle_perimeter,
    geometry_tool.triangle_area,
    geometry_tool.triangle_perimeter,
    geometry_tool.circle_area,
    geometry_tool.circle_circumference,
    geometry_tool.cuboid_volume,
    geometry_tool.cuboid_surface_area,
    geometry_tool.cylinder_volume,
    geometry_tool.cylinder_surface_area,
    geometry_tool.sphere_volume,
    geometry_tool.sphere_surface_area,
    geometry_tool.pythagorean_hypotenuse,
    geometry_tool.coordinate_distance,
    algebra_tool.solve_linear_equation,
    algebra_tool.solve_quadratic_equation,
    calculus_tool.differentiate_polynomial,
)
