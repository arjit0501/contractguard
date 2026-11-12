"""Clause-aware chunking for contracts.

Contracts are split at numbered clause headings ("1.", "3.2", "Section 4"),
then clauses are packed into chunks of roughly `max_tokens` tokens. Clauses
longer than the limit are split on word boundaries with `overlap_tokens` of
overlap so no sentence is lost at a boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

_HEADING_RE = re.compile(r"^\s*(?:(?:Section|Clause)\s+)?\d+(?:\.\d+)*[.)]?\s+\S", re.I)


def approx_tokens(text: str) -> int:
    """~0.75 words per token is the usual rule of thumb for English."""
    return max(1, round(len(text.split()) / 0.75))


@dataclass
class Chunk:
    index: int
    heading: Optional[str]
    text: str


def split_clauses(text: str) -> List[str]:
    clauses: List[List[str]] = [[]]
    for line in text.splitlines():
        if _HEADING_RE.match(line) and any(s.strip() for s in clauses[-1]):
            clauses.append([])
        clauses[-1].append(line)
    return [c for c in ("\n".join(lines).strip() for lines in clauses) if c]


def _split_long(text: str, max_tokens: int, overlap_tokens: int) -> List[str]:
    words = text.split()
    max_words = max(1, int(max_tokens * 0.75))
    overlap_words = int(overlap_tokens * 0.75)
    step = max(1, max_words - overlap_words)
    out = []
    for start in range(0, len(words), step):
        out.append(" ".join(words[start : start + max_words]))
        if start + max_words >= len(words):
            break
    return out


def chunk_contract(
    text: str, max_tokens: int = 500, overlap_tokens: int = 50, min_tokens: int = 25
) -> List[Chunk]:
    """One chunk per clause so citations point at a single clause. Tiny fragments
    (e.g. the document title) are merged forward; long clauses are split with overlap."""
    pieces: List[str] = []
    carry = ""
    for clause in split_clauses(text):
        clause = f"{carry}\n\n{clause}".strip() if carry else clause
        carry = ""
        if approx_tokens(clause) < min_tokens:
            carry = clause
            continue
        if approx_tokens(clause) > max_tokens:
            pieces.extend(_split_long(clause, max_tokens, overlap_tokens))
        else:
            pieces.append(clause)
    if carry:
        if pieces and approx_tokens(pieces[-1] + carry) <= max_tokens:
            pieces[-1] = f"{pieces[-1]}\n\n{carry}"
        else:
            pieces.append(carry)

    chunks = []
    for i, p in enumerate(pieces):
        first = p.strip().splitlines()[0] if p.strip() else ""
        chunks.append(Chunk(index=i, heading=first[:200] if _HEADING_RE.match(first) else None, text=p))
    return chunks
