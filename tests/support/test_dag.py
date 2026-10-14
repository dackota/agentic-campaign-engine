"""tests/support/dag.py: light enough that a unit test imports it without the stack."""

import subprocess
import sys

from tests.api import helpers
from tests.support import dag

HEAVY_MODULES = ("testcontainers", "temporalio", "httpx", "tests.harness")


def test_importing_the_dag_builders_loads_no_stack_modules() -> None:
    probe = (
        "import sys; import tests.support.dag; "
        f"print([m for m in {HEAVY_MODULES!r} if m in sys.modules])"
    )

    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_the_api_helpers_still_export_every_moved_name() -> None:
    for name in helpers.__all__:
        assert getattr(helpers, name) is getattr(dag, name)


def test_a_signature_covers_the_timestamp_and_the_body() -> None:
    first = dag.signed_headers("secret", b"{}", timestamp=1)
    later = dag.signed_headers("secret", b"{}", timestamp=2)
    other_body = dag.signed_headers("secret", b"[]", timestamp=1)

    assert first[dag.TIMESTAMP_HEADER] == "1"
    assert first[dag.SIGNATURE_HEADER] not in {
        later[dag.SIGNATURE_HEADER],
        other_body[dag.SIGNATURE_HEADER],
    }


def test_a_workflow_is_built_from_steps_and_edges() -> None:
    assert dag.step("a", "agent", retries=2) == {"id": "a", "kind": "agent", "retries": 2}
    assert dag.edge("a", "b") == {"from": "a", "to": "b"}
    assert [s["id"] for s in dag.DRAFT_APPROVE_PUBLISH["steps"]] == ["draft", "approve", "publish"]
