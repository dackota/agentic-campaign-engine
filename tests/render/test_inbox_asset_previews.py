"""What an approver is shown for the social and design assets of the inbox: the social posts'
text, escaped, and the design cards as images that never run as part of the page."""

import html
import random

import pytest
from render_service.assets import render_cards_html, render_social_html

from tests.support.scripted_outputs import scripted_output

SEED = 21
CASES = 200
ALPHABET = "ab <>&\"'/;=()xyz"
SVG = '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _post(text: str) -> dict[str, object]:
    return {"posts": [{"channel": "x", "text": text}]}


@pytest.mark.parametrize("text", ["a<b", "<script>alert(1)</script>", "say \"hi\" & 'bye'"])
def test_a_social_post_previews_its_text_escaped(text: str) -> None:
    assert html.escape(text) in render_social_html(_post(text))


def test_no_social_post_text_ever_reaches_the_page_as_markup() -> None:
    rng = random.Random(SEED)
    for _ in range(CASES):
        text = "".join(rng.choices(ALPHABET, k=rng.randint(1, 40)))

        page = render_social_html(_post(text))

        assert html.escape(text) in page
        if "<" in text:
            assert text not in page


def test_every_scripted_social_post_is_in_its_preview() -> None:
    social = scripted_output("social")

    page = render_social_html(social)

    assert all(html.escape(post["text"]) in page for post in social["posts"])


def test_the_design_asset_previews_one_image_per_card_and_the_brand_logo() -> None:
    design = scripted_output("design")

    page = render_cards_html(design)

    assert page.count("<img") == len(design["cards"]) + 1
    assert "<svg" not in page


def test_a_card_with_a_script_in_it_is_an_image_not_page_markup() -> None:
    page = render_cards_html({"cards": [{"name": "evil.svg", "svg": SVG}]})

    assert "<script" not in page and "alert(1)" not in page
    assert page.count("<img") == 2
