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
