from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import services
from .config import get_settings
from .db import get_session, init_db
from .models import Contract, Finding, Invoice, Vendor
from .retrieval import PgRetriever
from .schemas import ReviewRequest

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ContractGuard", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _read_pdf(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 20 MB)")
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, f"{file.filename} is not a PDF")
    return data


@app.get("/api/health")
def health() -> dict:
    s = get_settings()
    return {"status": "ok", "llm_enabled": s.llm_enabled, "model": s.chat_model if s.llm_enabled else None}


@app.get("/api/stats")
def stats(session: Session = Depends(get_session)) -> dict:
    open_risk = session.scalar(select(func.coalesce(func.sum(Finding.amount_at_risk), 0)).where(Finding.status == "open"))
    saved = session.scalar(select(func.coalesce(func.sum(Finding.amount_at_risk), 0)).where(Finding.status == "approved"))
    return {
        "vendors": session.scalar(select(func.count(Vendor.id))),
        "contracts": session.scalar(select(func.count(Contract.id))),
        "invoices": session.scalar(select(func.count(Invoice.id))),
        "flagged": session.scalar(select(func.count(Invoice.id)).where(Invoice.status == "flagged")),
        "open_amount_at_risk": round(float(open_risk), 2),
        "approved_recoveries": round(float(saved), 2),
    }


@app.get("/api/vendors")
def vendors(session: Session = Depends(get_session)) -> list:
    return [{"id": v.id, "name": v.name} for v in session.scalars(select(Vendor).order_by(Vendor.name))]


@app.get("/api/contracts")
def contracts(session: Session = Depends(get_session)) -> list:
    rows = session.scalars(select(Contract).order_by(Contract.id))
    return [
        {"id": c.id, "vendor": c.vendor.name, "filename": c.filename, "terms": c.terms, "chunks": len(c.chunks)}
        for c in rows
    ]


@app.post("/api/contracts", status_code=201)
async def upload_contract(
    file: UploadFile = File(...), vendor_name: str = Form(...), session: Session = Depends(get_session)
) -> dict:
    data = await _read_pdf(file)
    try:
        c = services.ingest_contract(session, data, file.filename or "contract.pdf", vendor_name)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": c.id, "vendor": c.vendor.name, "terms": c.terms, "chunks": len(c.chunks)}


@app.post("/api/invoices", status_code=201)
async def upload_invoice(file: UploadFile = File(...), session: Session = Depends(get_session)) -> dict:
    data = await _read_pdf(file)
    try:
        inv = services.ingest_invoice(session, data, file.filename or "invoice.pdf")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return services.invoice_to_dict(inv, with_findings=True)


@app.get("/api/invoices")
def invoices(
    status: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    vendor: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list:
    return [services.invoice_to_dict(i) for i in services.list_invoices(session, status, date_from, date_to, vendor)]


@app.get("/api/invoices/{invoice_id}")
def invoice_detail(invoice_id: int, session: Session = Depends(get_session)) -> dict:
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    return services.invoice_to_dict(inv, with_findings=True)


@app.post("/api/invoices/{invoice_id}/audit")
def reaudit(invoice_id: int, session: Session = Depends(get_session)) -> dict:
    inv = session.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    services.audit_invoice(session, inv)
    return services.invoice_to_dict(inv, with_findings=True)


@app.post("/api/findings/{finding_id}/review")
def review(finding_id: int, body: ReviewRequest, session: Session = Depends(get_session)) -> dict:
    try:
        f = services.review_finding(session, finding_id, body.decision, body.comment, body.reviewer)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    return services.finding_to_dict(f)


@app.get("/api/search")
def search(query: str, vendor: Optional[str] = None, k: int = 5, session: Session = Depends(get_session)) -> list:
    vendor_id = None
    if vendor:
        v = services.find_vendor(session, vendor)
        if v is None:
            raise HTTPException(404, f"unknown vendor {vendor}")
        vendor_id = v.id
    hits = PgRetriever(session, get_settings().active_embedding_model).search(query, vendor_id, k=min(k, 20))
    return [{"chunk_id": h.chunk_id, "contract_id": h.contract_id, "score": round(h.score, 4), "text": h.text} for h in hits]
