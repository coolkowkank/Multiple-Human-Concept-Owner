"""Unit tests for the Roman numeral conversion.

These tests cover a variety of cases including simple numbers, subtractive
notations, and boundary values.
"""

import unittest
from src.roman import int_to_roman


class TestRomanNumerals(unittest.TestCase):
    def test_simple_numbers(self):
        self.assertEqual(int_to_roman(1), "I")
        self.assertEqual(int_to_roman(4), "IV")
        self.assertEqual(int_to_roman(9), "IX")
        self.assertEqual(int_to_roman(58), "LVIII")  # 50 + 5 + 3

    def test_complex_numbers(self):
        self.assertEqual(int_to_roman(1994), "MCMXCIV")

    def test_boundary(self):
        self.assertEqual(int_to_roman(3999), "MMMCMXCIX")

    def test_invalid_inputs(self):
        with self.assertRaises(ValueError):
            int_to_roman(0)
        with self.assertRaises(ValueError):
            int_to_roman(4000)
        with self.assertRaises(TypeError):
            int_to_roman("100")


if __name__ == "__main__":
    unittest.main()
