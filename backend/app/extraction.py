"""Document extraction: invoice PDF -> InvoiceExtraction, contract text -> ContractTerms.

With an OpenAI key, both use Structured Outputs against the Pydantic schemas.
Without one, a deterministic parser for the seed-data layout is used so the
project runs fully offline.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from .config import get_settings
from .llm import structured_completion
from .schemas import (
    ContractDiscount,
    ContractRate,
    ContractTerms,
    InvoiceDiscount,
    InvoiceExtraction,
    LineItem,
    parse_net_days,
)

INVOICE_SYSTEM_PROMPT = """You extract data from vendor invoices for an accounts-payable audit.
Rules:
- Copy line item descriptions verbatim.
- quantity, unit_price and amount must be numbers exactly as printed (no currency symbols).
- Put any discount or credit lines in `discounts` with a POSITIVE amount; never as line items.
- invoice_date must be ISO YYYY-MM-DD.
- tax is 0 when no tax line is printed.
- Do not correct the vendor's arithmetic; report what is printed."""

CONTRACT_SYSTEM_PROMPT = """You extract commercial terms from a vendor contract for invoice auditing.
Return:
- rates: every item/service with a fixed contracted unit price.
- discounts: every discount the buyer is entitled to. percent is a number (5 for 5%).
  applies_to is the exact item name from `rates`, or 'all' if it applies to the whole invoice.
  min_quantity is the minimum quantity on one line for volume discounts, otherwise null.
- payment_terms_days: the Net payment days (e.g. 45 for 'Net 45')."""


def _money(s: str) -> float:
    return float(s.replace(",", "").replace("$", ""))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

_FIELD_RES = {
    "vendor_name": re.compile(r"^\s*Vendor:\s*(.+?)\s*$", re.M),
    "invoice_number": re.compile(r"^\s*Invoice (?:Number|No\.?|#):\s*(\S+)\s*$", re.M),
    "invoice_date": re.compile(r"^\s*Invoice Date:\s*(\d{4}-\d{2}-\d{2})\s*$", re.M),
    "payment_terms": re.compile(r"^\s*Payment Terms:\s*(.+?)\s*$", re.M),
}
_LINE_RE = re.compile(
    r"^\s*(?P<desc>\S.*?)\s+(?P<qty>\d+(?:\.\d+)?)\s+\$?(?P<price>[\d,]+\.\d{2})\s+\$?(?P<amount>[\d,]+\.\d{2})\s*$"
)
_DISCOUNT_RE = re.compile(r"^\s*(?P<desc>(?:Discount|Credit)\b.*?)\s+-\$?(?P<amount>[\d,]+\.\d{2})\s*$", re.I)
_TAX_RE = re.compile(r"^\s*Tax\b.*?\s+\$?(?P<amount>[\d,]+\.\d{2})\s*$", re.I)
_TOTAL_RE = re.compile(r"^\s*(?:Total Due|Total)\s*:?\s+\$?(?P<amount>[\d,]+\.\d{2})\s*$", re.I)


def parse_invoice_text(text: str) -> InvoiceExtraction:
    """Deterministic parser for the seed invoice layout (offline fallback)."""
    fields = {}
    for name, rx in _FIELD_RES.items():
        m = rx.search(text)
        fields[name] = m.group(1) if m else None
    if not fields["vendor_name"] or not fields["invoice_number"]:
        raise ValueError("Could not find vendor name / invoice number. Set OPENAI_API_KEY for LLM extraction.")

    items: List[LineItem] = []
    discounts: List[InvoiceDiscount] = []
    tax = 0.0
    total: Optional[float] = None
    for line in text.splitlines():
        if m := _DISCOUNT_RE.match(line):
            discounts.append(InvoiceDiscount(description=m["desc"].strip(), amount=_money(m["amount"])))
        elif m := _TAX_RE.match(line):
            tax = _money(m["amount"])
        elif m := _TOTAL_RE.match(line):
            total = _money(m["amount"])
        elif re.match(r"^\s*Subtotal\b", line, re.I):
            continue
        elif m := _LINE_RE.match(line):
            items.append(
                LineItem(
                    description=m["desc"].strip(),
                    quantity=float(m["qty"]),
                    unit_price=_money(m["price"]),
                    amount=_money(m["amount"]),
                )
            )
    if total is None:
        raise ValueError("Could not find invoice total")
    return InvoiceExtraction(
        vendor_name=fields["vendor_name"],
        invoice_number=fields["invoice_number"],
        invoice_date=fields["invoice_date"] or "",
        payment_terms=fields["payment_terms"],
        line_items=items,
        discounts=discounts,
        tax=tax,
        total=total,
    )


