# Demo script: one campaign, from report to results

Length: about three and a half minutes spoken (roughly 525 words). The company is Acme Security, a
made-up firm. Every system you see besides the app is a stand-in we built.

Before you record: run `make seed-demo` against the stack you will film, sign in as
`dg-owner@demo.example`, and keep `docs/demo-report.txt` open to paste from. The password for
every demo user is in the README.

## Beat 1: the problem

On screen: the sign-in page, then the `Campaigns` list with Acme's past campaign.

Hello. I want to show you how a security company turns bad news into a marketing campaign in
minutes instead of weeks. This is Acme Security. When a new threat appears, the marketing team
has to explain it to customers fast, in an email and more. Today that takes a pile of meetings. Here, an AI helper writes the
first draft, and people stay in charge of every decision.

## Beat 2: paste the threat report

On screen: the `Threat report` box and the `Create campaign` button.

It starts with a threat report, the kind the security researchers already write. I paste it in.
This one is about fake delivery notices that steal staff passwords. I press create. That is the
only thing I do to start. There is no setup, no meeting, and no hand-off to another team.
The report goes in, and the run begins at once.

## Beat 3: the campaign runs

On screen: the `Run steps` list, then the `Run cost` box below it.

Now watch the run. The steps appear in order: the email draft, a judge, an approval, and
a publish step. Each one lights up as it finishes. Under the steps, the cost box lists what
each model step cost. The whole run costs cents, so a leader can see what each campaign costs before asking for
the next one. A team can type a spending limit in
the `Budget (USD)` box before it starts.

## Beat 4: a judge checks the work

On screen: the `Judge scores` list, then the `Email draft`.

Before a person sees anything, a judge helper scores the email against our written rules and
says why. Here it gives the email a five out of five and explains that it is clear,
accurate and calm. Below that is the email itself. It has a subject, a short body taken
from the report, and a call to action. Nothing in it is invented: it repeats what the
report said. The judge works before any person spends time reading, so the approver starts
with a draft that already passed a first check.

## Beat 5: a person approves

On screen: sign in as the approver, open the campaign, and click `Approve`. Then show the `Inbox`.

Now the human part. The status says the campaign is waiting for approval, and the person
who wrote the request has no approve button, which is how real teams run. I sign in as the
team's approver. The approval inbox shows the email, its judge score, and a note from the
brand reviewer saying nothing is flagged. The approver can approve, or reject with a
comment. I click approve. The status changes to sent, and a receipt appears, so there is
proof of what went out.

## Beat 6: results and learning

On screen: the `A/B result` line on the campaign, then the `Learnings` page and the `Dashboard`.

We send two versions of the email to different slices of the audience. After a while the
system counts opens and clicks and calls a winner, with a confidence level. The page
shows which version won. That result becomes a learning, in plain words, saved for the
team on the learnings page. An approver can delete a learning that looks wrong. The
dashboard lists the click rate for each campaign, so the team can see how results move
over time.

## Beat 7: why it matters

On screen: the `Campaigns` list for one team.

Two teams use the same system, Demand Gen and Product Marketing, and each sees only its own
campaigns. To recap: one threat report in, an email out, scored by a judge, approved by a
person, sent, measured, and remembered. If your team spends days turning threat news into customer messages, this shows a faster
way that keeps a person in charge. Thank you.
