"""Configuration helpers for YAML-backed scout settings."""

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "configs"


def load_yaml_config(path: Path) -> dict[str, object]:
    """Load a YAML config file and return an empty mapping for blank files."""
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return data or {}


def load_named_config(name: str) -> dict[str, object]:
    """Load a config file from the repository-level configs directory."""
    return load_yaml_config(CONFIG_DIR / name)
