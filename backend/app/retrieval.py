"""Hybrid (vector + keyword) clause retrieval, fused with Reciprocal Rank Fusion.

`PgRetriever` runs both searches inside PostgreSQL (pgvector cosine distance +
full-text `ts_rank_cd`). `InMemoryRetriever` implements the same algorithm in
Python for tests and offline evals.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Sequence

from .llm import embed, tokenize

RRF_K = 60
CANDIDATES = 20

_STOPWORDS = {"the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "per", "is", "by", "with"}


@dataclass
class ClauseHit:
    chunk_id: int
    contract_id: int
    vendor_id: int
    text: str
    score: float
    heading: Optional[str] = None


class Retriever(Protocol):
    def search(self, query: str, vendor_id: Optional[int] = None, k: int = 3) -> List[ClauseHit]: ...


def rrf(rankings: Sequence[Sequence[int]], k: int = RRF_K) -> Dict[int, float]:
    scores: Dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def keyword_terms(query: str) -> List[str]:
    return [t for t in tokenize(query) if t not in _STOPWORDS]


def to_tsquery_or(query: str) -> Optional[str]:
    terms = [t for t in keyword_terms(query) if re.fullmatch(r"[a-z0-9]+", t)]
    return " | ".join(dict.fromkeys(terms)) or None


@dataclass
class _Doc:
    chunk_id: int
    contract_id: int
    vendor_id: int
    text: str
    heading: Optional[str]
    embedding: List[float]
    tokens: List[str]


class InMemoryRetriever:
    def __init__(self) -> None:
        self.docs: List[_Doc] = []

    def add(self, chunk_id: int, contract_id: int, vendor_id: int, text: str, heading: Optional[str] = None,
            embedding: Optional[List[float]] = None) -> None:
        emb = embedding if embedding is not None else embed([text])[0]
        self.docs.append(_Doc(chunk_id, contract_id, vendor_id, text, heading, emb, tokenize(text)))

    def search(self, query: str, vendor_id: Optional[int] = None, k: int = 3) -> List[ClauseHit]:
        docs = [d for d in self.docs if vendor_id is None or d.vendor_id == vendor_id]
        if not docs:
            return []
        q = embed([query])[0]
        by_vec = sorted(docs, key=lambda d: -sum(a * b for a, b in zip(q, d.embedding)))[:CANDIDATES]
        terms = set(keyword_terms(query))
        n = len(docs)

        def bm25ish(d: _Doc) -> float:
            score = 0.0
            for t in terms:
                tf = d.tokens.count(t)
                if tf:
                    df = sum(1 for x in docs if t in x.tokens)
                    score += (tf / (tf + 1.2)) * math.log(1 + (n - df + 0.5) / (df + 0.5))
            return score

        kw_scored = [(bm25ish(d), d) for d in docs]
        by_kw = [d for s, d in sorted(kw_scored, key=lambda x: -x[0]) if s > 0][:CANDIDATES]
        fused = rrf([[d.chunk_id for d in by_vec], [d.chunk_id for d in by_kw]])
        lookup = {d.chunk_id: d for d in docs}
        top = sorted(fused.items(), key=lambda x: -x[1])[:k]
        return [
            ClauseHit(cid, lookup[cid].contract_id, lookup[cid].vendor_id, lookup[cid].text, s, lookup[cid].heading)
            for cid, s in top
        ]


HYBRID_SQL = """
WITH vec AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY embedding <=> CAST(:qvec AS vector)) AS rnk
    FROM contract_chunks
    WHERE (CAST(:vid AS INTEGER) IS NULL OR vendor_id = CAST(:vid AS INTEGER))
      AND embedding_model = :model
    ORDER BY embedding <=> CAST(:qvec AS vector)
    LIMIT :cand
),
kw AS (
    SELECT id, ROW_NUMBER() OVER (ORDER BY ts_rank_cd(tsv, to_tsquery('english', CAST(:tsq AS TEXT))) DESC) AS rnk
    FROM contract_chunks
    WHERE (CAST(:vid AS INTEGER) IS NULL OR vendor_id = CAST(:vid AS INTEGER))
      AND tsv @@ to_tsquery('english', CAST(:tsq AS TEXT))
    ORDER BY ts_rank_cd(tsv, to_tsquery('english', CAST(:tsq AS TEXT))) DESC
    LIMIT :cand
)
SELECT c.id, c.contract_id, c.vendor_id, c.text, c.heading,
       COALESCE(1.0 / (:rrfk + vec.rnk), 0) + COALESCE(1.0 / (:rrfk + kw.rnk), 0) AS score
FROM contract_chunks c
LEFT JOIN vec ON vec.id = c.id
LEFT JOIN kw ON kw.id = c.id
WHERE vec.id IS NOT NULL OR kw.id IS NOT NULL
ORDER BY score DESC
LIMIT :k
"""


class PgRetriever:
    def __init__(self, session, embedding_model: str) -> None:
        self.session = session
        self.embedding_model = embedding_model

    def search(self, query: str, vendor_id: Optional[int] = None, k: int = 3) -> List[ClauseHit]:
        from sqlalchemy import text

        qvec = "[" + ",".join(f"{x:.6f}" for x in embed([query])[0]) + "]"
        rows = self.session.execute(
            text(HYBRID_SQL),
            {
                "qvec": qvec,
                "vid": vendor_id,
                "model": self.embedding_model,
                "tsq": to_tsquery_or(query) or "",
                "cand": CANDIDATES,
                "rrfk": RRF_K,
                "k": k,
            },
        ).all()
        return [ClauseHit(r.id, r.contract_id, r.vendor_id, r.text, float(r.score), r.heading) for r in rows]
