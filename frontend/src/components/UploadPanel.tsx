import { useState } from "react";
import { api } from "../api";
import type { InvoiceDetail } from "../types";

interface Props {
  onUploaded: (invoice?: InvoiceDetail) => void;
}

export function UploadPanel({ onUploaded }: Props) {
  const [vendor, setVendor] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setMsg(null);
    try {
      setMsg({ ok: true, text: await fn() });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const onContract = (file?: File) =>
    file &&
    run(async () => {
      if (!vendor.trim()) throw new Error("Enter the vendor name before uploading a contract.");
      const c = await api.uploadContract(file, vendor.trim());
      onUploaded();
      return `Indexed contract for ${c.vendor} (${c.chunks} clauses).`;
    });

  const onInvoice = (file?: File) =>
    file &&
    run(async () => {
      const inv = await api.uploadInvoice(file);
      onUploaded(inv);
      return `${inv.invoice_number}: ${inv.findings.length} finding(s).`;
    });

  return (
    <section className="card upload">
      <div className="upload-group">
        <label className="label">Contract PDF</label>
        <input placeholder="Vendor name" value={vendor} onChange={(e) => setVendor(e.target.value)} />
        <label className="btn ghost file">
          Upload contract
          <input type="file" accept="application/pdf" hidden disabled={busy}
            onChange={(e) => { onContract(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
      </div>
      <div className="upload-group">
        <label className="label">Invoice PDF</label>
        <label className="btn primary file">
          {busy ? "Working…" : "Upload & audit invoice"}
          <input type="file" accept="application/pdf" hidden disabled={busy}
            onChange={(e) => { onInvoice(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
      </div>
      {msg && <div className={msg.ok ? "ok-text" : "error-text"}>{msg.text}</div>}
    </section>
  );
}
