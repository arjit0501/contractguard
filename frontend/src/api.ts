import type { Finding, InvoiceDetail, InvoiceSummary, Stats } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; llm_enabled: boolean; model: string | null }>("/health"),
  stats: () => request<Stats>("/stats"),
  invoices: (status?: string) => request<InvoiceSummary[]>(`/invoices${status ? `?status=${status}` : ""}`),
  invoice: (id: number) => request<InvoiceDetail>(`/invoices/${id}`),
  reaudit: (id: number) => request<InvoiceDetail>(`/invoices/${id}/audit`, { method: "POST" }),
  review: (findingId: number, decision: "approved" | "rejected", comment: string, reviewer: string) =>
    request<Finding>(`/findings/${findingId}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, comment, reviewer }),
    }),
  uploadInvoice: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<InvoiceDetail>("/invoices", { method: "POST", body: fd });
  },
  uploadContract: (file: File, vendorName: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("vendor_name", vendorName);
    return request<{ id: number; vendor: string; chunks: number }>("/contracts", { method: "POST", body: fd });
  },
};

export const money = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2 });
