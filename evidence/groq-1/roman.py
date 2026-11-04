"""Roman numeral conversion utilities.

This module provides a simple `int_to_roman` function that converts an integer
in the inclusive range 1–3999 to its Roman numeral representation using the
standard subtractive notation.

The implementation is intentionally straightforward and does not rely on
external libraries. It iterates over a list of tuples containing the Roman
numeral symbols and their corresponding integer values, subtracting the
largest possible value at each step.

Example
-------
>>> int_to_roman(1994)
'MCMXCIV'
"""

from __future__ import annotations

__all__ = ["int_to_roman"]

# Mapping of integer values to Roman numerals, ordered from largest to smallest.
_ROMAN_MAP = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


def int_to_roman(n: int) -> str:
    """Convert an integer to a Roman numeral.

    Parameters
    ----------
    n : int
        Integer to convert. Must be in the inclusive range 1–3999.

    Returns
    -------
    str
        Roman numeral representation.

    Raises
    ------
    ValueError
        If ``n`` is not within the allowed range.
    """
    if not isinstance(n, int):
        raise TypeError("int_to_roman expects an integer")
    if n < 1 or n > 3999:
        raise ValueError("int_to_roman only supports values between 1 and 3999")

    result: list[str] = []
    remaining = n
    for value, symbol in _ROMAN_MAP:
        while remaining >= value:
            result.append(symbol)
            remaining -= value
    return "".join(result)
