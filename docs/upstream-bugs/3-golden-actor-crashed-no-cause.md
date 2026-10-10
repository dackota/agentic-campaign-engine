# Draft for kagent-dev/kagent: Agent status `GoldenActorCrashed` hides the cause

**Versions:** kagent 1.0.0-alpha9, Substrate 0.4.0-alpha1.

**Actual:** Agent `Ready=False`, reason `ActorTemplateFailed`, message
`GoldenActorCrashed: golden actor crashed before its snapshot was taken`. The real error
(see draft 2) is only in the worker pod's log, in the `RunWorkload` RPC response, and
nowhere in the Agent, Harness or controller output.

**Expected:** carry the first line of the ateom/atelet error into the condition message,
or point to the worker pod to read.
