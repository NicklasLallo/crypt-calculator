"""User-data and config locations for crypt_calculator.

Resolved via :mod:`platformdirs` so paths land in the right place on every
platform — XDG dirs on Linux/BSD (so existing installs keep working),
``%LOCALAPPDATA%`` on Windows, ``~/Library/Application Support`` on macOS.

Bundled examples live as package data under ``crypt_calculator/examples``
and are accessed via :mod:`importlib.resources` so they work both from a
source checkout and a ``pip install``.
"""

from __future__ import annotations

import importlib.resources as ir
from importlib.abc import Traversable
from pathlib import Path

import platformdirs
import yaml

APP_NAME = "crypt-calculator"


def data_dir() -> Path:
    return platformdirs.user_data_path(APP_NAME, appauthor=False)


def config_dir() -> Path:
    return platformdirs.user_config_path(APP_NAME, appauthor=False)


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
