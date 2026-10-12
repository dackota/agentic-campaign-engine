"""A fake `kagent` binary (a shell script) the sandbox tests put on PATH."""

FAKE = """#!/bin/sh
echo "$@" >> "$FAKE_LOG"
case "$*" in
  *"sandbox create"*) echo '{"id":"sb-1","state":"RUNTIME_STATE_READY"}' ;;
  *"sandbox exec"*) shift; while [ "$1" != "--" ]; do shift; done; shift; exec "$@" ;;
  *"sandbox delete"*) ;;
esac
"""
