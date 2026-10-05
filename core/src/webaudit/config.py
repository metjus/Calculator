"""Editable configuration.

Defaults live as JSON files in ``webaudit/defaults``. A user (desktop/CLI) can
override any key by putting a file with the same name into a config directory;
the SaaS backend passes per-workspace overrides as dicts. Overrides are deep
merged over the defaults, so an override file only needs the keys it changes.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

CONFIG_FILES = ("scanner", "scoring", "signatures", "texts", "cookie_banners", "devnotes")
ENV_CONFIG_DIR = "WEBAUDIT_CONFIG_DIR"


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _load_default(name: str) -> dict[str, Any]:
    text = resources.files("webaudit.defaults").joinpath(f"{name}.json").read_text("utf-8")
    return json.loads(text)


@dataclass(frozen=True)
class Config:
    scanner: dict[str, Any]
    scoring: dict[str, Any]
    signatures: dict[str, Any]
    texts: dict[str, Any]
    cookie_banners: dict[str, Any]
    devnotes: dict[str, Any]  # technical fix/verify notes for the Claude Code export

    @classmethod
    def load(
        cls,
        config_dir: str | Path | None = None,
        overrides: dict[str, dict[str, Any]] | None = None,
    ) -> Config:
        config_dir = config_dir or os.environ.get(ENV_CONFIG_DIR)
        data: dict[str, dict[str, Any]] = {}
        for name in CONFIG_FILES:
            merged = _load_default(name)
            if config_dir:
                path = Path(config_dir) / f"{name}.json"
                if path.is_file():
                    merged = deep_merge(merged, json.loads(path.read_text("utf-8")))
            if overrides and name in overrides:
                merged = deep_merge(merged, overrides[name])
            data[name] = merged
        return cls(**data)

    def threshold(self, key: str) -> Any:
        return self.scanner["thresholds"][key]


def export_defaults(target_dir: str | Path) -> list[Path]:
    """Copy the default JSON files into ``target_dir`` so they can be edited."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name in CONFIG_FILES:
        path = target / f"{name}.json"
        if not path.exists():
            path.write_text(json.dumps(_load_default(name), ensure_ascii=False, indent=2), "utf-8")
            written.append(path)
    return written
