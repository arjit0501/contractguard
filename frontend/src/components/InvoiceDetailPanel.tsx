import { useState } from "react";
import { api, money } from "../api";
import type { InvoiceDetail } from "../types";
import { FindingCard } from "./FindingCard";

interface Props {
  invoice: InvoiceDetail;
  onChanged: (inv: InvoiceDetail) => void;
}

export function InvoiceDetailPanel({ invoice, onChanged }: Props) {
  const [busy, setBusy] = useState(false);

  const reaudit = async () => {
    setBusy(true);
    try {
      onChanged(await api.reaudit(invoice.id));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="detail-head">
        <div>
          <h2>{invoice.invoice_number}</h2>
          <div className="muted">
            {invoice.vendor} · {invoice.invoice_date} · {invoice.payment_terms ?? "no terms"} ·{" "}
            <span title="How the invoice was extracted">{invoice.extraction_mode} extraction</span>
          </div>
        </div>
        <button className="btn ghost" onClick={reaudit} disabled={busy}>
          {busy ? "Auditing…" : "Re-run audit"}
        </button>
      </div>

      {invoice.audit_summary && <p className="summary">{invoice.audit_summary}</p>}
      {!invoice.totals_valid && <div className="banner warn">Invoice totals do not add up.</div>}

      <table className="table compact">
        <thead>
          <tr>
            <th>Line item</th>
            <th className="num">Qty</th>
            <th className="num">Unit</th>
            <th className="num">Amount</th>
          </tr>
        </thead>
        <tbody>
          {invoice.line_items.map((li, i) => (
            <tr key={i}>
              <td>{li.description}</td>
              <td className="num">{li.quantity}</td>
              <td className="num">{money(li.unit_price)}</td>
              <td className="num">{money(li.amount)}</td>
            </tr>
          ))}
          {invoice.discounts.map((d, i) => (
            <tr key={`d${i}`} className="muted">
              <td colSpan={3}>{d.description}</td>
              <td className="num">−{money(d.amount)}</td>
            </tr>
          ))}
          <tr className="strong">
            <td colSpan={3}>Total</td>
            <td className="num">{money(invoice.total)}</td>
          </tr>
        </tbody>
      </table>

      <h3>
        Findings <span className="muted">({invoice.findings.length})</span>
      </h3>
      {invoice.findings.length === 0 && <p className="muted">No issues found.</p>}
      {invoice.findings.map((f) => (
        <FindingCard key={f.id} finding={f} onReviewed={async () => onChanged(await api.invoice(invoice.id))} />
      ))}

      {invoice.audit_trace && (
        <details className="trace">
          <summary>Agent trace ({invoice.audit_trace.mode})</summary>
          <ol>
            {invoice.audit_trace.steps.map((s, i) => (
              <li key={i}>
                <code>{s.tool}</code> <span className="muted">by {s.by}</span>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
