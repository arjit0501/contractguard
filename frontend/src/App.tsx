import { useCallback, useEffect, useState } from "react";
import { api, money } from "./api";
import type { InvoiceDetail, InvoiceSummary, Stats } from "./types";
import { InvoiceDetailPanel } from "./components/InvoiceDetailPanel";
import { InvoiceTable } from "./components/InvoiceTable";
import { UploadPanel } from "./components/UploadPanel";

const FILTERS = [
  { key: "flagged", label: "Needs review" },
  { key: "reviewed", label: "Reviewed" },
  { key: "clean", label: "Clean" },
  { key: "", label: "All" },
] as const;

export default function App() {
  const [filter, setFilter] = useState<string>("flagged");
  const [invoices, setInvoices] = useState<InvoiceSummary[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [selected, setSelected] = useState<InvoiceDetail | null>(null);
  const [llm, setLlm] = useState<{ enabled: boolean; model: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [inv, st] = await Promise.all([api.invoices(filter || undefined), api.stats()]);
      setInvoices(inv);
      setStats(st);
      setError(null);
    } catch (e) {
      setError(`Cannot reach the API: ${(e as Error).message}`);
    }
  }, [filter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    api.health().then((h) => setLlm({ enabled: h.llm_enabled, model: h.model })).catch(() => setLlm(null));
  }, []);

  const open = async (id: number) => setSelected(await api.invoice(id));

  const onChanged = async (inv: InvoiceDetail) => {
    setSelected(inv);
    await refresh();
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden>
            ◆
          </span>
          ContractGuard
        </div>
        <span className={`mode ${llm?.enabled ? "on" : "off"}`}>
          {llm == null ? "API offline" : llm.enabled ? `LLM agent · ${llm.model}` : "Offline mode (rule planner)"}
        </span>
      </header>

      {error && <div className="banner error">{error}</div>}

      {stats && (
        <section className="stats">
          <Stat label="Open $ at risk" value={money(stats.open_amount_at_risk)} accent />
          <Stat label="Approved recoveries" value={money(stats.approved_recoveries)} />
          <Stat label="Invoices needing review" value={`${stats.flagged} / ${stats.invoices}`} />
          <Stat label="Contracts indexed" value={`${stats.contracts} (${stats.vendors} vendors)`} />
        </section>
      )}

      <UploadPanel onUploaded={async (inv) => { await refresh(); if (inv) setSelected(inv); }} />

      <main className="layout">
        <section className="card list">
          <div className="tabs" role="tablist">
            {FILTERS.map((f) => (
              <button
                key={f.key}
                role="tab"
                aria-selected={filter === f.key}
                className={filter === f.key ? "tab active" : "tab"}
                onClick={() => setFilter(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <InvoiceTable invoices={invoices} selectedId={selected?.id} onSelect={open} />
        </section>
        <section className="card detail">
          {selected ? (
            <InvoiceDetailPanel invoice={selected} onChanged={onChanged} />
          ) : (
            <p className="muted empty">Select an invoice to review its findings.</p>
          )}
        </section>
      </main>
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`stat card ${accent ? "accent" : ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
