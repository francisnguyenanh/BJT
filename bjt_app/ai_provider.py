# -*- coding: utf-8 -*-
"""Provider-priority wrapper: try Kaggle AI first, fall back to Vertex AI
on any failure (auth error, quota, timeout, proxy down, ...)."""

import json
import os

from ai_module import AIHub
from ai_module.kaggle_accounts import resolve_active_kaggle_account

CONFIG_PATH_DEFAULT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_module", "config", "ai.config.json"
)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROVIDER_ORDER = ["kaggle", "vertex_ai"]


def _resolve_path(path: str) -> str:
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(PROJECT_ROOT, path)


def _load_config(config_path: str = CONFIG_PATH_DEFAULT) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolved_kaggle_cfg(kg_cfg: dict) -> dict:
    """Fill username/api_key from credentials_json (multi-account file) if
    the inline config fields are empty, without persisting secrets back to
    ai.config.json."""
    kg_cfg = dict(kg_cfg or {})
    if kg_cfg.get("username") and kg_cfg.get("api_key"):
        return kg_cfg

    creds_path = _resolve_path(kg_cfg.get("credentials_json", ""))
    if not creds_path or not os.path.exists(creds_path):
        return kg_cfg

    with open(creds_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    resolved = resolve_active_kaggle_account(payload, kg_cfg.get("active_account_id", ""))
    selected = resolved.get("selected") or {}

    kg_cfg["username"] = kg_cfg.get("username") or selected.get("username", "")
    kg_cfg["api_key"] = kg_cfg.get("api_key") or selected.get("api_key", "")
    kg_cfg["model_proxy_url"] = kg_cfg.get("model_proxy_url") or selected.get("model_proxy_url", "")
    kg_cfg["model_proxy_api_key"] = kg_cfg.get("model_proxy_api_key") or selected.get("model_proxy_api_key", "")
    return kg_cfg


def _provider_cfg(provider: str, config: dict) -> dict:
    if provider == "kaggle":
        return _resolved_kaggle_cfg(config.get("kaggle", {}))
    if provider == "vertex_ai":
        return config.get("vertex_ai", {})
    raise ValueError(f"Unknown provider: {provider}")


def get_provider_priority(config_path: str = CONFIG_PATH_DEFAULT) -> list:
    """Return the user-configured provider priority order (primary first,
    falls back to the rest on error), defaulting to PROVIDER_ORDER."""
    config = _load_config(config_path)
    order = config.get("provider_priority")
    if isinstance(order, list) and order:
        ordered = [p for p in order if p in PROVIDER_ORDER]
        ordered += [p for p in PROVIDER_ORDER if p not in ordered]
        return ordered
    return list(PROVIDER_ORDER)


def set_provider_priority(order: list, config_path: str = CONFIG_PATH_DEFAULT) -> None:
    """Persist the primary provider preference to ai.config.json."""
    config = _load_config(config_path)
    ordered = [p for p in order if p in PROVIDER_ORDER]
    ordered += [p for p in PROVIDER_ORDER if p not in ordered]
    config["provider_priority"] = ordered
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def ask(prompt: str, config_path: str = CONFIG_PATH_DEFAULT, provider_order=None) -> tuple[str, str]:
    """Ask the first available provider in priority order, falling back to
    the next one on any error. Returns (answer, provider_used)."""
    config = _load_config(config_path)
    order = provider_order or get_provider_priority(config_path)

    errors = []
    for provider in order:
        try:
            cfg = _provider_cfg(provider, config)
            answer = AIHub.ask(provider=provider, prompt=prompt, provider_cfg=cfg)
            return answer, provider
        except Exception as exc:  # noqa: BLE001 - deliberately broad: try next provider
            errors.append(f"{provider}: {exc}")
            continue

    raise RuntimeError("All AI providers failed:\n" + "\n".join(errors))


if __name__ == "__main__":
    answer, provider = ask("Reply with exactly: OK")
    print(f"[{provider}] {answer}")
