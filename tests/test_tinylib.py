import unittest
from tinylib import add

class TestTinyLib(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)
