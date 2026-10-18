"""JSON-only reconciliation sales prototype; not accounting advice or a client delivery."""

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import re
import sys

SUPPORTED_CURRENCIES = frozenset({"CNY", "USD", "EUR", "GBP", "JPY", "HKD", "AUD", "CAD", "SGD"})


def identifier(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def amount(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Amount must be a decimal string or JSON number")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
        raise ValueError("Amount must use digits and an optional decimal point only")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError("Amount is not decimal") from None
    if not parsed.is_finite() or parsed < 0:
        raise ValueError("Amount must be finite and nonnegative; refunds are out of scope")
    if len(parsed.as_tuple().digits) > 24 or abs(parsed.as_tuple().exponent) > 12:
        raise ValueError("Amount exceeds prototype precision bounds")
    return parsed


def decimal_text(value):
    return format(value, "f")


def exact_add(left, right):
    with localcontext() as context:
        context.prec = 64
        return left + right


def reconcile(data):
    if not isinstance(data, dict):
        raise ValueError("Root must be a JSON object")
    if not isinstance(data.get("orders"), list) or not isinstance(data.get("payments"), list):
        raise ValueError("orders and payments must be arrays")
    if len(data["orders"]) > 100000 or len(data["payments"]) > 100000:
        raise ValueError("Prototype input limit: 100000 records per collection")
    exceptions = []

    def reject(kind, index, record, reasons):
        exceptions.append({"source": kind, "index": index, "reasons": reasons, "record": record})

    def duplicates(records, key):
        return Counter(r[key] for r in records if isinstance(r, dict) and identifier(r.get(key)))

    order_ids = duplicates(data["orders"], "order_id")
    payment_ids = duplicates(data["payments"], "payment_id")
    orders = {}
    totals = {}
    counted_payment_ids = {}

    def validate(record, kind, id_counts):
        if not isinstance(record, dict):
            return ["record_not_object"], None
        reasons = []
        key = "order_id" if kind == "orders" else "payment_id"
        if not identifier(record.get(key)):
            reasons.append("invalid_" + key)
        elif id_counts[record[key]] > 1:
            reasons.append("duplicate_" + key)
        if kind == "payments" and not identifier(record.get("order_id")):
            reasons.append("invalid_order_id")
        currency = record.get("currency")
        if not isinstance(currency, str) or currency not in SUPPORTED_CURRENCIES:
            reasons.append("unsupported_currency")
        try:
            parsed = amount(record.get("amount"))
        except ValueError:
            parsed = None
            reasons.append("invalid_amount")
        return reasons, parsed

    for index, record in enumerate(data["orders"]):
        reasons, parsed = validate(record, "orders", order_ids)
        if reasons:
            reject("orders", index, record, reasons)
            continue
        order_id = record["order_id"]
        orders[order_id] = (record, parsed)
        totals[order_id] = Decimal(0)
        counted_payment_ids[order_id] = []

    for index, record in enumerate(data["payments"]):
        reasons, parsed = validate(record, "payments", payment_ids)
        if isinstance(record, dict) and identifier(record.get("order_id")):
            order_id = record["order_id"]
            if order_id not in orders:
                reasons.append("ambiguous_or_invalid_order" if order_ids[order_id] else "unknown_order")
            elif record.get("currency") != orders[order_id][0]["currency"]:
                reasons.append("currency_mismatch")
        if reasons:
            reject("payments", index, record, reasons)
            continue
        order_id = record["order_id"]
        totals[order_id] = exact_add(totals[order_id], parsed)
        counted_payment_ids[order_id].append(record["payment_id"])

    results = []
    for order_id, (record, expected) in orders.items():
        received = totals[order_id]
        status = "missing_payment" if not counted_payment_ids[order_id] else ("matched" if received == expected else "amount_difference")
        results.append({
            "order_id": order_id, "currency": record["currency"],
            "expected": decimal_text(expected), "received": decimal_text(received),
            "difference_received_minus_expected": decimal_text(exact_add(received, expected.copy_negate())),
            "status": status, "counted_payment_ids": counted_payment_ids[order_id],
        })
    return {
        "prototype": True, "synthetic": data.get("synthetic") is True,
        "policy": "All duplicate-ID records are quarantined, not first-wins. No currency conversion. Exceptions remain visible. Review exceptions before acting on an order status.",
        "input_counts": {"orders": len(data["orders"]), "payments": len(data["payments"])},
        "order_results": results, "exceptions": exceptions,
        "summary": dict(Counter(item["status"] for item in results), exception_records=len(exceptions)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, help="Optional NEW output file; never overwrites an existing file")
    args = parser.parse_args()
    try:
        if args.output and args.output.resolve() == args.input.resolve():
            raise ValueError("Output must not replace source input")
        data = json.loads(args.input.read_text(encoding="utf-8"), parse_float=Decimal, parse_constant=Decimal)
        result = reconcile(data)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, default=decimal_text, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as handle:
                handle.write(rendered)
        else:
            sys.stdout.write(rendered)
        return 0
    except (ValueError, TypeError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
