"""The README, the architecture doc and the decisions index: every link resolves, the proof
table covers every job bullet, and the setup steps name things that exist."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
ARCH = ROOT / "docs/architecture.md"
DECISIONS = ROOT / "docs/decisions"
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
IMAGE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")


def _section(text: str, heading: str) -> str:
    """The body of one `## heading` block of Markdown text."""
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"no '## {heading}' section"
    return match.group(1)


def _relative_targets(path: Path) -> list[str]:
    text = path.read_text()
    found = LINK.findall(text) + IMAGE.findall(text)
    return [t for t in found if not re.match(r"[a-z]+:|#", t)]


def _check_links(path: Path) -> None:
    targets = _relative_targets(path)
    assert targets, f"{path.name} has no relative links"
    for target in targets:
        file_part = target.split("#")[0]
        assert (path.parent / file_part).exists(), f"{path.name} links to missing {target}"


def _job_bullets() -> list[str]:
    spec = _section((ROOT / "SPEC.md").read_text(), "Job bullet to proof")
    rows = [line for line in spec.splitlines() if line.startswith("|")][2:]
    return [row.split("|")[1].strip() for row in rows]


def test_readme_every_relative_link_resolves() -> None:
    _check_links(README)


def test_architecture_every_relative_link_resolves() -> None:
    _check_links(ARCH)


def test_readme_proof_table_has_a_row_per_job_bullet_with_code_and_test_links() -> None:
    bullets = _job_bullets()
    assert len(bullets) == 10
    table = _section(README.read_text(), "Job bullet to proof")
    rows = [line for line in table.splitlines() if line.startswith("|")][2:]
    assert len(rows) == len(bullets)
    for bullet, row in zip(bullets, rows, strict=True):
        assert row.split("|")[1].strip() == bullet
        targets = [t.split("#")[0] for t in LINK.findall(row)]
        assert any(not t.startswith(("tests/", "apps/web/e2e/")) for t in targets), bullet
        assert any(t.startswith(("tests/", "apps/web/e2e/", "evals/")) for t in targets), bullet


def test_readme_covers_problem_and_demo_gif_or_owed_placeholder() -> None:
    text = README.read_text()
    assert "## The problem" in text
    assert "Status: planning" not in text
    has_gif = "docs/demo.gif" in text and (ROOT / "docs/demo.gif").exists()
    owed = "demo gif is owed" in text.lower()
    assert has_gif or owed
    gif = ROOT / "docs/demo.gif"
    if gif.exists():
        assert gif.stat().st_size < 5 * 1024 * 1024


def test_architecture_doc_has_the_four_flow_diagrams() -> None:
    text = ARCH.read_text()
    assert text.count("```mermaid") >= 4
    for heading in (
        "Campaign run",
        "Approval and publish",
        "Webhooks and learnings",
        "Auth and team isolation",
    ):
        assert f"## {heading}" in text, heading


def test_decisions_index_covers_every_decision_row_and_every_adr() -> None:
    index = (DECISIONS / "README.md").read_text()
    spec = _section((ROOT / "SPEC.md").read_text(), "Decisions")
    numbers = re.findall(r"^\| (\d+) \|", spec, re.M)
    assert len(numbers) == 19
    for number in numbers:
        assert re.search(rf"^\| {number} \|", index, re.M), f"decision {number} missing"
    linked = {t.split("#")[0] for t in _relative_targets(DECISIONS / "README.md")}
    for adr in DECISIONS.glob("*.md"):
        if adr.name != "README.md":
            assert adr.name in linked, f"{adr.name} not in the index"
    _check_links(DECISIONS / "README.md")


def test_readme_setup_steps_name_real_make_targets_and_files() -> None:
    text = README.read_text()
    makefile = (ROOT / "Makefile").read_text()
    for target in re.findall(r"`make ([a-z-]+)", text):
        assert re.search(rf"^{target}:", makefile, re.M), target
    assert (ROOT / ".env.example").exists()
    assert "cp .env.example .env" in text
    assert "git clone" in text


def test_no_real_brand_or_job_link() -> None:
    spec = (ROOT / "SPEC.md").read_text()
    job_url = re.search(r"\[job post\]\(([^)]+)\)", spec)
    assert job_url
    host = job_url.group(1).split("/")[2].split(".")[0].lower()
    for path in (README, ARCH, DECISIONS / "README.md"):
        text = path.read_text().lower()
        assert job_url.group(1).lower() not in text
        assert host not in text, path.name
