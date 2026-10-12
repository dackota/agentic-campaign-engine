"""Stub programs and the make runner shared by the platform tooling tests."""

import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DOCKER_STUB = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
if { [ -n "$STUB_FAIL" ] && [ "$1" != info ]; } || [ "$STUB_DOCKER_FAIL" = "$1 $2" ]; then
  echo "docker: daemon unreachable" >&2; exit 1
fi
case "$1 $2" in
  "info --format") echo "${STUB_MEM_TOTAL:-25159827456}" ;;
  "stats --no-stream") echo "${STUB_MEM_USED:-3.54GiB / 23.4GiB}" ;;
  "port ace-registry") echo "5000/tcp -> 0.0.0.0:62546" ;;
  "image inspect") echo "sha256:0123456789abcdef0123456789abcdef" ;;
  "build "*)
    if [ -n "$STUB_BUILD_FAIL" ]; then echo "build broke" >&2; exit 1; fi ;;
  "volume ls") [ -n "$STUB_VOLUME" ] && echo "ace-ate"; echo "ace-ate-old" ;;
esac
exit 0
"""
K3D_STUB = """#!/bin/sh
echo "k3d $*" >> "$STUB_LOG"
if [ -n "$STUB_FAIL" ] || [ "$STUB_K3D_FAIL" = "$1 $2" ]; then
  echo "k3d: docker daemon unreachable" >&2; exit 1
fi
case "$1 $2" in
  "cluster list") [ -n "$STUB_CLUSTER" ] && echo "ace 1/1 0/0 true"; echo "ace-old 1/1 0/0 true" ;;
  "registry list")
    # The registry vanishes once deleted, unless STUB_REGISTRY_SURVIVES says delete does nothing.
    if [ -n "$STUB_REGISTRY" ] && { [ -n "$STUB_REGISTRY_SURVIVES" ] \\
      || ! grep -qx "k3d registry delete ace-registry" "$STUB_LOG"; }; then echo "ace-registry"; fi
    echo "ace-registry-old" ;;
esac
exit 0
"""

KEY = "sk-secret-value-never-shown"

KUBECTL_STUB = """#!/bin/sh
echo "kubectl $*" >> "$STUB_LOG"
case "$*" in
  *apply*"-f "*)
    if [ -n "$STUB_APPLY_FAIL" ]; then
      case "$*" in *"$STUB_APPLY_FAIL"*) echo "apply refused" >&2; exit 1 ;; esac
    fi
    # Keep every applied manifest file, so tests can read what a step sent to the cluster.
    f=""; prev=""
    for a in "$@"; do [ "$prev" = -f ] && f="$a"; prev="$a"; done
    if [ -f "$f" ]; then { echo "---"; cat "$f"; } >> "$STUB_LOG.applied"; fi ;;
esac
case "$*" in
  *"get secret"*"-o name"*)
    if [ -n "$STUB_SECRET_FAIL" ]; then echo "kubectl: forbidden" >&2; exit 1; fi
    if [ -n "$STUB_INSTALLED" ]; then
      for s in service-dns-ca-pool pod-identity-ca-pool actor-id-jwt-pool \\
        actor-id-ca-pool egress-mitm-ca-pool; do
        [ "$s" = "$STUB_MISSING_SECRET" ] || echo "secret/$s"
      done
    fi ;;
  *"rollout status"*)
    if [ -n "$STUB_ROLLOUT_FAIL" ]; then
      case "$*" in *"$STUB_ROLLOUT_FAIL"*) echo "rollout stuck" >&2; exit 1 ;; esac
    fi ;;
  *"get agent"*) echo "${STUB_AGENT_READY:-True}" ;;
  *"wait"*) [ -n "$STUB_WAIT_FAIL" ] && { echo "timed out" >&2; exit 1; } ;;
  *Ready*) echo True ;;
  *kubeletVersion*) echo "v1.37.1+k3s1" ;;
