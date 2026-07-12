# -*- coding: utf-8 -*-
"""
Kaggle AI inference client.

Cơ chế:
  1. Dùng Basic auth (username:api_key) để lấy Model Proxy token ngắn hạn (2h TTL)
     từ endpoint: POST https://www.kaggle.com/api/v1/models/proxy/token
  2. Dùng token đó để gọi inference qua OpenAI-compatible API:
     POST https://mp-staging.kaggle.net/models/openapi/v1/chat/completions

Models khả dụng (format: provider/model-name):
  - google/gemini-3-flash-preview
  - google/gemini-3.1-flash-lite-preview
  - anthropic/claude-haiku-4-5@20251001
  - deepseek-ai/deepseek-v3.2
  - openai/gpt-oss-120b
  - qwen/qwen3-next-80b-a3b-instruct
  - zai/glm-5
"""

import base64
import os
import time
from datetime import datetime, timezone

import requests

_KAGGLE_API = "https://www.kaggle.com/api/v1"
_PROXY_TOKEN_URL = f"{_KAGGLE_API}/models/proxy/token"
_BENCHMARK_MODELS_URL = f"{_KAGGLE_API}/benchmarks/models"

_STATUS_HINTS = {
    400: "Request không hợp lệ — tham số hoặc format body sai.",
    401: "Xác thực thất bại — kiểm tra lại username/API key.",
    403: "Không có quyền — tài khoản chưa xác thực số điện thoại, hoặc Benchmarks chưa được kích hoạt.",
    404: "Endpoint không tồn tại hoặc model không khả dụng trên Kaggle Proxy.",
    429: "Vượt quá Kaggle quota. Kiểm tra hạn mức tại kaggle.com.",
    500: "Lỗi Kaggle server (500). Thử lại sau.",
    502: "Kaggle server không phản hồi (502).",
    503: "Dịch vụ Kaggle tạm thời không khả dụng (503).",
}

# Proxy models available on Kaggle Benchmarks
AVAILABLE_PROXY_MODELS = [
    "google/gemini-3-flash-preview",
    "google/gemini-3.1-flash-lite-preview",
    "anthropic/claude-haiku-4-5@20251001",
    "deepseek-ai/deepseek-v3.2",
    "openai/gpt-oss-120b",
    "qwen/qwen3-next-80b-a3b-instruct",
    "zai/glm-5",
]


