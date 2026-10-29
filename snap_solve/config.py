"""Load non-secret defaults from .env and store app-entered keys securely."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import keyring


SERVICE_NAME = "Snap Solve DeepSeek"
ACCOUNT_NAME = "api-key"


def env_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    return Path(__file__).resolve().parent.parent / ".env"


def read_env() -> dict[str, str]:
    path = env_path()
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"\'')
    return result


def setting(name: str, default: str = "") -> str:
    return os.environ.get(name) or read_env().get(name) or default


def get_api_key() -> str:
    try:
        saved = keyring.get_password(SERVICE_NAME, ACCOUNT_NAME)
    except keyring.errors.KeyringError:
        saved = None
    return saved or setting("DEEPSEEK_API_KEY")


def save_api_key(value: str) -> None:
    value = value.strip()
    if not value:
        raise ValueError("API Key 不能为空")
    keyring.set_password(SERVICE_NAME, ACCOUNT_NAME, value)


def clear_api_key() -> None:
    keyring.delete_password(SERVICE_NAME, ACCOUNT_NAME)

