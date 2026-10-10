# Draft for kagent-dev/kagent (or substrate): a slow-booting BYO agent never wakes

**Versions:** kagent 1.0.0-alpha9, Substrate 0.4.0-alpha1, k3s v1.37.1 (k3d v5.9.0, arm64).
`kagent-adk` image `ghcr.io/kagent-dev/kagent/kagent-adk@sha256:f60b442fc9f729a7441db2b0814105354c118d5b940cc55bce3ac8c9c1f02f28`.

**Actual:** a Python BYO session answers its first message. After it is suspended, the next
message never gets an answer. The actor sits in `ACTOR_STATE_RESUMING`; the controller answers
`KAGENT_SEND_NOT_ACCEPTED` ("retry after the session becomes available") forever. The worker
restores again every 6 s. Each attempt in the atelet log:
`Restore timing breakdown ... snapshot.scope=data snapshot.kind=latest error.type=Canceled ateom_restore=4.98`.
The Go harness wakes in 0.1 s with the same scope. kagent's README reports
`Fatal Python error: Illegal instruction` here; this stack shows a timeout instead and no crash text.

**Repro:**
```
kubectl --context <ctx> apply -f manifests/spike/python-byo.yaml      # Harness, AgentTemplate, Agent s22-py-agent
scripts/spike/python-wakeup.sh                                        # prints RESULT: crashed, exit 0
kubectl-ate --context <ctx> get actors -A                             # the session stays ACTOR_STATE_RESUMING
kubectl --context <ctx> logs -n ate-system <atelet pod> | grep "Restore timing"   # error.type=Canceled, ~4.98 s
```

**Cause (from the logs):** a wake restores only the data (`scope=data`) and cold-starts the
process. Substrate waits about 5 s for `/readyz`. The Python process needs longer to import, is
cancelled, and is started again from scratch, so it can never finish. Proof: the same agent
with a `/readyz` thread that answers before the imports
(`manifests/spike/python-byo-early-readyz.yaml`) wakes in 0.4 s, twice.

**Expected:** either keep the process (a `full` snapshot on suspend), or make the wake-up probe
timeout configurable per Harness, or fail the actor with the timeout in its status instead of
retrying forever (see draft 3).
