"""The fake CMS and the fake S3 store: shaped like the real APIs, idempotent per key."""

from xml.etree import ElementTree

from fake_cms.app import create_app as create_cms
from fake_s3.app import create_app as create_s3
from fastapi.testclient import TestClient

S3_NAMESPACE = "{http://s3.amazonaws.com/doc/2006-03-01/}"
PAGE = {"title": "Patch now", "body": "<p>Hi</p>", "callToAction": "Patch"}


def test_same_page_twice_stays_one_page_with_the_same_id() -> None:
    cms = TestClient(create_cms())

    first = cms.put("/api/pages/c-1", json=PAGE)
    again = cms.put("/api/pages/c-1", json=PAGE)

    assert first.status_code == again.status_code == 200
    assert first.json()["data"]["id"] == again.json()["data"]["id"]
    assert [p["slug"] for p in cms.get("/api/pages").json()["data"]] == ["c-1"]
    assert cms.get("/api/pages/c-1").json()["data"]["writes"] == 2


def test_missing_page_is_404_and_a_blank_title_is_422() -> None:
    cms = TestClient(create_cms())

    assert cms.get("/api/pages/none").status_code == 404
    assert cms.put("/api/pages/c-1", json={**PAGE, "title": ""}).status_code == 422


def test_same_object_twice_stays_one_object_with_the_same_etag() -> None:
    s3 = TestClient(create_s3())
    assert s3.put("/b").status_code == 200

    first = s3.put("/b/c-1/email-a.html", content=b"<p>a</p>")
    again = s3.put("/b/c-1/email-a.html", content=b"<p>a</p>")

    assert first.headers["ETag"] == again.headers["ETag"]
    listing = ElementTree.fromstring(s3.get("/b", params={"list-type": "2"}).text)
    assert [k.text for k in listing.iter(f"{S3_NAMESPACE}Key")] == ["c-1/email-a.html"]
    assert s3.get("/b/c-1/email-a.html").content == b"<p>a</p>"


def test_object_in_a_missing_bucket_is_404() -> None:
    s3 = TestClient(create_s3())

    assert s3.put("/nope/k", content=b"x").status_code == 404
    assert s3.get("/nope", params={"list-type": "2"}).status_code == 404
