# agents

Home for this part. Later tickets fill it.

## templates.yaml

One AgentTemplate per role of the default workflow "Threat report to campaign":
strategist, research, email writer, landing page writer, social writer, and one-pager
writer. The system prompt in each template is the role's prompt in
`apps/engine/ace_engine/agent_roles.py`, and a test keeps the two equal. Each of those templates uses
the `gateway-model` config, so every model call goes through agentgateway. That includes
`ace-brand-reviewer`: the seeded default workflow sets `review_rounds` on every writer, and the
worker sends those review calls to the reviewer Agent.

## agents.yaml

One Agent per template on the Go harness (`spike-harness`, installed by the S0 spike
scripts). `make up` applies both files. The Agent's name is the last part of its A2A URL,
`http://kagent-controller.kagent.svc.cluster.local:8083/agents/kagent/<name>`, and the worker
picks it by the role's template name.

At fast depth the scripted agent (`tests/harness/scripted_agent.py`) plays every role and
speaks the same A2A contract as kagent's controller.
