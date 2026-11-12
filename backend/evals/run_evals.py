"""Precision / recall of the audit agent on the labelled seed invoices.

    python -m evals.run_evals            # offline (rule planner, seed parser, hash embeddings)
    python -m evals.run_evals --llm      # OpenAI extraction + tool-calling agent (needs OPENAI_API_KEY)

A predicted finding is a true positive when an expected finding on the same
invoice has the same check_type (and, where labelled, the same amount within
$0.01). Citation accuracy = share of contract-based true positives whose cited
clause is the clause that actually governs that check.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List

from app.local_pipeline import run_local
from seed.data import CONTRACTS, INVOICES
from seed.generate_pdfs import OUT
from seed.generate_pdfs import main as generate

HERE = Path(__file__).parent
CITATION_KEYWORDS = {
    "price_overcharge": ("per ",),
    "missing_discount": ("discount:",),
    "payment_terms_mismatch": ("payment terms",),
}


def evaluate(use_llm: bool) -> Dict[str, object]:
    if not (OUT / "invoices").exists():
        generate()
    labels: Dict[str, List[dict]] = json.loads((HERE / "labels.json").read_text())["invoices"]
    results = run_local(
        [(c["vendor"], (OUT / "contracts" / c["filename"]).read_bytes()) for c in CONTRACTS],
        [(i["filename"], (OUT / "invoices" / i["filename"]).read_bytes()) for i in INVOICES],
        use_llm=use_llm,
    )
    tp, fp, fn = Counter(), Counter(), Counter()
    cited_ok = cited_total = 0
    rows = []
    for r in results:
        expected = list(labels[r.filename])
        hits, misses = [], []
        for f in r.audit.findings:
            match = next(
                (
                    e
                    for e in expected
                    if e["check_type"] == f.check_type.value
                    and (e["amount_at_risk"] is None or abs(e["amount_at_risk"] - f.amount_at_risk) <= 0.01)
                ),
                None,
            )
            if match:
                expected.remove(match)
                tp[f.check_type.value] += 1
                hits.append(f.check_type.value)
                kws = CITATION_KEYWORDS.get(f.check_type.value)
                if kws:
                    cited_total += 1
                    clause = (f.cited_clause or "").lower()
                    item_ok = f.line_item is None or f.check_type.value != "price_overcharge" or f.line_item.lower() in clause
                    cited_ok += int(all(k in clause for k in kws) and item_ok)
            else:
                fp[f.check_type.value] += 1
                misses.append(f"FP:{f.check_type.value}")
        for e in expected:
            fn[e["check_type"]] += 1
            misses.append(f"FN:{e['check_type']}")
        rows.append((r.filename, hits, misses, r.audit.amount_at_risk))

    T, F, N = sum(tp.values()), sum(fp.values()), sum(fn.values())
    precision = T / (T + F) if T + F else 1.0
    recall = T / (T + N) if T + N else 1.0
    return {
        "mode": "llm" if use_llm else "offline",
        "tp": T, "fp": F, "fn": N,
        "precision": precision, "recall": recall,
        "citation_accuracy": cited_ok / cited_total if cited_total else 1.0,
        "per_type": {k: {"tp": tp[k], "fp": fp[k], "fn": fn[k]} for k in sorted(set(tp) | set(fp) | set(fn))},
        "rows": rows,
    }


def to_markdown(res: Dict[str, object]) -> str:
    lines = [
        f"### Eval results ({res['mode']} mode)",
        "",
        f"- **Precision:** {res['precision']:.0%}  **Recall:** {res['recall']:.0%}  "
        f"(TP {res['tp']}, FP {res['fp']}, FN {res['fn']})",
        f"- **Citation accuracy:** {res['citation_accuracy']:.0%} of findings cite the governing clause",
        "",
        "| Check | TP | FP | FN |",
        "|---|---|---|---|",
    ]
    for k, v in res["per_type"].items():  # type: ignore[union-attr]
        lines.append(f"| {k} | {v['tp']} | {v['fp']} | {v['fn']} |")
    lines += ["", "| Invoice | Correct findings | Errors | $ at risk |", "|---|---|---|---|"]
    for fn_, hits, misses, amt in res["rows"]:  # type: ignore[union-attr]
        lines.append(f"| {fn_} | {', '.join(hits) or '-'} | {', '.join(misses) or '-'} | {amt:,.2f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="use OpenAI extraction + agent")
    args = ap.parse_args()
    res = evaluate(use_llm=args.llm)
    md = to_markdown(res)
    print(md)
    (HERE / f"results_{res['mode']}.md").write_text(md)


if __name__ == "__main__":
    main()