def extract_invoice(text: str, use_llm: Optional[bool] = None) -> Tuple[InvoiceExtraction, str]:
    """Return (extraction, mode) where mode is 'llm' or 'parser'."""
    if use_llm is None:
        use_llm = get_settings().llm_enabled
    if use_llm:
        inv = structured_completion(INVOICE_SYSTEM_PROMPT, f"Invoice text:\n\n{text}", InvoiceExtraction)
        return inv, "llm"
    return parse_invoice_text(text), "parser"


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

# "(a) Copy paper A4 (case): USD 42.00 per case;"
_RATE_RE = re.compile(
    r"\(([a-z])\)\s+(?P<item>[^:;]+?):\s+(?:USD|\$)\s?(?P<price>[\d,]+\.\d{2})\s+per\s+(?P<unit>[^;.]+?)\s*[;.]"
)
# "DISCOUNT: 5% on Copy paper A4 (case) when a single invoice line has a quantity of at least 20."
# "DISCOUNT: 10% on all services."
_DISC_RE = re.compile(
    r"DISCOUNT:\s*(?P<pct>\d+(?:\.\d+)?)%\s+on\s+(?P<target>.+?)"
    r"(?:\s+when a single invoice line has a quantity of at least\s+(?P<minq>\d+(?:\.\d+)?))?\s*\.(?:\s|$)"
)
_PAY_RE = re.compile(r"Payment Terms\.?\s.*?\bNet\s+(\d{1,3})\b", re.I | re.S)


def parse_contract_terms(text: str, vendor_name: str) -> ContractTerms:
    """Deterministic parser for the seed contract layout (offline fallback)."""
    flat = re.sub(r"\s+", " ", text)
    rates = [
        ContractRate(item=m["item"].strip(), unit=m["unit"].strip(), unit_price=_money(m["price"]))
        for m in _RATE_RE.finditer(flat)
    ]
    discounts: List[ContractDiscount] = []
    for m in _DISC_RE.finditer(flat):
        target = m["target"].strip()
        applies_to = "all" if target.lower().startswith("all ") or target.lower() == "all" else target
        discounts.append(
            ContractDiscount(
                description=m.group(0).strip().rstrip("."),
                percent=float(m["pct"]),
                applies_to=applies_to,
                min_quantity=float(m["minq"]) if m["minq"] else None,
            )
        )
    pm = _PAY_RE.search(flat)
    days = int(pm.group(1)) if pm else parse_net_days(flat)
    return ContractTerms(vendor_name=vendor_name, rates=rates, discounts=discounts, payment_terms_days=days)


def extract_contract_terms(text: str, vendor_name: str, use_llm: Optional[bool] = None) -> ContractTerms:
    if use_llm is None:
        use_llm = get_settings().llm_enabled
    if use_llm:  # pragma: no cover - requires network
        terms = structured_completion(
            CONTRACT_SYSTEM_PROMPT, f"Vendor: {vendor_name}\n\nContract text:\n\n{text}", ContractTerms
        )
        return terms.model_copy(update={"vendor_name": vendor_name})
    return parse_contract_terms(text, vendor_name)
