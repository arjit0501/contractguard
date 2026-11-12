from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional


class Settings:
    def __init__(self) -> None:
        self.database_url: str = os.getenv(
            "DATABASE_URL",
            "postgresql+psycopg://contractguard:contractguard@localhost:5432/contractguard",
        )
        self.openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY") or None
        self.chat_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.embedding_model: str = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "1536"))
        self.upload_dir: str = os.getenv("UPLOAD_DIR", "./uploads")
        self.cors_origins: List[str] = [
            o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
        ]
        # Annual cost of capital used to price "paid too early" payment-terms findings.
        self.cost_of_capital: float = float(os.getenv("COST_OF_CAPITAL", "0.08"))
        self.force_offline: bool = os.getenv("CONTRACTGUARD_OFFLINE", "0") == "1"

    @property
    def llm_enabled(self) -> bool:
        """LLM features are used when an API key is configured, unless forced offline."""
        return bool(self.openai_api_key) and not self.force_offline

    @property
    def active_embedding_model(self) -> str:
        return self.embedding_model if self.llm_enabled else f"hash-{self.embedding_dim}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
