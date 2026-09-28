import unittest

from domain import Line
from pricing import total_for


class PricingTests(unittest.TestCase):
    def test_total_in_cents(self):
        self.assertEqual(total_for([Line("A", 150, 2)]), 300)

    def test_discount(self):
        self.assertEqual(total_for([Line("A", 150, 2)], 10), 270)

    def test_empty_order(self):
        with self.assertRaises(ValueError):
            total_for([])
