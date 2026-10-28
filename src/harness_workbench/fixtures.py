DEMO_PROMPT = (
    "Fix add(a, b) in calculator.py: it incorrectly subtracts. "
    "Preserve the test fixture and verify with test_calculator.py."
)


def demo_files() -> dict[str, str]:
    return {
        "calculator.py": "def add(a, b):\n    return a - b\n",
        "test_calculator.py": (
            "import unittest\nfrom calculator import add\n\n"
            "class CalculatorTests(unittest.TestCase):\n"
            "    def test_positive(self):\n        self.assertEqual(add(2, 3), 5)\n"
            "    def test_negative(self):\n        self.assertEqual(add(-2, -3), -5)\n"
            "    def test_zero(self):\n        self.assertEqual(add(0, 0), 0)\n"
        ),
    }
