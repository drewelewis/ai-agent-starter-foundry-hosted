"""Differentiate real-coefficient polynomials using the power rule."""

from operations.validation import finite_number, finite_result


def differentiate_polynomial(coefficients: list[float]) -> list[float]:
    """Return derivative coefficients in descending powers of x."""
    if not isinstance(coefficients, list) or not coefficients:
        raise ValueError("Polynomial coefficients must be a nonempty list in descending powers of x.")
    try:
        for index, coefficient in enumerate(coefficients):
            finite_number(coefficient, f"coefficients[{index}]")
        degree = len(coefficients) - 1
        derivative = [
            finite_result(float(coefficient) * (degree - index))
            for index, coefficient in enumerate(coefficients[:-1])
        ]
    except OverflowError as error:
        raise ValueError("The result is outside the supported finite numeric range.") from error

    first_nonzero = next(
        (index for index, coefficient in enumerate(derivative) if coefficient != 0),
        len(derivative),
    )
    return derivative[first_nonzero:] or [0.0]
