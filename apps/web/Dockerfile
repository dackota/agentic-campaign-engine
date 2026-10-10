# Web image. Build from the repo root: docker build -f apps/web/Dockerfile .
# Base images are pinned by index digest (docs/pinned-versions.md).
FROM node:22-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS build
RUN npm install --global pnpm@9.15.9
WORKDIR /repo
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile --filter web...
COPY apps/web apps/web
# Read by apps/web/src/auth.ts at build time.
ARG VITE_OIDC_ISSUER=http://127.0.0.1:5556/dex
ARG VITE_OIDC_CLIENT_ID=ace-web
ENV VITE_OIDC_ISSUER=$VITE_OIDC_ISSUER VITE_OIDC_CLIENT_ID=$VITE_OIDC_CLIENT_ID
RUN pnpm --filter web exec vite build

FROM nginxinc/nginx-unprivileged:1.31.5-alpine@sha256:19c132c9ab02d3b783f478743dafc7a7f42e27aa7d2bdcbec1bb1128ca8f2a07
# The image's entrypoint renders /etc/nginx/templates/*.template with the environment.
COPY apps/web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
# Defaults for a bare `docker run`; the chart sets all three (API_HOST fully qualified).
ENV API_HOST=api API_PORT=8000 DNS_RESOLVER=kube-dns.kube-system.svc.cluster.local
EXPOSE 8080
