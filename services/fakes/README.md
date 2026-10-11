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
- `fake_workfront`: a Workfront shaped like its REST API. `POST /oauth2/token` swaps OAuth2
  client credentials for a bearer token; every `/attask/api/v15.0/...` call without one is a
  401. `POST /proj`, `/task`, and `/appr` make projects, tasks, and approvals, idempotent per
  `externalID` (project and task) or per task (approval); a repeat task write updates the
  same task. `GET /proj/search`, `/task/search`, `/appr/search`, and `/task/{id}` read them
  back. `PUT /task/{id}` with a new `status` posts one HMAC-signed status event to the
  Campaign API webhook (`X-Workfront-Timestamp`,
  `X-Workfront-Signature: sha256=<hex of timestamp "." body>`), naming the task's
  `externalID` as `campaignId`. The client id, secret, and webhook key come from
  `WorkfrontConfig` (`ACE_WORKFRONT_*`), never from code. The chart does not deploy it yet;
  the worker and API publish to it only when `ACE_WORKFRONT_URL` is set.
