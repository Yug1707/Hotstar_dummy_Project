"""Shared helpers for the analysis scripts: paths, the experiment config, run discovery (plan section 8)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
EXPERIMENTS_YAML = ROOT / "harness" / "experiments.yaml"
CONFIG_DIR = ROOT / "config"


def load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def global_cfg() -> dict:
    return load_yaml(EXPERIMENTS_YAML)["global"]


def run_dirs(results: Path = RESULTS, pattern: str = "E*") -> list[Path]:
    """Every results/<EXP>/run<N>/ folder that has a meta.json, sorted."""
    return sorted(p for p in results.glob(f"{pattern}/run*") if p.is_dir() and (p / "meta.json").exists())


def read_json(path: Path):
    with path.open() as f:
        return json.load(f)


def median(xs: list[float | None]) -> float | None:
    ys = sorted(x for x in xs if x is not None)
    if not ys:
        return None
    m = len(ys) // 2
    return ys[m] if len(ys) % 2 else (ys[m - 1] + ys[m]) / 2
