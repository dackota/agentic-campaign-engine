"""The render service: the email contract in, brand HTML out."""

import re

import pytest
from render_service.email import MAX_EMAIL_BYTES, EmailTooLarge, render_email

DRAFT = {
    "subject": "Patch your VPN today",
    "preheader": "Attackers are scanning for it",
    "body": "Hello, apply the fix now.\n\nSecond paragraph.",
    "call_to_action": "Patch now",
}


def test_renders_brand_html_with_inline_styles_alt_text_and_size_limit() -> None:
    html = render_email(DRAFT)

    assert "Patch your VPN today" in html
    assert "Attackers are scanning for it" in html
    assert "Second paragraph." in html
    assert "Patch now" in html
    assert 'style="' in html
    assert "<style" not in html.split("<body")[1]
    images = re.findall(r"<img\b[^>]*>", html)
    assert images
    assert all(re.search(r'alt="[^"]+"', tag) for tag in images)
    assert len(html.encode()) < MAX_EMAIL_BYTES


def test_same_input_same_bytes() -> None:
    assert render_email(DRAFT) == render_email(dict(DRAFT))


def test_escapes_draft_text() -> None:
    html = render_email({**DRAFT, "body": "<script>alert(1)</script> & more"})

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_oversized_email_is_refused() -> None:
    with pytest.raises(EmailTooLarge):
        render_email({**DRAFT, "body": "x" * (MAX_EMAIL_BYTES + 1)})
