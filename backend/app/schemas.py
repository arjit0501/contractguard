"""Pydantic schemas shared by extraction, the audit agent, the API and the MCP server.

The extraction schemas intentionally have no default values: OpenAI Structured
Outputs (strict mode) requires every property to be present in `required`, so
optional data is modelled as `Optional[...]` (nullable) instead.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Invoice extraction
# ---------------------------------------------------------------------------


class LineItem(BaseModel):
    description: str = Field(description="Line item description exactly as printed")
    quantity: float
    unit_price: float = Field(description="Price per unit, before any discount")
    amount: float = Field(description="Line total as printed on the invoice")


class InvoiceDiscount(BaseModel):
    description: str
    amount: float = Field(description="Discount amount as a positive number")


class InvoiceExtraction(BaseModel):
    vendor_name: str
    invoice_number: str
    invoice_date: str = Field(description="Invoice date in ISO format YYYY-MM-DD")
    payment_terms: Optional[str] = Field(description="Payment terms as printed, e.g. 'Net 30'")
    line_items: List[LineItem]
    discounts: List[InvoiceDiscount]
    tax: float = Field(description="Total tax, 0 if none")
    total: float = Field(description="Invoice grand total as printed")

    @property
    def subtotal(self) -> float:
        return round(sum(li.amount for li in self.line_items), 2)

    @property
    def discount_total(self) -> float:
        return round(sum(d.amount for d in self.discounts), 2)


class TotalsCheck(BaseModel):
    line_items_sum: float
    discount_total: float
    tax: float
    expected_total: float
    stated_total: float
    line_errors: List[str]
    is_valid: bool


def validate_totals(inv: InvoiceExtraction, tolerance: float = 0.01) -> TotalsCheck:
    """Check that each line's qty x unit price matches its amount, and that
    total == sum(line items) - discounts + tax."""
    line_errors: List[str] = []
    for li in inv.line_items:
        expected = round(li.quantity * li.unit_price, 2)
        if abs(expected - li.amount) > tolerance:
            line_errors.append(
                f"'{li.description}': {li.quantity:g} x {li.unit_price:.2f} = {expected:.2f}, "
                f"but invoice shows {li.amount:.2f}"
            )
    expected_total = round(inv.subtotal - inv.discount_total + inv.tax, 2)
    is_valid = not line_errors and abs(expected_total - inv.total) <= tolerance
    return TotalsCheck(
        line_items_sum=inv.subtotal,
        discount_total=inv.discount_total,
        tax=inv.tax,
        expected_total=expected_total,
        stated_total=inv.total,
        line_errors=line_errors,
        is_valid=is_valid,
    )


# ---------------------------------------------------------------------------
# Contract terms (extracted once per contract at ingestion time)
# ---------------------------------------------------------------------------


class ContractRate(BaseModel):
    item: str = Field(description="Item or service name as written in the contract")
    unit: Optional[str] = Field(description="Billing unit, e.g. 'case', 'hour', 'visit'")
    unit_price: float


class ContractDiscount(BaseModel):
    description: str
    percent: float = Field(description="Discount percentage, e.g. 5 for 5%")
    applies_to: str = Field(description="Item name the discount applies to, or 'all'")
    min_quantity: Optional[float] = Field(
        description="Minimum quantity on a single line for the discount to apply, or null"
    )


class ContractTerms(BaseModel):
    vendor_name: str
    rates: List[ContractRate]
    discounts: List[ContractDiscount]
    payment_terms_days: Optional[int] = Field(description="Net payment days, e.g. 45 for Net 45")


_NET_RE = re.compile(r"net\s*(\d{1,3})", re.IGNORECASE)


def parse_net_days(terms: Optional[str]) -> Optional[int]:
    """'Net 45' -> 45, '2/10 Net 30' -> 30, 'Due on receipt' -> 0, unknown -> None."""
    if not terms:
        return None
    m = _NET_RE.search(terms)
    if m:
        return int(m.group(1))
    if re.search(r"(due\s+(up)?on\s+receipt|immediate)", terms, re.IGNORECASE):
        return 0
    return None


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class CheckType(str, Enum):
    PRICE = "price_overcharge"
    MISSING_DISCOUNT = "missing_discount"
    DUPLICATE = "duplicate_invoice"
    PAYMENT_TERMS = "payment_terms_mismatch"
    MATH = "math_error"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingDraft(BaseModel):
    """A finding produced by a deterministic check, before it is persisted."""

    check_type: CheckType
    severity: Severity
    title: str
    detail: str
    amount_at_risk: float
    line_item: Optional[str] = None
    clause_query: Optional[str] = None  # used to retrieve the cited contract clause
    cited_clause: Optional[str] = None
    clause_chunk_id: Optional[int] = None

    @property
    def key(self) -> str:
        return f"{self.check_type.value}:{self.line_item or '-'}:{self.title}"


def severity_for_amount(amount: float) -> Severity:
    if amount >= 500:
        return Severity.HIGH
    if amount >= 100:
        return Severity.MEDIUM
    return Severity.LOW


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------


class ReviewRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    comment: str = Field(min_length=1, max_length=2000)
    reviewer: str = Field(default="reviewer", max_length=100)
