"""Calculator engine tests. No GTK and no display."""

from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packaging" / "aidycalc"))

from aidycalc.engine import CalcError, evaluate, format_number, repeat_suffix, toggle_sign  # noqa: E402


def eq(expression: str, expected: str, **kwargs: object) -> None:
    got = format_number(evaluate(expression, **kwargs))  # type: ignore[arg-type]
    if got != expected:
        raise AssertionError(f"{expression} -> {got}, expected {expected}")


class CalculatorEngineTests(unittest.TestCase):
    def test_arithmetic_precedence_and_grouping(self) -> None:
        eq("2+2", "4")
        eq("2+3*4", "14")
        eq("(2+3)*4", "20")
        eq("1/3*3", "1")
        eq("0.1+0.2", "0.3")
        eq("-3+5", "2")
        eq("2*-3", "-6")

    def test_decimal_comma_and_symbols(self) -> None:
        eq("1,5+1,5", "3")
        eq("8÷2×3", "12")
        eq("2^3", "8")
        eq("2**3", "8")
        eq("2^3^2", "512")
        eq("-2^2", "-4")
        eq("2^-2", "0.25")

    def test_percent_is_calculator_style(self) -> None:
        eq("50%", "0.5")
        eq("200+10%", "220")
        eq("200-10%", "180")
        eq("200*10%", "20")
        eq("200/10%", "2000")
        eq("100+10%+10%", "121")
        eq("(200+10)%", "2.1")

    def test_implicit_multiplication_and_constants(self) -> None:
        eq("2(3+1)", "8")
        eq("2π/π", "2")
        eq("√9", "3")
        eq("√(9+7)", "4")
        eq("5!", "120")
        eq("(3+2)!", "120")

    def test_scientific_degrees_by_default(self) -> None:
        eq("sin(90)", "1")
        eq("sen(30)", "0.5")
        eq("cos(90)", "0")
        eq("cos(180)", "-1")
        eq("tan(45)", "1")
        eq("sqrt(9)+ln(e)", "4")
        eq("log(100)", "2")
        eq("log(100;10)", "2")
        eq("mod(17;5)", "2")
        eq("round(1.235;2)", "1.24")
        eq("abs(-4)+floor(1.9)+ceil(1.2)", "7")
        eq("sin(pi/2)", "1", angle="rad")

    def test_errors(self) -> None:
        with self.assertRaises(CalcError) as divided:
            evaluate("1/0")
        self.assertIn("cero", str(divided.exception))
        with self.assertRaises(CalcError) as incomplete:
            evaluate("2+")
        self.assertTrue(incomplete.exception.incomplete)
        with self.assertRaises(CalcError):
            evaluate("tan(90)")
        with self.assertRaises(CalcError):
            evaluate("sqrt(-1)")

    def test_repeat_and_sign_toggle(self) -> None:
        self.assertEqual(repeat_suffix("2+3"), ("+", "3"))
        self.assertEqual(repeat_suffix("200+10%"), ("+", "10%"))
        self.assertIsNone(repeat_suffix("5"))
        self.assertEqual(toggle_sign("12"), "-12")
        self.assertEqual(toggle_sign("-12"), "12")
        self.assertEqual(toggle_sign("2+12"), "2+(-12)")
        self.assertEqual(toggle_sign("2+(-12)"), "2+12")
        self.assertEqual(toggle_sign(""), "-")

    def test_ans_and_memory(self) -> None:
        eq("ans*2", "10", ans=Decimal(5))
        eq("mem+1", "4", memory="3")

    def test_profile_wires_calculator(self) -> None:
        installer = (ROOT / "scripts" / "install-debian-profile.sh").read_text(encoding="utf-8")
        uninstaller = (ROOT / "scripts" / "uninstall-debian-profile.sh").read_text(encoding="utf-8")
        seed = (ROOT / "scripts" / "seed-desktop-defaults.py").read_text(encoding="utf-8")
        self.assertIn("install_aidycalc", installer)
        self.assertIn("bind = SUPER, K, exec, aidycalc ui", installer)
        self.assertIn("/usr/local/bin/aidycalc", uninstaller)
        self.assertIn("aidycalc.desktop", uninstaller)
        self.assertIn('"Calculadora"', seed)


if __name__ == "__main__":
    unittest.main()
