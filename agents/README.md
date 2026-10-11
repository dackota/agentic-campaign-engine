# agents

Home for this part. Later tickets fill it.

## templates.yaml

One AgentTemplate per role of the default workflow "Threat report to campaign":
strategist, research, email writer, landing page writer, social writer, and one-pager
writer. At fast depth the scripted agent plays them all. The system prompt in each
template is the role's prompt in `apps/engine/ace_engine/agent_roles.py`, and a test keeps
the two equal. The model config name is the platform's; check it before the live run
(owed to the S3 live-depth ticket).
