"""Application services shared by the API, the seed loader and the MCP server."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .audit.agent import AuditContext, run_audit
from .chunking import chunk_contract
from .config import get_settings
from .extraction import extract_contract_terms, extract_invoice
from .llm import embed
from .models import Contract, ContractChunk, Finding, Invoice, ReviewDecision, Vendor
from .pdf import pdf_to_text
from .retrieval import PgRetriever
from .schemas import ContractTerms, InvoiceExtraction, validate_totals


def _norm_name(name: str) -> str:
    return " ".join(name.lower().split())


def get_or_create_vendor(session: Session, name: str) -> Vendor:
    vendor = session.scalar(select(Vendor).where(func.lower(Vendor.name) == _norm_name(name)))
    if vendor is None:
        vendor = Vendor(name=name.strip())
        session.add(vendor)
        session.flush()
    return vendor


def find_vendor(session: Session, name: str) -> Optional[Vendor]:
    return session.scalar(select(Vendor).where(func.lower(Vendor.name) == _norm_name(name)))


def ingest_contract(session: Session, data: bytes, filename: str, vendor_name: str) -> Contract:
    s = get_settings()
    text = pdf_to_text(data)
    if not text:
        raise ValueError("No text found in contract PDF (scanned PDFs need OCR first).")
    vendor = get_or_create_vendor(session, vendor_name)
    terms = extract_contract_terms(text, vendor.name)
    contract = Contract(vendor_id=vendor.id, filename=filename, text=text, terms=terms.model_dump())
    session.add(contract)
    session.flush()

    chunks = chunk_contract(text)
    vectors = embed([c.text for c in chunks])
    for c, v in zip(chunks, vectors):
        session.add(
            ContractChunk(
                contract_id=contract.id,
                vendor_id=vendor.id,
                chunk_index=c.index,
                heading=c.heading,
                text=c.text,
                embedding=v,
                embedding_model=s.active_embedding_model,
            )
        )
    session.flush()
    return contract


def vendor_terms(session: Session, vendor_id: int) -> Optional[ContractTerms]:
    """Latest contract's terms for a vendor."""
    contract = session.scalar(
        select(Contract).where(Contract.vendor_id == vendor_id).order_by(Contract.created_at.desc(), Contract.id.desc())
    )
    return ContractTerms.model_validate(contract.terms) if contract and contract.terms else None


def _parse_date(s: str) -> Optional[date]:
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def ingest_invoice(session: Session, data: bytes, filename: str) -> Invoice:
    text = pdf_to_text(data)
    if not text:
        raise ValueError("No text found in invoice PDF (scanned PDFs need OCR first).")
    extraction, mode = extract_invoice(text)
    tc = validate_totals(extraction)
    vendor = find_vendor(session, extraction.vendor_name)
    invoice = Invoice(
        vendor_id=vendor.id if vendor else None,
        filename=filename,
        invoice_number=extraction.invoice_number,
        invoice_date=_parse_date(extraction.invoice_date),
        payment_terms=extraction.payment_terms,
        subtotal=extraction.subtotal,
        discount_total=extraction.discount_total,
        tax=extraction.tax,
        total=extraction.total,
        totals_valid=tc.is_valid,
        extraction=extraction.model_dump(),
        extraction_mode=mode,
    )
    session.add(invoice)
    session.flush()
    audit_invoice(session, invoice)
    return invoice


