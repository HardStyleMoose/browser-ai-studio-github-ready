from __future__ import annotations

import json
import os
import subprocess
import threading
import time


_CACHE_LOCK = threading.Lock()
_COUNTER_CACHE = {
    "expires_at": 0.0,
    "payload": {
        "available": False,
        "overall_percent": 0.0,
        "per_pid": {},
    },
}
_HOST_CACHE = {
    "expires_at": 0.0,
    "payload": {
        "available": False,
        "name": "GPU unavailable",
        "memory_gb": 0.0,
    },
}
def _powershell_path() -> str:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return os.path.join(windir, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def _hidden_subprocess_kwargs() -> dict:
    kwargs = {}
    if os.name != "nt":
        return kwargs
    creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if creationflags:
        kwargs["creationflags"] = creationflags
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    return kwargs


def _run_powershell_json(script: str, timeout_s: float = 2.5):
    try:
        result = subprocess.run(
            [_powershell_path(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=max(1.0, float(timeout_s)),
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return None
    stdout = (result.stdout or "").strip()
    if not stdout:
        return None
    try:
        return json.loads(stdout)
    except Exception:
        return None


def get_host_gpu_info(ttl_s: float = 120.0) -> dict:
    now = time.time()
    with _CACHE_LOCK:
        if now < _HOST_CACHE["expires_at"]:
            return dict(_HOST_CACHE["payload"])
    payload = {
        "available": False,
        "name": "GPU unavailable",
        "memory_gb": 0.0,
    }
    script = """
$gpu = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
    Select-Object Name, AdapterRAM
if ($null -eq $gpu) {
    '[]'
} else {
    $gpu | ConvertTo-Json -Compress
}
"""
    rows = _run_powershell_json(script, timeout_s=3.0)
    if isinstance(rows, dict):
        rows = [rows]
    if isinstance(rows, list) and rows:
        first = next((row for row in rows if isinstance(row, dict) and str(row.get("Name", "")).strip()), None)
        if first is not None:
            adapter_ram = float(first.get("AdapterRAM") or 0.0)
            payload = {
                "available": True,
                "name": str(first.get("Name") or "Unknown GPU").strip(),
                "memory_gb": round(adapter_ram / (1024.0 ** 3), 1) if adapter_ram > 0 else 0.0,
            }
    with _CACHE_LOCK:
        _HOST_CACHE["expires_at"] = now + max(15.0, float(ttl_s))
        _HOST_CACHE["payload"] = dict(payload)
    return dict(payload)


def sample_gpu_usage(pid_list=None, ttl_s: float = 1.5) -> dict:
    now = time.time()
    with _CACHE_LOCK:
        if now < _COUNTER_CACHE["expires_at"]:
            counter_payload = dict(_COUNTER_CACHE["payload"])
        else:
            counter_payload = None
    if counter_payload is not None:
        tracked_pids = [int(pid) for pid in list(pid_list or []) if pid is not None]
        worker_percent = 0.0
        if tracked_pids:
            worker_percent = min(
                100.0,
                sum(float(counter_payload.get("per_pid", {}).get(pid, 0.0)) for pid in tracked_pids),
            )
        host_info = get_host_gpu_info()
        return {
            "available": bool(counter_payload.get("available")),
            "percent": worker_percent,
            "overall_percent": float(counter_payload.get("overall_percent", 0.0)),
            "host_name": host_info.get("name", "GPU unavailable"),
            "memory_gb": float(host_info.get("memory_gb", 0.0)),
        }
    script = """
$samples = Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty CounterSamples
$overall = 0.0
$perPid = @{}
if ($null -ne $samples) {
    foreach ($sample in $samples) {
        $instance = [string]$sample.InstanceName
        $instanceLower = $instance.ToLowerInvariant()
        if ($instanceLower -notmatch 'engtype_(3d|compute|videodecode|videoencode|videoprocess)') {
            continue
        }
        $value = [double]$sample.CookedValue
        if ($value -lt 0) {
            continue
        }
        $overall += $value
        if ($instanceLower -match 'pid_(\\d+)') {
            $gpuPid = [string]$Matches[1]
            if ($perPid.ContainsKey($gpuPid)) {
                $perPid[$gpuPid] += $value
            } else {
                $perPid[$gpuPid] = $value
            }
        }
    }
}
[PSCustomObject]@{
    Overall = [Math]::Min(100.0, $overall)
    PerPid = $perPid
} | ConvertTo-Json -Compress -Depth 4
"""
    rows = _run_powershell_json(script, timeout_s=2.5)
    overall = 0.0
    per_pid = {}
    if isinstance(rows, dict):
        overall = max(0.0, float(rows.get("Overall") or 0.0))
        raw_per_pid = rows.get("PerPid") or {}
        if isinstance(raw_per_pid, dict):
            for pid, value in raw_per_pid.items():
                try:
                    per_pid[int(pid)] = max(0.0, float(value or 0.0))
                except (TypeError, ValueError):
                    continue
    counter_payload = {
        "available": True,
        "overall_percent": min(100.0, overall),
        "per_pid": {int(pid): min(100.0, float(value)) for pid, value in per_pid.items()},
    }
    with _CACHE_LOCK:
        _COUNTER_CACHE["expires_at"] = now + max(0.8, float(ttl_s))
        _COUNTER_CACHE["payload"] = dict(counter_payload)
    tracked_pids = [int(pid) for pid in list(pid_list or []) if pid is not None]
    worker_percent = 0.0
    if tracked_pids:
        worker_percent = min(
            100.0,
            sum(float(counter_payload.get("per_pid", {}).get(pid, 0.0)) for pid in tracked_pids),
        )
    host_info = get_host_gpu_info()
    return {
        "available": bool(counter_payload.get("available")),
        "percent": worker_percent,
        "overall_percent": float(counter_payload.get("overall_percent", 0.0)),
        "host_name": host_info.get("name", "GPU unavailable"),
        "memory_gb": float(host_info.get("memory_gb", 0.0)),
    }
