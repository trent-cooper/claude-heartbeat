"""Configuration loading and saving for claude-heartbeat."""

import os
import re
from pathlib import Path

import yaml


CONFIG_DIR = Path.home() / ".claude-heartbeat"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
LOG_FILE = CONFIG_DIR / "heartbeat.log"


def expand_env_vars(value: str) -> str:
    """Expand ${ENV_VAR} references in a string."""
    if not isinstance(value, str):
        return value

    def replacer(match):
        var_name = match.group(1)
        env_val = os.environ.get(var_name)
        if env_val is None:
            raise ValueError(f"Environment variable {var_name} is not set")
        return env_val

    return re.sub(r'\$\{(\w+)\}', replacer, value)


def expand_config(config: dict) -> dict:
    """Recursively expand env vars in config values."""
    result = {}
    for key, value in config.items():
        if isinstance(value, dict):
            result[key] = expand_config(value)
        elif isinstance(value, str):
            result[key] = expand_env_vars(value)
        else:
            result[key] = value
    return result


def load_config(resolve_env: bool = True) -> dict:
    """Load config from ~/.claude-heartbeat/config.yaml."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(
            f"Config not found at {CONFIG_FILE}. Run 'heartbeat init' first."
        )
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f) or {}
    if resolve_env:
        config = expand_config(config)
    return config


def save_config(config: dict) -> None:
    """Save config to ~/.claude-heartbeat/config.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def get_tasks(config: dict) -> dict:
    """Get the tasks dict from config."""
    return config.get("tasks", {})


def ensure_config_dir() -> None:
    """Create the config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
