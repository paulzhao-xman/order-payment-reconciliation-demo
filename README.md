# Order and payment reconciliation demo

A small, AI-assisted Python prototype showing how transaction checks can remain traceable. All included business records are synthetic. This is a demonstration, not a client case study or a production accounting system.

## What it does

- Matches orders and payments by order ID and currency.
- Adds split payments using decimal arithmetic.
- Reports amount differences, orders without valid payments, and unknown order references.
- Quarantines every record with a duplicate ID rather than silently choosing one.
- Preserves invalid amounts and currency conflicts in an exception list.
- Leaves source files untouched and refuses to overwrite an existing output.

The included example produces one matched order, one amount difference, two orders without valid payments, and nine exception records. An order without valid payments is not necessarily unpaid: its payment may be in the exception list and requires review.

## Run

Python 3.10 or later. No third-party packages are required.

```bash
python3 reconcile.py synthetic_input.json
python3 -m unittest -v test_reconcile.py
```

To save a new result file:

```bash
python3 reconcile.py synthetic_input.json --output result.json
```

## Scope

JSON input and output only. No Excel import, user interface, refunds, exchange-rate conversion, tax calculations, or production database integration. Amounts must be nonnegative decimal values. Supported currency codes are explicit in the source. Duplicate IDs are treated as ambiguous; no records are silently discarded. Synthetic tests do not establish correctness on a customer's data or prove time savings.

Customer work would require agreed sample data, matching rules, acceptance tests, deployment requirements, and authorization for any AI-assisted processing before implementation.
