# Decision: a fake CMS and a fake S3 store, both run from our Python image

Date: 2026-10-10. Status: accepted (builder's call while building #36; SPEC decision 8 says
fakes by default).

**Decision.** The CMS is a fake, `services/fakes/fake_cms`: a headless-CMS-shaped REST API
(`PUT/GET /api/pages/{slug}`, `data` envelopes) that holds pages in memory. The asset library
is a fake S3, `services/fakes/fake_s3`: path-style `PUT` and `GET` of objects, bucket create,
and ListObjectsV2 as XML. Both run from the one Python image (`python -m fake_cms`,
`python -m fake_s3`), as the fake Marketo does, and the chart deploys both in the cluster.

**Why not a small real open-source CMS.** A real CMS (Strapi, Ghost, Directus) needs its own
database, an admin user, and an API token minted by hand or by a bootstrap job. The Fast
depth harness would need a container, and the chart would need another pinned image and
secret. None of that proves anything the demo needs: the pipeline publishes a page and gets
a link back. A fake shaped like the real API proves that, runs in the harness with no outside
account, and keeps `make up` small. The adapter talks plain REST, so a real CMS can replace
the fake by changing a URL and adding a token.

**Why not MinIO or moto for S3.** Both need signed (SigV4) requests, so the worker would take
`boto3`, a new dependency in the lockfile and the image. The fake takes unsigned requests and
checks no credentials: it is a stand-in inside the cluster, not a security boundary. Object
keys are `<campaign id>/<asset name>`.

**Idempotency.** A page is written by its slug (the campaign id) and an object by its key, so
a retried publish replaces an item with itself. The receipt id is the page id or the object's
ETag, the same on every retry. The API keeps one receipt per (campaign, target) and shows
them at `GET /campaigns/{id}/receipts`.
