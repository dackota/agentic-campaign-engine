"""The demo seed's own handling of a campaign's previews: one with no content yet is skipped,
and any other failure raises without echoing the reply body."""

import httpx
import pytest

from tests.harness import demo_seed


def _preview_client(statuses: dict[str, int]) -> httpx.Client:
    def answer(request: httpx.Request) -> httpx.Response:
        kind = request.url.path.rsplit("/preview", 1)[1].lstrip("/") or "email"
        return httpx.Response(statuses.get(kind, 200), text="secret-body")

    return httpx.Client(base_url="http://api", transport=httpx.MockTransport(answer))


def test_a_preview_with_no_content_is_skipped_and_another_failure_raises() -> None:
    campaign = {"id": "c1", "draft": {"subject": "s"}, "variant_b": None}

    with _preview_client({"social": 409}) as client:
        assets = demo_seed._assets(client, campaign)
    assert "social" not in assets["previews"]
    assert "email" in assets["previews"]

    with _preview_client({"cards": 500}) as client:
        with pytest.raises(RuntimeError) as failed:
            demo_seed._assets(client, campaign)
    assert "cards" in str(failed.value)
    assert "500" in str(failed.value)
    assert "secret-body" not in str(failed.value)
