# Demo script: one campaign, from report to results

Length: about four minutes spoken (roughly 550 words). The company is Acme Security, a
made-up firm. Every system you see besides the app is a stand-in we built.

Before you record: run `make seed-demo` against the stack you will film, sign in as
`dg-owner@demo.example`, and keep `docs/demo-report.txt` open to paste from. The password for
every demo user is in the README.

## Beat 1: the problem

On screen: the sign-in page, then the `Campaigns` list with Acme's past campaign.

Hello. I want to show you how a security company turns bad news into a marketing campaign in
minutes instead of weeks. This is Acme Security. When a new threat appears, the marketing team
has to explain it to customers fast, in an email, a web page, a social post and a one page
summary. Today that takes a pile of meetings. Here, a team of AI helpers does the first draft,
and people stay in charge of every decision.

## Beat 2: paste the threat report

On screen: the `Threat report` box and the `Create campaign` button.

It starts with a threat report, the kind the security researchers already write. I paste it in.
This one is about fake delivery notices that steal staff passwords. I press create. That is the
only thing I do to start.

## Beat 3: the helpers get to work

On screen: the `Run steps` list filling in, and the `Run cost` box.

Now watch the steps light up. One helper plans the message. Another reads the report and
collects the facts, and every claim has to point back to the report, so nothing is made up.
Then separate helpers write the email, the landing page, the social post and the one page
summary, and a design helper makes the picture. On the right you can see what each step cost.
The whole thing costs cents, and a team can set a spending limit before it starts.

## Beat 4: a judge checks the work

On screen: the `Judge scores` list, then the `Email draft`.

Before a person sees anything, a judge helper scores the email against our written rules and
says why. A brand checker flags words we should not use. Anything that scores too low stops
the run, with the reason, instead of reaching a customer. Here is the email. The subject is
clear, the call to action is clear, and it sticks to what the report says.

## Beat 5: a person approves

On screen: sign in as the approver, open the campaign, and click `Approve`. Then show the `Inbox`.

Now the human part. I sign in as the team's approver. The person who wrote the request cannot
approve their own work, which is how real teams run. The approver gets an inbox with each
piece, its score, and any flags, and can approve or reject with a comment. I read the email,
I click approve, and the campaign goes out through the marketing system. A receipt appears so
there is proof of what was sent.

## Beat 6: results and learning

On screen: the `A/B result` line on the campaign, then the `Learnings` page and the `Dashboard`.

We always send two versions of the email to different slices of the audience. After a while the
system counts opens and clicks and calls a winner, with a confidence level. The page
shows which version won. That result becomes a learning, in plain words, saved for the
team. The next time a helper drafts for this team, it reads those learnings first. So the second campaign starts smarter
than the first. The dashboard shows the click rate climbing across campaigns, and an approver
can delete a learning that looks wrong.

## Beat 7: why it matters

On screen: the `Campaigns` list, with both teams' work kept apart.

Two teams use the same system, Demand Gen and Product Marketing, and neither can see the
other's work. To recap: one threat report in, a full set of campaign pieces out, checked by a
judge, approved by a person, sent, measured, and remembered. Thank you.
