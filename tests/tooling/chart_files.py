"""Shared helpers for the chart tests: render charts/ace offline with `helm template`."""

import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHART = ROOT / "charts/ace"


def helm(args: list[str]) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def raw_render(*sets: str) -> str:
    args = ["helm", "template", "ace", str(CHART), "--namespace", "ace"]
    for value in sets:
        args += ["--set", value]
    return helm(args)


def render(*sets: str) -> list[dict[str, Any]]:
    return [d for d in yaml.safe_load_all(raw_render(*sets)) if d]


def by_kind(docs: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [d for d in docs if d["kind"] == kind]
