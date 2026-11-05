"""Shared validation for real-valued math operations."""

import math


def finite_number(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite real number.")
    if not math.isfinite(value):
        raise ValueError(f"{name} must be a finite real number.")
    return value


def positive_number(value: float, name: str) -> float:
    finite_number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def finite_result(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("The result is outside the supported finite numeric range.")
    return value
