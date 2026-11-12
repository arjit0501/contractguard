from __future__ import annotations

import pytest

from app.extraction import parse_contract_terms, parse_invoice_text
from app.pdf import pdf_to_text
from app.schemas import InvoiceDiscount, InvoiceExtraction, LineItem, parse_net_days, validate_totals
from seed.data import CONTRACTS, INVOICES
from seed.generate_pdfs import invoice_lines, render_contract, render_invoice


def _inv(**kw) -> InvoiceExtraction:
    base = dict(
        vendor_name="V", invoice_number="1", invoice_date="2026-01-01", payment_terms="Net 30",
        line_items=[LineItem(description="a", quantity=2, unit_price=10, amount=20)],
        discounts=[], tax=0.0, total=20.0,
    )
    base.update(kw)
    return InvoiceExtraction(**base)


class TestValidateTotals:
    def test_valid(self):
        assert validate_totals(_inv()).is_valid

    def test_discount_and_tax(self):
        inv = _inv(discounts=[InvoiceDiscount(description="d", amount=2)], tax=1.5, total=19.5)
        tc = validate_totals(inv)
        assert tc.is_valid and tc.expected_total == 19.5

    def test_total_mismatch(self):
        tc = validate_totals(_inv(total=25.0))
        assert not tc.is_valid and tc.expected_total == 20.0

    def test_line_math_error(self):
        inv = _inv(line_items=[LineItem(description="a", quantity=2, unit_price=10, amount=22)], total=22)
        tc = validate_totals(inv)
        assert not tc.is_valid and len(tc.line_errors) == 1


@pytest.mark.parametrize(
    "text,days",
    [("Net 45", 45), ("net30", 30), ("2/10 Net 30", 30), ("Due on receipt", 0), ("COD-ish", None), (None, None)],
)
def test_parse_net_days(text, days):
    assert parse_net_days(text) == days


def test_parse_invoice_text_from_layout():
    inv = parse_invoice_text("\n".join(invoice_lines(INVOICES[3])))  # NW-2001, has discount
    assert inv.vendor_name == "Northwind Cloud Services"
    assert inv.invoice_number == "NW-2001"
    assert inv.invoice_date == "2026-09-01"
    assert inv.payment_terms == "Net 30"
    assert [li.description for li in inv.line_items] == ["Compute instance (monthly)", "Storage (TB-month)"]
    assert inv.discount_total == 120.0
    assert inv.total == 1080.0
    assert validate_totals(inv).is_valid


def test_parse_invoice_rejects_unknown_layout():
    with pytest.raises(ValueError):
        parse_invoice_text("hello world")


@pytest.mark.parametrize("seed", INVOICES, ids=lambda i: i["filename"])
def test_invoice_pdf_round_trip(tmp_path, seed):
    """Render each seed invoice to PDF, extract text, parse, and check every field."""
    path = tmp_path / seed["filename"]
    render_invoice(seed, path)
    inv = parse_invoice_text(pdf_to_text(path.read_bytes()))
    assert inv.invoice_number == seed["number"]
    assert inv.vendor_name == seed["vendor"]
    assert inv.payment_terms == seed["terms"]
    assert [(li.description, li.quantity, li.unit_price) for li in inv.line_items] == [
        (d, float(q), p) for d, q, p in seed["lines"]
    ]
    assert validate_totals(inv).is_valid


def test_contract_terms_from_pdf(tmp_path):
    path = tmp_path / "acme.pdf"
    render_contract(CONTRACTS[0], path)
    terms = parse_contract_terms(pdf_to_text(path.read_bytes()), "Acme Office Supplies")
    assert {r.item: r.unit_price for r in terms.rates} == {
        "Copy paper A4 (case)": 42.0,
        "Toner cartridge black": 89.0,
        "Ballpoint pens (box of 50)": 12.5,
    }
    assert terms.payment_terms_days == 45
    (d,) = terms.discounts
    assert (d.percent, d.applies_to, d.min_quantity) == (5.0, "Copy paper A4 (case)", 20.0)


def test_contract_terms_blanket_discount():
    terms = parse_contract_terms(CONTRACTS[1]["text"], "Northwind Cloud Services")
    (d,) = terms.discounts
    assert (d.percent, d.applies_to, d.min_quantity) == (10.0, "all", None)
    assert terms.payment_terms_days == 30
