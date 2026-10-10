# platform

Home for this part. Later tickets fill it.

- `dex/config.yaml`: Dex, the stand-in for the company login. It holds the demo users of
  Demand Gen and Product Marketing with the roles owner, approver, and viewer, and the
  web app's public client (authorization code flow with PKCE). Every demo user's
  password is `demo-password`: demo only. The test harness (`tests/harness/dex.py`)
  starts it in Docker and rewrites the issuer and redirect URIs to its ports.
