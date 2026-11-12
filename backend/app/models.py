from __future__ import annotations

from datetime import date, datetime
from typing import Any, List, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Computed, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import get_settings

EMBED_DIM = get_settings().embedding_dim


class Base(DeclarativeBase):
    pass


class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contracts: Mapped[List[Contract]] = relationship(back_populates="vendor")


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    terms: Mapped[Optional[Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vendor: Mapped[Vendor] = relationship(back_populates="contracts")
    chunks: Mapped[List[ContractChunk]] = relationship(back_populates="contract", cascade="all, delete-orphan")


class ContractChunk(Base):
    __tablename__ = "contract_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[Optional[str]] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    embedding = mapped_column(Vector(EMBED_DIM))
    embedding_model: Mapped[str] = mapped_column(String(100))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))

    contract: Mapped[Contract] = relationship(back_populates="chunks")


class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vendors.id"), index=True)
    filename: Mapped[str] = mapped_column(String(300))
    invoice_number: Mapped[str] = mapped_column(String(100), index=True)
    invoice_date: Mapped[Optional[date]] = mapped_column(Date)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(100))
    subtotal: Mapped[float] = mapped_column(Numeric(14, 2))
    discount_total: Mapped[float] = mapped_column(Numeric(14, 2))
    tax: Mapped[float] = mapped_column(Numeric(14, 2))
    total: Mapped[float] = mapped_column(Numeric(14, 2))
    totals_valid: Mapped[bool]
    extraction: Mapped[Any] = mapped_column(JSON)
    extraction_mode: Mapped[str] = mapped_column(String(20))
    # clean | flagged | reviewed
    status: Mapped[str] = mapped_column(String(20), default="clean", index=True)
    amount_at_risk: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    audit_summary: Mapped[Optional[str]] = mapped_column(Text)
    audit_trace: Mapped[Optional[Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    vendor: Mapped[Optional[Vendor]] = relationship()
    findings: Mapped[List[Finding]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan", order_by="Finding.amount_at_risk.desc()"
    )


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id", ondelete="CASCADE"), index=True)
    check_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text)
    amount_at_risk: Mapped[float] = mapped_column(Numeric(14, 2))
    line_item: Mapped[Optional[str]] = mapped_column(String(300))
    cited_clause: Mapped[Optional[str]] = mapped_column(Text)
    clause_chunk_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contract_chunks.id", ondelete="SET NULL"))
    # open | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    invoice: Mapped[Invoice] = relationship(back_populates="findings")
    decisions: Mapped[List[ReviewDecision]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="ReviewDecision.created_at"
    )


class ReviewDecision(Base):
    """Append-only audit trail of reviewer decisions."""

    __tablename__ = "review_decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(ForeignKey("findings.id", ondelete="CASCADE"), index=True)
    decision: Mapped[str] = mapped_column(String(20))
    comment: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    finding: Mapped[Finding] = relationship(back_populates="decisions")
