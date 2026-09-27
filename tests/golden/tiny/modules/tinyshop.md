# Module `tinyshop`

<!-- prism:generated:facts -->
- Files: tinyshop/__init__.py, tinyshop/cart.py, tinyshop/cli.py, tinyshop/pricing.py
- Docstring: A tiny shop used as a PRISM test fixture.
- Public API (by importance):
  - `eligible_rules(total: float, coupon: str | None) -> list[float]` — Return the discount rates that apply to this total. (tinyshop/pricing.py:4)
  - `apply_discount(total: float, coupon: str | None = None) -> float` — Apply the best eligible discount to a total. (tinyshop/pricing.py:14)
  - `class Cart` — A list of priced items. (tinyshop/cart.py:6)
  - `main(argv: list[str] | None = None) -> int` (tinyshop/cli.py:8)
- Tests: tests/test_pricing.py
- Entry points: `tinyshop`, `tinyshop.cli.main`
<!-- /prism:generated:facts -->

## Summary
<!-- prism:narrative:summary -->
_Not written yet. Run the prism-refresh skill to fill this section._
<!-- /prism:narrative:summary -->
