# Draft for kagent-dev/kagent: Harness `.status` is never populated

**Versions:** kagent 1.0.0-alpha9, Substrate 0.4.0-alpha1, k3s v1.37.1 (k3d v5.9.0, arm64).

**Repro:** apply a Harness (`runtime kagent`, golang-adk by digest) and an Agent that uses
it (manifests/spike/agent.yaml). Wait until the Agent is `Ready=True` and answers over A2A.
```
kubectl get harness spike-harness -n kagent
NAME            READY   AGE
spike-harness           7m
kubectl get harness spike-harness -n kagent -o json | jq .status
null
```
**Expected:** the CRD defines `status.conditions`, `status.capabilities`, `observedGeneration`
and a `Ready` printer column; the controller should set them.

**Note:** AgentTemplate has no status in its schema (likely by design), so only the Agent
reports readiness.