def audit_invoice(session: Session, invoice: Invoice) -> Invoice:
    s = get_settings()
    extraction = InvoiceExtraction.model_validate(invoice.extraction)
    terms = vendor_terms(session, invoice.vendor_id) if invoice.vendor_id else None
    prior = []
    if invoice.vendor_id:
        prior = [
            {"id": p.id, "invoice_number": p.invoice_number, "invoice_date": str(p.invoice_date), "total": p.total}
            for p in session.scalars(
                select(Invoice).where(Invoice.vendor_id == invoice.vendor_id, Invoice.id < invoice.id)
            )
        ]
    ctx = AuditContext(
        invoice=extraction,
        terms=terms,
        prior_invoices=prior,
        retriever=PgRetriever(session, s.active_embedding_model) if invoice.vendor_id else None,
        vendor_id=invoice.vendor_id,
        cost_of_capital=s.cost_of_capital,
    )
    result = run_audit(ctx)

    # Re-audits replace open findings but never touch reviewed ones (audit trail).
    reviewed = {(f.check_type, f.title) for f in invoice.findings if f.status != "open"}
    for f in [f for f in invoice.findings if f.status == "open"]:
        invoice.findings.remove(f)
    session.flush()
    for f in result.findings:
        if (f.check_type.value, f.title) in reviewed:
            continue
        invoice.findings.append(
            Finding(
                check_type=f.check_type.value,
                severity=f.severity.value,
                title=f.title,
                detail=f.detail,
                amount_at_risk=f.amount_at_risk,
                line_item=f.line_item,
                cited_clause=f.cited_clause,
                clause_chunk_id=f.clause_chunk_id,
                status="open",
            )
        )
    note = "" if terms else " No contract on file for this vendor; contract checks skipped."
    invoice.audit_summary = result.summary + note
    invoice.audit_trace = {"mode": result.mode, "checks_run": result.checks_run, "steps": result.trace}
    invoice.amount_at_risk = result.amount_at_risk
    if any(f.status == "open" for f in invoice.findings):
        invoice.status = "flagged"
    else:
        invoice.status = "reviewed" if invoice.findings else "clean"
    session.flush()
    return invoice


def review_finding(session: Session, finding_id: int, decision: str, comment: str, reviewer: str) -> Finding:
    finding = session.get(Finding, finding_id)
    if finding is None:
        raise LookupError(f"finding {finding_id} not found")
    session.add(ReviewDecision(finding_id=finding.id, decision=decision, comment=comment, reviewer=reviewer))
    finding.status = decision
    session.flush()
    invoice = finding.invoice
    if all(f.status != "open" for f in invoice.findings):
        invoice.status = "reviewed"
    session.flush()
    return finding


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def _money(v: Any) -> float:
    return round(float(v or 0), 2)


def finding_to_dict(f: Finding) -> Dict[str, Any]:
    return {
        "id": f.id,
        "invoice_id": f.invoice_id,
        "check_type": f.check_type,
        "severity": f.severity,
        "title": f.title,
        "detail": f.detail,
        "amount_at_risk": _money(f.amount_at_risk),
        "line_item": f.line_item,
        "cited_clause": f.cited_clause,
        "status": f.status,
        "decisions": [
            {
                "decision": d.decision,
                "comment": d.comment,
                "reviewer": d.reviewer,
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in f.decisions
        ],
    }


def invoice_to_dict(inv: Invoice, with_findings: bool = False) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "id": inv.id,
        "vendor": inv.vendor.name if inv.vendor else (inv.extraction or {}).get("vendor_name"),
        "vendor_id": inv.vendor_id,
        "filename": inv.filename,
        "invoice_number": inv.invoice_number,
        "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
        "payment_terms": inv.payment_terms,
        "subtotal": _money(inv.subtotal),
        "discount_total": _money(inv.discount_total),
        "total": _money(inv.total),
        "totals_valid": inv.totals_valid,
        "status": inv.status,
        "amount_at_risk": _money(inv.amount_at_risk),
        "open_findings": sum(1 for f in inv.findings if f.status == "open"),
        "finding_count": len(inv.findings),
        "audit_summary": inv.audit_summary,
        "extraction_mode": inv.extraction_mode,
    }
    if with_findings:
        out["line_items"] = (inv.extraction or {}).get("line_items", [])
        out["discounts"] = (inv.extraction or {}).get("discounts", [])
        out["audit_trace"] = inv.audit_trace
        out["findings"] = [finding_to_dict(f) for f in inv.findings]
    return out


def list_invoices(
    session: Session,
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    vendor: Optional[str] = None,
) -> List[Invoice]:
    q = select(Invoice).options(selectinload(Invoice.findings), selectinload(Invoice.vendor))
    if status:
        q = q.where(Invoice.status == status)
    if date_from:
        q = q.where(Invoice.invoice_date >= date_from)
    if date_to:
        q = q.where(Invoice.invoice_date <= date_to)
    if vendor:
        v = find_vendor(session, vendor)
        q = q.where(Invoice.vendor_id == (v.id if v else -1))
    return list(session.scalars(q.order_by(Invoice.amount_at_risk.desc(), Invoice.id)))
