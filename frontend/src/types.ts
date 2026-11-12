export type InvoiceStatus = "clean" | "flagged" | "reviewed";
export type FindingStatus = "open" | "approved" | "rejected";
export type Severity = "low" | "medium" | "high";

export interface Decision {
  decision: "approved" | "rejected";
  comment: string;
  reviewer: string;
  created_at: string | null;
}

export interface Finding {
  id: number;
  invoice_id: number;
  check_type: string;
  severity: Severity;
  title: string;
  detail: string;
  amount_at_risk: number;
  line_item: string | null;
  cited_clause: string | null;
  status: FindingStatus;
  decisions: Decision[];
}

export interface LineItem {
  description: string;
  quantity: number;
  unit_price: number;
  amount: number;
}

export interface InvoiceSummary {
  id: number;
  vendor: string | null;
  invoice_number: string;
  invoice_date: string | null;
  payment_terms: string | null;
  subtotal: number;
  discount_total: number;
  total: number;
  totals_valid: boolean;
  status: InvoiceStatus;
  amount_at_risk: number;
  open_findings: number;
  finding_count: number;
  audit_summary: string | null;
  extraction_mode: string;
  filename: string;
}

export interface InvoiceDetail extends InvoiceSummary {
  line_items: LineItem[];
  discounts: { description: string; amount: number }[];
  findings: Finding[];
  audit_trace: { mode: string; checks_run: string[]; steps: { tool: string; by: string }[] } | null;
}

export interface Stats {
  vendors: number;
  contracts: number;
  invoices: number;
  flagged: number;
  open_amount_at_risk: number;
  approved_recoveries: number;
}
