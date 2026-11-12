from __future__ import annotations

import pytest

from app.audit import checks
from app.audit.agent import AuditContext, run_audit
from app.retrieval import InMemoryRetriever
from app.schemas import (
    CheckType,
    ContractDiscount,
    ContractRate,
    ContractTerms,
    InvoiceDiscount,
    InvoiceExtraction,
    LineItem,
)

TERMS = ContractTerms(
    vendor_name="Acme",
    rates=[
        ContractRate(item="Copy paper A4 (case)", unit="case", unit_price=42.0),
        ContractRate(item="Toner cartridge black", unit="cartridge", unit_price=89.0),
    ],
    discounts=[
        ContractDiscount(description="vol", percent=5, applies_to="Copy paper A4 (case)", min_quantity=20),
    ],
    payment_terms_days=45,
)


def inv(lines, discounts=(), terms="Net 45", number="A-1") -> InvoiceExtraction:
    items = [LineItem(description=d, quantity=q, unit_price=p, amount=round(q * p, 2)) for d, q, p in lines]
    disc = [InvoiceDiscount(description=d, amount=a) for d, a in discounts]
    total = round(sum(i.amount for i in items) - sum(d.amount for d in disc), 2)
    return InvoiceExtraction(
        vendor_name="Acme", invoice_number=number, invoice_date="2026-10-01", payment_terms=terms,
        line_items=items, discounts=disc, tax=0.0, total=total,
    )


class TestPrice:
    def test_overcharge(self):
        (f,) = checks.check_price_vs_contract(inv([("Toner cartridge black", 10, 95.0)]), TERMS)
        assert f.check_type == CheckType.PRICE and f.amount_at_risk == 60.0

    def test_at_contract_rate(self):
        assert checks.check_price_vs_contract(inv([("Toner cartridge black", 10, 89.0)]), TERMS) == []

    def test_undercharge_is_not_flagged(self):
        assert checks.check_price_vs_contract(inv([("Toner cartridge black", 10, 80.0)]), TERMS) == []

    def test_fuzzy_item_match(self):
        (f,) = checks.check_price_vs_contract(inv([("TONER CARTRIDGE - BLACK", 1, 99.0)]), TERMS)
        assert f.amount_at_risk == 10.0

    def test_unknown_item_ignored(self):
        assert checks.check_price_vs_contract(inv([("Standing desk", 1, 900.0)]), TERMS) == []


class TestDiscounts:
    def test_volume_discount_missing(self):
        (f,) = checks.check_missing_discounts(inv([("Copy paper A4 (case)", 25, 42.0)]), TERMS)
        assert f.check_type == CheckType.MISSING_DISCOUNT and f.amount_at_risk == 52.5

    def test_below_threshold(self):
        assert checks.check_missing_discounts(inv([("Copy paper A4 (case)", 19, 42.0)]), TERMS) == []

    def test_discount_applied(self):
        i = inv([("Copy paper A4 (case)", 25, 42.0)], discounts=[("Volume discount 5%", 52.5)])
        assert checks.check_missing_discounts(i, TERMS) == []

    def test_partial_discount(self):
        i = inv([("Copy paper A4 (case)", 25, 42.0)], discounts=[("Volume discount", 20.0)])
        (f,) = checks.check_missing_discounts(i, TERMS)
        assert f.amount_at_risk == 32.5

    def test_blanket_discount(self):
        t = TERMS.model_copy(update={"discounts": [ContractDiscount(description="all", percent=10, applies_to="all", min_quantity=None)]})
        (f,) = checks.check_missing_discounts(inv([("Copy paper A4 (case)", 10, 42.0), ("Toner cartridge black", 1, 89.0)]), t)
        assert f.amount_at_risk == 50.9


class TestDuplicate:
    def test_duplicate_number(self):
        prior = [{"id": 7, "invoice_number": "a-1", "invoice_date": "2026-09-01", "total": 100}]
        (f,) = checks.check_duplicate_invoice(inv([("Toner cartridge black", 1, 89.0)], number="A-1"), prior)
        assert f.check_type == CheckType.DUPLICATE and f.amount_at_risk == 89.0

    def test_unique(self):
        prior = [{"invoice_number": "A-0", "invoice_date": "2026-09-01", "total": 100}]
        assert checks.check_duplicate_invoice(inv([("x", 1, 1.0)]), prior) == []


class TestPaymentTerms:
    def test_shorter_terms(self):
        i = inv([("Toner cartridge black", 10, 89.0)], terms="Net 15")
        (f,) = checks.check_payment_terms(i, TERMS, cost_of_capital=0.08)
        assert f.check_type == CheckType.PAYMENT_TERMS
        assert f.amount_at_risk == pytest.approx(890 * 0.08 * 30 / 365, abs=0.01)

    @pytest.mark.parametrize("terms", ["Net 45", "Net 60", None, "see attached"])
    def test_ok_or_unknown(self, terms):
        assert checks.check_payment_terms(inv([("x", 1, 1.0)], terms=terms), TERMS) == []


def test_math_error():
    i = inv([("x", 2, 10.0)]).model_copy(update={"total": 25.0})
    (f,) = checks.check_invoice_math(i)
    assert f.check_type == CheckType.MATH and f.amount_at_risk == 5.0


class TestAgentOffline:
    def _ctx(self, invoice, terms=TERMS, prior=()):
        r = InMemoryRetriever()
        r.add(1, 1, 1, "2. Pricing. (b) Toner cartridge black: USD 89.00 per cartridge;")
        r.add(2, 1, 1, "3. Volume Discount. DISCOUNT: 5% on Copy paper A4 (case) when quantity at least 20.")
        r.add(3, 1, 1, "4. Payment Terms. Buyer shall pay within Net 45 days.")
        return AuditContext(invoice=invoice, terms=terms, prior_invoices=list(prior), retriever=r, vendor_id=1)

    def test_multiple_findings_with_citations(self):
        i = inv([("Toner cartridge black", 10, 95.0), ("Copy paper A4 (case)", 25, 42.0)], terms="Net 15")
        res = run_audit(self._ctx(i), use_llm=False)
        types = {f.check_type for f in res.findings}
        assert types == {CheckType.PRICE, CheckType.MISSING_DISCOUNT, CheckType.PAYMENT_TERMS}
        by_type = {f.check_type: f for f in res.findings}
        assert "Toner" in by_type[CheckType.PRICE].cited_clause
        assert "DISCOUNT" in by_type[CheckType.MISSING_DISCOUNT].cited_clause
        assert "Payment Terms" in by_type[CheckType.PAYMENT_TERMS].cited_clause
        assert res.findings == sorted(res.findings, key=lambda f: -f.amount_at_risk)

    def test_no_contract_runs_only_required_checks(self):
        res = run_audit(self._ctx(inv([("x", 1, 1.0)]), terms=None), use_llm=False)
        assert set(res.checks_run) == {"check_duplicate_invoice", "check_invoice_math"}
        assert res.findings == []

    def test_clean_invoice(self):
        res = run_audit(self._ctx(inv([("Toner cartridge black", 2, 89.0)])), use_llm=False)
        assert res.findings == [] and res.summary == "No issues found."
