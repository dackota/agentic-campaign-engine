"""The judge: its AgentTemplate, its rubric file, its contract, and the floor rule."""

import jsonschema
from ace_engine import judge
from ace_engine.agent_roles import ROLES

from tests.tooling.gateway_files import ROOT, yaml_docs

TEMPLATES = ROOT / "agents/templates.yaml"


def scores(*pairs: tuple[str, int]) -> dict[str, object]:
    return {"scores": [{"step": s, "score": n, "reason": f"why {s}"} for s, n in pairs]}


def test_judge_role_has_template_and_prompt_carries_the_rubric() -> None:
    templates = {d["metadata"]["name"]: d for d in yaml_docs(TEMPLATES)}
    role = ROLES["judge"]

    assert templates[role.template]["spec"]["systemPrompt"] == role.prompt
    assert judge.RUBRIC_PATH.is_file()
    for line in judge.RUBRIC_PATH.read_text().splitlines():
        assert line.strip() in role.prompt
    jsonschema.Draft202012Validator.check_schema(role.schema)
    assert str(judge.FLOOR) in role.prompt


def test_floor_rule_blocks_only_scores_below_the_floor() -> None:
    assets = ["a", "b"]

    assert judge.blocking(scores(("a", judge.FLOOR), ("b", judge.MAX_SCORE)), assets) == []
    low = judge.blocking(scores(("a", judge.FLOOR - 1), ("b", judge.MAX_SCORE)), assets)
    assert len(low) == 1 and "a" in low[0] and "why a" in low[0]


def test_scores_for_steps_that_are_not_assets_are_ignored() -> None:
    assert judge.blocking(scores(("other", 1)), ["a"]) == []
    assert judge.asset_scores(scores(("other", 1), ("a", 4)), ["a"]) == [
        {"step": "a", "score": 4, "reason": "why a"}
    ]


def test_contract_rejects_out_of_range_scores() -> None:
    assert judge.score_problems(scores(("a", 3))) == []
    assert judge.score_problems(scores(("a", judge.MAX_SCORE + 1)))
    assert judge.score_problems(scores(("a", 0)))
    assert judge.score_problems({"scores": [{"step": "a", "score": 3}]})
