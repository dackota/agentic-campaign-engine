# agents

Home for this part. Later tickets fill it.

## templates.yaml

One AgentTemplate per role of the default workflow "Threat report to campaign":
strategist, research, email writer, landing page writer, social writer, and one-pager
writer. The system prompt in each template is the role's prompt in
`apps/engine/ace_engine/agent_roles.py`, and a test keeps the two equal. Each of those templates uses
the `gateway-model` config, so every model call goes through agentgateway. The exception is
`ace-brand-reviewer`. The seeded default workflow sets `review_rounds` on every writer, so the
reviewer step runs. `agents.yaml` has no reviewer Agent, so at live depth the step posts to
`settings.agent_url`. The template stays on `mock-model` until a reviewer Agent is added (#85).

## agents.yaml

One Agent per template on the Go harness (`spike-harness`, installed by the S0 spike
scripts). `make up` applies both files. The Agent's name is the last part of its A2A URL,
`http://kagent-controller.kagent.svc.cluster.local:8083/agents/kagent/<name>`, and the worker
picks it by the role's template name.

At fast depth the scripted agent (`tests/harness/scripted_agent.py`) plays every role and
speaks the same A2A contract as kagent's controller.

## mcp.yaml

One `RemoteMCPServer` per read-only MCP server (`services/mcp`): Workfront, Marketo, the CMS,
and the asset library. `make up` applies it before `templates.yaml`. An AgentTemplate binds
only the tools it needs under `spec.tools`: the research agent binds the Workfront reads, no
other agent binds any. No agent has a write tool, and a test proves it.
