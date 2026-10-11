# services/fakes

Fake third-party services. Later tickets add more.

- `fake_marketo`: a Marketo shaped like the real REST API. `POST /identity/oauth/token`
  swaps OAuth2 client credentials for a bearer token; every `/rest/...` call without one is
  a 401. `POST /rest/asset/v1/programs.json` creates a program, idempotent per
  `externalId`. `POST /rest/asset/v1/program/{id}/abSend.json` sends the A and B variants
  once per program; a repeat returns the same receipt. The first send posts one
  HMAC-signed `send` activity per variant to the Campaign API webhook
  (`X-Marketo-Timestamp`, `X-Marketo-Signature: sha256=<hex of timestamp "." body>`).
  `GET /rest/asset/v1/programs.json?externalId=` shows programs and their sends, so a test
  can check a send from the outside. The client id, secret, and webhook key come from
  `MarketoConfig`, never from code.
- `fake_cms`: a headless-CMS-shaped fake. `PUT /api/pages/{slug}` creates or replaces a
  page (idempotent per slug); `GET /api/pages[/{slug}]` reads pages back.
- `fake_s3`: a path-style S3 fake with no signature checks. `PUT /{bucket}`,
  `PUT/GET /{bucket}/{key}`, and ListObjectsV2 at `GET /{bucket}?list-type=2`.
  Why both are fakes: `docs/decisions/cms-and-asset-store.md`.
