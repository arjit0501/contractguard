"""The audit agent.

With an OpenAI key the agent is an LLM tool-calling loop: it reads the
invoice and the contract's terms, decides which checks are relevant, can
search the contract for clauses, and writes a short summary. The checks
themselves are deterministic tools (see checks.py), so the LLM can choose
what to examine but cannot invent amounts.

A guardrail runs every required check the agent skipped, and the trace
records that. Offline, a rule-based planner runs every applicable check.

After the checks run, each finding gets a citation: the contract clause
returned by hybrid retrieval for that finding's `clause_query`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..config import get_settings
from ..retrieval import Retriever
from ..schemas import ContractTerms, FindingDraft, InvoiceExtraction
from . import checks

MAX_STEPS = 8
REQUIRED_CHECKS = ("check_duplicate_invoice", "check_invoice_math")
CONTRACT_CHECKS = ("check_price_vs_contract", "check_missing_discounts", "check_payment_terms")

AGENT_SYSTEM_PROMPT = """You are an accounts-payable audit agent. Your job is to find money the
company would lose by paying this invoice as-is.

You have tools that run deterministic checks. Decide which checks are relevant to THIS
invoice given the contract terms, call them, and use search_contract_clauses when you
need to read the contract wording. Do not compute amounts yourself; the tools do that.
Contract-dependent checks are only meaningful when contract terms are available.

