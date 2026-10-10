"""The workflow JSON Schema is the one source of truth: the web app's TypeScript types are
generated from it by scripts/gen_workflow_types.py, and must not drift from it."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts/gen_workflow_types.py"
SCHEMA = ROOT / "apps/engine/ace_engine/workflow.schema.json"
TYPES = ROOT / "apps/web/src/workflow.gen.ts"


def generate(schema: Path) -> str:
    return subprocess.run(
        [sys.executable, str(GENERATOR), "--schema", str(schema), "--stdout"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_checked_in_typescript_types_match_the_schema() -> None:
    assert TYPES.read_text() == generate(SCHEMA), (
        "apps/web/src/workflow.gen.ts is stale: run `make types`"
    )


def test_types_name_every_step_kind_in_the_schema() -> None:
    kinds = json.loads(SCHEMA.read_text())["$defs"]["StepKind"]["enum"]
    assert set(kinds) == {"agent", "render", "approval", "publish", "wait"}
    generated = TYPES.read_text()
    for kind in kinds:
        assert f'"{kind}"' in generated
    assert "export interface Workflow " in generated
    assert "export interface WorkflowStep " in generated


def test_generator_output_changes_when_the_schema_changes(tmp_path: Path) -> None:
    schema = json.loads(SCHEMA.read_text())
    schema["$defs"]["StepKind"]["enum"].append("teleport")
    changed = tmp_path / "workflow.schema.json"
    changed.write_text(json.dumps(schema))

    assert '"teleport"' in generate(changed)
    assert '"teleport"' not in TYPES.read_text()
