import copy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from reconcile import reconcile


def order(identifier="A", amount="100.00", currency="CNY"):
    return {"order_id": identifier, "amount": amount, "currency": currency}


def payment(identifier="P1", order_id="A", amount="100.00", currency="CNY"):
    return {"payment_id": identifier, "order_id": order_id, "amount": amount, "currency": currency}


class ReconciliationTests(unittest.TestCase):
    def run_case(self, orders, payments):
        return reconcile({"synthetic": True, "orders": orders, "payments": payments})

    def test_normal_and_no_mutation(self):
        source = {"orders": [order()], "payments": [payment()]}
        previous = copy.deepcopy(source)
        result = reconcile(source)
        self.assertEqual(result["order_results"][0]["status"], "matched")
        self.assertEqual(source, previous)

    def test_split_payment_and_decimal_accuracy(self):
        result = self.run_case([order(amount="0.30")], [payment(amount="0.10"), payment("P2", amount="0.20")])
        self.assertEqual(result["order_results"][0]["received"], "0.30")
        self.assertEqual(result["order_results"][0]["status"], "matched")

    def test_duplicate_payments_all_quarantined(self):
        result = self.run_case([order()], [payment(), payment()])
        self.assertEqual(result["order_results"][0]["received"], "0")
        self.assertEqual(len(result["exceptions"]), 2)
        self.assertTrue(all("duplicate_payment_id" in x["reasons"] for x in result["exceptions"]))

    def test_duplicate_orders_are_ambiguous(self):
        result = self.run_case([order(), order()], [payment()])
        self.assertEqual(result["order_results"], [])
        self.assertEqual(len(result["exceptions"]), 3)
        self.assertIn("ambiguous_or_invalid_order", result["exceptions"][-1]["reasons"])

    def test_bad_amounts_are_retained(self):
        for invalid in [None, "", " 1 ", "1,000.00", "NaN", "Infinity", "-1", True, [], "1e999", "1_000"]:
            with self.subTest(invalid=invalid):
                result = self.run_case([order()], [payment(amount=invalid)])
                self.assertEqual(len(result["exceptions"]), 1)
                self.assertIn("invalid_amount", result["exceptions"][0]["reasons"])
                self.assertEqual(result["exceptions"][0]["record"]["amount"], invalid)

    def test_difference_missing_unknown(self):
        result = self.run_case([order(), order("B")], [payment(amount="90"), payment("P2", "UNKNOWN")])
        self.assertEqual([r["status"] for r in result["order_results"]], ["amount_difference", "missing_payment"])
        self.assertEqual(result["order_results"][0]["difference_received_minus_expected"], "-10.00")
        self.assertIn("unknown_order", result["exceptions"][0]["reasons"])

    def test_currencies_are_never_mixed(self):
        result = self.run_case([order(), order("B", currency="USD"), order("C", currency="ZZZ")], [payment(), payment("P2", "B", currency="CNY"), payment("P3", "B", currency="ZZZ")])
        self.assertEqual(result["order_results"][0]["status"], "matched")
        self.assertEqual(result["order_results"][1]["received"], "0")
        self.assertEqual(len(result["exceptions"]), 3)
        self.assertIn("currency_mismatch", result["exceptions"][1]["reasons"])
        self.assertIn("unsupported_currency", result["exceptions"][2]["reasons"])

    def test_invalid_records_and_ids(self):
        result = self.run_case([None, order(identifier=" ")], [None, payment(identifier="")])
        self.assertEqual(len(result["exceptions"]), 4)

    def test_numeric_decimal_input(self):
        result = self.run_case([order(amount=Decimal("12.30"))], [payment(amount=Decimal("12.30"))])
        self.assertEqual(result["order_results"][0]["status"], "matched")

    def test_numeric_nonfinite_is_never_counted(self):
        for value in [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]:
            result = self.run_case([order()], [payment(amount=value)])
            self.assertEqual(result["order_results"][0]["received"], "0")
            self.assertIn("invalid_amount", result["exceptions"][0]["reasons"])

    def test_high_precision_arithmetic(self):
        # Use a separate valid-size order and a large aggregate; no binary float rounding.
        result = self.run_case([order(amount="1.00")], [payment(amount="99999999999999999999999"), payment("P2", amount="0.000000000001")])
        self.assertEqual(result["order_results"][0]["received"], "99999999999999999999999.000000000001")
        self.assertEqual(result["order_results"][0]["difference_received_minus_expected"], "99999999999999999999998.000000000001")

    def test_invalid_root_schema(self):
        for data in [[], {}, {"orders": {}, "payments": []}]:
            with self.assertRaises(ValueError):
                reconcile(data)

    def test_cli_stdout_and_source_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source.json"
            content = json.dumps({"synthetic": True, "orders": [order()], "payments": [payment()]})
            source.write_text(content, encoding="utf-8")
            command = [sys.executable, str(Path(__file__).with_name("reconcile.py")), str(source)]
            normal = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(normal.returncode, 0, normal.stderr)
            self.assertTrue(json.loads(normal.stdout)["synthetic"])
            blocked = subprocess.run(command + ["--output", str(source)], capture_output=True, text=True)
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(source.read_text(encoding="utf-8"), content)


if __name__ == "__main__":
    unittest.main()
