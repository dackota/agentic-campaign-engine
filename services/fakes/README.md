# services/fakes

Fake third-party services. Later tickets add more.

- `fake_marketo`: a minimal Marketo. `POST /rest/v1/emails/send` returns a receipt; a repeat
  send for the same `campaign_id` returns the same receipt and sends nothing. `GET /_sends`
  lists what it delivered, so a test can check a send from the outside.
