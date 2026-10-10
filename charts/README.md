# charts

`ace/` is the one chart for our services. It holds the web app so far; the API, worker,
fake Marketo, Postgres, and Temporal dev server join it in later tickets.

- Release `ace` in namespace `ace`. `make dev` (Tilt, `helm_resource`) and `make up` both
  run `helm upgrade --install` on that one release.
- The web image comes from `web.image.*`; the web app is on the NodePort the cluster maps
  to host port 15180.
- Platform pieces (Dex, CoreDNS override, Substrate, kagent, agentgateway) stay in
  `platform/`, not here.
