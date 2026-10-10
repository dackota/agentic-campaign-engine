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
