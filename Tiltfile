# Edit loop for the `ace` cluster: `make dev` (platform/dev.sh) starts Tilt on k3d-ace only.
# The chart is deployed with helm_resource (`helm upgrade --install`), not Tilt's helm():
# helm() renders with `helm template`, where `lookup` finds nothing, and its objects carry no
# release ownership, so `make up` could not later take the release over. Decisions A22.

# Only this context. Tilt refuses any other, and never the first cluster.
allow_k8s_contexts('k3d-ace')

RELEASE = 'ace'  # the release `make up` installs too
NAMESPACE = 'ace'
# Baked into the web build (apps/web/src/auth.ts). One constant for the Dex step, make status,
# and this build: platform/oidc-issuer.txt (decisions A20).
OIDC_ISSUER = str(read_file('platform/oidc-issuer.txt')).strip()

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

# One image for the API, the worker, and the fake Marketo. Saving a Python file is a live
# update: Tilt syncs it into the running pods, and the chart's file watcher (python.reload)
# restarts the process. No image rebuild and no `helm upgrade`. A dependency change
# (pyproject.toml, uv.lock) or a Dockerfile change rebuilds the image.
docker_build(
    'ace-python',
    '.',
    dockerfile='apps/python.Dockerfile',
    only=['pyproject.toml', 'uv.lock', 'apps/engine', 'apps/api', 'apps/worker', 'services'],
    ignore=['**/__pycache__', '**/*.pyc'],
    live_update=[
        fall_back_on(['pyproject.toml', 'uv.lock']),
        sync('apps', '/app/apps'),
        sync('services', '/app/services'),
    ],
)

helm_resource(
    RELEASE,
    'charts/ace',
    namespace=NAMESPACE,
    flags=['--create-namespace', '--set', 'python.reload=true'],
    deps=['charts/ace'],
    image_deps=['ace-web', 'ace-python'],
    image_keys=[
        ('web.image.repository', 'web.image.tag'),
        ('python.image.repository', 'python.image.tag'),
    ],
    labels=['ace'],
)
