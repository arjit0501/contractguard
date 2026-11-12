from __future__ import annotations

from app.chunking import approx_tokens, chunk_contract, split_clauses
from app.retrieval import InMemoryRetriever, rrf, to_tsquery_or
from seed.data import CONTRACTS


def test_split_clauses_on_numbered_headings():
    clauses = split_clauses(CONTRACTS[0]["text"])
    assert any(c.startswith("2. Pricing.") for c in clauses)
    assert any(c.startswith("4. Payment Terms.") for c in clauses)


def test_one_chunk_per_clause():
    chunks = chunk_contract(CONTRACTS[0]["text"])
    pricing = [c for c in chunks if "Toner cartridge black" in c.text]
    assert len(pricing) == 1 and "Payment Terms" not in pricing[0].text


def test_long_clause_split_with_overlap():
    words = [f"w{i}" for i in range(2000)]
    chunks = chunk_contract("1. Long clause " + " ".join(words), max_tokens=100, overlap_tokens=20)
    assert len(chunks) > 1
    assert all(approx_tokens(c.text) <= 101 for c in chunks)
    first, second = chunks[0].text.split(), chunks[1].text.split()
    assert first[-15:] == second[:15]  # 20 tokens ~= 15 words of overlap


def test_rrf_rewards_agreement():
    scores = rrf([[1, 2, 3], [2, 1, 3]])
    assert scores[1] == scores[2] > scores[3]


def test_tsquery_sanitised():
    assert to_tsquery_or("price per case; DROP TABLE") == "price | case | drop | table"
    assert to_tsquery_or("the of") is None


def test_hybrid_search_filters_by_vendor():
    r = InMemoryRetriever()
    r.add(1, 1, 1, "Payment Terms. Net 45 days.")
    r.add(2, 2, 2, "Payment Terms. Net 30 days.")
    hits = r.search("payment terms", vendor_id=2, k=5)
    assert [h.chunk_id for h in hits] == [2]


def test_end_to_end_offline_pipeline(tmp_path):
    """Seed PDFs through the full in-memory pipeline find every labelled issue."""
    from evals.run_evals import evaluate

    res = evaluate(use_llm=False)
    assert res["recall"] == 1.0
    assert res["precision"] == 1.0
    assert res["citation_accuracy"] == 1.0
