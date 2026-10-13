# Decision: Helm for our services, Tilt for the edit loop, GHCR images pinned by digest

Status: accepted. Decided in planning (SPEC.md Decisions, row 15). No Argo.

## Decision

- **Helm.** One chart, `charts/ace/`, installs our services as the release `ace` in the
  namespace `ace`. `make up` and `make dev` both run `helm upgrade --install` on it.
- **Tilt.** `make dev` (`platform/dev.sh`, `Tiltfile`) rebuilds and replaces the web pod when
  a web file is saved. It is allowed on the `k3d-ace` context only.
- **GHCR with digest pins.** On a push to main, `.github/workflows/publish-images.yml`
  builds the two images, pushes them to GHCR, checks the packages stay private, signs each
  digest with cosign, verifies the signature with the committed `cosign.pub`, and lists the
  `image@sha256:` lines in the job summary. Pull requests only build
  (`.github/workflows/images.yml`); they never push or sign.
- Third-party versions and digests are pinned in `docs/pinned-versions.md`.

## Why

kagent wants images pinned by digest, so a tag is not enough. Argo CD was already shown in
the last repo, so it would add weight and no new evidence. Helm plus Tilt is the smaller
loop for one laptop cluster.

## Trade-offs

- The signed-image path only runs after a merge to main, so its live proof is owed until
  then (see the README proof table).
- `make up` builds and pushes to the cluster's own registry rather than pulling from GHCR.
  GHCR is for the signed, shareable build.

## Proof

`tests/tooling/test_chart.py`, `tests/tooling/test_tiltfile.py`,
`tests/tooling/test_image_build_workflow.py`, `tests/tooling/test_publish_images_workflow.py`.
