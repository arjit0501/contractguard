"""ContractGuard MCP server.

Exposes ContractGuard data to MCP clients such as Claude Desktop over stdio:

  search_contracts(query, vendor)                -> matching contract clauses
  list_flagged_invoices(status, date_from, date_to) -> invoices with findings
  get_invoice_findings(invoice_id)               -> findings + review history

Run:  python -m mcp_server.server   (from the backend/ directory)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from app import services
from app.config import get_settings
from app.db import session_scope
from app.models import Invoice
from app.retrieval import PgRetriever

mcp = FastMCP("contractguard")


def _date(s: Optional[str]) -> Optional[date]:
    return date.fromisoformat(s) if s else None


@mcp.tool()
def search_contracts(query: str, vendor: Optional[str] = None, k: int = 5) -> List[Dict[str, Any]]:
    """Hybrid (semantic + keyword) search over vendor contract clauses.

    Args:
        query: what to look for, e.g. "volume discount on paper" or "payment terms".
        vendor: optional vendor name to restrict the search to one vendor's contracts.
        k: number of clauses to return (max 20).
    """
    with session_scope() as session:
        vendor_id = None
        if vendor:
            v = services.find_vendor(session, vendor)
            if v is None:
                return [{"error": f"unknown vendor '{vendor}'"}]
            vendor_id = v.id
        hits = PgRetriever(session, get_settings().active_embedding_model).search(query, vendor_id, k=min(k, 20))
        return [{"contract_id": h.contract_id, "score": round(h.score, 4), "clause": h.text} for h in hits]


@mcp.tool()
def list_flagged_invoices(
    status: str = "flagged",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    vendor: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List invoices by audit status, sorted by amount at risk (highest first).

    Args:
        status: "flagged" (open findings), "reviewed", "clean", or "all".
        date_from: optional ISO date (YYYY-MM-DD), inclusive, on invoice date.
        date_to: optional ISO date (YYYY-MM-DD), inclusive, on invoice date.
        vendor: optional vendor name.
    """
    with session_scope() as session:
        rows = services.list_invoices(
            session, None if status == "all" else status, _date(date_from), _date(date_to), vendor
        )
        return [services.invoice_to_dict(i) for i in rows]


@mcp.tool()
def get_invoice_findings(invoice_id: int) -> Dict[str, Any]:
    """Get one invoice's audit findings, each with severity, amount at risk, the cited
    contract clause, and the reviewer decision history."""
    with session_scope() as session:
        inv = session.get(Invoice, invoice_id)
        if inv is None:
            return {"error": f"invoice {invoice_id} not found"}
        return services.invoice_to_dict(inv, with_findings=True)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
