from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.config_manager import ConfigManager
from distributed.browser_prewarm_pool import BrowserPrewarmPool
from distributed.cluster_worker_runtime import ClusterWorkerConfig, ClusterWorkerRuntime


def _safe_json_write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    os.replace(temp_path, path)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return float(ordered[index])


def build_runtime_config(config: ConfigManager, target_fps: int) -> ClusterWorkerConfig:
    training = config.get("training", {}) or {}
    cluster = config.get("cluster", {}) or {}
    region = dict(training.get("region", {}) or {})
    return ClusterWorkerConfig(
        worker_id="worker-probe",
        mode=str(training.get("game_mode", "browser") or "browser"),
        browser_url=str(training.get("browser_url", "https://lom.joynetgame.com") or "https://lom.joynetgame.com"),
        desktop_exe=str(training.get("desktop_exe", "") or ""),
        desktop_window_title=str(training.get("desktop_window_title", "") or ""),
        capture_region={
            "left": int(region.get("x", 0) or 0),
            "top": int(region.get("y", 0) or 0),
            "width": int(region.get("width", 1280) or 1280),
            "height": int(region.get("height", 720) or 720),
        },
        behavior_graph={},
        model_name="ppo_model",
        memory_limit_gb=float(cluster.get("worker_memory_gb", 4.0) or 4.0),
        cpu_limit_percent=float(cluster.get("worker_cpu_limit_percent", 200) or 200),
        target_fps=target_fps,
        gpu_acceleration_enabled=bool(cluster.get("gpu_acceleration_enabled", True)),
        mouse_enabled=True,
        keyboard_enabled=True,
        antiban_config={},
        quick_mode=False,
        watch_reward_ads=bool(cluster.get("watch_reward_ads", False)),
        auto_learning_enabled=bool(cluster.get("auto_learning", True)),
        learning_store_dir=str(PROJECT_ROOT / "data" / "worker_learning"),
        browser_dom_drive_mode=str(cluster.get("browser_dom_drive_mode", "legacy") or "legacy"),
        dom_confirmation_required=bool(cluster.get("dom_confirmation_required", True)),
        dom_live_cooldown_ms=int(cluster.get("dom_live_cooldown_ms", 850) or 850),
        dom_live_max_repeat_attempts=int(cluster.get("dom_live_max_repeat_attempts", 3) or 3),
        dom_evidence_weight=float(cluster.get("dom_evidence_weight", 1.3) or 1.3),
        browser_prewarm_enabled=bool(cluster.get("browser_prewarm_enabled", True)),
        preview_target_fps=int(cluster.get("preview_target_fps", 10) or 10),
        control_preview_target_fps=int(cluster.get("control_preview_target_fps", 15) or 15),
    )


