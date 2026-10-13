"""A fake `kagent` binary (a shell script) the sandbox tests put on PATH. Like the real
alpha9 CLI, `sandbox create` refuses to run without `--request-id`."""

FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
case "$*" in
  *"sandbox create"*"--request-id "*) echo '{"id":"sb-1","state":"RUNTIME_STATE_READY"}' ;;
  *"sandbox create"*) echo 'Error: required flag(s) "request-id" not set' >&2; exit 1 ;;
  *"sandbox exec"*) shift; while [ "$1" != "--" ]; do shift; done; shift; exec "$@" ;;
  *"sandbox delete"*) ;;
esac
"""
