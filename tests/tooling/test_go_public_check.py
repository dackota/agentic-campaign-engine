"""The go-public check script: secret scan of every ref, brand deny list, license flags.
Each test builds a throwaway git repo at run time; the fake secret and the brand name are
assembled here so no tracked file holds either."""

import itertools
import os
import random
import re
import secrets
import string
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/go-public-check.sh"
DOC = ROOT / "docs/go-public.md"
EXIT_SECRET = 1
EXIT_FINDINGS = 2
BRAND = "Mark" + "eto"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _fake_token() -> str:
    alphabet = string.ascii_letters + string.digits
    return "ghp_" + "".join(secrets.choice(alphabet) for _ in range(36))


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for name, body in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(body)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args], cwd=repo, capture_output=True, text=True, timeout=120
    )


def test_clean_history_passes_the_scan(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"a.txt": "nothing to see\n"})

    result = _run(repo)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "secret scan: PASS" in result.stdout


def test_secret_in_history_fails_the_scan_and_is_not_printed(tmp_path: Path) -> None:
    token = _fake_token()
    repo = _repo(tmp_path, {"cfg.txt": f"github_token = {token}\n"})
    _git(repo, "rm", "-q", "cfg.txt")
    _git(repo, "commit", "-q", "-m", "remove it")

    result = _run(repo)

    assert result.returncode == EXIT_SECRET
    assert "secret scan: FAIL" in result.stdout
    assert token not in result.stdout + result.stderr
    assert token[4:20] not in result.stdout + result.stderr


def test_secret_on_a_non_head_ref_is_found(tmp_path: Path) -> None:
    token = _fake_token()
    repo = _repo(tmp_path, {"a.txt": "ok\n"})
    _git(repo, "checkout", "-q", "-b", "side")
    (repo / "cfg.txt").write_text(f"github_token = {token}\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "side secret")
    _git(repo, "checkout", "-q", "main")

    result = _run(repo)

    assert result.returncode == EXIT_SECRET
    assert token not in result.stdout + result.stderr


def test_planted_brand_line_is_listed_with_file_and_line(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"notes.md": f"one\ntwo uses {BRAND} here\n"})

    result = _run(repo)

    assert "notes.md:2:" in result.stdout


def test_brand_hit_output_never_includes_the_line_text(tmp_path: Path) -> None:
    line_text = "api_key_value_" + "x7Q9zK2mP4"
    repo = _repo(tmp_path, {"notes.md": f"one\n{line_text} {BRAND}\n"})

    result = _run(repo)

    assert f"notes.md:2:{BRAND}" in result.stdout
    assert line_text not in result.stdout + result.stderr


def test_brand_hits_alone_exit_with_the_brand_code(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"notes.md": f"{BRAND}\n"})

    assert _run(repo).returncode == EXIT_FINDINGS


def test_script_and_its_doc_are_not_scanned_for_brands(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        {"scripts/go-public-check.sh": f"{BRAND}\n", "docs/go-public.md": f"{BRAND}\n"},
    )

    result = _run(repo)

    assert result.returncode == 0, result.stdout
    assert "scripts/go-public-check.sh:" not in result.stdout
    assert "docs/go-public.md:" not in result.stdout


@pytest.mark.parametrize(
    ("license_text", "verdict"),
    [
        ("MIT", "ok"),
        ("Apache-2.0", "ok"),
        ("BSD-3-Clause", "ok"),
        ("MIT OR Apache-2.0", "ok"),
        ("GPL-3.0-only", "flagged"),
        ("AGPL-3.0", "flagged"),
        ("GNU Lesser General Public License v3", "flagged"),
        ("", "flagged"),
        ("UNKNOWN", "flagged"),
    ],
)
def test_license_classifier_flags_copyleft_and_unknown(license_text: str, verdict: str) -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--classify", license_text], capture_output=True, text=True
    )

    assert result.stdout.strip() == verdict


PERMISSIVE_TERMS = ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"]
COPYLEFT_TERMS = ["GPL-2.0", "GPL-3.0-only", "AGPL-3.0", "LGPL-3.0-only"]


