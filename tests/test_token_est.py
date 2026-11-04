import unittest
from launcher.token_est import estimate_tokens, measure_prompt


class TestTokenEst(unittest.TestCase):
    def test_estimate_tokens(self):
        # 400 characters should give 100 tokens
        self.assertEqual(estimate_tokens("a" * 400), 100)
        # empty string should give 0 tokens
        self.assertEqual(estimate_tokens(""), 0)
        # 401 characters should round up to 101 tokens
        self.assertEqual(estimate_tokens("a" * 401), 101)

    def test_measure_prompt(self):
        system = "s" * 150
        task = "t" * 250
        stats = measure_prompt(system, task)
        self.assertEqual(stats["system_chars"], 150)
        self.assertEqual(stats["task_chars"], 250)
        self.assertEqual(stats["total_chars"], 400)
        self.assertEqual(stats["est_tokens"], 100)


if __name__ == "__main__":
    unittest.main()
