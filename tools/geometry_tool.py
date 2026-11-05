"""Typed geometry tools with formulas for the tutor's explanations."""

from typing import Annotated

from operations import geometry_operations as geometry


def rectangle_area(
    length: Annotated[float, "Positive rectangle length"],
    width: Annotated[float, "Positive rectangle width, in the same units"],
) -> str:
    """Find the area of a rectangle or square."""
    return f"Area = length * width = {length} * {width} = {geometry.rectangle_area(length, width)} square units."


def rectangle_perimeter(
    length: Annotated[float, "Positive rectangle length"],
    width: Annotated[float, "Positive rectangle width, in the same units"],
) -> str:
    """Find the perimeter of a rectangle or square."""
    return f"Perimeter = 2 * (length + width) = 2 * ({length} + {width}) = {geometry.rectangle_perimeter(length, width)} units."


def triangle_area(
    base: Annotated[float, "Positive triangle base length"],
    height: Annotated[float, "Positive perpendicular height, in the same units"],
) -> str:
    """Find triangle area using a base and its perpendicular height."""
    return f"Area = base * height / 2 = {base} * {height} / 2 = {geometry.triangle_area(base, height)} square units."


def triangle_perimeter(
    a: Annotated[float, "Positive first side length"],
    b: Annotated[float, "Positive second side length, in the same units"],
    c: Annotated[float, "Positive third side length, in the same units"],
) -> str:
    """Find triangle perimeter; reject sides that cannot form a triangle."""
    return f"Perimeter = a + b + c = {a} + {b} + {c} = {geometry.triangle_perimeter(a, b, c)} units."


def circle_area(radius: Annotated[float, "Positive circle radius, not diameter"]) -> str:
    """Find the area of a circle from its radius."""
    return f"Area = pi * radius^2 = pi * {radius}^2 = {geometry.circle_area(radius)} square units."


def circle_circumference(radius: Annotated[float, "Positive circle radius, not diameter"]) -> str:
    """Find the circumference of a circle from its radius."""
    return f"Circumference = 2 * pi * radius = 2 * pi * {radius} = {geometry.circle_circumference(radius)} units."


def cuboid_volume(
    length: Annotated[float, "Positive cuboid length"],
    width: Annotated[float, "Positive cuboid width, in the same units"],
    height: Annotated[float, "Positive cuboid height, in the same units"],
) -> str:
    """Find the volume of a cuboid (rectangular prism) or cube."""
    return f"Volume = length * width * height = {length} * {width} * {height} = {geometry.cuboid_volume(length, width, height)} cubic units."


def cuboid_surface_area(
    length: Annotated[float, "Positive cuboid length"],
    width: Annotated[float, "Positive cuboid width, in the same units"],
    height: Annotated[float, "Positive cuboid height, in the same units"],
) -> str:
    """Find total surface area of a cuboid or cube."""
    return f"Surface area = 2 * (length * width + length * height + width * height); length={length}, width={width}, height={height}; result = {geometry.cuboid_surface_area(length, width, height)} square units."


def cylinder_volume(
    radius: Annotated[float, "Positive cylinder radius, not diameter"],
    height: Annotated[float, "Positive cylinder height, in the same units"],
) -> str:
    """Find cylinder volume from its radius and height."""
    return f"Volume = pi * radius^2 * height = pi * {radius}^2 * {height} = {geometry.cylinder_volume(radius, height)} cubic units."


def cylinder_surface_area(
    radius: Annotated[float, "Positive cylinder radius, not diameter"],
    height: Annotated[float, "Positive cylinder height, in the same units"],
) -> str:
    """Find total cylinder surface area, including both ends."""
    return f"Surface area = 2 * pi * radius * (radius + height) = 2 * pi * {radius} * ({radius} + {height}) = {geometry.cylinder_surface_area(radius, height)} square units."


def sphere_volume(radius: Annotated[float, "Positive sphere radius, not diameter"]) -> str:
    """Find the volume of a sphere."""
    return f"Volume = (4/3) * pi * radius^3 = (4/3) * pi * {radius}^3 = {geometry.sphere_volume(radius)} cubic units."


def sphere_surface_area(radius: Annotated[float, "Positive sphere radius, not diameter"]) -> str:
    """Find the surface area of a sphere."""
    return f"Surface area = 4 * pi * radius^2 = 4 * pi * {radius}^2 = {geometry.sphere_surface_area(radius)} square units."


def pythagorean_hypotenuse(
    a: Annotated[float, "Positive first perpendicular leg of a right triangle"],
    b: Annotated[float, "Positive second perpendicular leg, in the same units"],
) -> str:
    """Find a right triangle's hypotenuse, not a missing leg."""
    return f"Hypotenuse = sqrt(a^2 + b^2) = sqrt({a}^2 + {b}^2) = {geometry.pythagorean_hypotenuse(a, b)} units."


def coordinate_distance(
    x1: Annotated[float, "First point's x coordinate"],
    y1: Annotated[float, "First point's y coordinate"],
    x2: Annotated[float, "Second point's x coordinate"],
    y2: Annotated[float, "Second point's y coordinate"],
) -> str:
    """Find the distance between two points in a two-dimensional plane."""
    return f"Distance = sqrt((x2 - x1)^2 + (y2 - y1)^2); points=({x1}, {y1}), ({x2}, {y2}); result = {geometry.coordinate_distance(x1, y1, x2, y2)} units."
