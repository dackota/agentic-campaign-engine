"""The seeded default workflow, "Threat report to campaign": a strategist and a research agent
run first, then the design agent and four writers at the same time. Each step has its own
session and its own contract."""

import asyncio
import uuid
from typing import Any

import pytest
from ace_engine import dag as graph
from ace_engine.agent_roles import ROLES, message_for
from ace_engine.contracts import REPORT_MARKER, citation_problems, violations
from ace_engine.default_workflow import (
    DEFAULT_WORKFLOW_NAME,
    DEFAULT_WORKFLOW_VERSION,
    default_workflow_dag,
)
from ace_engine.settings import APPROVE_SIGNAL
from ace_engine.workflow_spec import validate
from campaign_api.workflows import _find, seed_default_workflow
from campaign_worker.activities import session_key
from sqlalchemy.engine import Engine
from temporalio.client import WorkflowHandle
from temporalio.testing import WorkflowEnvironment

from tests.harness.scripted_agent import FIXED_CARDS, default_reply
from tests.support.run_stubs import (
    FINISHED,
    StubActivities,
    run_workflow,
    time_skipping_env,
    until,
)

WRITERS = ["email_writer", "landing_page", "social", "one_pager"]
REPORT = (
    "Volt Typhoon targets edge routers\n"
    "Actors exploit unpatched VPN appliances.\n"
    "\n"
    "They stay hidden for months using living-off-the-land tools.\n"
    "Patching and credential rotation stop the known intrusion path."
)
EMAIL_REPLIES = 2
ALL_STARTED_SECONDS = 3


def test_default_workflow_is_valid_and_starts_with_the_strategist_then_research() -> None:
    dag = default_workflow_dag()

    ids = [s["id"] for s in dag["steps"]]
    assert validate(dag) == []
    assert ids[:2] == ["strategist", "research"]
    assert set(ids) >= set(WRITERS)
    assert DEFAULT_WORKFLOW_VERSION == 2


def test_seeding_saves_the_default_workflow_once_however_often_it_runs(
    sqlite_engine: Engine,
) -> None:
    seed_default_workflow(sqlite_engine)
    seed_default_workflow(sqlite_engine)

    found = _find(sqlite_engine, DEFAULT_WORKFLOW_NAME, None)
    assert found is not None
    assert (found.version, found.dag) == (DEFAULT_WORKFLOW_VERSION, default_workflow_dag())


def test_design_and_all_four_writers_are_ready_as_soon_as_research_is_done() -> None:
    dag = default_workflow_dag()

    ready = graph.ready_steps(dag, {"strategist", "research"})

    assert [s["id"] for s in ready] == [
        "design",
        "landing_page",
        "social",
        "one_pager",
        "email_writer",
    ]


def test_every_step_has_its_own_session_and_a_second_email_reply_has_another() -> None:
    campaign_id = str(uuid.uuid4())
    steps = [s["id"] for s in default_workflow_dag()["steps"]]

    sessions = [session_key(campaign_id, step) for step in steps]

    assert len(set(sessions)) == len(steps)
    assert all(
        session == graph.step_key(campaign_id, step)
        for session, step in zip(sessions, steps, strict=True)
    )
    assert (
        session_key(campaign_id, "email_writer", 1) == f"{sessions[steps.index('email_writer')]}:v1"
    )


def _reply_for(step: str, context: dict[str, Any]) -> dict[str, Any]:
    return default_reply(message_for(ROLES[step], REPORT, context))


@pytest.mark.parametrize("step", sorted(ROLES))
def test_the_scripted_agent_replies_with_a_contract_valid_output_for_each_role(step: str) -> None:
    context = {"landing_page": {"headline": "h"}} if step == "judge" else {}

    reply = _reply_for(step, context)

    assert violations(reply, ROLES[step].reply_schema) == []


def test_the_scripted_design_cards_fit_the_design_contract() -> None:
    assert violations({"cards": list(FIXED_CARDS)}, ROLES["design"].schema) == []


def test_every_research_fact_cites_a_line_in_the_report() -> None:
    facts = _reply_for("research", {})["facts"]
    lines = REPORT.splitlines()

    assert facts
    assert citation_problems({"facts": facts}, REPORT) == []
    for fact in facts:
        assert 1 <= fact["line"] <= len(lines), fact
        assert fact["quote"].strip() and fact["quote"] in lines[fact["line"] - 1], fact


def test_the_email_writer_is_asked_for_two_replies_one_per_variant() -> None:
    assert ROLES["email_writer"].replies == EMAIL_REPLIES
    assert REPORT_MARKER in message_for(ROLES["email_writer"], REPORT, {})


WRITER_STEPS = {"design", *WRITERS}


def test_design_and_all_four_writers_start_before_any_of_them_finishes() -> None:
    started: set[str] = set()
    all_started = asyncio.Event()

    async def agent(step_id: str) -> dict[str, Any]:
        started.add(step_id)
        if started >= WRITER_STEPS:
            all_started.set()
        if step_id in WRITER_STEPS:
            # A sequential engine never lets the others start, so this wait would time out.
            await asyncio.wait_for(all_started.wait(), timeout=ALL_STARTED_SECONDS)
        # The email writer's drafts are a list, as the publish step takes them; the rest a dict.
        output = [{"step": step_id}] if step_id == "email_writer" else {"step": step_id}
        return {"output": output, "session": step_id, "usage": {}}

    async def approve(
        env: WorkflowEnvironment, handle: WorkflowHandle[Any, Any], stubs: StubActivities
    ) -> None:
        await until(lambda: bool(stubs.called("announce_approval")))
        await handle.signal(APPROVE_SIGNAL)

    async def go() -> tuple[str, StubActivities]:
        stubs = StubActivities(agent)
        async with time_skipping_env() as env:
            return await run_workflow(env, default_workflow_dag(), stubs, approve), stubs

    outcome, stubs = asyncio.run(go())

    order = [
        (name, args[0])
        for name, args in stubs.calls
        if name in {"run_agent_step", "save_agent_output"}
    ]
    first_saved_writer = next(
        i for i, (n, s) in enumerate(order) if n == "save_agent_output" and s in WRITER_STEPS
    )
    assert outcome == FINISHED
    assert {s for n, s in order[:first_saved_writer] if n == "run_agent_step"} >= WRITER_STEPS
    assert order.index(("save_agent_output", "research")) < order.index(
        ("run_agent_step", "design")
    )
