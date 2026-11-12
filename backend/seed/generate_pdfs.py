"""Render the seed contracts and invoices to PDF.

    python -m seed.generate_pdfs        # writes seed/pdfs/{contracts,invoices}/*.pdf
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any, Dict, List

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from .data import CONTRACTS, INVOICES

OUT = Path(__file__).parent / "pdfs"
MARGIN = 54
LINE_H = 13


class _Writer:
    def __init__(self, path: Path, font: str = "Helvetica", size: int = 10) -> None:
        self.c = canvas.Canvas(str(path), pagesize=LETTER, invariant=1)  # invariant -> reproducible bytes
        self.font, self.size = font, size
        self.y = LETTER[1] - MARGIN
        self.c.setFont(font, size)

    def line(self, text: str = "", bold: bool = False, font: str = "") -> None:
        if self.y < MARGIN:
            self.c.showPage()
            self.y = LETTER[1] - MARGIN
        f = font or self.font
        self.c.setFont(f + ("-Bold" if bold else ""), self.size)
        self.c.drawString(MARGIN, self.y, text)
        self.y -= LINE_H

    def save(self) -> None:
        self.c.save()


def render_contract(contract: Dict[str, Any], path: Path) -> None:
    w = _Writer(path)
    for para in contract["text"].splitlines():
        if not para.strip():
            w.line()
            continue
        for i, chunk in enumerate(textwrap.wrap(para, 95)):
            w.line(chunk, bold=(i == 0 and para.isupper()))
    w.save()


def invoice_lines(inv: Dict[str, Any]) -> List[str]:
    subtotal = round(sum(q * p for _, q, p in inv["lines"]), 2)
    disc = round(sum(a for _, a in inv["discounts"]), 2)
    total = round(subtotal - disc, 2)
    out = [
        "INVOICE",
        "",
        f"Vendor: {inv['vendor']}",
        "Bill To: Contoso Holdings Inc., Accounts Payable",
        f"Invoice Number: {inv['number']}",
        f"Invoice Date: {inv['date']}",
        f"Payment Terms: {inv['terms']}",
        "",
        f"{'Description':<34}{'Qty':>8}{'Unit Price':>14}{'Amount':>14}",
        "-" * 70,
    ]
    for desc, qty, price in inv["lines"]:
        out.append(f"{desc:<34}{qty:>8}{price:>14,.2f}{round(qty * price, 2):>14,.2f}")
    out += ["-" * 70, f"{'Subtotal':<56}{subtotal:>14,.2f}"]
    for desc, amount in inv["discounts"]:
        out.append(f"{desc:<56}{'-' + format(amount, ',.2f'):>14}")
    out += [f"{'Total Due':<56}{total:>14,.2f}", "", "Thank you for your business."]
    return out


def render_invoice(inv: Dict[str, Any], path: Path) -> None:
    w = _Writer(path, font="Courier", size=10)
    for ln in invoice_lines(inv):
        w.line(ln)
    w.save()


def main() -> None:
    (OUT / "contracts").mkdir(parents=True, exist_ok=True)
    (OUT / "invoices").mkdir(parents=True, exist_ok=True)
    for c in CONTRACTS:
        render_contract(c, OUT / "contracts" / c["filename"])
    for inv in INVOICES:
        render_invoice(inv, OUT / "invoices" / inv["filename"])
    print(f"Wrote {len(CONTRACTS)} contracts and {len(INVOICES)} invoices to {OUT}")


if __name__ == "__main__":
    main()
