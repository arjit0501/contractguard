"""Seed data: 3 vendors, 3 contracts, 10 invoices.

Ground-truth labels for the evals live in evals/labels.json. Seven of the ten
invoices contain deliberate problems (8 issues in total); three are clean.
"""

from __future__ import annotations

from typing import Any, Dict, List

CONTRACTS: List[Dict[str, Any]] = [
    {
        "vendor": "Acme Office Supplies",
        "filename": "acme_office_supplies_msa.pdf",
        "text": """MASTER SUPPLY AGREEMENT
Between Contoso Holdings Inc. ("Buyer") and Acme Office Supplies ("Supplier")
Effective Date: 2026-01-01. Term: 24 months.

1. Scope. Supplier shall provide office consumables to Buyer's offices on request. Orders are placed
by purchase order and delivered within three business days to the address on the order.

2. Pricing. Supplier shall invoice the following items at the contracted unit prices, which are fixed
for the term of this Agreement and exclusive of tax:
(a) Copy paper A4 (case): USD 42.00 per case;
(b) Toner cartridge black: USD 89.00 per cartridge;
(c) Ballpoint pens (box of 50): USD 12.50 per box.
Any price change requires a written amendment signed by both parties.

3. Volume Discount. To reward bulk ordering, the following discount applies.
DISCOUNT: 5% on Copy paper A4 (case) when a single invoice line has a quantity of at least 20.
The discount must be shown as a separate line on the invoice.

4. Payment Terms. Buyer shall pay undisputed invoices within Net 45 days of the invoice date.
Supplier may not shorten payment terms on individual invoices.

5. Invoicing. Each invoice must carry a unique invoice number. Supplier shall not re-issue an invoice
number. Disputed amounts may be withheld pending resolution.

6. Governing Law. This Agreement is governed by the laws of the State of Delaware.
""",
    },
    {
        "vendor": "Northwind Cloud Services",
        "filename": "northwind_cloud_services_agreement.pdf",
        "text": """CLOUD SERVICES AGREEMENT
Between Contoso Holdings Inc. ("Customer") and Northwind Cloud Services ("Provider")
Effective Date: 2026-02-01. Term: 12 months, renewing annually.

1. Services. Provider shall supply managed compute, storage and support services as described in
Order Forms. Service levels are set out in the Service Level Schedule.

2. Fees. Provider shall invoice monthly in arrears at the following contracted rates:
(a) Compute instance (monthly): USD 250.00 per instance;
(b) Storage (TB-month): USD 20.00 per TB;
(c) Support hours: USD 150.00 per hour.
Rates are fixed for the initial term.

3. Committed-Spend Discount. In consideration of Customer's annual commitment:
DISCOUNT: 10% on all services.
The discount shall be applied to every invoice as a separate discount line.

4. Payment Terms. Customer shall pay each invoice within Net 30 days of receipt.

5. Service Credits. Missed service levels entitle Customer to service credits per the Service
Level Schedule, applied to the following invoice.

6. Confidentiality. Each party shall protect the other's confidential information.
""",
    },
    {
        "vendor": "BrightClean Facilities",
        "filename": "brightclean_facilities_services.pdf",
        "text": """FACILITIES SERVICES AGREEMENT
Between Contoso Holdings Inc. ("Client") and BrightClean Facilities ("Contractor")
Effective Date: 2026-03-01. Term: 36 months.

1. Services. Contractor shall provide janitorial and specialist cleaning at Client's headquarters
according to the agreed schedule. Contractor supplies all equipment and consumables.

2. Rates. Contractor shall invoice at the following rates:
(a) Office cleaning (per visit): USD 180.00 per visit;
(b) Window cleaning (per visit): USD 95.00 per visit;
(c) Carpet shampoo (sq ft): USD 0.35 per sq ft.
Rates are adjusted only on each anniversary by written notice.

3. Payment Terms. Client shall pay within Net 60 days of the invoice date. Late payment does not
accrue interest during the first 15 days after the due date.

4. Invoices. Contractor shall invoice monthly. Each invoice number must be unique; resubmissions of
a corrected invoice must use a new invoice number and reference the original.

5. Insurance. Contractor shall maintain general liability insurance of at least USD 2,000,000.
""",
    },
]

