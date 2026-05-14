"""User-data and config locations for crypt_calculator.

The TUI stores user-saved YAML files (crypts + rule-sets) under the XDG
data directory, and a small config file (first-run state) under the XDG
config directory. Falls back to the conventional Linux defaults when the
XDG environment variables aren't set.

Bundled examples live as package data under ``crypt_calculator/examples``
and are accessed via :mod:`importlib.resources` so they work both from a
source checkout and a ``pip install``.
"""

from __future__ import annotations

import importlib.resources as ir
import os
from importlib.abc import Traversable
from pathlib import Path

import yaml

APP_NAME = "crypt-calculator"


def data_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.yaml"


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def save_config(data: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False)


def is_first_run() -> bool:
    return not load_config().get("first_run_complete", False)


def mark_first_run_done() -> None:
    cfg = load_config()
    cfg["first_run_complete"] = True
    save_config(cfg)


def _bundled_examples_root() -> Traversable:
    return ir.files("crypt_calculator") / "examples"


def bundled_examples() -> list[Traversable]:
    """Bundled example YAMLs that ship with the package."""
    root = _bundled_examples_root()
    return sorted(
        (p for p in root.iterdir() if p.is_file() and p.name.endswith(".yaml")),
        key=lambda p: p.name.lower(),
    )


def install_examples(*, overwrite: bool = False) -> list[Path]:
    """Copy bundled examples to the user's data directory.

    Returns the list of files actually written. Existing files are kept
    unless ``overwrite`` is True — this means a user who has edited a
    previously-installed example won't lose their edits on a reinstall.
    """
    dest = data_dir()
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for src in bundled_examples():
        target = dest / src.name
        if target.exists() and not overwrite:
            continue
        target.write_bytes(src.read_bytes())
        copied.append(target)
    return copied
