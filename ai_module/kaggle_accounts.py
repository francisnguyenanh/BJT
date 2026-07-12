# -*- coding: utf-8 -*-
"""Helpers for multi-account Kaggle credential storage and switching."""

import time


def _clean_account_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    return {
        "id": str(item.get("id") or "").strip(),
        "name": str(item.get("name") or "").strip(),
        "username": str(item.get("username") or "").strip(),
        "api_key": str(item.get("api_key") or "").strip(),
        "model_proxy_url": str(item.get("model_proxy_url") or "").strip(),
        "model_proxy_api_key": str(item.get("model_proxy_api_key") or "").strip(),
    }


def normalize_kaggle_accounts_payload(raw: dict) -> dict:
    """
    Normalized shape:
    {
      "active_account_id": "acc_xxx",
      "accounts": [{id,name,username,api_key,model_proxy_url,model_proxy_api_key}, ...]
    }

    Backward compatible with legacy single-account format.
    """
    raw = raw if isinstance(raw, dict) else {}

    # New multi-account shape
    if isinstance(raw.get("accounts"), list):
        accounts = []
        for item in raw.get("accounts", []):
            acc = _clean_account_item(item)
            if not acc:
                continue
            if not acc["id"]:
                seed = acc["username"] or acc["name"] or str(int(time.time() * 1000))
                acc["id"] = f"acc_{seed}".replace(" ", "_")
            if not acc["name"]:
                acc["name"] = acc["username"] or acc["id"]
            accounts.append(acc)

        active_id = str(raw.get("active_account_id") or "").strip()
        if not active_id and accounts:
            active_id = accounts[0]["id"]

        return {"active_account_id": active_id, "accounts": accounts}

    # Legacy single-account shape
    legacy = _clean_account_item(raw)
    if not any([legacy.get("username"), legacy.get("api_key"), legacy.get("model_proxy_api_key")]):
        return {"active_account_id": "", "accounts": []}

    legacy_id = legacy["id"] or f"acc_{legacy.get('username') or 'default'}"
    legacy_name = legacy["name"] or legacy.get("username") or legacy_id
    legacy["id"] = legacy_id
    legacy["name"] = legacy_name
    return {"active_account_id": legacy_id, "accounts": [legacy]}


def resolve_active_kaggle_account(payload: dict, preferred_account_id: str = "") -> dict:
    normalized = normalize_kaggle_accounts_payload(payload)
    accounts = normalized.get("accounts", [])
    if not accounts:
        return {
            "active_account_id": "",
            "accounts": [],
            "selected": {},
        }

    preferred = (preferred_account_id or "").strip()
    active_id = preferred or (normalized.get("active_account_id") or "").strip()

    selected = None
    for acc in accounts:
        if acc.get("id") == active_id:
            selected = acc
            break
    if selected is None:
        selected = accounts[0]
        active_id = selected.get("id", "")

    return {
        "active_account_id": active_id,
        "accounts": accounts,
        "selected": selected,
    }


def upsert_kaggle_account(payload: dict, account_data: dict, preferred_account_id: str = "") -> dict:
    normalized = normalize_kaggle_accounts_payload(payload)
    accounts = normalized.get("accounts", [])

    incoming = _clean_account_item(account_data or {})
    has_secret = any([incoming.get("username"), incoming.get("api_key"), incoming.get("model_proxy_api_key")])
    if not has_secret:
        return normalized

    active_id = (preferred_account_id or incoming.get("id") or normalized.get("active_account_id") or "").strip()
    if not active_id:
        seed = incoming.get("username") or str(int(time.time() * 1000))
        active_id = f"acc_{seed}".replace(" ", "_")

    incoming["id"] = active_id
    if not incoming.get("name"):
        incoming["name"] = incoming.get("username") or active_id

    replaced = False
    for idx, acc in enumerate(accounts):
        if acc.get("id") == active_id:
            merged = dict(acc)
            for k, v in incoming.items():
                if v:
                    merged[k] = v
            accounts[idx] = merged
            replaced = True
            break

    if not replaced:
        accounts.append(incoming)

    return {
        "active_account_id": active_id,
        "accounts": accounts,
    }
