"""Flexible PPO trainer wrapper with optional recurrent and maskable support."""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np

from ai.envs.game_env import GameEnv

_SB3_IMPORT_STDERR = io.StringIO()
_BASE_PPO = None
_SB3_IMPORT_ERROR = None
_MASKABLE_PPO = None
_RECURRENT_PPO = None
_CONTRIB_IMPORT_ATTEMPTED = False
_CONTRIB_IMPORT_ERROR = None
_METADATA_SUFFIX = ".meta.json"


def _resolve_ppo():
    global _BASE_PPO, _SB3_IMPORT_ERROR
    if _BASE_PPO is not None:
        return _BASE_PPO
    if _SB3_IMPORT_ERROR is not None:
        raise RuntimeError("stable-baselines3 is not installed") from _SB3_IMPORT_ERROR
    try:
        with contextlib.redirect_stderr(_SB3_IMPORT_STDERR):
            from stable_baselines3 import PPO as sb3_ppo
    except ImportError as exc:  # pragma: no cover - depends on local environment
        _SB3_IMPORT_ERROR = exc
        raise RuntimeError("stable-baselines3 is not installed") from exc
    _BASE_PPO = sb3_ppo
    _sb3_warning = _SB3_IMPORT_STDERR.getvalue().strip()
    if _sb3_warning and "Gym has been unmaintained since 2022" not in _sb3_warning:
        print(_sb3_warning, file=sys.stderr)
    return _BASE_PPO


def _resolve_contrib_algorithms():
    global _MASKABLE_PPO, _RECURRENT_PPO, _CONTRIB_IMPORT_ATTEMPTED, _CONTRIB_IMPORT_ERROR
    if _CONTRIB_IMPORT_ATTEMPTED:
        return _MASKABLE_PPO, _RECURRENT_PPO
    _CONTRIB_IMPORT_ATTEMPTED = True
    try:
        from sb3_contrib import MaskablePPO as maskable_ppo
        from sb3_contrib import RecurrentPPO as recurrent_ppo
    except ImportError as exc:  # pragma: no cover - optional local dependency
        _CONTRIB_IMPORT_ERROR = exc
        maskable_ppo = None
        recurrent_ppo = None
    _MASKABLE_PPO = maskable_ppo
    _RECURRENT_PPO = recurrent_ppo
    return _MASKABLE_PPO, _RECURRENT_PPO


