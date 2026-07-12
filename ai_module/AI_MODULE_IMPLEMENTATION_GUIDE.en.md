# AI Module Implementation Guide (English)

**Goal:** When copying the ai_module directory to another project, any AI agent reading this file can quickly understand and implement it correctly.

## 1. Overview

ai_module is a unified AI package containing:
- Vertex AI Gemini REST client
- Kaggle AI inference client
- AIHub facade for provider-agnostic calls
- Multi-account Kaggle credential helpers

Public API (canonical imports):
```python
from ai_module import AIHub
from ai_module import GeminiClient, ChatSession
from ai_module import KaggleClient
from ai_module import normalize_kaggle_accounts_payload, resolve_active_kaggle_account, upsert_kaggle_account
```

## 2. Minimum File Structure to Copy

Copy the entire ai_module/ directory. Required files:
- `ai_module/__init__.py` — Package exports
- `ai_module/hub.py` — Provider-agnostic factory
- `ai_module/vertex_client.py` — Vertex AI Gemini client
- `ai_module/kaggle_client.py` — Kaggle AI client
- `ai_module/kaggle_accounts.py` — Multi-account helpers
- `ai_module/config/ai.config.json` — Configuration template
- `ai_module/credentials/vertex/service-account.json` — GCP service account (if using Vertex)
- `ai_module/credentials/kaggle/kaggle.json` — Kaggle credentials (if using Kaggle)

**Do NOT include:** legacy folders `vertex_ai/` or `kaggle_ai/`

## 3. Dependencies

Minimum requirements:
- `requests`
- `google-auth`

Install: `pip install requests google-auth`

## 4. Configuration

Config file: `ai_module/config/ai.config.json`

Minimal schema:
```json
{
  "translation_mode": "vertex_ai",
  "vertex_ai": {
    "project_id": "your-gcp-project-id",
    "regions": "us-central1,europe-west4",
    "model": "gemini-2.5-flash-lite",
    "fallback_model": "gemini-2.5-flash",
    "service_account_json": "ai_module/credentials/vertex/service-account.json"
  },
  "kaggle": {
    "active_account_id": "acc_default",
    "username": "",
    "api_key": "",
    "model_proxy_url": "",
    "model_proxy_api_key": "",
    "model": "google/gemini-3-flash-preview",
    "temperature": 0.2,
    "max_output_tokens": 8192
  }
}
```

**Notes:**
- Paths can be relative (from project root) or absolute
- Never hardcode secrets in source; store in credential files or env vars
- GCP service account JSON must be placed in `ai_module/credentials/vertex/`
- Kaggle credentials must be placed in `ai_module/credentials/kaggle/`

## 5. Integration Patterns

### Pattern A: Use AIHub (Recommended)

```python
import json
from ai_module import AIHub

with open("ai_module/config/ai.config.json") as f:
    cfg = json.load(f)

provider = cfg.get("translation_mode", "vertex_ai")
provider_cfg = cfg.get(provider, {})

answer = AIHub.ask(
    provider=provider,
    prompt="Translate to Vietnamese: Hello world",
    provider_cfg=provider_cfg,
)
print(answer)
```

### Pattern B: Use Direct Client (for custom control)

Vertex AI:
```python
from ai_module import GeminiClient

client = GeminiClient(
    project_id="your-gcp-project-id",
    model="gemini-2.5-flash-lite",
    fallback_model="gemini-2.5-flash",
    regions=["us-central1", "europe-west4"],
    key_file="ai_module/credentials/vertex/service-account.json",
)
answer = client.ask("Say hello")
```

Kaggle:
```python
from ai_module import KaggleClient

client = KaggleClient(
    username="your-kaggle-username",
    api_key="your-kaggle-api-key",
    model="google/gemini-3-flash-preview",
)
answer = client.ask("Say hello", temperature=0.2, max_tokens=1024)
```

## 6. Multi-Account Kaggle Support

Use helpers to manage multi-account payloads:

```python
from ai_module import (
    normalize_kaggle_accounts_payload,
    resolve_active_kaggle_account,
    upsert_kaggle_account,
)

payload = {
    "active_account_id": "acc_a",
    "accounts": [
        {"id": "acc_a", "name": "Team A", "username": "user_a", "api_key": "***"},
        {"id": "acc_b", "name": "Team B", "username": "user_b", "api_key": "***"}
    ]
}

normalized = normalize_kaggle_accounts_payload(payload)
resolved = resolve_active_kaggle_account(normalized)
selected = resolved["selected"]  # Currently active account

updated = upsert_kaggle_account(normalized, {"id": "acc_c", "username": "user_c", "api_key": "***"})
```

## 7. Implementation Checklist (for AI agent)

If you are an AI agent integrating ai_module into a new project, follow in order:

1. Copy `ai_module/` directory to project root
2. Install dependencies: `pip install requests google-auth`
3. Create/update `ai_module/config/ai.config.json` with correct values:
   - Set `project_id` for Vertex
   - Set Kaggle credentials (username, api_key) if using Kaggle
4. Place credential files:
   - GCP: `ai_module/credentials/vertex/service-account.json`
   - Kaggle: `ai_module/credentials/kaggle/kaggle.json`
5. Use `AIHub.ask()` for standard flow; use direct clients only for customization
6. For multi-account Kaggle, apply helpers from `ai_module/kaggle_accounts.py`
7. Run minimal tests:
   ```python
   from ai_module import AIHub, GeminiClient, KaggleClient
   # Should not raise ImportError
   
   # Test with config
   cfg = json.load(open("ai_module/config/ai.config.json"))
   result = AIHub.ask(provider=cfg["translation_mode"], prompt="Test", provider_cfg=cfg[cfg["translation_mode"]])
   ```
8. Scan entire codebase to ensure no legacy imports:
   - No `from vertex_ai import ...`
   - No `from kaggle_ai import ...`

## 8. Verification Checklist

- [ ] `from ai_module import AIHub, GeminiClient, KaggleClient` imports successfully
- [ ] Config file loads without error
- [ ] Vertex AI call succeeds (if using Vertex)
- [ ] Kaggle call succeeds (if using Kaggle)
- [ ] No secrets exposed in API responses or logs
- [ ] No legacy folder references remain

## 9. Common Issues

| Issue | Solution |
|-------|----------|
| `FileNotFoundError` for service account | Check `service_account_json` path is relative to project root or absolute |
| `ValueError: Missing Vertex AI project_id` | Ensure `project_id` is set in config or service account JSON contains it |
| Kaggle auth fails | Verify username, api_key, and model_proxy credentials are correct |
| Account switching not working | Ensure payload uses `{active_account_id, accounts:[...]}` structure, not flat dict |
| Secrets leaked in config response | Use `AIHub.ask()` and mask credentials before exposing config via API |

## 10. Architecture Notes

- **Vertex AI:** Standalone REST client using `google-auth` library. No `google-cloud-aiplatform` SDK needed. Auto-rotates through regions on 429/503 errors.
- **Kaggle:** Uses basic auth to get proxy token, then calls OpenAI-compatible endpoint.
- **AIHub:** Factory that builds and caches providers based on config; simplifies provider switching.
- **Backward Compatibility:** Kaggle account helpers accept both legacy single-account and new multi-account shapes.

## 11. Backward Compatibility Promise

The public API (`__all__` in `ai_module/__init__.py`) will remain stable. Internal refactoring may occur, but external imports should not break between minor versions.

If you modify internal code, test with:
```python
from ai_module import AIHub, GeminiClient, ChatSession, KaggleClient
from ai_module import normalize_kaggle_accounts_payload, resolve_active_kaggle_account, upsert_kaggle_account
```
