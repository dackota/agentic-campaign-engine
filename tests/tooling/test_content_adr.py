"""The decision record for the CMS and the asset store."""

from pathlib import Path

ADR = Path(__file__).resolve().parents[2] / "docs/decisions/cms-and-asset-store.md"


def test_adr_records_fake_cms_and_s3_choice() -> None:
    text = ADR.read_text().lower()

    assert "fake" in text and "cms" in text
    assert "s3" in text and "decision" in text
    assert "real" in text  # says why a real open-source CMS was not chosen
