import { money } from "../api";
import type { InvoiceSummary } from "../types";

interface Props {
  invoices: InvoiceSummary[];
  selectedId?: number;
  onSelect: (id: number) => void;
}

export function InvoiceTable({ invoices, selectedId, onSelect }: Props) {
  if (invoices.length === 0) return <p className="muted empty">No invoices here.</p>;
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Invoice</th>
          <th>Vendor</th>
          <th className="num">Total</th>
          <th className="num">At risk</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {invoices.map((inv) => (
          <tr
            key={inv.id}
            className={inv.id === selectedId ? "selected" : ""}
            onClick={() => onSelect(inv.id)}
            tabIndex={0}
            onKeyDown={(e) => e.key === "Enter" && onSelect(inv.id)}
          >
            <td>
              <div className="strong">{inv.invoice_number}</div>
              <div className="muted small">{inv.invoice_date}</div>
            </td>
            <td>{inv.vendor}</td>
            <td className="num">{money(inv.total)}</td>
            <td className={`num ${inv.amount_at_risk > 0 ? "risk" : ""}`}>{money(inv.amount_at_risk)}</td>
            <td>
              <span className={`pill ${inv.status}`}>
                {inv.status === "flagged" ? `${inv.open_findings} open` : inv.status}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
