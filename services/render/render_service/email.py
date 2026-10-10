"""Email renderer: the email contract in, brand HTML out, through MJML.

Pure and deterministic: the same draft gives the same bytes. MJML inlines the CSS.
"""

from collections.abc import Mapping
from html import escape

from mjml import mjml2html

MAX_EMAIL_BYTES = 100_000  # Gmail clips messages past about 102 KB
BRAND_NAME = "Agentic Campaign Engine"
BRAND_COLOR = "#0b5fff"
BRAND_LOGO_URL = "https://assets.example.com/brand/logo.png"
BRAND_LOGO_ALT = f"{BRAND_NAME} logo"
CTA_URL = "https://example.com/act"

_TEMPLATE = """<mjml>
  <mj-head>
    <mj-title>{subject}</mj-title>
    <mj-preview>{preheader}</mj-preview>
    <mj-attributes>
      <mj-all font-family="Helvetica, Arial, sans-serif" />
      <mj-text font-size="16px" line-height="1.5" color="#1f2933" />
    </mj-attributes>
  </mj-head>
  <mj-body background-color="#f4f6f8">
    <mj-section background-color="{color}" padding="16px">
      <mj-column>
        <mj-image src="{logo}" alt="{logo_alt}" width="160px" />
      </mj-column>
    </mj-section>
    <mj-section background-color="#ffffff" padding="24px">
      <mj-column>
        <mj-text font-size="24px" font-weight="bold">{subject}</mj-text>
        {paragraphs}
        <mj-button background-color="{color}" href="{cta_url}">{cta}</mj-button>
      </mj-column>
    </mj-section>
  </mj-body>
</mjml>
"""


class EmailTooLarge(Exception):
    """The rendered email is over MAX_EMAIL_BYTES."""


def _paragraphs(body: str) -> str:
    parts = [p.strip() for p in body.split("\n\n") if p.strip()]
    return "\n        ".join(
        f"<mj-text>{escape(p).replace(chr(10), '<br />')}</mj-text>" for p in parts
    )


def render_email(draft: Mapping[str, str]) -> str:
    # Refuse before MJML parses an oversized input; the output is larger than the input.
    if len(draft["body"].encode()) > MAX_EMAIL_BYTES:
        raise EmailTooLarge(f"email body is over {MAX_EMAIL_BYTES} bytes")
    source = _TEMPLATE.format(
        subject=escape(draft["subject"]),
        preheader=escape(draft["preheader"]),
        paragraphs=_paragraphs(draft["body"]),
        cta=escape(draft["call_to_action"]),
        cta_url=CTA_URL,
        color=BRAND_COLOR,
        logo=BRAND_LOGO_URL,
        logo_alt=BRAND_LOGO_ALT,
    )
    html: str = mjml2html(source)
    if len(html.encode()) > MAX_EMAIL_BYTES:
        raise EmailTooLarge(f"rendered email is over {MAX_EMAIL_BYTES} bytes")
    return html
