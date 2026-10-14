"""One trace per campaign, in process with the in-memory span exporter: `POST /campaigns` is the
root of the campaign's trace, and every later request for the campaign from someone allowed to
see it (a signed-in user of its team, or a webhook with a good signature) joins it. A request
from another team, with no valid token, or with a bad signature starts a trace of its own. Row
level security decides who is on the campaign's team, so those runs use a real Postgres. The
trace across all six services is the API test's."""

import json
import random
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from ace_engine import db, telemetry
from ace_engine.webhooks import MARKETO_HEADERS, SignatureHeaders
from campaign_api.main import create_app
from campaign_api.trace_middleware import WebhookSigner, _campaign_in, _token
from campaign_api.trace_middleware import reset as reset_trace_cache
from campaign_api.webhook_routes import WORKFRONT_HEADERS
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from tests.support.app import StubTemporal, StubVerifier
from tests.support.campaigns import add_campaign, add_run_event, set_status
from tests.support.dag import GOOD_DRAFT, OWNER, REPORT, signed_headers, workfront_signed_headers
from tests.support.settings import DUMMY_SETTINGS, unit_settings
from tests.support.telemetry import install_span_exporter

OTHER_TEAM_OWNER = "pm-owner@demo.example"
MARKETO_SECRET = DUMMY_SETTINGS.marketo_webhook_secret
MARKETO_PATH = "/webhooks/marketo"


