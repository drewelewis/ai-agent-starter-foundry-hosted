"""Geometry calculations. Dimensions must be positive and use consistent units."""

import math

from operations.validation import finite_number, finite_result, positive_number


def rectangle_area(length: float, width: float) -> float:
    """Calculate rectangle area: length * width."""
    return finite_result(
        positive_number(length, "length") * positive_number(width, "width")
    )


def rectangle_perimeter(length: float, width: float) -> float:
    """Calculate rectangle perimeter: 2 * (length + width)."""
    return finite_result(
        2 * (positive_number(length, "length") + positive_number(width, "width"))
    )


def triangle_area(base: float, height: float) -> float:
    """Calculate triangle area from base and perpendicular height."""
    return finite_result(
        0.5 * positive_number(base, "base") * positive_number(height, "height")
    )


def triangle_perimeter(a: float, b: float, c: float) -> float:
    """Calculate the perimeter of a non-degenerate triangle."""
    sides = sorted(
        (positive_number(a, "a"), positive_number(b, "b"), positive_number(c, "c"))
    )
    if sides[0] <= sides[2] - sides[1]:
        raise ValueError("Triangle sides must satisfy the strict triangle inequality.")
    return finite_result(a + b + c)


def circle_area(radius: float) -> float:
    """Calculate circle area: pi * radius * radius."""
    radius = positive_number(radius, "radius")
    return finite_result(math.pi * radius * radius)


def circle_circumference(radius: float) -> float:
    """Calculate circle circumference: 2 * pi * radius."""
    return finite_result(2 * math.pi * positive_number(radius, "radius"))


def cuboid_volume(length: float, width: float, height: float) -> float:
    """Calculate cuboid volume: length * width * height."""
    return finite_result(
        positive_number(length, "length")
        * positive_number(width, "width")
        * positive_number(height, "height")
    )


def cuboid_surface_area(length: float, width: float, height: float) -> float:
    """Calculate total cuboid surface area: 2 * (lw + lh + wh)."""
    positive_number(length, "length")
    positive_number(width, "width")
    positive_number(height, "height")
    return finite_result(2 * (length * width + length * height + width * height))


def cylinder_volume(radius: float, height: float) -> float:
    """Calculate cylinder volume: pi * radius * radius * height."""
    return finite_result(circle_area(radius) * positive_number(height, "height"))


def cylinder_surface_area(radius: float, height: float) -> float:
    """Calculate total cylinder surface area, including both circular ends."""
    positive_number(radius, "radius")
    positive_number(height, "height")
    return finite_result(2 * math.pi * radius * (radius + height))


def sphere_volume(radius: float) -> float:
    """Calculate sphere volume: (4/3) * pi * radius * radius * radius."""
    radius = positive_number(radius, "radius")
    return finite_result((4 / 3) * math.pi * radius * radius * radius)


def sphere_surface_area(radius: float) -> float:
    """Calculate sphere surface area: 4 * pi * radius * radius."""
    radius = positive_number(radius, "radius")
    return finite_result(4 * math.pi * radius * radius)


def pythagorean_hypotenuse(a: float, b: float) -> float:
    """Find the hypotenuse from the two perpendicular legs of a right triangle."""
    return finite_result(
        math.hypot(positive_number(a, "a"), positive_number(b, "b"))
    )


def coordinate_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Calculate Euclidean distance between two points in the plane."""
    for name, value in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
        finite_number(value, name)
    return finite_result(math.hypot(x2 - x1, y2 - y1))