def run_probe(target_fps: int, sample_seconds: int, startup_timeout: int) -> dict:
    baseline_ready_seconds = 26.0
    config = ConfigManager()
    base_runtime_config = build_runtime_config(config, target_fps)
    runtime = None
    pool = BrowserPrewarmPool(PROJECT_ROOT)
    standby_started_at = time.time()
    standby_ready_at = None
    claim_started_at = None
    ready_at = None
    cold_start_fallback_seconds = 0.0
    try:
        pool.arm(base_runtime_config)
        while time.time() - standby_started_at < startup_timeout:
            pool_snapshot = pool.snapshot()
            if str(pool_snapshot.get("status", "")).strip().lower() == "ready":
                standby_ready_at = time.time()
                break
            time.sleep(1.0)
        if standby_ready_at is not None:
            claim_started_at = time.time()
            runtime = pool.claim(base_runtime_config)
        if runtime is None:
            claim_started_at = time.time()
            runtime = ClusterWorkerRuntime(base_runtime_config)
            runtime.start()
        while time.time() - claim_started_at < startup_timeout:
            snapshot = runtime.snapshot()
            if str(snapshot.get("status", "")).lower() == "running":
                ready_at = time.time()
                break
            time.sleep(1.0)
        if ready_at is None:
            snapshot = runtime.snapshot() if runtime is not None else {}
            return {
                "target_fps": target_fps,
                "startup_seconds": round(time.time() - claim_started_at, 2) if claim_started_at is not None else 0.0,
                "standby_ready_seconds": round(standby_ready_at - standby_started_at, 2) if standby_ready_at is not None else 0.0,
                "claim_to_running_seconds": 0.0,
                "cold_start_fallback_seconds": 0.0,
                "status": snapshot.get("status", "unknown"),
                "capture": snapshot.get("capture", ""),
                "average_fps": 0.0,
                "average_preview_fps": 0.0,
                "p5_fps": 0.0,
                "min_fps": 0.0,
                "longest_below_20_s": 0.0,
                "preview_target_fps": int(getattr(runtime.config, "preview_target_fps", 10) or 10),
                "ready_baseline_seconds": baseline_ready_seconds,
                "recommended_default_fps": 20,
                "passed_for_30": False,
                "message": "Worker did not reach running state before timeout.",
            }

        fps_samples: list[float] = []
        last_capture_token = None
        preview_frame_count = 0
        below_20_run = 0.0
        longest_below_20 = 0.0
        sample_started = time.time()
        last_loop = sample_started
        preview_target_fps = int(getattr(runtime.config, "preview_target_fps", 10) or 10)
        while time.time() - sample_started < sample_seconds:
            payload = runtime.preview_payload(last_capture_token, tier="preview")
            captured_at = payload.get("captured_at")
            if captured_at is not None and captured_at != last_capture_token:
                preview_frame_count += 1
                last_capture_token = captured_at
            fps_value = float(payload.get("fps") or 0.0)
            if fps_value > 0:
                fps_samples.append(fps_value)
            now = time.time()
            delta = max(0.0, now - last_loop)
            if fps_value < 20.0:
                below_20_run += delta
                longest_below_20 = max(longest_below_20, below_20_run)
            else:
                below_20_run = 0.0
            last_loop = now
            time.sleep(0.05)

        snapshot = runtime.snapshot()
        average_fps = statistics.mean(fps_samples) if fps_samples else 0.0
        average_preview_fps = preview_frame_count / max(1.0, time.time() - sample_started)
        p5_fps = _percentile(fps_samples, 5.0)
        min_fps = min(fps_samples) if fps_samples else 0.0
        ready_seconds = round(ready_at - claim_started_at, 2) if claim_started_at is not None else 0.0
        ready_improved = ready_seconds <= 20.0 or ready_seconds <= (baseline_ready_seconds * 0.85)
        runtime.stop()
        runtime.join(timeout=12.0)
        runtime = ClusterWorkerRuntime(replace(base_runtime_config, browser_prewarm_enabled=False))
        cold_started_at = time.time()
        runtime.start()
        cold_ready_at = None
        while time.time() - cold_started_at < startup_timeout:
            cold_snapshot = runtime.snapshot()
            if str(cold_snapshot.get("status", "")).lower() == "running":
                cold_ready_at = time.time()
                break
            time.sleep(1.0)
        cold_start_fallback_seconds = round((cold_ready_at or time.time()) - cold_started_at, 2)
        passed_for_30 = (
            average_fps >= 28.0
            and p5_fps >= 22.0
            and longest_below_20 <= 10.0
            and average_preview_fps >= 9.0
            and ready_improved
        )
        return {
            "target_fps": target_fps,
            "startup_seconds": ready_seconds,
            "standby_ready_seconds": round(standby_ready_at - standby_started_at, 2) if standby_ready_at is not None else 0.0,
            "claim_to_running_seconds": ready_seconds,
            "cold_start_fallback_seconds": cold_start_fallback_seconds,
            "status": snapshot.get("status", "unknown"),
            "capture": snapshot.get("capture", ""),
            "average_fps": round(average_fps, 2),
            "average_preview_fps": round(average_preview_fps, 2),
            "p5_fps": round(p5_fps, 2),
            "min_fps": round(min_fps, 2),
            "longest_below_20_s": round(longest_below_20, 2),
            "preview_target_fps": preview_target_fps,
            "ready_baseline_seconds": baseline_ready_seconds,
            "recommended_default_fps": 30 if passed_for_30 else 20,
            "passed_for_30": passed_for_30,
            "message": (
                "Probe complete. 30 FPS is viable."
                if passed_for_30
                else "Probe complete. Keep the shipped default at 20 FPS and leave 30 FPS as an opt-in target."
            ),
        }
    finally:
        pool.disarm("Probe finished.")
        if runtime is not None:
            runtime.stop()
            runtime.join(timeout=12.0)


def main():
    parser = argparse.ArgumentParser(description="Run a live browser worker FPS probe.")
    parser.add_argument("--target-fps", type=int, default=30)
    parser.add_argument("--sample-seconds", type=int, default=90)
    parser.add_argument("--startup-timeout", type=int, default=90)
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / "benchmarks" / "worker_fps_probe.json"),
    )
    args = parser.parse_args()
    result = run_probe(args.target_fps, args.sample_seconds, args.startup_timeout)
    output_path = Path(args.output)
    _safe_json_write(output_path, result)
    print(json.dumps(result, indent=2))
    print(f"Saved probe results to {output_path}")


if __name__ == "__main__":
    main()
