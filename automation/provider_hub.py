from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from core.security_utils import (
    normalize_env_var_name,
    redact_sensitive_payload,
    redact_sensitive_text,
    validate_env_var_reference,
    validate_https_or_loopback_url,
)


CATALOG_SITE_URL = "https://nocostai.vercel.app/"
CATALOG_README_URL = "https://raw.githubusercontent.com/zebbern/no-cost-ai/main/README.md"

CATALOG_CATEGORIES = ("chat", "media", "voice", "apis")


def _safe_json_write(path: Path, payload: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
    os.replace(temp_path, path)


def _slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return text or "item"


def _normalize_category(label: str) -> str:
    text = str(label or "").strip().lower()
    if any(token in text for token in ("voice", "speech", "audio", "music", "tts", "stt")):
        return "voice"
    if any(token in text for token in ("api", "model", "endpoint", "sdk", "compatible")):
        return "apis"
    if any(token in text for token in ("image", "video", "media", "photo", "art", "avatar")):
        return "media"
    return "chat"


def _extract_limit_note(line: str) -> str:
    text = " ".join(str(line or "").replace("\n", " ").split())
    if not text:
        return ""
    patterns = [
        r"(free[^.]*?(?:limit|credits?|daily|monthly|usage)[^.]*\.)",
        r"((?:daily|monthly|hourly)[^.]*?(?:limit|credits?|requests?)[^.]*\.)",
        r"((?:rate|usage)[^.]*?(?:limit|free)[^.]*\.)",
        r"((?:no|without)\s+rate\s+limit[^.]*\.)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return text[:180].strip() if any(token in text.lower() for token in ("free", "limit", "credit", "request", "quota")) else ""


def _infer_signup_required(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in ("signup", "sign up", "account", "login", "log in", "api key"))


def _infer_supports_api(text: str, link: str = "") -> bool:
    lowered = f"{text} {link}".lower()
    return any(
        token in lowered
        for token in ("api", "endpoint", "openai compatible", "openai-compatible", "/v1/", "sdk", "curl", "rest")
    )


def _infer_api_style(text: str) -> str:
    lowered = str(text or "").lower()
    if "responses" in lowered:
        return "openai_responses"
    if "openai" in lowered or "chat completions" in lowered or "openai-compatible" in lowered:
        return "openai_chat"
    if "ollama" in lowered:
        return "ollama_chat"
    return "documented_api"


def _extract_models(text: str) -> list[str]:
    quoted = re.findall(r"`([^`]+)`", str(text or ""))
    models = []
    for value in quoted:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        if any(token in normalized.lower() for token in ("gpt", "llama", "claude", "gemini", "mistral", "qwen", "deepseek")):
            models.append(normalized)
    return list(dict.fromkeys(models))[:8]


@dataclass(slots=True)
class ProviderCatalogEntry:
    name: str
    category: str
    link: str
    signup_required: bool = False
    limit_note: str = ""
    supports_api: bool = False
    api_style: str = ""
    models: list[str] = field(default_factory=list)
    source: str = ""
    notes: str = ""

    def normalized(self) -> dict:
        payload = asdict(self)
        payload["category"] = _normalize_category(payload.get("category", "chat"))
        payload["name"] = str(payload.get("name") or "").strip() or "Unnamed Provider"
        payload["link"] = str(payload.get("link") or "").strip()
        payload["signup_required"] = bool(payload.get("signup_required"))
        payload["limit_note"] = str(payload.get("limit_note") or "").strip()
        payload["supports_api"] = bool(payload.get("supports_api"))
        payload["api_style"] = str(payload.get("api_style") or "").strip()
        payload["models"] = [str(model).strip() for model in payload.get("models", []) if str(model).strip()]
        payload["source"] = str(payload.get("source") or "").strip()
        payload["notes"] = str(payload.get("notes") or "").strip()
        payload["token"] = f"{_slugify(payload['name'])}|{_slugify(payload['link'])}"
        return payload


@dataclass(slots=True)
class ProviderEndpointProfile:
    label: str
    base_url: str
    api_key_env_var: str = ""
    api_style: str = "openai_chat"
    models: list[str] = field(default_factory=list)
    enabled: bool = False
    notes: str = ""
    last_status: str = ""
    last_latency_ms: float = 0.0

    def normalized(self) -> dict:
        payload = asdict(self)
        payload["label"] = str(payload.get("label") or "").strip() or "Provider"
        payload["base_url"] = str(payload.get("base_url") or "").strip()
        payload["api_key_env_var"] = normalize_env_var_name(str(payload.get("api_key_env_var") or ""))
        payload["api_style"] = str(payload.get("api_style") or "openai_chat").strip() or "openai_chat"
        payload["models"] = [str(model).strip() for model in payload.get("models", []) if str(model).strip()]
        payload["enabled"] = bool(payload.get("enabled"))
        payload["notes"] = str(payload.get("notes") or "").strip()
        payload["last_status"] = str(payload.get("last_status") or "").strip()
        payload["last_latency_ms"] = float(payload.get("last_latency_ms", 0.0) or 0.0)
        payload["token"] = _slugify(f"{payload['label']} {payload['base_url']}")
        return payload


def validate_endpoint_profile_config(payload: dict) -> dict:
    base_url_ok, normalized_url, url_error = validate_https_or_loopback_url(str((payload or {}).get("base_url") or ""))
    if not base_url_ok:
        return {"ok": False, "error": url_error, "normalized_base_url": ""}
    env_ok, normalized_env_var, env_error = validate_env_var_reference(
        str((payload or {}).get("api_key_env_var") or ""),
        label="API Key Env Var",
    )
    if not env_ok:
        return {"ok": False, "error": env_error, "normalized_base_url": normalized_url}
    return {
        "ok": True,
        "error": "",
        "normalized_base_url": normalized_url,
        "normalized_api_key_env_var": normalized_env_var,
    }


class ProviderCatalogService:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)
        self.data_dir = self.project_root / "data"
        self.cache_path = self.data_dir / "provider_catalog_cache.json"
        self.profile_path = self.data_dir / "provider_endpoint_profiles.json"

    def default_catalog_payload(self) -> dict:
        return {
            "updated_at": "",
            "entries": [],
            "sources": [],
            "warnings": [
                "Catalog entries are informational until you configure a documented compatible API profile.",
            ],
        }

    def load_cache(self) -> dict:
        if not self.cache_path.exists():
            return self.default_catalog_payload()
        try:
            with open(self.cache_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return self.default_catalog_payload()
        entries = [self._normalize_catalog_entry(entry) for entry in payload.get("entries", [])]
        payload = dict(payload)
        payload["entries"] = entries
        payload.setdefault("sources", [])
        payload.setdefault("warnings", [])
        return payload

    def save_cache(self, payload: dict):
        normalized = dict(payload or {})
        normalized["entries"] = [self._normalize_catalog_entry(entry) for entry in normalized.get("entries", [])]
        normalized.setdefault("sources", [])
        normalized.setdefault("warnings", [])
        _safe_json_write(self.cache_path, normalized)

    def load_endpoint_profiles(self) -> list[dict]:
        if not self.profile_path.exists():
            return []
        try:
            with open(self.profile_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return []
        if isinstance(payload, dict):
            payload = payload.get("profiles", [])
        return [self._normalize_profile(entry) for entry in list(payload or [])]

    def save_endpoint_profiles(self, profiles: Iterable[dict]):
        payload = {"profiles": [self._normalize_profile(entry) for entry in profiles]}
        _safe_json_write(self.profile_path, payload)

    def refresh(self, timeout_s: float = 20.0) -> dict:
        warnings = []
        sources = []
        entries = []

        site_html = ""
        try:
            site_html = self._fetch_text(CATALOG_SITE_URL, timeout_s=timeout_s)
            sources.append({"label": "nocostai.vercel.app", "url": CATALOG_SITE_URL, "kind": "site"})
            entries.extend(self.parse_site_html(site_html, source=CATALOG_SITE_URL))
        except Exception as exc:
            warnings.append(f"Unable to refresh NoCostAI site catalog: {exc}")

        readme_markdown = ""
        try:
            readme_markdown = self._fetch_text(CATALOG_README_URL, timeout_s=timeout_s)
            sources.append({"label": "zebbern/no-cost-ai README", "url": CATALOG_README_URL, "kind": "readme"})
            entries.extend(self.parse_markdown_catalog(readme_markdown, source=CATALOG_README_URL))
        except Exception as exc:
            warnings.append(f"Unable to refresh no-cost-ai README: {exc}")

        merged = self.merge_entries(entries)
        payload = {
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "entries": merged,
            "sources": sources,
            "warnings": warnings,
        }
        if merged:
            self.save_cache(payload)
            return payload
        cached = self.load_cache()
        cached["warnings"] = list(dict.fromkeys(list(cached.get("warnings", [])) + warnings))
        return cached

    def parse_markdown_catalog(self, markdown: str, source: str = "") -> list[dict]:
        entries = []
        current_category = "chat"
        for raw_line in str(markdown or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
                current_category = _normalize_category(heading)
                continue
            if "[" not in line or "](" not in line:
                continue
            for name, link in re.findall(r"\[([^\]]+)\]\((https?://[^)]+)\)", line):
                note = line
                entry = ProviderCatalogEntry(
                    name=name,
                    category=current_category,
                    link=link,
                    signup_required=_infer_signup_required(note),
                    limit_note=_extract_limit_note(note),
                    supports_api=_infer_supports_api(note, link=link),
                    api_style=_infer_api_style(note),
                    models=_extract_models(note),
                    source=source,
                    notes=note[:260],
                ).normalized()
                entries.append(entry)
        return entries

    def parse_site_html(self, html: str, source: str = "") -> list[dict]:
        entries = []
        pattern = re.compile(
            r"<a[^>]+href=[\"'](?P<link>https?://[^\"']+)[\"'][^>]*>(?P<body>.*?)</a>",
            flags=re.IGNORECASE | re.DOTALL,
        )
        for match in pattern.finditer(str(html or "")):
            link = str(match.group("link") or "").strip()
            body = re.sub(r"<[^>]+>", " ", str(match.group("body") or ""))
            body = " ".join(body.split())
            if not body:
                continue
            name = body.split("  ")[0].strip() or body[:80].strip()
            surrounding = html[max(0, match.start() - 220) : match.end() + 220]
            category = _normalize_category(surrounding)
            note = " ".join(re.sub(r"<[^>]+>", " ", surrounding).split())
            entries.append(
                ProviderCatalogEntry(
                    name=name,
                    category=category,
                    link=link,
                    signup_required=_infer_signup_required(note),
                    limit_note=_extract_limit_note(note),
                    supports_api=_infer_supports_api(note, link=link),
                    api_style=_infer_api_style(note),
                    models=_extract_models(note),
                    source=source,
                    notes=note[:260],
                ).normalized()
            )
        return entries

    def merge_entries(self, entries: Iterable[dict]) -> list[dict]:
        merged = {}
        for entry in entries:
            normalized = self._normalize_catalog_entry(entry)
            token = normalized["token"]
            current = merged.get(token)
            if current is None:
                merged[token] = normalized
                continue
            current["signup_required"] = bool(current.get("signup_required") or normalized.get("signup_required"))
            if not current.get("limit_note") and normalized.get("limit_note"):
                current["limit_note"] = normalized["limit_note"]
            current["supports_api"] = bool(current.get("supports_api") or normalized.get("supports_api"))
            if not current.get("api_style") and normalized.get("api_style"):
                current["api_style"] = normalized["api_style"]
            current["models"] = list(dict.fromkeys(list(current.get("models", [])) + list(normalized.get("models", []))))
            current_sources = [value for value in {current.get("source", ""), normalized.get("source", "")} if value]
            current["source"] = " | ".join(current_sources)
            if normalized.get("notes") and normalized["notes"] not in str(current.get("notes", "")):
                current["notes"] = "\n".join(filter(None, [str(current.get("notes", "")).strip(), normalized["notes"]]))
        merged_entries = list(merged.values())
        merged_entries.sort(key=lambda item: (item.get("category", "chat"), item.get("name", "").lower()))
        return merged_entries

    def _fetch_text(self, url: str, timeout_s: float = 20.0) -> str:
        request = Request(url, headers={"User-Agent": "BrowserAI-ProviderHub/1.0"})
        with urlopen(request, timeout=max(5.0, float(timeout_s))) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")

    def _normalize_catalog_entry(self, payload: dict | ProviderCatalogEntry) -> dict:
        if isinstance(payload, ProviderCatalogEntry):
            return payload.normalized()
        return ProviderCatalogEntry(
            name=str((payload or {}).get("name") or ""),
            category=str((payload or {}).get("category") or "chat"),
            link=str((payload or {}).get("link") or ""),
            signup_required=bool((payload or {}).get("signup_required")),
            limit_note=str((payload or {}).get("limit_note") or ""),
            supports_api=bool((payload or {}).get("supports_api")),
            api_style=str((payload or {}).get("api_style") or ""),
            models=list((payload or {}).get("models") or []),
            source=str((payload or {}).get("source") or ""),
            notes=str((payload or {}).get("notes") or ""),
        ).normalized()

    def _normalize_profile(self, payload: dict | ProviderEndpointProfile) -> dict:
        if isinstance(payload, ProviderEndpointProfile):
            return payload.normalized()
        return ProviderEndpointProfile(
            label=str((payload or {}).get("label") or ""),
            base_url=str((payload or {}).get("base_url") or ""),
            api_key_env_var=str((payload or {}).get("api_key_env_var") or ""),
            api_style=str((payload or {}).get("api_style") or "openai_chat"),
            models=list((payload or {}).get("models") or []),
            enabled=bool((payload or {}).get("enabled")),
            notes=str((payload or {}).get("notes") or ""),
            last_status=str((payload or {}).get("last_status") or ""),
            last_latency_ms=float((payload or {}).get("last_latency_ms", 0.0) or 0.0),
        ).normalized()


class ProviderClient:
    def __init__(self, timeout_s: float = 30.0):
        self.timeout_s = max(5.0, float(timeout_s))

    def run_prompt(self, profile: dict, prompt: str, attachments=None) -> dict:
        validation = validate_endpoint_profile_config(profile)
        if not validation.get("ok"):
            return {"ok": False, "error": redact_sensitive_text(str(validation.get("error") or "Invalid provider profile."))}
        normalized = ProviderEndpointProfile(
            label=str((profile or {}).get("label") or ""),
            base_url=str(validation.get("normalized_base_url") or (profile or {}).get("base_url") or ""),
            api_key_env_var=str(validation.get("normalized_api_key_env_var") or (profile or {}).get("api_key_env_var") or ""),
            api_style=str((profile or {}).get("api_style") or "openai_chat"),
            models=list((profile or {}).get("models") or []),
            enabled=bool((profile or {}).get("enabled")),
            notes=str((profile or {}).get("notes") or ""),
        ).normalized()
        if not normalized.get("base_url"):
            return {"ok": False, "error": "Provider base URL is empty."}
        if not str(prompt or "").strip():
            return {"ok": False, "error": "Prompt is empty."}
        api_key = ""
        api_key_env_var = normalized.get("api_key_env_var", "")
        if api_key_env_var:
            api_key = os.environ.get(api_key_env_var, "")
            if not api_key:
                return {"ok": False, "error": f"Environment variable {api_key_env_var} is not set."}
        started_at = time.perf_counter()
        try:
            if normalized["api_style"] == "openai_responses":
                result = self._post_json(
                    urljoin(normalized["base_url"].rstrip("/") + "/", "v1/responses"),
                    {
                        "model": (normalized.get("models") or ["gpt-4.1-mini"])[0],
                        "input": str(prompt).strip(),
                    },
                    api_key=api_key,
                )
                output_text = self._extract_responses_text(result)
            elif normalized["api_style"] == "ollama_chat":
                result = self._post_json(
                    urljoin(normalized["base_url"].rstrip("/") + "/", "api/chat"),
                    {
                        "model": (normalized.get("models") or ["llama3.1"])[0],
                        "messages": [{"role": "user", "content": str(prompt).strip()}],
                        "stream": False,
                    },
                    api_key=api_key,
                )
                output_text = str((((result or {}).get("message") or {}).get("content")) or "").strip()
            elif normalized["api_style"] == "documented_api":
                result = self._post_json(
                    normalized["base_url"],
                    {"prompt": str(prompt).strip(), "attachments": list(attachments or [])},
                    api_key=api_key,
                )
                output_text = json.dumps(result, indent=2, ensure_ascii=True)
            else:
                result = self._post_json(
                    urljoin(normalized["base_url"].rstrip("/") + "/", "v1/chat/completions"),
                    {
                        "model": (normalized.get("models") or ["gpt-4.1-mini"])[0],
                        "messages": [{"role": "user", "content": str(prompt).strip()}],
                    },
                    api_key=api_key,
                )
                output_text = self._extract_chat_text(result)
        except Exception as exc:
            return {
                "ok": False,
                "error": redact_sensitive_text(str(exc)),
                "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
            }
        return {
            "ok": True,
            "output_text": output_text,
            "raw": redact_sensitive_payload(result),
            "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
        }

    def check_health(self, profile: dict) -> dict:
        validation = validate_endpoint_profile_config(profile)
        if not validation.get("ok"):
            return {"ok": False, "status": redact_sensitive_text(str(validation.get("error") or "Invalid provider profile.")), "latency_ms": 0.0}
        normalized = ProviderEndpointProfile(
            label=str((profile or {}).get("label") or ""),
            base_url=str(validation.get("normalized_base_url") or (profile or {}).get("base_url") or ""),
            api_key_env_var=str(validation.get("normalized_api_key_env_var") or (profile or {}).get("api_key_env_var") or ""),
            api_style=str((profile or {}).get("api_style") or "openai_chat"),
            models=list((profile or {}).get("models") or []),
            enabled=bool((profile or {}).get("enabled")),
            notes=str((profile or {}).get("notes") or ""),
        ).normalized()
        if not normalized.get("base_url"):
            return {"ok": False, "status": "Missing base URL", "latency_ms": 0.0}
        started_at = time.perf_counter()
        try:
            request = Request(normalized["base_url"], headers={"User-Agent": "BrowserAI-ProviderHub/1.0"})
            with urlopen(request, timeout=self.timeout_s) as response:
                status_code = int(getattr(response, "status", 200) or 200)
        except (HTTPError, URLError) as exc:
            return {
                "ok": False,
                "status": redact_sensitive_text(str(exc)),
                "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
            }
        return {
            "ok": True,
            "status": f"HTTP {status_code}",
            "latency_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
        }

    def _post_json(self, url: str, payload: dict, api_key: str = "") -> dict:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "BrowserAI-ProviderHub/1.0",
        }
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=self.timeout_s) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset, errors="replace"))

    def _extract_chat_text(self, payload: dict) -> str:
        choices = list((payload or {}).get("choices") or [])
        if not choices:
            return json.dumps(payload, indent=2, ensure_ascii=True)
        message = dict((choices[0] or {}).get("message") or {})
        return str(message.get("content") or "").strip()

    def _extract_responses_text(self, payload: dict) -> str:
        output = list((payload or {}).get("output") or [])
        parts = []
        for item in output:
            for content in list((item or {}).get("content") or []):
                text = str((content or {}).get("text") or "").strip()
                if text:
                    parts.append(text)
        if parts:
            return "\n".join(parts)
        return str((payload or {}).get("output_text") or "").strip() or json.dumps(payload, indent=2, ensure_ascii=True)