def _as(email: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {email}"}


@pytest.fixture
def spans() -> InMemorySpanExporter:
    exporter = install_span_exporter()
    exporter.clear()
    return exporter


def _client_on(engine: Engine) -> Iterator[TestClient]:
    reset_trace_cache()
    app = create_app(
        unit_settings(),
        engine=engine,
        verifier=StubVerifier(),  # type: ignore[arg-type]
        temporal=StubTemporal(),  # type: ignore[arg-type]
    )
    with TestClient(app) as client:
        yield client
    reset_trace_cache()


@pytest.fixture
def client(spans: InMemorySpanExporter, sqlite_engine: Engine) -> Iterator[TestClient]:
    yield from _client_on(sqlite_engine)


@pytest.fixture
def secured_client(spans: InMemorySpanExporter, postgres_engine: Engine) -> Iterator[TestClient]:
    """The same app on a Postgres with row-level security, where a team sees only its own."""
    yield from _client_on(postgres_engine)


def _create(client: TestClient) -> str:
    response = client.post("/campaigns", json={"report": REPORT}, headers=_as(OWNER))
    assert response.status_code == 201, response.text
    created: str = response.json()["id"]
    return created


def campaign_spans(exporter: InMemorySpanExporter, campaign_id: str) -> list[ReadableSpan]:
    """The spans of one campaign: the trace whose root is the request span of its
    `POST /campaigns`, which names the campaign."""
    finished = exporter.get_finished_spans()
    roots = [
        s
        for s in finished
        if s.attributes
        and s.attributes.get(telemetry.CAMPAIGN_ATTRIBUTE) == campaign_id
        and s.name.startswith("POST /campaigns")
    ]
    assert len(roots) == 1, "the create request's span names the campaign"
    return [s for s in finished if s.context.trace_id == roots[0].context.trace_id]


def _from_a_trace_of_its_own(send: Callable[[dict[str, str]], httpx.Response]) -> tuple[int, int]:
    """Send a request that carries a trace of the test's own; return its status and trace id.
    The request's server span lands in that trace unless the API puts it in a campaign's. The
    test holds no span itself: with one active, the instrumentation would nest the request in
    it and ignore the header, as it does for a call inside a process."""
    trace_id, span_id = random.getrandbits(128) or 1, random.getrandbits(64) or 1
    carried = {telemetry.TRACEPARENT_HEADER: f"00-{trace_id:032x}-{span_id:016x}-01"}
    return send(carried).status_code, trace_id


def _server_spans(exporter: InMemorySpanExporter, trace_id: int) -> list[ReadableSpan]:
    return [
        s
        for s in exporter.get_finished_spans()
        if s.context.trace_id == trace_id and s.kind is SpanKind.SERVER
    ]


def _assert_outside_campaign_trace(
    exporter: InMemorySpanExporter, campaign_id: str, trace_id: int
) -> None:
    own = _server_spans(exporter, trace_id)
    assert own, "the request's server span stays in the caller's trace"
    in_campaign_trace = {s.context.trace_id for s in campaign_spans(exporter, campaign_id)}
    assert in_campaign_trace.isdisjoint({s.context.trace_id for s in own})


def _open_event(campaign_id: str) -> bytes:
    event = {"id": str(uuid.uuid4()), "type": "open", "campaignId": campaign_id, "variant": "A"}
    return json.dumps(event).encode()


def test_the_post_campaigns_request_is_the_root_of_one_trace_for_every_request(
    client: TestClient, sqlite_engine: Engine, spans: InMemorySpanExporter
) -> None:
    campaign_id = _create(client)
    set_status(sqlite_engine, uuid.UUID(campaign_id), db.AWAITING_APPROVAL)
    approver = _as("dg-approver@demo.example")
    assert client.post(f"/campaigns/{campaign_id}/approve", headers=approver).status_code == 202
    assert client.get(f"/campaigns/{campaign_id}", headers=_as(OWNER)).status_code == 200
    body = _open_event(campaign_id)
    hook = client.post(MARKETO_PATH, content=body, headers=signed_headers(MARKETO_SECRET, body))
    assert hook.status_code == 202, hook.text

    in_trace = campaign_spans(spans, campaign_id)

    roots = [s for s in in_trace if s.parent is None]
    assert len(roots) == 1
    assert roots[0].name.startswith("POST /campaigns")
    servers = {s.name for s in in_trace if s.kind is SpanKind.SERVER}
    assert any(n.startswith("POST /campaigns/{campaign_id}/approve") for n in servers), servers
    assert any(n.startswith("POST /webhooks/marketo") for n in servers), servers
    assert any(n.startswith("GET /campaigns/{campaign_id}") for n in servers), servers
    names = {s.name for s in in_trace}
    assert {"campaign.start", "campaign.approve"} <= names


def test_a_second_campaign_is_a_second_trace(
    client: TestClient, spans: InMemorySpanExporter
) -> None:
    first, second = _create(client), _create(client)

    first_ids = {s.context.trace_id for s in campaign_spans(spans, first)}
    second_ids = {s.context.trace_id for s in campaign_spans(spans, second)}

    assert len(first_ids) == len(second_ids) == 1
    assert first_ids != second_ids


def test_the_campaign_teams_requests_join_its_trace(
    client: TestClient, spans: InMemorySpanExporter, sqlite_engine: Engine
) -> None:
    campaign_id = _create(client)
    set_status(sqlite_engine, uuid.UUID(campaign_id), db.AWAITING_APPROVAL)
    add_run_event(sqlite_engine, uuid.UUID(campaign_id), db.RUN_STEP, db.AWAITING_APPROVAL)
    with Session(sqlite_engine) as session, session.begin():
        session.get_one(db.Campaign, uuid.UUID(campaign_id)).draft = GOOD_DRAFT
    path = f"/campaigns/{campaign_id}"
    sent: list[tuple[int, int]] = []

    def get(
        url: str, headers: dict[str, str] | None = None, params: dict[str, str] | None = None
    ) -> Callable[[dict[str, str]], httpx.Response]:
        return lambda carried: client.get(
            url, headers={**carried, **(headers or {})}, params=params
        )

    for send in (
        get(f"{path}/steps", headers=_as(OWNER)),
        get(f"{path}/preview", params={"access_token": OWNER}),
        get(f"{path}/events", params={"access_token": OWNER}),
        get(f"{path}/events", headers=_as(OWNER)),
        get(f"{path}/steps", headers=_as(OWNER)),
    ):
        sent.append(_from_a_trace_of_its_own(send))

    assert [status for status, _ in sent] == [200] * len(sent)
    campaign_trace = campaign_spans(spans, campaign_id)[0].context.trace_id
    joined = {s.name for s in _server_spans(spans, campaign_trace)}
    for tail in ("steps", "preview", "events"):
        assert f"GET /campaigns/{{campaign_id}}/{tail}" in joined, joined
    # None of them stayed in the trace the caller sent.
    for _, trace_id in sent:
        assert _server_spans(spans, trace_id) == []


@pytest.mark.parametrize("by_query", [False, True], ids=["header token", "access_token query"])
def test_another_teams_request_is_not_in_the_campaign_trace(
    secured_client: TestClient, spans: InMemorySpanExporter, by_query: bool
) -> None:
    # The create request remembers the campaign's traceparent: the other team must not get it.
    campaign_id = _create(secured_client)
    other = (
        {"params": {"access_token": OTHER_TEAM_OWNER}}
        if by_query
        else {"headers": _as(OTHER_TEAM_OWNER)}
    )
    url = f"/campaigns/{campaign_id}" + ("/events" if by_query else "")

    status, trace_id = _from_a_trace_of_its_own(
        lambda carried: secured_client.get(
            url, headers={**carried, **other.get("headers", {})}, params=other.get("params")
        )
    )

    assert status == 404
    _assert_outside_campaign_trace(spans, campaign_id, trace_id)


def test_a_trace_one_team_read_is_not_served_to_another_from_the_cache(
    secured_client: TestClient, spans: InMemorySpanExporter
) -> None:
    campaign_id = _create(secured_client)
    reset_trace_cache()
    url = f"/campaigns/{campaign_id}"
    own_team = _from_a_trace_of_its_own(
        lambda carried: secured_client.get(url, headers={**carried, **_as(OWNER)})
    )
    again = _from_a_trace_of_its_own(
        lambda carried: secured_client.get(url, headers={**carried, **_as(OWNER)})
    )

    status, trace_id = _from_a_trace_of_its_own(
        lambda carried: secured_client.get(url, headers={**carried, **_as(OTHER_TEAM_OWNER)})
    )

    assert (own_team[0], again[0], status) == (200, 200, 404)
    assert _server_spans(spans, own_team[1]) == [] == _server_spans(spans, again[1])
    _assert_outside_campaign_trace(spans, campaign_id, trace_id)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-token"}])
def test_a_request_without_a_valid_token_is_not_in_the_campaign_trace(
    client: TestClient, spans: InMemorySpanExporter, headers: dict[str, str]
) -> None:
    campaign_id = _create(client)

    status, trace_id = _from_a_trace_of_its_own(
        lambda carried: client.get(f"/campaigns/{campaign_id}", headers={**carried, **headers})
    )

    assert status == 401
    _assert_outside_campaign_trace(spans, campaign_id, trace_id)


@pytest.mark.parametrize("signed", ["wrong secret", "no signature"])
def test_an_unsigned_webhook_is_not_in_the_campaign_trace(
    client: TestClient, spans: InMemorySpanExporter, signed: str
) -> None:
    campaign_id = _create(client)
    body = _open_event(campaign_id)
    headers = (
        signed_headers("not-the-secret", body)
        if signed == "wrong secret"
        else {"Content-Type": "application/json"}
    )

    status, trace_id = _from_a_trace_of_its_own(
        lambda carried: client.post(MARKETO_PATH, content=body, headers={**carried, **headers})
    )

    assert status == 401
    _assert_outside_campaign_trace(spans, campaign_id, trace_id)


def test_a_malformed_webhook_body_gets_the_routes_answer(client: TestClient) -> None:
    body = b'{"campaignId": '

    response = client.post(MARKETO_PATH, content=body, headers=signed_headers(MARKETO_SECRET, body))

    assert response.status_code == 422, response.text


def test_a_signed_body_the_middleware_read_is_still_whole_for_the_route(
    client: TestClient, sqlite_engine: Engine
) -> None:
    campaign_id = str(add_campaign(sqlite_engine))
    body = _open_event(campaign_id)

    response = client.post(MARKETO_PATH, content=body, headers=signed_headers(MARKETO_SECRET, body))

    assert response.status_code == 202, response.text
    assert response.json()["id"] == json.loads(body)["id"]


@pytest.mark.parametrize("key", ["http.url", "url.full", "http.target", "url.path"])
def test_no_span_attribute_keeps_the_access_token_of_the_event_stream(
    spans: InMemorySpanExporter, key: str
) -> None:
    """The browser sends its bearer token in the event stream's query string, so no span
    attribute may keep a query."""
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span(
        "stream", attributes={key: "/events?access_token=SECRET"}
    ) as span:
        span.set_attribute(telemetry.QUERY_ATTRIBUTE, "access_token=SECRET")
        telemetry._drop_query(span)

    [exported] = [s for s in spans.get_finished_spans() if s.name == "stream"]
    assert exported.attributes is not None
    assert exported.attributes[key] == "/events"
    assert exported.attributes[telemetry.QUERY_ATTRIBUTE] == ""
    assert "SECRET" not in str(dict(exported.attributes))


def test_a_request_with_the_token_in_the_query_exports_no_span_that_holds_it(
    client: TestClient, spans: InMemorySpanExporter, sqlite_engine: Engine
) -> None:
    campaign_id = uuid.UUID(_create(client))
    add_run_event(sqlite_engine, campaign_id, db.RUN_STEP, db.AWAITING_APPROVAL)

    response = client.get(f"/campaigns/{campaign_id}/events", params={"access_token": OWNER})

    assert response.status_code == 200
    exported = [
        s
        for s in spans.get_finished_spans()
        if s.name == "GET /campaigns/{campaign_id}/events"
        and (s.attributes or {}).get("http.method") == "GET"
    ]
    assert exported, "the GET /events server span was not exported"
    held = [
        (s.name, key)
        for s in spans.get_finished_spans()
        for key, value in (s.attributes or {}).items()
        if OWNER in str(value) or "access_token" in str(value)
    ]
    assert held == []


@pytest.mark.parametrize(
    ("names", "sign"),
    [(MARKETO_HEADERS, signed_headers), (WORKFRONT_HEADERS, workfront_signed_headers)],
    ids=["marketo", "workfront"],
)
def test_a_webhook_is_signed_only_with_its_senders_secret_and_header_names(
    names: SignatureHeaders, sign: Callable[[str, bytes], dict[str, str]]
) -> None:
    signer = WebhookSigner("secret", names)
    body = b'{"campaignId": "x"}'

    assert signer.signed(sign("secret", body), body) is True
    assert signer.signed(sign("another", body), body) is False
    assert signer.signed({}, body) is False
    assert signer.signed(sign("secret", body), body + b" ") is False


def test_the_token_is_read_from_the_header_before_the_query() -> None:
    def scope(headers: list[tuple[bytes, bytes]], query: bytes) -> dict[str, Any]:
        return {"type": "http", "headers": headers, "query_string": query}

    bearer = [(b"authorization", b"Bearer from-header")]

    assert _token(scope(bearer, b"access_token=from-query")) == "from-header"
    assert _token(scope([], b"access_token=from-query")) == "from-query"
    assert _token(scope([(b"authorization", b"Basic abc")], b"")) is None
    assert _token(scope([(b"authorization", b"Bearer ")], b"")) is None
    assert _token(scope([], b"")) is None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            b'{"campaignId": "11111111-2222-3333-4444-555555555555"}',
            "11111111-2222-3333-4444-555555555555",
        ),
        (b'{"campaignId": "not-a-uuid"}', None),
        (b'{"campaignId": 7}', None),
        (b"[]", None),
        (b"{not json", None),
        (b"", None),
    ],
)
def test_the_campaign_a_webhook_names_is_read_from_its_body(
    body: bytes, expected: str | None
) -> None:
    found = _campaign_in(body)

    assert (None if found is None else str(found)) == expected
