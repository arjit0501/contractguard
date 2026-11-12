# ContractGuard

**An AI agent that audits vendor invoices against vendor contracts and catches overcharges before they are paid.**

Upload vendor contracts and invoices. ContractGuard extracts each invoice into validated JSON, retrieves the governing contract clauses with hybrid RAG, and runs an audit agent that checks price vs contracted rate, missing discounts, duplicate invoice numbers, payment terms and invoice arithmetic. Every finding carries a severity, the dollar amount at risk and the cited contract clause. A human reviewer approves or rejects each flag, and every decision goes into an audit trail. An MCP server lets Claude Desktop answer questions like *"Which vendors overcharged us last month?"*

![CI](https://img.shields.io/badge/tests-52%20passing-brightgreen) ![Python](https://img.shields.io/badge/python-3.12-blue) ![License](https://img.shields.io/badge/license-MIT-lightgrey)

| Capability | Implementation |
|---|---|
| **Structured outputs / document extraction** | Invoice PDF → `InvoiceExtraction` Pydantic schema via OpenAI Structured Outputs; totals validated (`qty × unit price = amount`, `Σ lines − discounts + tax = total`) |
| **RAG + vector database** | Contracts chunked one clause per chunk (≤500 tokens, 50-token overlap for long clauses), embedded and stored in **pgvector**; hybrid search = vector cosine + Postgres full-text, fused with Reciprocal Rank Fusion, filtered by vendor |
| **AI agent (tool calling)** | LLM agent decides which checks to run and can search the contract; checks are deterministic tools, so the agent **cannot invent amounts**. Guardrails make sure the required checks always run |
| **MCP** | Official Python MCP SDK server exposing `search_contracts`, `list_flagged_invoices`, `get_invoice_findings` |
| **Human-in-the-loop** | React review queue sorted by $ at risk; approve or reject each finding with a required comment; append-only `review_decisions` table |
| **Evals** | 10 labelled invoices with 8 seeded issues; script reports precision, recall and citation accuracy |

## Architecture

```mermaid
flowchart LR
    subgraph Ingestion
        C[Contract PDF] --> CT[pypdf text]
        CT --> TERMS[Structured Outputs<br/>ContractTerms]
        CT --> CH[Clause chunker]
        CH --> EMB[OpenAI embeddings]
        I[Invoice PDF] --> IT[pypdf text]
        IT --> EX[Structured Outputs<br/>InvoiceExtraction]
        EX --> VAL[Totals validation]
    end

    subgraph PG[PostgreSQL + pgvector]
        CHUNKS[(contract_chunks<br/>vector + tsvector)]
        INV[(invoices)]
        FIND[(findings)]
        REV[(review_decisions)]
    end

    EMB --> CHUNKS
    TERMS --> PG
    VAL --> INV

    subgraph Agent[Audit agent]
        LLM[LLM planner<br/>tool calling] -->|calls| TOOLS[Deterministic checks<br/>price · discount · duplicate<br/>payment terms · math]
        LLM -->|calls| SEARCH[search_contract_clauses]
        GR[Guardrail: required checks] --> TOOLS
    end

    INV --> Agent
    SEARCH --> HY[Hybrid retrieval<br/>vector + keyword → RRF]
    HY --> CHUNKS
    TOOLS --> CITE[Attach cited clause]
    CITE --> FIND

    FIND --> API[FastAPI]
    API --> UI[React review queue]
    UI -->|approve / reject + comment| REV
    PG --> MCP[MCP server] --> CD[Claude Desktop]
```

**Design choice: the LLM plans, code computes.** Overcharge amounts come from deterministic functions in [`backend/app/audit/checks.py`](backend/app/audit/checks.py), not from model output. The agent chooses which checks fit the invoice and contract, reads clauses when it needs to, and writes the reviewer summary. That keeps every dollar figure reproducible and testable, which matters in finance.

## Eval results

`python -m evals.run_evals` on the 10 seed invoices (3 clean, 7 with 8 seeded issues):

| Mode | Precision | Recall | Citation accuracy |
|---|---|---|---|
| Offline (seed-layout parser + rule planner + hash embeddings) | **100%** (8/8) | **100%** (8/8) | **100%** |
| LLM (`--llm`, OpenAI extraction + tool-calling agent) | run `python -m evals.run_evals --llm` with your key | | |

| Seeded issue | Invoice | Caught | $ at risk |
|---|---|---|---|
| Toner billed $95 vs $89 contract | ACME-1002 | ✅ | $60.00 |
| Missing 5% volume discount (25 cases paper) | ACME-1003 | ✅ | $52.50 |
| Missing 10% committed-spend discount | NW-2002 | ✅ | $120.00 |
| Net 15 vs contract Net 30 | NW-2002 | ✅ | $3.95 (working capital) |
| Support hours $175 vs $150 | NW-2003 | ✅ | $200.00 |
| Re-used invoice number BC-3001 | BC-3001 (resubmitted) | ✅ | $3,790.00 |
| Net 30 vs contract Net 60 | BC-3003 | ✅ | $35.24 (working capital) |
| Window cleaning $110 vs $95 | BC-3004 | ✅ | $60.00 |

> Note: offline extraction uses a parser written for the seed PDF layout, so offline numbers measure the retrieval and audit logic, not extraction on arbitrary vendor PDFs. Use `--llm` to measure the full LLM pipeline.

## Quick start (Docker)

```bash
git clone https://github.com/<your-username>/contractguard.git
cd contractguard
cp .env.example .env              # optionally add OPENAI_API_KEY
docker compose up -d --build
docker compose exec backend python -m seed.load
```

- Review dashboard: http://localhost:8080
- API docs (Swagger): http://localhost:8000/docs

Without an `OPENAI_API_KEY` everything runs offline, and the header shows *Offline mode*. If you add a key after seeding, reload with `python -m seed.load --reset` so contract embeddings are recomputed with the OpenAI model.

## Local development

```bash
# Postgres with pgvector
docker compose up -d db

# Backend (Python 3.10+)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://localhost:8000
python -m seed.load                    # in another shell
pytest -q                              # 52 tests, no network or DB needed
python -m evals.run_evals

# Frontend
cd ../frontend
npm install
npm run dev                            # http://localhost:5173 (proxies /api to :8000)
```

## MCP server (Claude Desktop)

The MCP server reads the same Postgres database. Add this to `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "contractguard": {
      "command": "/absolute/path/to/contractguard/backend/.venv/bin/python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/absolute/path/to/contractguard/backend",
      "env": {
        "DATABASE_URL": "postgresql+psycopg://contractguard:contractguard@localhost:5432/contractguard",
        "PYTHONPATH": "/absolute/path/to/contractguard/backend"
      }
    }
  }
}
```

| Tool | Arguments | Returns |
|---|---|---|
| `search_contracts` | `query`, `vendor?`, `k?` | Matching contract clauses (hybrid search) |
| `list_flagged_invoices` | `status?` (`flagged`/`reviewed`/`clean`/`all`), `date_from?`, `date_to?`, `vendor?` | Invoices sorted by $ at risk |
| `get_invoice_findings` | `invoice_id` | Findings, cited clauses, reviewer decisions |

Example prompts: *"Which vendors overcharged us in October 2026?"*, *"What does the Acme contract say about volume discounts?"*, *"Show me the findings for the largest flagged invoice."*

## API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/contracts` | Upload contract PDF (`file`, `vendor_name`) → terms extracted, clauses chunked and embedded |
| `POST` | `/api/invoices` | Upload invoice PDF → extracted, validated, audited |
| `GET` | `/api/invoices?status=flagged` | Review queue, sorted by $ at risk |
| `GET` | `/api/invoices/{id}` | Invoice with line items, findings, agent trace |
| `POST` | `/api/invoices/{id}/audit` | Re-run the audit (reviewed findings are preserved) |
| `POST` | `/api/findings/{id}/review` | `{decision: approved\|rejected, comment, reviewer}` |
| `GET` | `/api/search?query=&vendor=` | Hybrid clause search |
| `GET` | `/api/stats` | Open $ at risk, approved recoveries, counts |

## Project structure

```
backend/
  app/
    schemas.py          Pydantic schemas (extraction, contract terms, findings) + totals validation
    extraction.py       Structured-output extraction for invoices and contract terms
    chunking.py         Clause-aware chunker
    retrieval.py        Hybrid search: pgvector + full-text, RRF (Postgres and in-memory)
    audit/checks.py     Deterministic checks (price, discount, duplicate, terms, math)
    audit/agent.py      Tool-calling agent, guardrails, citations
    services.py         Ingestion, audit and review workflows
    main.py             FastAPI app
    models.py           SQLAlchemy models (pgvector column, generated tsvector)
  mcp_server/server.py  MCP server for Claude Desktop
  seed/                 3 vendors, 3 contracts, 10 invoices (+ PDF generator)
  evals/                Labels + precision/recall script
  tests/                Extraction, checks, chunking, retrieval, end-to-end
frontend/               React + TypeScript review dashboard
```

## Screenshots

> Add screenshots after running `docker compose up` and `python -m seed.load`.

| Review queue | Finding with cited clause | Claude Desktop via MCP |
|---|---|---|
| `docs/screenshots/queue.png` | `docs/screenshots/finding.png` | `docs/screenshots/mcp.png` |

## Roadmap

- OCR (e.g. Tesseract) for scanned invoices
- PO and goods-receipt three-way match
- Store contract-term extraction confidence and route low-confidence extractions to review
- Auth and roles for reviewers

## License

MIT
