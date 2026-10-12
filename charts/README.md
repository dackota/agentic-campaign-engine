# charts

`ace/` is the one chart for our services: the web app, the Campaign API, the worker, the
fake Marketo, Postgres, and the Temporal dev server (SQLite on a volume).

- Release `ace` in namespace `ace`. `make dev` (Tilt, `helm_resource`) and `make up` both
  run `helm upgrade --install` on that one release.
- The web image comes from `web.image.*`; the web app is on the NodePort the cluster maps
  to host port 15180.
- The API, worker, and fake Marketo share one Python image (`python.image.*`, built from
  `apps/python.Dockerfile`) and differ by command (`python -m <package>`). Their settings
  are `ACE_*` variables, read by `apps/engine/ace_engine/env.py`.
- App secrets: one Secret, `<release>-app`, holds the Postgres password and the Marketo
  client and webhook secrets. The chart generates each value on first install and keeps it
  on every upgrade (Helm `lookup`); pods read them only by `secretKeyRef`. No value is in a
  values file. Read its identity with `-o jsonpath='{.metadata.uid}'`, never its data.
- `python.reload` (set by `make dev`) runs each Python process under a file watcher, so a
  saved `.py` file that Tilt syncs into the pod restarts the process.
- `worker.agentUrl` is the kagent controller's A2A base URL. At `depth: live` the worker
  adds the role's agent name (`ace-email-writer`, ...) to it. `make up` installs those Agents.
- Platform pieces (Dex, CoreDNS override, Substrate, kagent, agentgateway) stay in
  `platform/`, not here. The API trusts the issuer in `platform/oidc-issuer.txt`
  (`api.oidcIssuer`; a test checks they match).
