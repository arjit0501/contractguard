"""Thin wrapper around the OpenAI API with deterministic offline fallbacks.

Offline mode (no OPENAI_API_KEY, or CONTRACTGUARD_OFFLINE=1) lets the whole
pipeline, the tests and the evals run without network access:
  * embeddings fall back to a feature-hashing bag-of-words vector
  * structured extraction falls back to a parser for the seed-data PDF layout
  * the agent falls back to a rule-based planner
"""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import List, Optional, Sequence, Type, TypeVar

from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T", bound=BaseModel)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@lru_cache
def get_client():  # pragma: no cover - requires network
    from openai import OpenAI

    return OpenAI(api_key=get_settings().openai_api_key)


def tokenize(text: str) -> List[str]:
    return _TOKEN_RE.findall(text.lower())


def hash_embedding(text: str, dim: int) -> List[float]:
    """Feature-hashing embedding of unigrams + bigrams, L2-normalised."""
    vec = [0.0] * dim
    toks = tokenize(text)
    feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:])]
    for f in feats:
        h = int(hashlib.md5(f.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: Sequence[str]) -> List[List[float]]:
    s = get_settings()
    if not s.llm_enabled:
        return [hash_embedding(t, s.embedding_dim) for t in texts]
    resp = get_client().embeddings.create(  # pragma: no cover - requires network
        model=s.embedding_model, input=list(texts), dimensions=s.embedding_dim
    )
    return [d.embedding for d in resp.data]  # pragma: no cover


def structured_completion(system: str, user: str, schema: Type[T]) -> T:  # pragma: no cover
    """Call the chat model with Structured Outputs and return a validated Pydantic object."""
    s = get_settings()
    client = get_client()
    completions = getattr(client.chat.completions, "parse", None) or client.beta.chat.completions.parse
    resp = completions(
        model=s.chat_model,
        temperature=0,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format=schema,
    )
    msg = resp.choices[0].message
    if getattr(msg, "refusal", None):
        raise RuntimeError(f"Model refused extraction: {msg.refusal}")
    parsed: Optional[T] = msg.parsed
    if parsed is None:
        raise RuntimeError("Model returned no parsed output")
    return parsed
