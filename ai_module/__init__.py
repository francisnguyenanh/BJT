"""
Unified AI module for reusable integration across projects.

Exports:
- AIHub: provider-agnostic factory/helper for Vertex AI and Kaggle AI
- normalize_kaggle_accounts_payload / resolve_active_kaggle_account: account switching helpers
"""

from ai_module.hub import AIHub
from ai_module.vertex_client import GeminiClient, ChatSession
from ai_module.kaggle_client import KaggleClient
from ai_module.kaggle_accounts import (
    normalize_kaggle_accounts_payload,
    resolve_active_kaggle_account,
    upsert_kaggle_account,
)

__all__ = [
    "AIHub",
    "GeminiClient",
    "ChatSession",
    "KaggleClient",
    "normalize_kaggle_accounts_payload",
    "resolve_active_kaggle_account",
    "upsert_kaggle_account",
]