@pytest.mark.parametrize(
    ("permissive", "copyleft", "joiner"),
    list(itertools.product(PERMISSIVE_TERMS, COPYLEFT_TERMS, [" AND ", " and ", " / "]))
    + list(itertools.product(COPYLEFT_TERMS, PERMISSIVE_TERMS, [" AND "])),
)
def test_copyleft_outside_an_or_choice_is_flagged(
    permissive: str, copyleft: str, joiner: str
) -> None:
    text = permissive + joiner + copyleft if joiner != " / " else copyleft + joiner + permissive
    result = subprocess.run(
        ["bash", str(SCRIPT), "--classify", text], capture_output=True, text=True
    )

    assert result.stdout.strip() == "flagged", text


def test_or_choice_with_a_permissive_side_is_ok() -> None:
    result = subprocess.run(
        ["bash", str(SCRIPT), "--classify", "MIT OR GPL-2.0"], capture_output=True, text=True
    )

    assert result.stdout.strip() == "ok"


def test_repo_has_an_mit_license_file() -> None:
    text = (ROOT / "LICENSE").read_text()

    assert text.startswith("MIT License")
    assert "Dackota Johnson" in text


def test_gitleaks_ignore_covers_only_the_two_known_placeholder_lines() -> None:
    lines = [
        ln for ln in (ROOT / ".gitleaksignore").read_text().splitlines() if ln and ln[0] != "#"
    ]

    assert sorted(ln.split(":", 1)[1] for ln in lines) == [
        "docs/learning-proof.md:generic-api-key:11",
        "evals/README.md:generic-api-key:23",
    ]


def test_go_public_doc_records_the_run_and_open_items() -> None:
    text = DOC.read_text()

    for needle in ("secret scan", "Brand hits", "Licenses", "Open items", "LICENSE"):
        assert needle in text, needle


def test_go_public_doc_holds_no_hit_or_brand_counts() -> None:
    text = DOC.read_text()

    assert not re.search(r"\b\d+ (hit )?lines?\b", text)
    assert not re.search(r"\b(Marketo|Workfront|Slack|Google|Figma)\s+\d+\b", text)
    assert not re.search(r"\b[\w.]+\.(py|ts|tsx|yaml)\s+\d+\b", text)


NON_PERMISSIVE_TERMS = [
    "EPL-2.0",
    "SSPL-1.0",
    "GPL-3.0-only",
    "Acme Private Terms",
    "Foo-1.0",
    "???",
]


def _classify(text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--classify", text], capture_output=True, text=True, timeout=60
    )


@pytest.mark.parametrize(
    ("permissive", "other", "joiner"),
    list(
        itertools.product(
            PERMISSIVE_TERMS, NON_PERMISSIVE_TERMS, [" AND ", " and ", " / ", " AND (", "("]
        )
    ),
)
def test_permissive_and_non_permissive_is_flagged(permissive: str, other: str, joiner: str) -> None:
    text = (
        f"({permissive}{joiner}{other}))" if joiner.endswith("(") else permissive + joiner + other
    )

    assert _classify(text).stdout.strip() == "flagged", text


@pytest.mark.parametrize("text", ["Foo-1.0", "EPL-2.0", "SSPL-1.0", "Acme Private Terms"])
def test_unknown_or_weak_copyleft_names_are_flagged(text: str) -> None:
    assert _classify(text).stdout.strip() == "flagged"


@pytest.mark.parametrize("text", ["(MIT AND Apache-2.0)", " mit  or  Foo-1.0 ", "MIT License"])
def test_whole_permissive_terms_are_ok(text: str) -> None:
    assert _classify(text).stdout.strip() == "ok"


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "x" * 100_000,  # under Linux MAX_ARG_STRLEN (128 KiB) for one argv string
        "(((",
        ")(",
        "OR",
        " AND ",
        "a\tb\nc",
        "\x01\xff",
        "$(id)",
        "'\"`;|&*?[",
        "-n",
        "--",
    ],
)
def test_classify_prints_ok_or_flagged_and_exits_zero_for_any_input(text: str) -> None:
    result = _classify(text)

    assert result.returncode == 0
    assert result.stdout.strip() in {"ok", "flagged"}
    assert result.stdout.count("\n") == 1


