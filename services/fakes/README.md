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
