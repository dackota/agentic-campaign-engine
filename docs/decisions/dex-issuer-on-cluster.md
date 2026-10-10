# Decision: Dex on the cluster is a platform piece, with one issuer URL for the browser and the pods, `http://dex.ace.localhost:15656/dex`

Date: 2026-10-10. Status: proposed (plan for #26, ticket 04; the user chose Dex in `platform/`).

Dex, the stand-in company IdP, is installed by a step under `platform/dex/` that `make up` runs in
its platform stage, not by our app chart: slice #3 keeps `charts/` for our services and platform
pieces in `platform/`. The same step applies the k3s CoreDNS override in `kube-system`.

The API checks the token's `iss` against its configured issuer and fetches signing keys from
`<issuer>/keys`, and the web app bakes the issuer into its build, so the browser and the API pod
must use the same URL. On the `ace` cluster the issuer is `http://dex.ace.localhost:15656/dex`.
Browsers and curl resolve any `*.localhost` name to 127.0.0.1, where the k3d load balancer maps
port 15656 to Dex. Inside the cluster a k3s CoreDNS rewrite (`coredns-custom`) sends the same name
to the Dex Service, which listens on 15656. Port 15656 is chosen because the browser seam's own Dex
binds 15556 (`apps/web/playwright.config.ts`), and both must run at once. This needs no code change.
The rejected alternative, a second "JWKS URL" setting in the API, is the fallback if the rewrite
fails on k3s.