def test_malformed_js_manifest_fails_the_license_scan(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"web/package.json": "{ not json"})

    result = _run(repo)

    assert "licenses: FAIL" in result.stdout, result.stdout
    assert result.returncode in (EXIT_SECRET, EXIT_FINDINGS)


def test_parenthesised_choice_beside_a_term_fails_closed() -> None:
    assert _classify("(MIT OR Apache-2.0) AND GPL-3.0-only").stdout.strip() == "flagged"


@pytest.mark.parametrize("text", ["GPL-3.0\x01MIT", "MIT\x01GPL-3.0", "Apache-2.0\x01EPL-2.0"])
def test_control_byte_in_a_license_is_flagged(text: str) -> None:
    assert _classify(text).stdout.strip() == "flagged"


@pytest.mark.parametrize(
    ("odd", "plain"),
    [
        ("MIT And GPL-3.0", "MIT AND GPL-3.0"),
        ("MIT aNd GPL-3.0", "MIT AND GPL-3.0"),
        ("MIT OR  GPL-3.0", "MIT OR GPL-3.0"),
        ("MIT   or   Foo-1.0", "MIT OR Foo-1.0"),
        ("Apache-2.0  AND  MIT", "Apache-2.0 AND MIT"),
    ],
)
def test_odd_case_and_extra_space_separators_match_the_plain_form(odd: str, plain: str) -> None:
    assert _classify(odd).stdout.strip() == _classify(plain).stdout.strip()


CONTROL_BYTES = [chr(c) for c in [*range(1, 9), *range(11, 32), 127]]
SEPARATORS = ["AND", "OR"]


def _odd_case(word: str, rng: random.Random) -> str:
    return "".join(rng.choice((c.lower(), c.upper())) for c in word)


def _generate_expression(rng: random.Random) -> tuple[str, str]:
    """Return (text, expected verdict) for a random flat AND/OR expression of known terms."""
    permissive = PERMISSIVE_TERMS + ["ISC", "MPL-2.0"]
    alternatives = [
        [
            (rng.choice(permissive + COPYLEFT_TERMS + NON_PERMISSIVE_TERMS))
            for _ in range(rng.randint(1, 3))
        ]
        for _ in range(rng.randint(1, 3))
    ]
    has_control = rng.random() < 0.3
    pieces: list[str] = []
    for ai, alt in enumerate(alternatives):
        if ai:
            pieces.append(" " * rng.randint(1, 3) + _odd_case("or", rng) + " " * rng.randint(1, 3))
        for ti, term in enumerate(alt):
            if ti:
                pieces.append(
                    " " * rng.randint(1, 3) + _odd_case("and", rng) + " " * rng.randint(1, 3)
                )
            pieces.append(term)
    text = "".join(pieces)
    if has_control:
        at = rng.randint(0, len(text))
        text = text[:at] + rng.choice(CONTROL_BYTES) + text[at:]
    all_known = {t.lower() for t in permissive}
    ok = any(all(t.lower() in all_known for t in alt) for alt in alternatives)
    return text, "ok" if ok and not has_control else "flagged"


def test_classify_verdict_matches_the_model_over_generated_inputs() -> None:
    rng = random.Random(115)
    for _ in range(120):
        text, expected = _generate_expression(rng)

        assert _classify(text).stdout.strip() == expected, repr(text)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_unreadable_tracked_file_fails_the_brand_scan(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"ok.txt": "fine\n", "locked.txt": "fine\n"})
    (repo / "locked.txt").chmod(0)

    result = _run(repo)

    assert "brand scan: FAIL" in result.stdout, result.stdout
    assert "brand hits: 0" not in result.stdout
    assert result.returncode != 0
    assert "result: PASS" not in result.stdout
