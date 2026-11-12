"""Load the seed PDFs into the database through the normal ingestion pipeline.

    python -m seed.load            # idempotent: skips if invoices already exist
    python -m seed.load --reset    # drop all data first
"""

from __future__ import annotations

import argparse

from sqlalchemy import func, select

from app.db import get_engine, init_db, session_scope
from app.models import Base, Invoice
from app.services import ingest_contract, ingest_invoice

from .data import CONTRACTS, INVOICES
from .generate_pdfs import OUT
from .generate_pdfs import main as generate


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    if args.reset:
        Base.metadata.drop_all(get_engine())
    init_db()
    if not (OUT / "invoices").exists():
        generate()

    with session_scope() as s:
        if s.scalar(select(func.count(Invoice.id))):
            print("Database already seeded (use --reset to reload).")
            return
        for c in CONTRACTS:
            contract = ingest_contract(s, (OUT / "contracts" / c["filename"]).read_bytes(), c["filename"], c["vendor"])
            print(f"contract  {c['filename']:<45} {len(contract.chunks)} chunks")
        for inv in INVOICES:
            row = ingest_invoice(s, (OUT / "invoices" / inv["filename"]).read_bytes(), inv["filename"])
            print(f"invoice   {inv['filename']:<45} {row.status:<8} ${float(row.amount_at_risk):>9,.2f} at risk")


if __name__ == "__main__":
    main()
