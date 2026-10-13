"""The learnings store's embeddings: a fixed stand-in at fast depth, the gateway at live."""

import json
import math

import httpx
from ace_engine import learnings
from ace_engine.db import EMBEDDING_DIMENSIONS

GATEWAY = "http://gateway.test/demand-gen/v1"
MODEL = "text-embedding-3-small"


def test_stand_in_embedding_is_fixed_unit_length_and_of_the_column_size() -> None:
    first = learnings.stand_in_embedding("Patch your VPN today")
    again = learnings.stand_in_embedding("Patch your VPN today")
    other = learnings.stand_in_embedding("Quarterly webinar invite")

    assert first == again
    assert len(first) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.fsum(x * x for x in first), 1.0, rel_tol=1e-9)
    assert first != other
    # Text that shares words sits closer than text that shares none.
    near = learnings.stand_in_embedding("patch the VPN now")
    assert _dot(first, near) > _dot(first, other)


def test_stand_in_embedding_of_blank_text_is_still_a_valid_vector() -> None:
    blank = learnings.stand_in_embedding("   ")

    assert len(blank) == EMBEDDING_DIMENSIONS
    assert math.isclose(math.fsum(x * x for x in blank), 1.0, rel_tol=1e-9)


def test_live_embedder_asks_the_gateway_for_an_embedding() -> None:
    seen: list[httpx.Request] = []
    vector = [0.5] * EMBEDDING_DIMENSIONS

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

    client = httpx.Client(transport=httpx.MockTransport(reply))
    embed = learnings.GatewayEmbedder(client, GATEWAY, MODEL)

    assert embed("Patch your VPN today") == vector
    (request,) = seen
    assert str(request.url) == f"{GATEWAY}/embeddings"
    assert json.loads(request.content) == {
        "model": MODEL,
        "input": "Patch your VPN today",
        "dimensions": EMBEDDING_DIMENSIONS,
    }


def test_live_embedder_refuses_a_vector_of_the_wrong_size() -> None:
    def reply(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 2.0]}]})

    embed = learnings.GatewayEmbedder(
        httpx.Client(transport=httpx.MockTransport(reply)), GATEWAY, MODEL
    )

    try:
        embed("x")
    except ValueError as exc:
        assert str(EMBEDDING_DIMENSIONS) in str(exc)
    else:
        raise AssertionError("a short vector was accepted")


def _dot(a: list[float], b: list[float]) -> float:
    return math.fsum(x * y for x, y in zip(a, b, strict=True))
