"""Email renderer: the email contract in, brand HTML out, through MJML.

Pure and deterministic: the same draft gives the same bytes. MJML inlines the CSS.
"""

from collections.abc import Mapping
from html import escape

from ace_engine import telemetry
from mjml import mjml2html

MAX_EMAIL_BYTES = 100_000  # Gmail clips messages past about 102 KB
BRAND_NAME = "Agentic Campaign Engine"
BRAND_COLOR = "#0b5fff"
BRAND_LOGO_URL = "https://assets.example.com/brand/logo.png"
BRAND_LOGO_ALT = f"{BRAND_NAME} logo"
CTA_URL = "https://example.com/act"
PAGE_BACKGROUND = "#f4f6f8"
CARD_BACKGROUND = "#ffffff"
TEXT_COLOR = "#1f2933"
FONT_STACK = "Helvetica, Arial, sans-serif"
TEXT_SIZE = "16px"
TEXT_LINE_HEIGHT = "1.5"
TITLE_SIZE = "24px"
LOGO_WIDTH = "160px"
NEWLINE = "\n"
SERVICE = "render"

_TEMPLATE = """<mjml>
  <mj-head>
    <mj-title>{subject}</mj-title>
    <mj-preview>{preheader}</mj-preview>
    <mj-attributes>
      <mj-all font-family="{font}" />
      <mj-text font-size="{text_size}" line-height="{line_height}" color="{text_color}" />
    </mj-attributes>
  </mj-head>
  <mj-body background-color="{page_bg}">
    <mj-section background-color="{color}" padding="16px">
      <mj-column>
        <mj-image src="{logo}" alt="{logo_alt}" width="{logo_width}" />
      </mj-column>
    </mj-section>
    <mj-section background-color="{card_bg}" padding="24px">
      <mj-column>
        <mj-text font-size="{title_size}" font-weight="bold">{subject}</mj-text>
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
        f"<mj-text>{escape(p).replace(NEWLINE, '<br />')}</mj-text>" for p in parts
    )


def render_email(draft: Mapping[str, str]) -> str:
    """Render an email draft (subject, preheader, body, call_to_action) to brand HTML.

    Raises EmailTooLarge when the body or the rendered email is over MAX_EMAIL_BYTES.
    Exports a span in the caller's trace; the render service runs inside its callers.
    """
    with telemetry.span(SERVICE, "render_email"):
        return _render(draft)


def _render(draft: Mapping[str, str]) -> str:
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
        font=FONT_STACK,
        text_size=TEXT_SIZE,
        line_height=TEXT_LINE_HEIGHT,
        text_color=TEXT_COLOR,
        page_bg=PAGE_BACKGROUND,
        card_bg=CARD_BACKGROUND,
        title_size=TITLE_SIZE,
        logo_width=LOGO_WIDTH,
    )
    html: str = mjml2html(source)
    if len(html.encode()) > MAX_EMAIL_BYTES:
        raise EmailTooLarge(f"rendered email is over {MAX_EMAIL_BYTES} bytes")
    return html
