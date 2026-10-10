# Edit loop for the `ace` cluster: `make dev` (platform/dev.sh) starts Tilt on k3d-ace only.
# The chart is deployed with helm_resource (`helm upgrade --install`), not Tilt's helm():
# helm() renders with `helm template`, where `lookup` finds nothing, and its objects carry no
# release ownership, so `make up` could not later take the release over. Decisions A22.

# Only this context. Tilt refuses any other, and never the first cluster.
allow_k8s_contexts('k3d-ace')

RELEASE = 'ace'  # the release `make up` installs too
NAMESPACE = 'ace'
# Baked into the web build (apps/web/src/auth.ts); the Dex issuer from decisions A20.
OIDC_ISSUER = 'http://dex.ace.localhost:15656/dex'

# tilt-extensions, pinned by commit (docs/pinned-versions.md).
v1alpha1.extension_repo(
    name='ace-tilt-extensions',
    url='https://github.com/tilt-dev/tilt-extensions',
    ref='7f9f376076bbe18cb76474d7cdda16894d139b81',
)
v1alpha1.extension(name='helm_resource', repo_name='ace-tilt-extensions', repo_path='helm_resource')
load('ext://helm_resource', 'helm_resource')

# Saving a web source file rebuilds this image and replaces the web pod.
docker_build(
    'ace-web',
    '.',
    dockerfile='apps/web/Dockerfile',
    build_args={'VITE_OIDC_ISSUER': OIDC_ISSUER},
    only=['package.json', 'pnpm-workspace.yaml', 'pnpm-lock.yaml', 'apps/web'],
    ignore=['apps/web/node_modules', 'apps/web/dist', 'apps/web/e2e', 'apps/web/test-results'],
)

helm_resource(
    RELEASE,
    'charts/ace',
    namespace=NAMESPACE,
    flags=['--create-namespace'],
    deps=['charts/ace'],
    image_deps=['ace-web'],
    image_keys=[('web.image.repository', 'web.image.tag')],
    labels=['ace'],
)
