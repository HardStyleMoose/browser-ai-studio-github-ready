from __future__ import annotations

import hashlib
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlparse


ENV_VAR_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")

_SECRET_FIELD_PATTERN = re.compile(
    r"(?P<field>\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|bearer|token|secret|password|passwd|authorization)\b)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>[^\s,;]+)",
    flags=re.IGNORECASE,
)
_BEARER_PATTERN = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b", flags=re.IGNORECASE)
_ENV_ASSIGNMENT_PATTERN = re.compile(
    r"\b([A-Z][A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY))\s*=\s*([^\s]+)",
    flags=re.IGNORECASE,
)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(str(value or "").encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def redact_sensitive_text(value: str) -> str:
    text = str(value or "")
    text = _BEARER_PATTERN.sub("Bearer [REDACTED]", text)
    text = _ENV_ASSIGNMENT_PATTERN.sub(r"\1=[REDACTED]", text)
    text = _SECRET_FIELD_PATTERN.sub(lambda match: f"{match.group('field')}{match.group('sep')}[REDACTED]", text)
    return text


def redact_sensitive_payload(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key or "")
            if any(token in key_text.lower() for token in ("token", "secret", "password", "authorization", "api_key")):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_sensitive_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_payload(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def normalize_env_var_name(value: str) -> str:
    text = str(value or "").strip().upper()
    return text if ENV_VAR_NAME_RE.fullmatch(text) else ""


def looks_like_secret(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith(("sk-", "ghp_", "gho_", "ghu_", "github_pat_", "eyj", "bearer ")):
        return True
    if any(token in lowered for token in ("secret", "token", "password", "apikey", "api_key")) and "=" in text:
        return True
    if not ENV_VAR_NAME_RE.fullmatch(text.upper()) and len(text) >= 20 and re.search(r"[a-z0-9][A-Z]|[A-Za-z0-9_-]{20,}", text):
        return True
    return False


def validate_env_var_reference(value: str, label: str = "Environment variable") -> tuple[bool, str, str]:
    text = str(value or "").strip()
    if not text:
        return True, "", ""
    normalized = normalize_env_var_name(text)
    if normalized:
        return True, normalized, ""
    if looks_like_secret(text):
        return False, "", f"{label} must be an environment variable name, not a raw secret."
    return False, "", f"{label} must use uppercase letters, numbers, and underscores only."


def is_loopback_host(hostname: str) -> bool:
    host = str(hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_https_or_loopback_url(url: str) -> tuple[bool, str, str]:
    text = str(url or "").strip()
    if not text:
        return False, "", "URL is empty."
    try:
        parsed = urlparse(text)
    except Exception:
        return False, "", "URL is invalid."
    scheme = str(parsed.scheme or "").lower()
    hostname = str(parsed.hostname or "").strip()
    if scheme not in {"https", "http"}:
        return False, "", "URL must use https, or http only for localhost/loopback."
    if not hostname:
        return False, "", "URL must include a host."
    if parsed.username or parsed.password:
        return False, "", "URLs with embedded credentials are not allowed."
    if scheme == "http" and not is_loopback_host(hostname):
        return False, "", "Insecure http URLs are only allowed for localhost or loopback addresses."
    return True, text, ""