esac
exit 0
"""
HELM_STUB = """#!/bin/sh
echo "helm $*" >> "$STUB_LOG"
if [ "$3" = list ]; then
  if [ -n "$STUB_HELM_FAIL" ]; then echo "helm: cluster unreachable" >&2; exit 1; fi
  if [ -n "$STUB_INSTALLED" ]; then
    for r in substrate-crds substrate kagent-crds kagent agentgateway-crds agentgateway; do
      [ "$r" = "$STUB_MISSING_RELEASE" ] || echo "$r"
    done
  fi
fi
exit 0
"""
CURL_STUB = """#!/bin/sh
echo "curl $*" >> "$STUB_LOG"
case "$*" in
  *openid-configuration*)
    if [ -n "$STUB_DEX_FAIL" ]; then echo "curl: (7) connection refused" >&2; exit 7; fi
    printf '{\n  "issuer": "%s"\n}\n' "${STUB_DEX_ISSUER:-http://dex.ace.localhost:15656/dex}"
    exit 0 ;;
esac
out=""
while [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done
echo "not the real binary" > "$out"
exit 0
"""
ATE_STUB = "#!/bin/sh\nexit 0\n"
SPIKE_STUB = """#!/bin/sh
echo "SPIKE $(basename "$0") KCTX=$KCTX AGENT=$AGENT HARNESS=$HARNESS \\
WORKER_IMAGE=${WORKER_IMAGE:+set} OTEL=${ACE_OTEL_ENDPOINT:+set}" >> "$STUB_LOG"
[ "$(basename "$0")" = "$STUB_SPIKE_FAIL" ] && { echo "$0 failed" >&2; exit 1; }
if [ "$(basename "$0")" = a2a-smoke.sh ]; then
  n="$(cat "$STUB_LOG.smoke" 2>/dev/null || echo 0)"
  echo $((n + 1)) > "$STUB_LOG.smoke"
  if [ "$n" -lt "${STUB_SMOKE_BUSY:-0}" ]; then
    echo 'FAIL: no answer in response: {"error":{"code":-32004,"message":"not accepted"}}' >&2
    exit 1
  fi
  [ -z "$STUB_SMOKE_OTHER_FAIL" ] || { echo "FAIL: A2A request failed" >&2; exit 1; }
  echo 42
fi
exit 0
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def run_make(
    tmp_path: Path,
    *args: str,
    env_text: str | None = f"OPENCODE_KEY={KEY}\n",
    ate: bool = True,
    **stub_env: str,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    ate_dir = tmp_path / "ate-bin"
    spike = tmp_path / "spike"
    for d in (bin_dir, ate_dir, spike):
        d.mkdir(exist_ok=True)
    bodies = {"docker": DOCKER_STUB, "k3d": K3D_STUB, "kubectl": KUBECTL_STUB, "helm": HELM_STUB}
    for tool in ("k3d", "docker", "kubectl", "helm", "jq", "curl"):
        _exe(
            bin_dir / tool, bodies.get(tool, CURL_STUB if tool == "curl" else "#!/bin/sh\nexit 0\n")
        )
    if ate:
        _exe(ate_dir / "kubectl-ate", ATE_STUB)
    for name in ("install.sh", "gateway-install.sh", "a2a-smoke.sh"):
        _exe(spike / name, SPIKE_STUB)
    dotenv = tmp_path / "dotenv"
    if env_text is not None:
        dotenv.write_text(env_text)
    log = tmp_path / "calls.log"
    log.touch()
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "STUB_LOG": str(log),
        "ENV_FILE": str(dotenv),
        "ATE_BIN_DIR": str(ate_dir),
        "SPIKE_DIR": str(spike),
        **stub_env,
    }
    result = subprocess.run(
        ["make", "-s", *args], cwd=ROOT, env=env, capture_output=True, text=True
    )
    return result, log.read_text().splitlines()
