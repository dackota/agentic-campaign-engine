"""The go-public check script: secret scan of every ref, brand deny list, license flags.
Each test builds a throwaway git repo at run time; the fake secret and the brand name are
assembled here so no tracked file holds either."""

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


def test_no_license_file_is_added() -> None:
    names = {p.name.upper().split(".")[0] for p in ROOT.iterdir() if p.is_file()}

    assert "LICENSE" not in names


def test_go_public_doc_records_the_run_and_open_items() -> None:
    text = DOC.read_text()

    for needle in ("secret scan", "Brand hits", "Licenses", "Open items", "job link", "LICENSE"):
        assert needle in text, needle