When you are done, reply with a 1-3 sentence summary for the human reviewer. Do not
call tools after writing the summary."""


@dataclass
class AuditContext:
    invoice: InvoiceExtraction
    terms: Optional[ContractTerms]
    prior_invoices: Sequence[Dict[str, Any]]
    retriever: Optional[Retriever]
    vendor_id: Optional[int]
    cost_of_capital: float = 0.08


@dataclass
class AuditResult:
    findings: List[FindingDraft]
    checks_run: List[str]
    summary: str
    mode: str
    trace: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def amount_at_risk(self) -> float:
        return round(sum(f.amount_at_risk for f in self.findings), 2)


TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    }
    for name, desc in [
        ("check_price_vs_contract", "Compare each line's unit price with the contracted rate."),
        ("check_missing_discounts", "Check that every contractual discount (volume, blanket) was applied."),
        ("check_duplicate_invoice", "Check whether this invoice number was already received from this vendor."),
        ("check_payment_terms", "Compare invoice payment terms with contract payment terms."),
        ("check_invoice_math", "Verify qty x unit price per line and that the total adds up."),
    ]
] + [
    {
        "type": "function",
        "function": {
            "name": "search_contract_clauses",
            "description": "Hybrid search over this vendor's contract clauses.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    }
]


class _Toolbox:
    def __init__(self, ctx: AuditContext) -> None:
        self.ctx = ctx
        self.findings: Dict[str, FindingDraft] = {}
        self.checks_run: List[str] = []

    def _record(self, name: str, fn: Callable[[], List[FindingDraft]]) -> Dict[str, Any]:
        if name in self.checks_run:
            return {"note": "already run"}
        self.checks_run.append(name)
        found = fn()
        for f in found:
            self.findings.setdefault(f.key, f)
        return {"findings": [f.model_dump(mode="json", include={"check_type", "title", "amount_at_risk"}) for f in found]}

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        ctx = self.ctx
        if name == "search_contract_clauses":
            if ctx.retriever is None:
                return {"error": "no contract indexed for this vendor"}
            hits = ctx.retriever.search(str(args.get("query", "")), ctx.vendor_id, k=3)
            return {"clauses": [h.text[:1200] for h in hits]}
        if name in CONTRACT_CHECKS and ctx.terms is None:
            return {"error": "no contract terms on file for this vendor"}
        terms = ctx.terms
        impl: Dict[str, Callable[[], List[FindingDraft]]] = {
            "check_price_vs_contract": lambda: checks.check_price_vs_contract(ctx.invoice, terms),  # type: ignore[arg-type]
            "check_missing_discounts": lambda: checks.check_missing_discounts(ctx.invoice, terms),  # type: ignore[arg-type]
            "check_payment_terms": lambda: checks.check_payment_terms(ctx.invoice, terms, ctx.cost_of_capital),  # type: ignore[arg-type]
            "check_duplicate_invoice": lambda: checks.check_duplicate_invoice(ctx.invoice, ctx.prior_invoices),
            "check_invoice_math": lambda: checks.check_invoice_math(ctx.invoice),
        }
        if name not in impl:
            return {"error": f"unknown tool {name}"}
        return self._record(name, impl[name])


def _plan_offline(ctx: AuditContext) -> List[str]:
    plan = list(REQUIRED_CHECKS)
    if ctx.terms is not None:
        if ctx.terms.rates:
            plan.append("check_price_vs_contract")
        if ctx.terms.discounts:
            plan.append("check_missing_discounts")
        if ctx.terms.payment_terms_days is not None and ctx.invoice.payment_terms:
            plan.append("check_payment_terms")
    return plan


def _invoice_brief(ctx: AuditContext) -> str:
    return json.dumps(
        {
            "invoice": ctx.invoice.model_dump(),
            "contract_terms": ctx.terms.model_dump() if ctx.terms else None,
            "prior_invoices_from_vendor": len(ctx.prior_invoices),
        },
        indent=2,
    )


def _run_llm(ctx: AuditContext, box: _Toolbox, trace: List[Dict[str, Any]]) -> str:  # pragma: no cover
    from ..llm import get_client

    s = get_settings()
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": f"Audit this invoice.\n\n{_invoice_brief(ctx)}"},
    ]
    for _ in range(MAX_STEPS):
        resp = get_client().chat.completions.create(
            model=s.chat_model, temperature=0, messages=messages, tools=TOOL_SPECS
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip()
        messages.append(msg.model_dump(exclude_none=True))
        for tc in msg.tool_calls:
            args = json.loads(tc.function.arguments or "{}")
            result = box.call(tc.function.name, args)
            trace.append({"step": "tool", "tool": tc.function.name, "args": args, "by": "agent"})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})
    return "Agent reached the step limit; results below come from the checks it ran plus guardrails."


def _attach_citations(ctx: AuditContext, findings: List[FindingDraft]) -> None:
    if ctx.retriever is None:
        return
    for f in findings:
        if not f.clause_query:
            continue
        hits = ctx.retriever.search(f.clause_query, ctx.vendor_id, k=1)
        if hits:
            f.cited_clause = hits[0].text
            f.clause_chunk_id = hits[0].chunk_id


def run_audit(ctx: AuditContext, use_llm: Optional[bool] = None) -> AuditResult:
    if use_llm is None:
        use_llm = get_settings().llm_enabled
    box = _Toolbox(ctx)
    trace: List[Dict[str, Any]] = []

    if use_llm:
        summary = _run_llm(ctx, box, trace)
        mode = "llm-agent"
    else:
        for name in _plan_offline(ctx):
            box.call(name, {})
            trace.append({"step": "tool", "tool": name, "by": "rule-planner"})
        summary = ""
        mode = "rule-planner"

    # Guardrail: required checks always run, even if the agent skipped them.
    for name in REQUIRED_CHECKS:
        if name not in box.checks_run:
            box.call(name, {})
            trace.append({"step": "tool", "tool": name, "by": "guardrail"})

    findings = sorted(box.findings.values(), key=lambda f: -f.amount_at_risk)
    _attach_citations(ctx, findings)
    if not summary:
        total = sum(f.amount_at_risk for f in findings)
        summary = (
            f"{len(findings)} issue(s) found, ${total:,.2f} at risk." if findings else "No issues found."
        )
    return AuditResult(findings=findings, checks_run=box.checks_run, summary=summary, mode=mode, trace=trace)
