import os
import json
from datetime import datetime
from typing import Dict, Any, Optional

DEFAULT_RUNNER_CONFIG = {
    "_comment": "Configure these parameters before running main.py. Any value set here will be loaded automatically.",
    "port": 9223,
    "concurrency": 25,
    "batch_size": 35,
    "delay": 0.05,
    "strategy": "smart",
    "prune_threshold": 0.04,
    "max_depth_delta": 2,
    "catalyst_cap": 24,
    "max_recipes": None,
    "rate_limit_cooldown": 60.0,
    "query_interval_ms": 300,
    "cache_path": "data/recipes_cache.bin",
    "discoveries_dir": "discoveries"
}

DEFAULT_SETTINGS = {
    "_comment": "Persistent settings file. Remembers your last-used parameters, preferences, and session statistics.",
    "last_used_parameters": {
        "port": 9223,
        "concurrency": 25,
        "batch_size": 35,
        "delay": 0.05,
        "strategy": "smart",
        "prune_threshold": 0.04,
        "max_depth_delta": 2,
        "catalyst_cap": 24,
        "max_recipes": None,
        "rate_limit_cooldown": 60.0,
        "query_interval_ms": 300,
        "cache_path": "data/recipes_cache.bin",
        "discoveries_dir": "discoveries"
    },
    "preferences": {
        "auto_save_interval_sec": 25,
        "auto_reconnect": True,
        "auto_solve_cloudflare": True,
        "verbose_output": True
    },
    "stats_summary": {
        "last_session_time": None,
        "total_session_runs": 0,
        "lifetime_discoveries": 0
    }
}

class ConfigManager:
    def __init__(
        self,
        runner_config_path: str = "runner_config.json",
        settings_path: str = "settings.json"
    ):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.runner_config_path = os.path.join(base_dir, runner_config_path)
        self.settings_path = os.path.join(base_dir, settings_path)

        self._ensure_files()

    def _ensure_files(self):
        if not os.path.exists(self.runner_config_path):
            self._save_json(self.runner_config_path, DEFAULT_RUNNER_CONFIG)
        if not os.path.exists(self.settings_path):
            self._save_json(self.settings_path, DEFAULT_SETTINGS)

    def _load_json(self, path: str) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_json(self, path: str, data: Dict[str, Any]):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ConfigManager] Warning: failed to save {path}: {e}")

    def load_active_config(self, cli_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Loads and merges configuration in order: defaults -> settings -> runner_config -> cli_args."""
        settings = self._load_json(self.settings_path)
        runner_cfg = self._load_json(self.runner_config_path)

        # 1. Start with remembered parameters from settings.json
        active = dict(DEFAULT_RUNNER_CONFIG)
        active.update(settings.get("last_used_parameters", {}))

        # 2. Apply parameters from runner_config.json (pre-run setup file)
        for k, v in runner_cfg.items():
            if not k.startswith("_") and v is not None:
                active[k] = v

        # 3. Apply CLI arguments if explicitly provided by user
        if cli_args:
            for k, v in cli_args.items():
                if v is not None:
                    active[k] = v

        # Remember this active configuration in settings.json
        self.save_remembered_settings(active)
        return active

    def save_remembered_settings(self, active_params: Dict[str, Any]):
        """Persists the active parameters and updates run counts into settings.json."""
        settings = self._load_json(self.settings_path)
        if not settings:
            settings = dict(DEFAULT_SETTINGS)

        clean_params = {k: v for k, v in active_params.items() if not k.startswith("_")}
        settings["last_used_parameters"] = clean_params
        
        stats = settings.get("stats_summary", {})
        stats["last_session_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats["total_session_runs"] = stats.get("total_session_runs", 0) + 1
        settings["stats_summary"] = stats

        self._save_json(self.settings_path, settings)

    def update_lifetime_stats(self, session_discoveries: int):
        """Updates cumulative discovery counts in settings.json on exit."""
        settings = self._load_json(self.settings_path)
        if settings:
            stats = settings.get("stats_summary", {})
            stats["lifetime_discoveries"] = stats.get("lifetime_discoveries", 0) + session_discoveries
            settings["stats_summary"] = stats
            self._save_json(self.settings_path, settings)
