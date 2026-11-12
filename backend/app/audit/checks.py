"""Deterministic audit checks.

Every number in a finding comes from these functions, never from the LLM, so
amounts at risk are reproducible and testable. The agent decides *which*
checks to run; these functions decide *what* they find.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence

from ..schemas import (
    CheckType,
    ContractRate,
    ContractTerms,
    FindingDraft,
    InvoiceExtraction,
    LineItem,
    Severity,
    parse_net_days,
    severity_for_amount,
    validate_totals,
)

PRICE_TOLERANCE = 0.005  # ignore sub-cent rounding


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def item_similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb)
    return max(SequenceMatcher(None, na, nb).ratio(), jaccard)


def match_rate(description: str, rates: Sequence[ContractRate], threshold: float = 0.6) -> Optional[ContractRate]:
    best, best_score = None, 0.0
    for r in rates:
        score = item_similarity(description, r.item)
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= threshold else None


def check_price_vs_contract(invoice: InvoiceExtraction, terms: ContractTerms) -> List[FindingDraft]:
    findings = []
    for li in invoice.line_items:
        rate = match_rate(li.description, terms.rates)
        if rate is None:
            continue
        diff = round(li.unit_price - rate.unit_price, 4)
        if diff > PRICE_TOLERANCE:
            at_risk = round(diff * li.quantity, 2)
            pct = diff / rate.unit_price * 100 if rate.unit_price else 0
            findings.append(
                FindingDraft(
                    check_type=CheckType.PRICE,
                    severity=severity_for_amount(at_risk) if pct < 15 else Severity.HIGH,
                    title=f"Billed above contracted rate: {li.description}",
                    detail=(
                        f"Invoice bills {li.quantity:g} x ${li.unit_price:,.2f}; contract rate is "
                        f"${rate.unit_price:,.2f} per {rate.unit or 'unit'} (+{pct:.1f}%). "
                        f"Overcharge: ${at_risk:,.2f}."
                    ),
                    amount_at_risk=at_risk,
                    line_item=li.description,
                    clause_query=f"{rate.item} price per {rate.unit or 'unit'}",
                )
            )
    return findings


def _discount_targets(li: LineItem, applies_to: str) -> bool:
    return applies_to.lower() == "all" or item_similarity(li.description, applies_to) >= 0.6


def check_missing_discounts(invoice: InvoiceExtraction, terms: ContractTerms) -> List[FindingDraft]:
    """Compute every discount the contract entitles us to and compare with what
    the invoice actually applied. Applied discounts are allocated to entitlements
    in contract order, so one generic discount line can satisfy one entitlement."""
    findings = []
    applied_pool = invoice.discount_total
    for disc in terms.discounts:
        eligible = [
            li
            for li in invoice.line_items
            if _discount_targets(li, disc.applies_to)
            and (disc.min_quantity is None or li.quantity >= disc.min_quantity)
        ]
        if not eligible:
            continue
        base = sum(li.amount for li in eligible)
        entitled = round(base * disc.percent / 100, 2)
        covered = min(applied_pool, entitled)
        applied_pool = round(applied_pool - covered, 2)
        shortfall = round(entitled - covered, 2)
        if shortfall > 0.01:
            target = "invoice subtotal" if disc.applies_to.lower() == "all" else disc.applies_to
            findings.append(
                FindingDraft(
                    check_type=CheckType.MISSING_DISCOUNT,
                    severity=severity_for_amount(shortfall),
                    title=f"Missing {disc.percent:g}% discount on {target}",
                    detail=(
                        f"Contract grants {disc.percent:g}% on {target}"
                        + (f" (qty >= {disc.min_quantity:g})" if disc.min_quantity else "")
                        + f". Eligible amount ${base:,.2f} -> entitled ${entitled:,.2f}, "
                        f"applied ${covered:,.2f}. Shortfall: ${shortfall:,.2f}."
                    ),
                    amount_at_risk=shortfall,
                    line_item=None if disc.applies_to.lower() == "all" else eligible[0].description,
                    clause_query=f"discount {disc.percent:g}% {disc.applies_to}",
                )
            )
    return findings


def check_duplicate_invoice(
    invoice: InvoiceExtraction, prior_invoices: Sequence[Dict[str, object]]
) -> List[FindingDraft]:
    """`prior_invoices`: earlier invoices from the same vendor, each a dict with
    invoice_number, invoice_date, total and (optionally) id."""
    num = _norm(invoice.invoice_number)
    for p in prior_invoices:
        if _norm(str(p["invoice_number"])) == num:
            return [
                FindingDraft(
                    check_type=CheckType.DUPLICATE,
                    severity=Severity.HIGH,
                    title=f"Duplicate invoice number {invoice.invoice_number}",
                    detail=(
                        f"Invoice number {invoice.invoice_number} was already received "
                        f"(dated {p.get('invoice_date')}, total ${float(p['total']):,.2f}"  # type: ignore[arg-type]
                        + (f", invoice id {p['id']}" if p.get("id") is not None else "")
                        + f"). Paying again would double-pay ${invoice.total:,.2f}."
                    ),
                    amount_at_risk=round(invoice.total, 2),
                    clause_query=None,
                )
            ]
    return []


def check_payment_terms(
    invoice: InvoiceExtraction, terms: ContractTerms, cost_of_capital: float = 0.08
) -> List[FindingDraft]:
    contract_days = terms.payment_terms_days
    invoice_days = parse_net_days(invoice.payment_terms)
    if contract_days is None or invoice_days is None or invoice_days >= contract_days:
        return []
    gap = contract_days - invoice_days
    cost = round(invoice.total * cost_of_capital * gap / 365, 2)
    return [
        FindingDraft(
            check_type=CheckType.PAYMENT_TERMS,
            severity=Severity.MEDIUM,
            title=f"Payment terms shorter than contract ({invoice.payment_terms} vs Net {contract_days})",
            detail=(
                f"Invoice demands payment in {invoice_days} days but the contract allows {contract_days}. "
                f"Paying {gap} days early on ${invoice.total:,.2f} costs about ${cost:,.2f} "
                f"in working capital at {cost_of_capital:.0%}/yr. Pay on contract terms."
            ),
            amount_at_risk=cost,
            clause_query="payment terms net days",
        )
    ]


def check_invoice_math(invoice: InvoiceExtraction) -> List[FindingDraft]:
    tc = validate_totals(invoice)
    if tc.is_valid:
        return []
    over = round(max(tc.stated_total - tc.expected_total, 0), 2)
    return [
        FindingDraft(
            check_type=CheckType.MATH,
            severity=severity_for_amount(over) if over else Severity.LOW,
            title="Invoice arithmetic does not add up",
            detail="; ".join(
                tc.line_errors
                + [f"Expected total ${tc.expected_total:,.2f}, invoice states ${tc.stated_total:,.2f}"]
            ),
            amount_at_risk=over,
            clause_query=None,
        )
    ]
