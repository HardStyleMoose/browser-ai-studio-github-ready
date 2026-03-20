from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from core.security_utils import normalize_env_var_name, redact_sensitive_text


PINNED_N8N_VERSION = "2.12.3"


def _safe_json_write(path: Path, payload: dict | list):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=True)
    os.replace(temp_path, path)


def _startupinfo():
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return {"startupinfo": startupinfo, "creationflags": creationflags}


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=8.0,
                check=False,
                **_startupinfo(),
            )
        except Exception:
            return False
        stdout = str(result.stdout or "").lower()
        return result.returncode == 0 and "no tasks are running" not in stdout and str(pid) in stdout
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


@dataclass(slots=True)
class N8nWorkflowTemplate:
    key: str
    name: str
    description: str
    payload: dict

    def normalized(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class N8nRunSummary:
    workflow_id: str
    workflow_name: str
    status: str
    started_at: str
    stopped_at: str = ""
    duration_ms: float = 0.0

    def normalized(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class N8nWebhookBinding:
    key: str
    workflow_id: str
    endpoint: str
    description: str = ""

    def normalized(self) -> dict:
        return asdict(self)


class N8nSidecarManager:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root)
        self.legacy_data_root = self.project_root / "data" / "n8n_sidecar"
        self.data_root = self.project_root / "data" / "n8n_runtime"
        self.workflow_template_path = self.data_root / "workflow_templates.json"
        self.webhook_binding_path = self.data_root / "webhook_bindings.json"
        self.runtime_state_path = self.data_root / "runtime_state.json"
        self.log_path = self.data_root / "n8n_runtime.log"
        self.mode = "node_managed_local"
        self.port = 5678
        self.editor_url = "http://localhost:5678"
        self.install_dir = str(self.data_root / "node_runtime")
        self.data_dir = str(self.data_root / "user_data")
        self.auto_start = False
        self.editor_mode = "embedded"
        self.open_editor_externally = False
        self.last_template = "provider_summary"
        self.last_installed_version = ""
        self.api_key_env_var = "N8N_API_KEY"
        self._ensure_defaults()

    def _canonical_editor_url(self, port: int | None = None) -> str:
        safe_port = max(1024, min(65535, int(port or self.port or 5678)))
        return f"http://localhost:{safe_port}"

    def _ensure_defaults(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        self._migrate_legacy_data()
        if not self.workflow_template_path.exists():
            self.save_templates(self.default_templates())
        if not self.webhook_binding_path.exists():
            _safe_json_write(self.webhook_binding_path, {"bindings": []})

    def _migrate_legacy_data(self):
        legacy_templates = self.legacy_data_root / "workflow_templates.json"
        legacy_bindings = self.legacy_data_root / "webhook_bindings.json"
        if legacy_templates.exists() and not self.workflow_template_path.exists():
            shutil.copy2(legacy_templates, self.workflow_template_path)
        if legacy_bindings.exists() and not self.webhook_binding_path.exists():
            shutil.copy2(legacy_bindings, self.webhook_binding_path)

    def apply_settings(self, payload: dict | None):
        payload = dict(payload or {})
        mode = str(payload.get("mode") or "node_managed_local").strip().lower()
        if mode == "docker_sidecar":
            mode = "node_managed_local"
        self.mode = mode or "node_managed_local"
        self.port = max(1024, min(65535, int(payload.get("port", 5678) or 5678)))
        self.editor_url = self._canonical_editor_url(self.port)
        install_dir = payload.get("install_dir") or payload.get("runtime_dir") or (self.data_root / "node_runtime")
        data_dir = payload.get("data_dir") or payload.get("user_data_dir") or (self.data_root / "user_data")
        if str(data_dir).replace("\\", "/").endswith("n8n_sidecar"):
            data_dir = self.data_root / "user_data"
        self.install_dir = str(install_dir).strip() or str(self.data_root / "node_runtime")
        self.data_dir = str(data_dir).strip() or str(self.data_root / "user_data")
        editor_mode = str(payload.get("editor_mode") or "").strip().lower()
        if editor_mode not in {"embedded", "external"}:
            editor_mode = "external" if bool(payload.get("open_editor_externally", False)) else "embedded"
        self.editor_mode = editor_mode
        self.auto_start = bool(payload.get("auto_start", False))
        self.open_editor_externally = bool(payload.get("open_editor_externally", self.editor_mode == "external"))
        self.last_template = str(payload.get("last_template") or "provider_summary").strip() or "provider_summary"
        self.last_installed_version = str(payload.get("last_installed_version") or "").strip()
        self.api_key_env_var = normalize_env_var_name(str(payload.get("api_key_env_var") or "N8N_API_KEY")) or "N8N_API_KEY"

    def collect_state(self) -> dict:
        return {
            "mode": self.mode,
            "port": self.port,
            "editor_url": self.editor_url,
            "install_dir": self.install_dir,
            "data_dir": self.data_dir,
            "auto_start": self.auto_start,
            "editor_mode": self.editor_mode,
            "open_editor_externally": self.editor_mode == "external",
            "last_template": self.last_template,
            "last_installed_version": self.installed_version() or self.last_installed_version,
            "api_key_env_var": self.api_key_env_var,
        }

    def _read_runtime_state(self) -> dict:
        try:
            with open(self.runtime_state_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_runtime_state(self, payload: dict):
        _safe_json_write(self.runtime_state_path, payload)

    def _clear_runtime_state(self):
        try:
            self.runtime_state_path.unlink()
        except FileNotFoundError:
            pass
        except Exception:
            _safe_json_write(self.runtime_state_path, {})

    def _find_node_path(self) -> str:
        return str(shutil.which("node") or "").strip()

    def _find_npm_path(self) -> str:
        return str(shutil.which("npm.cmd") or shutil.which("npm") or "").strip()

    def _run_command(
        self,
        command: list[str],
        cwd: str | Path | None = None,
        timeout_s: float = 25.0,
        env: dict | None = None,
    ) -> dict:
        try:
            result = subprocess.run(
                command,
                cwd=str(cwd) if cwd is not None else None,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                check=False,
                **_startupinfo(),
            )
        except Exception as exc:
            return {"ok": False, "stdout": "", "stderr": str(exc), "returncode": -1}
        return {
            "ok": result.returncode == 0,
            "stdout": str(result.stdout or "").strip(),
            "stderr": str(result.stderr or "").strip(),
            "returncode": result.returncode,
        }

    def node_available(self) -> dict:
        node_path = self._find_node_path()
        if not node_path:
            return {"available": False, "message": "Node.js is not installed or not on PATH."}
        result = self._run_command([node_path, "--version"], timeout_s=10.0)
        if not result.get("ok"):
            message = result.get("stderr") or result.get("stdout") or "Node.js check failed."
            return {"available": False, "message": message}
        return {"available": True, "message": f"Node.js {result.get('stdout', '').strip()}", "node_path": node_path}

    def npm_available(self) -> dict:
        npm_path = self._find_npm_path()
        if not npm_path:
            return {"available": False, "message": "npm is not installed or not on PATH."}
        result = self._run_command([npm_path, "--version"], timeout_s=10.0)
        if not result.get("ok"):
            message = result.get("stderr") or result.get("stdout") or "npm check failed."
            return {"available": False, "message": message}
        return {"available": True, "message": f"npm {result.get('stdout', '').strip()}", "npm_path": npm_path}

    def _entrypoint_path(self) -> Path:
        return Path(self.install_dir) / "node_modules" / "n8n" / "bin" / "n8n"

    def installed_version(self) -> str:
        package_json = Path(self.install_dir) / "node_modules" / "n8n" / "package.json"
        if not package_json.exists():
            return ""
        try:
            with open(package_json, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return ""
        return str(payload.get("version") or "").strip()

    def install_status(self) -> dict:
        node_info = self.node_available()
        npm_info = self.npm_available()
        installed_version = self.installed_version()
        entrypoint = self._entrypoint_path()
        install_dir = Path(self.install_dir)
        return {
            "mode": self.mode,
            "node_available": bool(node_info.get("available")),
            "node_message": node_info.get("message", ""),
            "npm_available": bool(npm_info.get("available")),
            "npm_message": npm_info.get("message", ""),
            "installed": bool(installed_version and entrypoint.exists()),
            "installed_version": installed_version,
            "install_dir": str(install_dir),
            "data_dir": str(Path(self.data_dir)),
            "entrypoint": str(entrypoint),
        }

    def _ensure_local_runtime_package(self):
        install_dir = Path(self.install_dir)
        install_dir.mkdir(parents=True, exist_ok=True)
        package_json = install_dir / "package.json"
        if package_json.exists():
            return
        _safe_json_write(
            package_json,
            {
                "name": "browerai-studio-n8n-runtime",
                "private": True,
                "description": "Managed local n8n runtime for BrowerAI Studio Labs",
            },
        )

    def install(self, update: bool = False) -> dict:
        node_info = self.node_available()
        if not node_info.get("available"):
            return {"ok": False, "message": node_info.get("message", "Node.js unavailable")}
        npm_info = self.npm_available()
        if not npm_info.get("available"):
            return {"ok": False, "message": npm_info.get("message", "npm unavailable")}
        if not update and self.install_status().get("installed"):
            version = self.installed_version()
            return {"ok": True, "message": f"n8n is already installed ({version or 'unknown version'}).", "installed_version": version}
        self._ensure_local_runtime_package()
        install_dir = Path(self.install_dir)
        command = [
            str(npm_info["npm_path"]),
            "install",
            "--no-audit",
            "--no-fund",
            "--loglevel=error",
            f"n8n@{PINNED_N8N_VERSION}",
        ]
        result = self._run_command(command, cwd=install_dir, timeout_s=600.0)
        version = self.installed_version()
        if version and not result.get("ok"):
            self.last_installed_version = version
            message = redact_sensitive_text(result.get("stderr") or result.get("stdout") or f"Installed n8n {version}")
            return {
                "ok": True,
                "message": f"{message} (runtime detected as installed)",
                "installed_version": version,
            }
        if not result.get("ok") or not version:
            message = redact_sensitive_text(result.get("stderr") or result.get("stdout") or "n8n install failed.")
            return {"ok": False, "message": message, "installed_version": version}
        self.last_installed_version = version
        return {
            "ok": True,
            "message": f"Installed n8n {version}",
            "installed_version": version,
        }

    def update(self) -> dict:
        return self.install(update=True)

    def _n8n_env(self) -> dict:
        env = dict(os.environ)
        env["N8N_HOST"] = "127.0.0.1"
        env["N8N_PORT"] = str(self.port)
        env["N8N_PROTOCOL"] = "http"
        env["N8N_EDITOR_BASE_URL"] = self._canonical_editor_url(self.port)
        env["N8N_USER_FOLDER"] = str(Path(self.data_dir))
        return env

    def process_status(self) -> dict:
        install_info = self.install_status()
        state = self._read_runtime_state()
        pid = int(state.get("pid") or 0)
        pid_alive = _process_is_alive(pid)
        status = {
            "mode": self.mode,
            "node_available": install_info.get("node_available", False),
            "node_message": install_info.get("node_message", ""),
            "npm_available": install_info.get("npm_available", False),
            "npm_message": install_info.get("npm_message", ""),
            "installed": install_info.get("installed", False),
            "installed_version": install_info.get("installed_version", ""),
            "install_dir": install_info.get("install_dir", ""),
            "data_dir": install_info.get("data_dir", ""),
            "editor_url": self.editor_url,
            "port": self.port,
            "pid": pid if pid_alive else 0,
            "process_running": pid_alive,
            "message": "",
            "health": "unknown",
            "health_message": "",
            "editor_mode": self.editor_mode,
        }
        if not install_info.get("node_available"):
            status["message"] = install_info.get("node_message", "")
            return status
        if not install_info.get("installed"):
            status["message"] = "n8n is not installed yet."
            return status
        if not pid_alive and pid:
            self._clear_runtime_state()
        status["message"] = "n8n runtime is running on local loopback." if pid_alive else "n8n runtime is installed but stopped."
        return status

    def health_check(self) -> dict:
        status = self.process_status()
        if not status.get("process_running"):
            status["health_message"] = status.get("message", "n8n is not running.")
            return status
        endpoints = [
            urljoin(self.editor_url.rstrip("/") + "/", "healthz"),
            urljoin(self.editor_url.rstrip("/") + "/", "healthz/readiness"),
            self.editor_url,
        ]
        for endpoint in endpoints:
            try:
                request = Request(endpoint, headers={"User-Agent": "BrowerAI-Studio-Labs/1.0"})
                started = time.perf_counter()
                with urlopen(request, timeout=5.0) as response:
                    _ = response.read(256)
                    latency_ms = (time.perf_counter() - started) * 1000.0
                status["health"] = "ready"
                status["health_message"] = f"HTTP ready at {endpoint}"
                status["latency_ms"] = round(latency_ms, 1)
                return status
            except URLError as exc:
                status["health_message"] = f"Health probe failed: {redact_sensitive_text(str(exc))}"
            except Exception as exc:
                status["health_message"] = f"Health probe failed: {redact_sensitive_text(str(exc))}"
        status["health"] = "starting"
        return status

    def _wait_for_health(self, timeout_s: float = 30.0) -> dict:
        deadline = time.time() + timeout_s
        last = self.health_check()
        while time.time() < deadline:
            if last.get("health") == "ready":
                return last
            time.sleep(1.0)
            last = self.health_check()
        return last

    def start(self, install_if_missing: bool = True) -> dict:
        status = self.process_status()
        if not status.get("node_available"):
            return status
        if status.get("process_running"):
            status["message"] = "n8n runtime is already running."
            return status
        if not status.get("installed") and install_if_missing:
            install_result = self.install(update=False)
            if not install_result.get("ok"):
                return {
                    **status,
                    "message": install_result.get("message", "Unable to install n8n."),
                    "installed_version": install_result.get("installed_version", ""),
                }
        status = self.process_status()
        if not status.get("installed"):
            status["message"] = "n8n must be installed before it can be started."
            return status
        entrypoint = self._entrypoint_path()
        node_path = self._find_node_path()
        if not entrypoint.exists() or not node_path:
            status["message"] = "The local n8n runtime entrypoint was not found."
            return status
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            log_handle = open(self.log_path, "a", encoding="utf-8")
        except Exception:
            log_handle = open(os.devnull, "w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                [node_path, str(entrypoint), "start"],
                cwd=str(Path(self.install_dir)),
                env=self._n8n_env(),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                **_startupinfo(),
            )
        finally:
            log_handle.close()
        version = self.installed_version()
        self.last_installed_version = version
        self._write_runtime_state(
            {
                "pid": int(process.pid),
                "started_at": time.time(),
                "command": [node_path, str(entrypoint), "start"],
                "editor_url": self.editor_url,
                "install_dir": self.install_dir,
                "data_dir": self.data_dir,
                "installed_version": version,
                "log_path": str(self.log_path),
            }
        )
        status = self._wait_for_health(timeout_s=35.0)
        if not status.get("process_running"):
            status["message"] = "n8n process exited before it became ready."
        elif status.get("health") == "ready":
            status["message"] = f"n8n runtime started on {self.editor_url}"
        return status

    def _terminate_pid(self, pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":
            result = self._run_command(["taskkill", "/PID", str(pid), "/T", "/F"], timeout_s=18.0)
            return bool(result.get("ok"))
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return False
        return True

    def stop(self) -> dict:
        status = self.process_status()
        pid = int(status.get("pid") or 0)
        if not pid:
            status["message"] = "n8n runtime is not running."
            return status
        stopped = self._terminate_pid(pid)
        deadline = time.time() + 10.0
        while time.time() < deadline and _process_is_alive(pid):
            time.sleep(0.4)
        if not _process_is_alive(pid):
            self._clear_runtime_state()
        status = self.process_status()
        status["message"] = "n8n runtime stopped." if stopped else "Failed to stop the n8n runtime cleanly."
        return status

    def restart(self) -> dict:
        if self.process_status().get("process_running"):
            self.stop()
        return self.start(install_if_missing=True)

    def open_editor(self) -> dict:
        try:
            opened = webbrowser.open(self.editor_url)
        except Exception as exc:
            return {"ok": False, "message": f"Unable to open n8n editor: {redact_sensitive_text(str(exc))}"}
        return {"ok": bool(opened), "message": f"Opened {self.editor_url}"}

    def default_templates(self) -> list[dict]:
        templates = [
            N8nWorkflowTemplate(
                key="provider_summary",
                name="Provider Summary",
                description="Run provider-prompt summarization jobs for Provider Hub analysis queues.",
                payload={
                    "name": "Provider Summary",
                    "nodes": [],
                    "connections": {},
                    "meta": {"browserai_template": "provider_summary"},
                },
            ),
            N8nWorkflowTemplate(
                key="replay_batch",
                name="Replay Batch Analysis",
                description="Batch replay processing and Guide Coach export orchestration.",
                payload={
                    "name": "Replay Batch Analysis",
                    "nodes": [],
                    "connections": {},
                    "meta": {"browserai_template": "replay_batch"},
                },
            ),
            N8nWorkflowTemplate(
                key="evidence_export",
                name="Evidence Export",
                description="Bundle DOM evidence, diagnostics exports, and worker summaries.",
                payload={
                    "name": "Evidence Export",
                    "nodes": [],
                    "connections": {},
                    "meta": {"browserai_template": "evidence_export"},
                },
            ),
            N8nWorkflowTemplate(
                key="catalog_refresh",
                name="Catalog Refresh",
                description="Refresh NoCostAI catalog and provider health notes on a schedule.",
                payload={
                    "name": "Catalog Refresh",
                    "nodes": [],
                    "connections": {},
                    "meta": {"browserai_template": "catalog_refresh"},
                },
            ),
        ]
        return [template.normalized() for template in templates]

    def load_templates(self) -> list[dict]:
        if not self.workflow_template_path.exists():
            return self.default_templates()
        try:
            with open(self.workflow_template_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return self.default_templates()
        if isinstance(payload, dict):
            payload = payload.get("templates", [])
        rows = list(payload or [])
        return rows or self.default_templates()

    def save_templates(self, templates: list[dict]):
        _safe_json_write(self.workflow_template_path, {"templates": list(templates or [])})

    def export_template(self, template_key: str, destination: str | Path) -> dict:
        template_key = str(template_key or "").strip()
        templates = self.load_templates()
        selected = next((row for row in templates if str(row.get("key") or "") == template_key), None)
        if selected is None:
            raise FileNotFoundError(f"Unknown n8n template: {template_key}")
        destination = Path(destination)
        _safe_json_write(destination, selected)
        return dict(selected)

    def import_template(self, source: str | Path) -> dict:
        path = Path(source)
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        template = dict(payload or {})
        key = str(template.get("key") or path.stem).strip() or path.stem
        template["key"] = key
        templates = [row for row in self.load_templates() if str(row.get("key") or "") != key]
        templates.append(template)
        self.save_templates(templates)
        return template

    def load_bindings(self) -> list[dict]:
        try:
            with open(self.webhook_binding_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return []
        rows = payload.get("bindings", []) if isinstance(payload, dict) else []
        return [dict(row or {}) for row in rows]

    def save_bindings(self, bindings: list[dict]):
        _safe_json_write(self.webhook_binding_path, {"bindings": list(bindings or [])})

    def execution_summaries(self, limit: int = 8) -> list[dict]:
        api_key = os.environ.get(self.api_key_env_var or "N8N_API_KEY", "").strip()
        if not api_key:
            return []
        endpoint = urljoin(self.editor_url.rstrip("/") + "/", f"api/v1/executions?limit={max(1, int(limit))}")
        request = Request(endpoint, headers={"X-N8N-API-KEY": api_key, "User-Agent": "BrowerAI-Studio-Labs/1.0"})
        try:
            with urlopen(request, timeout=8.0) as response:
                payload = json.load(response)
        except Exception:
            return []
        rows = list(payload.get("data", []) or []) if isinstance(payload, dict) else list(payload or [])
        summaries = []
        for row in rows[:limit]:
            summary = N8nRunSummary(
                workflow_id=str(row.get("workflowId") or ""),
                workflow_name=str(row.get("workflowName") or row.get("id") or "Workflow"),
                status=str(row.get("status") or row.get("finished") or "unknown"),
                started_at=str(row.get("startedAt") or ""),
                stopped_at=str(row.get("stoppedAt") or ""),
                duration_ms=float(row.get("duration") or 0.0),
            )
            summaries.append(summary.normalized())
        return summaries
