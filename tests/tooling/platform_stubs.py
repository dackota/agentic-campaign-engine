"""Stub docker and k3d programs shared by the platform tooling tests."""

DOCKER_STUB = """#!/bin/sh
echo "docker $*" >> "$STUB_LOG"
if { [ -n "$STUB_FAIL" ] && [ "$1" != info ]; } || [ "$STUB_DOCKER_FAIL" = "$1 $2" ]; then
  echo "docker: daemon unreachable" >&2; exit 1
fi
case "$1 $2" in
  "info --format") echo "${STUB_MEM_TOTAL:-25159827456}" ;;
  "stats --no-stream") echo "${STUB_MEM_USED:-3.54GiB / 23.4GiB}" ;;
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
    [ -n "$STUB_REGISTRY" ] && echo "k3d-ace-registry"
    echo "k3d-ace-registry-old" ;;
esac
exit 0
"""
