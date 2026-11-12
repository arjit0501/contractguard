"""Run the full pipeline (PDF -> extraction -> chunk/embed -> hybrid retrieval ->
agent) in memory, without PostgreSQL. Used by the evals and end-to-end tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .audit.agent import AuditContext, AuditResult, run_audit
from .chunking import chunk_contract
from .config import get_settings
from .extraction import extract_contract_terms, extract_invoice
from .llm import embed
from .pdf import pdf_to_text
from .retrieval import InMemoryRetriever
from .schemas import ContractTerms, InvoiceExtraction


@dataclass
class LocalInvoiceResult:
    filename: str
    extraction: InvoiceExtraction
    audit: AuditResult


def run_local(
    contracts: Sequence[Tuple[str, bytes]],  # (vendor_name, pdf bytes)
    invoices: Sequence[Tuple[str, bytes]],  # (filename, pdf bytes), in arrival order
    use_llm: Optional[bool] = None,
) -> List[LocalInvoiceResult]:
    retriever = InMemoryRetriever()
    vendor_ids: Dict[str, int] = {}
    terms: Dict[int, ContractTerms] = {}
    chunk_id = 0
    for contract_id, (vendor, data) in enumerate(contracts, start=1):
        vid = vendor_ids.setdefault(vendor.lower(), len(vendor_ids) + 1)
        text = pdf_to_text(data)
        terms[vid] = extract_contract_terms(text, vendor, use_llm=use_llm)
        chunks = chunk_contract(text)
        for c, v in zip(chunks, embed([c.text for c in chunks])):
            chunk_id += 1
            retriever.add(chunk_id, contract_id, vid, c.text, c.heading, v)

    seen: Dict[int, List[dict]] = {}
    out: List[LocalInvoiceResult] = []
    for filename, data in invoices:
        inv, _ = extract_invoice(pdf_to_text(data), use_llm=use_llm)
        vid = vendor_ids.get(inv.vendor_name.strip().lower())
        ctx = AuditContext(
            invoice=inv,
            terms=terms.get(vid) if vid else None,
            prior_invoices=seen.get(vid, []) if vid else [],
            retriever=retriever if vid else None,
            vendor_id=vid,
            cost_of_capital=get_settings().cost_of_capital,
        )
        result = run_audit(ctx, use_llm=use_llm)
        if vid:
            seen.setdefault(vid, []).append(
                {"invoice_number": inv.invoice_number, "invoice_date": inv.invoice_date, "total": inv.total}
            )
        out.append(LocalInvoiceResult(filename, inv, result))
    return out