class PPOTrainer:
    def __init__(
        self,
        env: Optional[GameEnv] = None,
        save_path: str = "models/ppo_model",
        algorithm: str = "auto",
        policy: str = "auto",
        use_action_masking: bool = True,
    ):
        self.env = env
        self.save_path = save_path
        self.algorithm_preference = str(algorithm or "auto").strip().lower()
        self.policy_preference = str(policy or "auto").strip().lower()
        self.use_action_masking = bool(use_action_masking)
        self.model = None
        self._train_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._predict_state = None
        self._episode_start = np.array([True], dtype=bool)
        self.last_backend_name = "PPO"
        self.last_policy_name = "MlpPolicy"
        self.last_checkpoint_path = ""
        self.last_metadata = {}
        self.last_eval_reward: Optional[float] = None
        self.last_train_timesteps = 0
        self.last_status = "idle"
        self.last_note = "Base PPO ready."

    def capabilities(self) -> dict[str, Any]:
        maskable_ppo, recurrent_ppo = _resolve_contrib_algorithms()
        action_mask_ready = self._env_supports_action_masks()
        return {
            "base_ppo": True,
            "maskable_available": maskable_ppo is not None,
            "recurrent_available": recurrent_ppo is not None,
            "action_mask_ready": action_mask_ready,
            "selected_algorithm": self.algorithm_preference,
            "selected_policy": self.policy_preference,
            "action_masking_enabled": bool(self.use_action_masking),
        }

    def configure(
        self,
        *,
        save_path: str | None = None,
        algorithm: str | None = None,
        policy: str | None = None,
        use_action_masking: bool | None = None,
    ):
        previous = (
            self.save_path,
            self.algorithm_preference,
            self.policy_preference,
            self.use_action_masking,
        )
        if save_path is not None:
            self.save_path = str(save_path).strip() or self.save_path
        if algorithm is not None:
            self.algorithm_preference = str(algorithm or "auto").strip().lower() or "auto"
        if policy is not None:
            self.policy_preference = str(policy or "auto").strip().lower() or "auto"
        if use_action_masking is not None:
            self.use_action_masking = bool(use_action_masking)
        current = (
            self.save_path,
            self.algorithm_preference,
            self.policy_preference,
            self.use_action_masking,
        )
        if self.model is not None and previous != current:
            self.model = None
            self._reset_predict_state()
            self.last_status = "reconfigured"
            self.last_note = "Trainer settings changed. Rebuild required on next load/train."

    def short_backend_label(self) -> str:
        return self.last_backend_name

    def summary(self) -> str:
        masking = "masking on" if self.use_action_masking else "masking off"
        return f"{self.last_backend_name} | {self.last_policy_name} | {masking}"

    def capabilities_summary(self) -> str:
        info = self.capabilities()
        parts = [
            "PPO",
            "MaskablePPO ready" if info["maskable_available"] else "MaskablePPO unavailable",
            "RecurrentPPO ready" if info["recurrent_available"] else "RecurrentPPO unavailable",
            "env masks ready" if info["action_mask_ready"] else "env masks unavailable",
        ]
        return ", ".join(parts)

    def checkpoint_summary(self) -> str:
        checkpoint = Path(self.save_path + ".zip")
        metadata = Path(self.save_path + _METADATA_SUFFIX)
        if checkpoint.exists():
            suffix = " + metadata" if metadata.exists() else ""
            return f"Present{suffix}"
        return "Missing"

    def _metadata_path(self, save_path: str | None = None) -> Path:
        base = save_path or self.save_path
        return Path(base + _METADATA_SUFFIX)

    def _build_metadata(self) -> dict[str, Any]:
        return {
            "saved_at": time.time(),
            "backend": self.last_backend_name,
            "policy": self.last_policy_name,
            "algorithm_preference": self.algorithm_preference,
            "policy_preference": self.policy_preference,
            "use_action_masking": bool(self.use_action_masking),
            "last_eval_reward": self.last_eval_reward,
            "last_train_timesteps": int(self.last_train_timesteps),
            "capabilities": self.capabilities(),
            "note": self.last_note,
        }

    def _write_metadata(self, save_path: str | None = None):
        metadata_path = self._metadata_path(save_path)
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._build_metadata()
        metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.last_metadata = payload

    def _read_metadata(self) -> dict[str, Any]:
        metadata_path = self._metadata_path()
        if not metadata_path.exists():
            return {}
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        self.last_metadata = payload
        return payload

    def _env_supports_action_masks(self) -> bool:
        return self.env is not None and callable(getattr(self.env, "action_masks", None))

    def _action_masks(self):
        if not self.use_action_masking or not self._env_supports_action_masks():
            return None
        try:
            masks = self.env.action_masks()
        except Exception:
            return None
        if masks is None:
            return None
        mask_array = np.asarray(masks, dtype=bool).reshape(-1)
        if mask_array.size == 0:
            return None
        if not mask_array.any():
            mask_array[:] = True
        return mask_array

    def _select_backend(self):
        base_ppo = _resolve_ppo()
        maskable_ppo, recurrent_ppo = _resolve_contrib_algorithms()
        preferred = self.algorithm_preference
        wants_recurrent = preferred == "recurrent_ppo" or self.policy_preference == "recurrent"
        wants_masking = bool(self.use_action_masking and self._env_supports_action_masks())

        if preferred == "maskable_ppo":
            if maskable_ppo is not None and wants_masking:
                self.last_note = "Using MaskablePPO with environment-provided action masks."
                return maskable_ppo, "MaskablePPO"
            self.last_note = "MaskablePPO requested but sb3-contrib or env masks are unavailable. Falling back to PPO."
            return base_ppo, "PPO"

        if preferred == "recurrent_ppo":
            if recurrent_ppo is not None:
                self.last_note = "Using RecurrentPPO for sequence-aware training."
                return recurrent_ppo, "RecurrentPPO"
            self.last_note = "RecurrentPPO requested but sb3-contrib is unavailable. Falling back to PPO."
            return base_ppo, "PPO"

        if wants_recurrent and recurrent_ppo is not None:
            self.last_note = "Auto-selected RecurrentPPO because recurrent policy was requested."
            return recurrent_ppo, "RecurrentPPO"
        if wants_masking and maskable_ppo is not None:
            self.last_note = "Auto-selected MaskablePPO because action masks are available."
            return maskable_ppo, "MaskablePPO"
        if wants_recurrent and recurrent_ppo is None:
            self.last_note = "Recurrent policy requested but sb3-contrib is unavailable. Using PPO."
        elif wants_masking and maskable_ppo is None:
            self.last_note = "Action masking requested but sb3-contrib is unavailable. Using PPO."
        else:
            self.last_note = "Using base PPO."
        return base_ppo, "PPO"

    def _select_policy_name(self, backend_name: str) -> str:
        preferred = self.policy_preference
        if backend_name == "RecurrentPPO":
            if preferred == "mlp":
                self.last_note = f"{self.last_note} Recurrent backend requires an LSTM policy."
            return "MlpLstmPolicy"
        return "MlpPolicy"

    def _reset_predict_state(self):
        self._predict_state = None
        self._episode_start = np.array([True], dtype=bool)

    def _model_supports_action_masks(self) -> bool:
        if self.model is None:
            return False
        try:
            signature = inspect.signature(self.model.predict)
        except Exception:
            return False
        return "action_masks" in signature.parameters

    def _create_model(self):
        if self.env is None:
            raise RuntimeError("Environment not set for PPOTrainer")
        backend_cls, backend_name = self._select_backend()
        policy_name = self._select_policy_name(backend_name)
        os.makedirs(os.path.dirname(self.save_path), exist_ok=True)
        self.model = backend_cls(policy_name, self.env, verbose=1)
        self.last_backend_name = backend_name
        self.last_policy_name = policy_name
        self.last_status = "ready"
        self._reset_predict_state()

    def train(self, timesteps: int = 10000):
        if not self.env:
            raise RuntimeError("Environment not set for PPOTrainer")
        if self.model is None:
            self._create_model()

        self._stop_event.clear()
        self.last_status = "training"
        self.last_train_timesteps = int(max(1, timesteps))
        try:
            self.model.learn(
                total_timesteps=self.last_train_timesteps,
                reset_num_timesteps=False,
                callback=self._stop_callback,
            )
            self.save_checkpoint()
            self.last_status = "ready"
        except Exception:
            self.last_status = "error"
            raise

    def _predict_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"deterministic": True}
        masks = self._action_masks()
        if masks is not None and self._model_supports_action_masks():
            kwargs["action_masks"] = masks
        return kwargs

    def predict(self, observation):
        if self.model is None:
            return 0
        obs = np.asarray(observation, dtype=np.float32)
        try:
            if self.last_backend_name == "RecurrentPPO":
                action, self._predict_state = self.model.predict(
                    obs,
                    state=self._predict_state,
                    episode_start=self._episode_start,
                    deterministic=True,
                )
                self._episode_start = np.array([False], dtype=bool)
            else:
                action, _ = self.model.predict(obs, **self._predict_kwargs())
            return int(np.asarray(action).reshape(-1)[0])
        except Exception:
            self._reset_predict_state()
            return 0

    def _stop_callback(self, _locals, _globals):
        return not self._stop_event.is_set()

    def stop(self):
        self._stop_event.set()

    def tune_hyperparameters(self, n_trials=20):
        import optuna

        backend_cls, backend_name = self._select_backend()
        policy_name = self._select_policy_name(backend_name)

        def objective(trial):
            lr = trial.suggest_float("lr", 1e-5, 1e-3, log=True)
            gamma = trial.suggest_float("gamma", 0.9, 0.999)
            clip_range = trial.suggest_float("clip_range", 0.1, 0.4)
            model = backend_cls(
                policy_name,
                self.env,
                learning_rate=lr,
                gamma=gamma,
                clip_range=clip_range,
                verbose=0,
            )
            model.learn(3000)
            return self.evaluate_model(model, episodes=3)

        study = optuna.create_study(direction="maximize")
        study.optimize(objective, n_trials=max(1, int(n_trials)))
        return study.best_params

    def evaluate_model(self, model, episodes: int = 10):
        total_reward = 0.0
        for _ in range(max(1, int(episodes))):
            reset_result = self.env.reset()
            obs = reset_result[0] if isinstance(reset_result, tuple) else reset_result
            done = False
            recurrent_state = None
            episode_start = np.array([True], dtype=bool)
            while not done:
                predict_kwargs = {"deterministic": True}
                if "action_masks" in inspect.signature(model.predict).parameters:
                    masks = self._action_masks()
                    if masks is not None:
                        predict_kwargs["action_masks"] = masks
                if "state" in inspect.signature(model.predict).parameters:
                    action, recurrent_state = model.predict(
                        obs,
                        state=recurrent_state,
                        episode_start=episode_start,
                        **predict_kwargs,
                    )
                    episode_start = np.array([False], dtype=bool)
                else:
                    action, _ = model.predict(obs, **predict_kwargs)
                step_result = self.env.step(action)
                if len(step_result) == 5:
                    obs, reward, terminated, truncated, _ = step_result
                    done = terminated or truncated
                else:
                    obs, reward, done, _ = step_result
                total_reward += float(reward or 0.0)
        return total_reward / float(max(1, int(episodes)))

    def evaluate_current_model(self, episodes: int = 5):
        if self.model is None and not self.load():
            raise RuntimeError("No PPO checkpoint is available to evaluate.")
        self.last_status = "evaluating"
        try:
            self.last_eval_reward = float(self.evaluate_model(self.model, episodes=max(1, int(episodes))))
            self.last_status = "ready"
            return self.last_eval_reward
        except Exception:
            self.last_status = "error"
            raise

    def save_checkpoint(self, save_path: str | None = None):
        if self.model is None:
            raise RuntimeError("No PPO model is currently loaded")
        target = save_path or self.save_path
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        self.model.save(target)
        self.last_checkpoint_path = target
        self._write_metadata(target)
        self.last_status = "ready"
        return target

    def load(self):
        backend_cls, backend_name = self._select_backend()
        metadata = self._read_metadata()
        if metadata:
            backend_hint = str(metadata.get("backend") or "").strip()
            if backend_hint == "MaskablePPO" and _resolve_contrib_algorithms()[0] is not None and self._env_supports_action_masks():
                backend_cls = _resolve_contrib_algorithms()[0]
                backend_name = "MaskablePPO"
            elif backend_hint == "RecurrentPPO" and _resolve_contrib_algorithms()[1] is not None:
                backend_cls = _resolve_contrib_algorithms()[1]
                backend_name = "RecurrentPPO"
            self.last_policy_name = str(metadata.get("policy") or self._select_policy_name(backend_name))
            self.last_eval_reward = metadata.get("last_eval_reward")
            self.last_train_timesteps = int(metadata.get("last_train_timesteps", 0) or 0)
            self.last_note = str(metadata.get("note") or self.last_note)
        checkpoint_path = Path(self.save_path + ".zip")
        if checkpoint_path.exists():
            self.model = backend_cls.load(self.save_path, env=self.env)
            self.last_backend_name = backend_name
            if not self.last_policy_name:
                self.last_policy_name = self._select_policy_name(backend_name)
            self.last_checkpoint_path = self.save_path
            self.last_status = "ready"
            self._reset_predict_state()
            return True
        self.last_status = "idle"
        return False
