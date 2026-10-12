# Decision: prompt caching stays with the provider; we keep the prompt prefix stable (S11)

Date: 2026-10-12. Status: accepted.

## Decision

Prompt caching is on, and it needs no engine setting. OpenCode Go caches by itself and asks
for a stable `x-opencode-session` header per conversation (`docs/sources.md`); the gateway
routes already set that header. The engine's part is the prompt: `message_for` puts the
role's fixed prompt first and the varying report last, so repeated calls share a long
prefix. A unit test (`tests/engine/test_step_cache.py`) keeps that order.

The engine does not add `cache_control` marks. The model in use (`glm-5.3-flash`) is served
on the chat-completions endpoint, and OpenCode's page documents no `cache_control` for it.

## Measured effect (live, k3d-ace, 2026-10-12)

`scripts/measure_prompt_cache.py` sends the email writer Agent long prompts (about 5,800
input tokens) over A2A, through kagent and agentgateway to OpenCode Go (`glm-5.3-flash`), and
reads the token counts from the gateway's access log
(`gen_ai.usage.cache_read.input_tokens`). Three prompts that share no prefix, then one
prompt sent four times:

| Group | Input tokens | Served from cache |
|---|---|---|
| 3 unique prompts | 5,995 / 5,755 / 5,995 | 0 / 0 / 0 |
| same prompt, 1st send | 5,755 | 0 |
| same prompt, 2nd to 4th send | 5,755 each | 5,440 each (94.5%) |

An earlier two-call probe of a 3,115-token prompt read 2,176 cached tokens (70%) on the
second call. The first send fills the cache; every send after it reads about 94% of the
prompt from it. Time to first token did not improve in a way these few calls can show
(0.76 to 1.70 s cold, 0.92 to 1.70 s repeated), so no latency gain is claimed.

## Consequences

- The cost ledger cannot show the saving. kagent's A2A reply reports `promptTokenCount`,
  `candidatesTokenCount` and `totalTokenCount` only, with no cached count, so the ledger
  books every input token at the list price, as the token-usage ADR says. The budget caps
  use; it is not a copy of the bill. The gateway log and its trace attribute
  `gen_ai.usage.cache_read.input_tokens` are where cached tokens show.
- Caching helps only calls that share a prefix and a session id. Two agents with different
  prompts do not share it; a fix round to the same writer session does.
- The saving on a repeated *step* comes from the step cache
  (`docs/decisions/step-cache.md`), which skips the call altogether.
