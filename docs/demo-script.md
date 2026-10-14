# Demo script: one campaign, from report to results

Length: about four minutes spoken (roughly 620 words). The audience is marketers and marketing
leaders, so every beat shows what a marketer does and sees, then says in one line what the
system does underneath. The company is Acme Security, a made-up firm. Every system you see
besides the app is a stand-in we built.

Before you record: run `make seed-demo` against the stack you will film, sign in as
`dg-owner@demo.example`, and keep `docs/demo-report.txt` open to paste from. The password for
every demo user is in the README. Record after the marketer-ready UI work (slice S15) lands, so
the screens look the way this script describes them.

## What each beat shows

| Beat | Capability it proves |
|---|---|
| 1 | Plain-language framing for marketing leadership |
| 2 | A web UI a non-technical marketer can use, sign-in and roles |
| 3 | The orchestration layer: agents in parallel, live status, recovery from a failure |
| 4 | Agents that use the marketing stack as tools; production tooling (email, page, one-pager, deck, social cards) |
| 5 | Quality scoring before any person reads a draft |
| 6 | The approval interface, permissions, and publishing to the marketing stack |
| 7 | Analytics: A/B results, the feedback loop, and the dashboard |
| 8 | Cost control, caching, and a backup model |
| 9 | The workflow builder: marketers change the process without an engineer |
| 10 | Many teams on one system; tests and alerts behind every change |

## Beat 1: the problem

On screen: the sign-in page, then the `Campaigns` list with Acme's past campaigns.

When a new threat appears, a security company has to tell its customers fast. Today one threat
report turns into a week of meetings, hand-offs, and copy-paste between tools. I built a system
that does the busy work in minutes and keeps people in charge of every decision. Let me show you
one campaign from start to finish.

## Beat 2: start a campaign

On screen: the `Threat report` box, the `Budget (USD)` box, and the `Create campaign` button.

I am a campaign owner on the Demand Gen team. I paste in a threat report from our researchers.
I can set a spending limit if I want one. I press create. That is the only thing I do to start.
No ticket, no setup, no waiting for another team.

## Beat 3: the team of helpers goes to work

On screen: the `Run steps` view as the steps light up, then `Retry step` on a step that failed.

Each box is an AI helper with one job. A strategist plans the campaign and a researcher checks
the facts. Then the email writer, the landing page writer, the social writer, and the designer
all work at the same time, so the whole campaign is ready in minutes. You see each step light up
as it happens. If a step fails, the rest of the work is kept, and one click tries that step
again.

## Beat 4: real assets, from your real tools

On screen: the `Email draft` and the asset previews in the `Approval inbox`.

The helpers do not guess. They read the team's own systems, like past campaigns, the content
library, and the audience lists, so they write from facts. They make the real assets: a ready
to send email, a landing page, a one-pager, a short deck, and social cards in brand colors.

## Beat 5: a judge checks the work first

On screen: the `Judge scores` next to each asset.

Before a person reads anything, a judge helper scores each asset against our written brand rules
and explains why. A brand reviewer flags risky claims, like promising one hundred percent
protection. So the approver starts from drafts that already passed a first check.

## Beat 6: a person approves, then it ships

On screen: sign in as the approver, open the `Approval inbox`, and click `Approve`.

The person who asked for the campaign cannot approve it. That is a real control, not a
reminder. The team's approver signs in, sees every asset with its score and flags, and approves
or sends it back with a comment. On approval, the system publishes the page, schedules the
email in the marketing tool, and posts a note to the team chat. There is a receipt for
everything that went out.

## Beat 7: results, and the system learns

On screen: the A/B result on the campaign, then `Learnings`, then the `Team dashboard`.

We sent two versions of the email. The system counts opens and clicks and names a winner with a
confidence level. That result becomes a learning in plain words, and the helpers read it on the
next campaign, so each campaign starts smarter than the last. The dashboard shows cost, quality,
and click rate for every campaign, and the trend over time.

## Beat 8: cost you can see and control

On screen: the `Run cost` box, then `Raise budget` on a paused campaign.

Every step shows what it cost. This whole campaign cost cents. Work that was already done is
reused, not paid for twice. If a campaign hits its limit, it pauses and asks, and the owner can
raise the budget. If one AI provider goes down, a backup takes over.

## Beat 9: change the process without an engineer

On screen: the `Workflow builder`, `Use template`, then drag a step and add an approval step from the `Step palette`.

Every team works a little differently. In the builder, a marketer starts from a template, drags
steps into a new order, and adds an approval gate where they want one. The builder says in plain
words if something is missing. Save it, and the next campaign runs the new way.

## Beat 10: built for many teams, and built to last

On screen: sign in as Product Marketing and show its own `Campaigns` list.

Product Marketing uses the same system and sees only its own campaigns, its own helpers, and its
own spending. Behind the scenes, every change is tested against a set of sample reports before
it ships, and alerts fire if quality drops. To recap: one report in, a full campaign out, judged,
approved by a person, published, measured, and remembered. Thank you.
