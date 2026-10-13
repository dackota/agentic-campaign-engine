"""Functions stay short: no function or method in a tracked Python file runs over the limit.
Ruff has no rule for function length, so this test is the check."""

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_FUNCTION_LINES = 50


def _tracked_python() -> list[Path]:
    listed = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return [ROOT / name for name in listed.stdout.splitlines()]


def _long_functions(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as error:
        return [f"{path.relative_to(ROOT).as_posix()}: cannot parse: {error}"]
    return [
        f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {node.name} is {span} lines"
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.end_lineno is not None
        and (span := node.end_lineno - node.lineno + 1) > MAX_FUNCTION_LINES
    ]


def test_no_function_is_over_the_line_limit() -> None:
    offenders = [line for path in _tracked_python() for line in _long_functions(path)]

    assert offenders == [], f"over {MAX_FUNCTION_LINES} lines:\n" + "\n".join(offenders)
