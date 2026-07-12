# -*- coding: utf-8 -*-
"""Provider-agnostic AI hub (Vertex AI + Kaggle AI)."""

import json
import os


class AIHub:
    """Small factory/helper wrapper so projects can use one AI module."""

    @staticmethod
    def build_vertex_client(va_cfg: dict):
        from ai_module.vertex_client import GeminiClient

        default_sa = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "ai_module",
            "credentials",
            "vertex",
            "service-account.json",
        )

        key_file = (va_cfg.get("service_account_json") or "").strip()
        if key_file and not os.path.isabs(key_file):
            key_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                key_file,
            )
        if not key_file and os.path.exists(default_sa):
            key_file = default_sa

        project_id = (va_cfg.get("project_id") or "").strip()
        if not project_id and key_file and os.path.exists(key_file):
            try:
                with open(key_file, "r", encoding="utf-8") as f:
                    project_id = (json.load(f).get("project_id") or "").strip()
            except Exception:
                project_id = ""

        if not project_id:
            raise ValueError("Missing Vertex AI project_id.")

        regions_raw = va_cfg.get("regions", "") or va_cfg.get("location", "us-central1")
        regions = [r.strip() for r in str(regions_raw).split(",") if r.strip()] or ["us-central1"]

        return GeminiClient(
            project_id=project_id,
            model=(va_cfg.get("model") or "gemini-2.5-flash-lite").strip() or "gemini-2.5-flash-lite",
            fallback_model=(va_cfg.get("fallback_model") or "gemini-2.5-flash").strip() or "gemini-2.5-flash",
            regions=regions,
            key_file=key_file,
        )

    @staticmethod
    def build_kaggle_client(kg_cfg: dict):
        from ai_module.kaggle_client import KaggleClient

        return KaggleClient(
            username=(kg_cfg.get("username") or "").strip(),
            api_key=(kg_cfg.get("api_key") or "").strip(),
            model_proxy_url=(kg_cfg.get("model_proxy_url") or "").strip(),
            model_proxy_api_key=(kg_cfg.get("model_proxy_api_key") or "").strip(),
            model=(kg_cfg.get("model") or "google/gemini-3-flash-preview").strip() or "google/gemini-3-flash-preview",
        )

    @staticmethod
    def ask(provider: str, prompt: str, provider_cfg: dict, *, temperature: float = 0.2, max_tokens: int = 8192) -> str:
        provider = (provider or "").strip().lower()
        if provider == "vertex_ai":
            client = AIHub.build_vertex_client(provider_cfg)
            return client.ask(prompt)
        if provider == "kaggle":
            client = AIHub.build_kaggle_client(provider_cfg)
            return client.ask(prompt, temperature=temperature, max_tokens=max_tokens)
        raise ValueError(f"Unsupported provider: {provider}")

    @staticmethod
    def list_models(provider: str, provider_cfg: dict) -> list:
        provider = (provider or "").strip().lower()
        if provider == "kaggle":
            from ai_module.kaggle_client import KaggleClient

            return KaggleClient.list_models(
                username=(provider_cfg.get("username") or "").strip(),
                api_key=(provider_cfg.get("api_key") or "").strip(),
                page_size=int(provider_cfg.get("page_size") or 100),
            )
        if provider == "vertex_ai":
            # Vertex does not have a public list endpoint in current app flow.
            return []
        raise ValueError(f"Unsupported provider: {provider}")
