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

  After the first send, a simulated audience (`audience.py`) opens and clicks. Seeded
  personas score each variant by a hidden rule, so the same seed always gives the same
  events. Each event posts as a signed `open` or `click` activity once its simulated time,
  divided by the time speed, has passed. `PUT /_audience {seed, time_speed}` sets both for
  the sends that follow; `GET /_audience/events?externalId=` shows what was planned. The
  Campaign API's `GET /campaigns/{id}` shows `engagement` as opens and clicks per variant.
- `fake_cms`: a headless-CMS-shaped fake. `PUT /api/pages/{slug}` creates or replaces a
  page (idempotent per slug); `GET /api/pages[/{slug}]` reads pages back.
- `fake_s3`: a path-style S3 fake with no signature checks. `PUT /{bucket}`,
  `PUT/GET /{bucket}/{key}`, and ListObjectsV2 at `GET /{bucket}?list-type=2`.
  Why both are fakes: `docs/decisions/cms-and-asset-store.md`.
- `fake_workfront`: a Workfront shaped like its REST API. `POST /oauth2/token` swaps OAuth2
  client credentials for a bearer token; every `/attask/api/v15.0/...` call without one is a
  401. `POST /proj`, `/task`, and `/appr` make projects, tasks, and approvals, idempotent per
  `externalID` (project and task) or per task (approval); a repeat task write updates the
  same task. `GET /proj/search`, `/task/search`, `/appr/search`, and `/task/{id}` read them
  back. `PUT /task/{id}` with a new `status` posts one HMAC-signed status event to the
  Campaign API webhook (`X-Workfront-Timestamp`,
  `X-Workfront-Signature: sha256=<hex of timestamp "." body>`), naming the task's
  `externalID` as `campaignId`. The client id, secret, and webhook key come from
  `WorkfrontConfig` (`ACE_WORKFRONT_*`), never from code. The chart deploys it for the MCP server
  to read; the worker and API publish to it only when `ACE_WORKFRONT_URL` is set.
- `fake_slack`: a Slack with `POST /chat.postMessage` (bearer token, `channel` and `text`).
  A wrong token gets `{"ok": false, "error": "invalid_auth"}`. `GET /_messages` lists what it
  received. The token comes from `SlackConfig`, never from code.
- `fake_google`: a Google OAuth and Docs API. `POST /token` swaps the refresh token for an
  access token; `POST /v1/documents` creates a document and
  `POST /v1/documents/{id}:batchUpdate` inserts text. `GET /_documents` lists the documents
  with their text.

Slack and Google Docs are off unless `ACE_SLACK_TOKEN` with `ACE_SLACK_CHANNEL`, or the
`ACE_GOOGLE_CLIENT_ID`, `ACE_GOOGLE_CLIENT_SECRET`, and `ACE_GOOGLE_REFRESH_TOKEN` triple, are
set. `ACE_SLACK_URL`, `ACE_GOOGLE_TOKEN_URL`, and `ACE_GOOGLE_DOCS_URL` point them at these
stand-ins.