# Each line: (description, qty, unit_price). Discounts: (description, amount).
INVOICES: List[Dict[str, Any]] = [
    # ---- Acme ----------------------------------------------------------------
    {
        "filename": "acme_ACME-1001.pdf", "vendor": "Acme Office Supplies", "number": "ACME-1001",
        "date": "2026-09-03", "terms": "Net 45",
        "lines": [("Copy paper A4 (case)", 10, 42.00), ("Ballpoint pens (box of 50)", 6, 12.50)],
        "discounts": [],
    },
    {   # price overcharge: toner at 95 vs 89 -> 10 x 6 = 60.00
        "filename": "acme_ACME-1002.pdf", "vendor": "Acme Office Supplies", "number": "ACME-1002",
        "date": "2026-09-17", "terms": "Net 45",
        "lines": [("Toner cartridge black", 10, 95.00), ("Copy paper A4 (case)", 5, 42.00)],
        "discounts": [],
    },
    {   # missing 5% volume discount on 25 cases of paper -> 52.50
        "filename": "acme_ACME-1003.pdf", "vendor": "Acme Office Supplies", "number": "ACME-1003",
        "date": "2026-10-01", "terms": "Net 45",
        "lines": [("Copy paper A4 (case)", 25, 42.00), ("Toner cartridge black", 2, 89.00)],
        "discounts": [],
    },
    # ---- Northwind -----------------------------------------------------------
    {
        "filename": "northwind_NW-2001.pdf", "vendor": "Northwind Cloud Services", "number": "NW-2001",
        "date": "2026-09-01", "terms": "Net 30",
        "lines": [("Compute instance (monthly)", 4, 250.00), ("Storage (TB-month)", 10, 20.00)],
        "discounts": [("Discount - 10% committed spend", 120.00)],
    },
    {   # missing 10% discount (-> 120.00) AND Net 15 vs Net 30
        "filename": "northwind_NW-2002.pdf", "vendor": "Northwind Cloud Services", "number": "NW-2002",
        "date": "2026-10-01", "terms": "Net 15",
        "lines": [("Compute instance (monthly)", 4, 250.00), ("Storage (TB-month)", 10, 20.00)],
        "discounts": [],
    },
    {   # support at 175 vs 150 -> 8 x 25 = 200.00 (discount correctly applied)
        "filename": "northwind_NW-2003.pdf", "vendor": "Northwind Cloud Services", "number": "NW-2003",
        "date": "2026-11-01", "terms": "Net 30",
        "lines": [("Compute instance (monthly)", 4, 250.00), ("Support hours", 8, 175.00)],
        "discounts": [("Discount - 10% committed spend", 240.00)],
    },
    # ---- BrightClean ---------------------------------------------------------
    {
        "filename": "brightclean_BC-3001.pdf", "vendor": "BrightClean Facilities", "number": "BC-3001",
        "date": "2026-09-30", "terms": "Net 60",
        "lines": [("Office cleaning (per visit)", 20, 180.00), ("Window cleaning (per visit)", 2, 95.00)],
        "discounts": [],
    },
    {   # duplicate: re-uses invoice number BC-3001
        "filename": "brightclean_BC-3001_resubmitted.pdf", "vendor": "BrightClean Facilities", "number": "BC-3001",
        "date": "2026-10-06", "terms": "Net 60",
        "lines": [("Office cleaning (per visit)", 20, 180.00), ("Window cleaning (per visit)", 2, 95.00)],
        "discounts": [],
    },
    {   # Net 30 vs Net 60
        "filename": "brightclean_BC-3003.pdf", "vendor": "BrightClean Facilities", "number": "BC-3003",
        "date": "2026-10-31", "terms": "Net 30",
        "lines": [("Office cleaning (per visit)", 22, 180.00), ("Carpet shampoo (sq ft)", 4000, 0.35)],
        "discounts": [],
    },
    {   # window cleaning at 110 vs 95 -> 4 x 15 = 60.00
        "filename": "brightclean_BC-3004.pdf", "vendor": "BrightClean Facilities", "number": "BC-3004",
        "date": "2026-11-10", "terms": "Net 60",
        "lines": [("Office cleaning (per visit)", 21, 180.00), ("Window cleaning (per visit)", 4, 110.00)],
        "discounts": [],
    },
]