class KaggleClient:
    """Kaggle AI inference client qua Model Proxy — không retry, lỗi báo ngay."""

    def __init__(
        self,
        *,
        username: str,
        api_key: str,
        model: str,
        timeout: int = 120,
        model_proxy_url: str = "",
        model_proxy_api_key: str = "",
        # Legacy fields kept for backward compat but unused
        api_token: str = "",
    ):
        self.username = username.strip() or os.getenv("KAGGLE_USERNAME", "").strip()
        self.api_key = api_key.strip() or os.getenv("KAGGLE_API_KEY", "").strip()
        self.model = model.strip()
        self.timeout = timeout
        # Optional direct proxy credentials (from `kaggle benchmarks auth` .env)
        self.model_proxy_url = (
            model_proxy_url.strip()
            or os.getenv("MODEL_PROXY_URL", "").strip()
        )
        self.model_proxy_api_key = (
            model_proxy_api_key.strip()
            or os.getenv("MODEL_PROXY_API_KEY", "").strip()
        )

        if not self.model:
            raise ValueError("Chưa chọn model Kaggle.")
        if not self._has_direct_proxy_credentials() and not (self.username and self.api_key):
            raise ValueError(
                "Thiếu thông tin xác thực Kaggle.\n"
                "Cần cung cấp một trong hai cách:\n"
                "1) username + API key (từ kaggle.json), hoặc\n"
                "2) model_proxy_url + model_proxy_api_key (từ `kaggle benchmarks auth`)."
            )

        self._proxy_token: str = ""
        self._proxy_base: str = ""
        self._proxy_expiry: float = 0.0  # unix timestamp

    # ------------------------------------------------------------------
    def _has_direct_proxy_credentials(self) -> bool:
        return bool(self.model_proxy_url and self.model_proxy_api_key)

    @staticmethod
    def _normalize_proxy_base(url: str) -> str:
        u = (url or "").strip().rstrip("/")
        marker = "/openapi/v1/chat/completions"
        if u.endswith(marker):
            u = u[: -len(marker)]
        marker2 = "/v1/chat/completions"
        if u.endswith(marker2):
            u = u[: -len(marker2)]
        return u

    # ------------------------------------------------------------------
    def _basic_auth_headers(self) -> dict:
        cred = base64.b64encode(f"{self.username}:{self.api_key}".encode()).decode()
        return {"Authorization": f"Basic {cred}"}

    def _ensure_proxy_token(self) -> None:
        """Fetch or refresh proxy token if missing/expired (with 60s buffer)."""
        if self._has_direct_proxy_credentials():
            self._proxy_token = self.model_proxy_api_key
            self._proxy_base = self._normalize_proxy_base(self.model_proxy_url)
            self._proxy_expiry = time.time() + 86400 * 365  # effectively non-expiring in process scope
            return

        now = time.time()
        if self._proxy_token and now < self._proxy_expiry - 60:
            return

        try:
            resp = requests.post(
                _PROXY_TOKEN_URL,
                headers={**self._basic_auth_headers(), "Content-Type": "application/json"},
                json={},
                timeout=15,
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"Không kết nối được Kaggle API: {exc}")
        except requests.exceptions.Timeout:
            raise RuntimeError("Kaggle API timeout khi lấy proxy token.")

        if resp.status_code >= 400:
            hint = _STATUS_HINTS.get(resp.status_code, "")
            body = ""
            try:
                body = resp.json().get("message") or resp.text[:200]
            except Exception:
                body = resp.text[:200]
            raise RuntimeError(
                f"Không lấy được Kaggle proxy token — HTTP {resp.status_code}\n"
                + (f"{hint}\n" if hint else "")
                + (f"Chi tiết: {body}" if body else "")
            )

        data = resp.json()
        self._proxy_token = data["token"]
        self._proxy_base = data["baseUri"].rstrip("/")

        expiry_str = data.get("expiryTime", "")
        if expiry_str:
            try:
                dt = datetime.fromisoformat(expiry_str.rstrip("Z")).replace(tzinfo=timezone.utc)
                self._proxy_expiry = dt.timestamp()
            except Exception:
                self._proxy_expiry = now + 7200  # fallback 2h
        else:
            self._proxy_expiry = now + 7200

    def _inference_url(self) -> str:
        return f"{self._proxy_base}/openapi/v1/chat/completions"

    # ------------------------------------------------------------------
    def ask(self, prompt: str, temperature: float = 0.2, max_tokens: int = 8192) -> str:
        """Single-turn inference — raises ngay lập tức nếu có lỗi."""
        self._ensure_proxy_token()

        url = self._inference_url()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self._proxy_token}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.exceptions.Timeout:
            raise RuntimeError(
                f"Kaggle không phản hồi sau {self.timeout}s.\nURL: {url}"
            )
        except requests.exceptions.ConnectionError as exc:
            raise RuntimeError(f"Không kết nối được Kaggle proxy: {exc}")

        if resp.status_code >= 400:
            hint = _STATUS_HINTS.get(resp.status_code, "")
            body_detail = ""
            try:
                body = resp.json()
                body_detail = body.get("message") or body.get("error") or body.get("detail") or ""
            except Exception:
                body_detail = resp.text[:400]

            parts = [f"Kaggle AI lỗi HTTP {resp.status_code}"]
            if hint:
                parts.append(hint)
            if body_detail:
                parts.append(f"Chi tiết: {body_detail}")
            else:
                parts.append("Response: (trống)")
            parts.append(f"Model: {self.model}")
            parts.append(f"URL: {url}")
            raise RuntimeError("\n".join(parts))

        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(
                f"Kaggle trả về dữ liệu không hợp lệ.\nURL: {url}\nResponse: {resp.text[:300]}"
            )

        return self._extract_text(data)

    # ------------------------------------------------------------------
    @staticmethod
    def _extract_text(data: dict) -> str:
        choices = data.get("choices")
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content", "")
            if content:
                return content
        if "text" in data:
            return str(data["text"])
        raise RuntimeError(
            f"Không nhận dạng được response Kaggle.\nRaw: {str(data)[:500]}"
        )

    # ------------------------------------------------------------------
    def diagnose(self) -> dict:
        """Chạy kiểm tra step-by-step để xác định endpoint + auth hoạt động."""
        results = {}

        # 1. Lấy proxy token
        try:
            self._proxy_token = ""  # force refresh
            self._ensure_proxy_token()
            results["proxy_token"] = {
                "ok": True,
                "base_uri": self._proxy_base,
                "note": f"Token lấy thành công, hết hạn: {datetime.fromtimestamp(self._proxy_expiry).isoformat()}",
            }
        except Exception as exc:
            results["proxy_token"] = {"ok": False, "error": str(exc)}
            return results

        # 2. Gọi inference thử
        url = self._inference_url()
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {self._proxy_token}", "Content-Type": "application/json"},
                json={"model": self.model, "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 5},
                timeout=30,
            )
            results["inference"] = {
                "url": url,
                "model": self.model,
                "status": resp.status_code,
                "ok": resp.status_code < 400,
                "body": resp.text[:300],
            }
        except Exception as exc:
            results["inference"] = {"url": url, "model": self.model, "error": str(exc)}

        return results

    # ------------------------------------------------------------------
    @classmethod
    def list_models(
        cls,
        username: str = "",
        api_key: str = "",
        api_token: str = "",  # kept for compat
        page_size: int = 100,
        max_pages: int = 5,
    ) -> list:
        """Trả về danh sách model Kaggle AI.

        Ưu tiên lấy động từ endpoint benchmarks/models (có pagination),
        fallback về danh sách static nếu không truy cập được.
        """
        dynamic_items = []

        # 1) Dynamic discovery via official Kaggle benchmarks endpoint
        if username.strip() and api_key.strip():
            token = ""
            safe_page_size = max(20, min(int(page_size or 100), 200))
            pages = 0

            while pages < max(1, int(max_pages or 1)):
                pages += 1
                params = {"pageSize": safe_page_size}
                if token:
                    params["pageToken"] = token

                try:
                    resp = requests.get(
                        _BENCHMARK_MODELS_URL,
                        auth=(username.strip(), api_key.strip()),
                        params=params,
                        timeout=20,
                    )
                except Exception:
                    break

                if resp.status_code >= 400:
                    break

                try:
                    data = resp.json()
                except Exception:
                    break

                batch = data.get("benchmarkModels", []) or []
                for bm in batch:
                    version = bm.get("version", {}) or {}
                    model_slug = (
                        version.get("modelProxySlugNullable")
                        or version.get("modelProxySlug")
                        or ""
                    ).strip()
                    if not model_slug:
                        continue
                    allow_proxy = version.get("allowModelProxy")
                    if allow_proxy is False:
                        continue

                    display = (
                        version.get("displayNameNullable")
                        or version.get("displayName")
                        or bm.get("displayName")
                        or model_slug
                    )
                    dynamic_items.append({"label": display, "value": model_slug})

                token = (data.get("nextPageTokenNullable") or data.get("nextPageToken") or "").strip()
                if not token:
                    break

        # Deduplicate while preserving first occurrence
        dedup = {}
        for item in dynamic_items:
            val = (item.get("value") or "").strip()
            if val and val not in dedup:
                dedup[val] = item

        if dedup:
            # Sort by label for stable UI
            return sorted(dedup.values(), key=lambda x: (x.get("label") or "").lower())

        # 2) Static fallback
        return [{"label": m, "value": m} for m in AVAILABLE_PROXY_MODELS]
