import { useState } from "react";
import { api, money } from "../api";
import type { Finding } from "../types";

const LABELS: Record<string, string> = {
  price_overcharge: "Price overcharge",
  missing_discount: "Missing discount",
  duplicate_invoice: "Duplicate invoice",
  payment_terms_mismatch: "Payment terms",
  math_error: "Math error",
};

interface Props {
  finding: Finding;
  onReviewed: () => void;
}

export function FindingCard({ finding: f, onReviewed }: Props) {
  const [comment, setComment] = useState("");
  const [reviewer, setReviewer] = useState(() => localStorage.getItem("cg-reviewer") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const decide = async (decision: "approved" | "rejected") => {
    if (!comment.trim()) {
      setError("Add a comment explaining the decision.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const name = reviewer.trim() || "reviewer";
      localStorage.setItem("cg-reviewer", name);
      await api.review(f.id, decision, comment.trim(), name);
      setComment("");
      onReviewed();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <article className={`finding sev-${f.severity}`}>
      <div className="finding-head">
        <span className={`sev sev-${f.severity}`}>{f.severity}</span>
        <span className="tag">{LABELS[f.check_type] ?? f.check_type}</span>
        <span className="finding-amount">{money(f.amount_at_risk)}</span>
      </div>
      <h4>{f.title}</h4>
      <p>{f.detail}</p>

      {f.cited_clause && (
        <blockquote className="clause">
          <div className="clause-label">Cited contract clause</div>
          {f.cited_clause}
        </blockquote>
      )}

      {f.status === "open" ? (
        <div className="review">
          <textarea
            placeholder="Reason for your decision (required, stored in the audit trail)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            rows={2}
          />
          <div className="review-row">
            <input placeholder="Your name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
            <button className="btn approve" disabled={busy} onClick={() => decide("approved")}>
              Approve flag
            </button>
            <button className="btn reject" disabled={busy} onClick={() => decide("rejected")}>
              Reject flag
            </button>
          </div>
          {error && <div className="error-text">{error}</div>}
        </div>
      ) : (
        <div className={`decision ${f.status}`}>
          {f.decisions.map((d, i) => (
            <div key={i}>
              <strong>{d.decision === "approved" ? "Approved" : "Rejected"}</strong> by {d.reviewer}
              {d.created_at && <span className="muted"> · {new Date(d.created_at).toLocaleString()}</span>}
              <div>“{d.comment}”</div>
            </div>
          ))}
        </div>
      )}
    </article>
  );
}
