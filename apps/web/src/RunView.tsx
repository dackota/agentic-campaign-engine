import { useState, type FormEvent } from "react";
import {
  MAX_SCORE,
  previewUrl,
  type AssetScore,
  type Campaign,
  type CampaignCost,
  type EmailDraft,
  type Me,
  type RunEvent,
} from "./api";
import {
  abResultText,
  campaignTitle,
  costText,
  DEFAULT_WORKFLOW,
  dollarsOf,
  dollarsText,
  failureText,
  nextStepText,
  statusLabel,
  stepLabel,
  workflowLabel,
} from "./labels";
import { PreviewFrame } from "./PreviewFrame";
import { RunGraph } from "./RunGraphView";
import { Card, EmptyBlock, ErrorBlock, StatusBadge, STATUS_TONES } from "./ui";

/** What the run cost, in dollars and cents. */
function RunCost({ cost }: { cost: CampaignCost }) {
  return (
    <p>
      Cost: <span data-testid="run-cost">{dollarsText(cost.cost_usd)}</span>
    </p>
  );
}

/** Tokens and exact cost of each model step that ran, then the run's total. For engineers. */
function RunCostDetails({ cost }: { cost: CampaignCost }) {
  return (
    <section aria-label="Run cost details">
      <ul>
        {cost.steps.map((s) => (
          <li key={s.step}>
            {s.step}: <span data-testid={`step-cost-${s.step}`}>{costText(s)}</span>
          </li>
        ))}
      </ul>
      <p>
        Total: <span data-testid="run-tokens">{costText(cost)}</span>
      </p>
    </section>
  );
}

/** The judge's score and reason for each asset of the run. */
function RunScores({ scores }: { scores: AssetScore[] }) {
  if (scores.length === 0) return <EmptyBlock>No quality check yet.</EmptyBlock>;
  return (
    <section aria-label="Judge scores">
      <ul className="score-list">
        {scores.map((s) => (
          <li key={s.step}>
            {stepLabel(s.step)}: <strong data-testid={`judge-score-${s.step}`}>{`${s.score}/${MAX_SCORE}`}</strong>{" "}
            <span data-testid={`judge-reason-${s.step}`}>{s.reason}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function DraftView({ draft, id, showDetails }: { draft: EmailDraft; id: string; showDetails: boolean }) {
  return (
    <>
      <h3 data-testid="draft-subject">{draft.subject}</h3>
      <p className="hint">{draft.preheader}</p>
      <EmailPreview id={id} />
      {/* The raw text is for engineers; a marketer reads the rendered email above. */}
      {showDetails && <pre data-testid="draft-body">{draft.body}</pre>}
    </>
  );
}

/** Owners run campaigns, so they raise the budget of a paused one. The API enforces the same. */
function canRaiseBudget(me: Me, campaign: Campaign): boolean {
  return campaign.status === "budget_paused" && me.roles.includes("owner");
}

/** Owners run campaigns, so they retry the step that stopped one. The API enforces the same. */
function canRetry(me: Me, campaign: Campaign): boolean {
  return campaign.status === "failed" && me.roles.includes("owner");
}

/** Approvers approve; nobody approves a campaign they created. The API enforces the same. */
function canApprove(me: Me, campaign: Campaign): boolean {
  return (
    campaign.status === "awaiting_approval" &&
    me.roles.includes("approver") &&
    campaign.created_by !== me.subject
  );
}

interface EmailPreviewProps {
  id: string;
}

function EmailPreview({ id }: EmailPreviewProps) {
  return (
    <PreviewFrame title="Email preview" src={previewUrl(id)} isTall />
  );
}

interface RaiseBudgetFormProps {
  onRaise: (budgetUsd: number) => void;
}

function RaiseBudgetForm({ onRaise }: RaiseBudgetFormProps) {
  const [budget, setBudget] = useState("");

  function submit(event: FormEvent) {
    event.preventDefault();
    const dollars = dollarsOf(budget);
    if (dollars !== null) onRaise(dollars);
  }

  return (
    <form onSubmit={submit}>
      <label>
        New budget (USD)
        <input
          type="number"
          min="0"
          step="any"
          value={budget}
          onChange={(e) => setBudget(e.target.value)}
        />
      </label>
      <button type="submit" disabled={!budget.trim()}>
        Raise budget
      </button>
    </form>
  );
}

interface RunViewProps {
  me: Me;
  campaign: Campaign;
  events: RunEvent[];
  onApprove: (id: string) => void;
  onRetry: (id: string) => void;
  onRaiseBudget: (id: string, budgetUsd: number) => void;
}

/** The workflow the run pinned, by name; its raw id and the run id sit behind Details. */
function RunWorkflow({ campaign, showDetails }: { campaign: Campaign; showDetails: boolean }) {
  return (
    <>
      {campaign.workflow_version !== null && (
        <p>
          Workflow:{" "}
          <span data-testid="workflow-version">{`${workflowLabel(campaign.workflow ?? DEFAULT_WORKFLOW)} version ${campaign.workflow_version}`}</span>
        </p>
      )}
      {showDetails && <RunIds campaign={campaign} />}
    </>
  );
}

/** The raw ids an engineer needs to find the run in logs and the database. */
function RunIds({ campaign }: { campaign: Campaign }) {
  return (
    <p>
      Workflow id: <code data-testid="workflow-id">{campaign.workflow ?? DEFAULT_WORKFLOW}</code>, run id:{" "}
      <code>{campaign.id}</code>
    </p>
  );
}

function RunCards({ campaign, showDetails }: { campaign: Campaign; showDetails: boolean }) {
  return (
    <div className="card-grid">
      <Card label="Quality">
        <h2>Quality</h2>
        <RunScores scores={campaign.scores} />
      </Card>
      <Card label="Cost">
        <h2>Cost</h2>
        <RunCost cost={campaign.cost} />
        {campaign.budget_usd !== null && (
          <p>
            Budget: <span data-testid="run-budget">{dollarsText(campaign.budget_usd)}</span>
          </p>
        )}
        {showDetails && <RunCostDetails cost={campaign.cost} />}
      </Card>
      <div className="card-wide">
        <Card label="Draft">
          <h2>Draft</h2>
          {campaign.draft ? (
            <DraftView draft={campaign.draft} id={campaign.id} showDetails={showDetails} />
          ) : (
            <EmptyBlock>The draft appears here when the AI finishes writing it.</EmptyBlock>
          )}
        </Card>
      </div>
    </div>
  );
}

export function RunView({ me, campaign, events, onApprove, onRetry, onRaiseBudget }: RunViewProps) {
  const [showDetails, setShowDetails] = useState(false);
  return (
    <>
      <h1 className="page-title">{campaignTitle(campaign)}</h1>
      <p>
        <StatusBadge tone={STATUS_TONES[campaign.status]}>
          <span data-testid="run-status">{statusLabel(campaign.status)}</span>
        </StatusBadge>
      </p>
      <p className="next-step" data-testid="next-step">
        {nextStepText(campaign.status)}
      </p>
      {campaign.status === "failed" && <ErrorBlock>{failureText(campaign.failure_reason)}</ErrorBlock>}
      {campaign.status === "failed" && showDetails && <pre data-testid="failure-raw">{campaign.failure_reason}</pre>}
      <div className="action-row">
        {canRetry(me, campaign) && (
          <button type="button" className="btn btn-primary" onClick={() => onRetry(campaign.id)}>
            Retry step
          </button>
        )}
        {canRaiseBudget(me, campaign) && (
          <RaiseBudgetForm onRaise={(dollars) => onRaiseBudget(campaign.id, dollars)} />
        )}
        {canApprove(me, campaign) && (
          <button type="button" className="btn btn-primary" onClick={() => onApprove(campaign.id)}>
            Approve
          </button>
        )}
        <button type="button" aria-expanded={showDetails} onClick={() => setShowDetails(!showDetails)}>Details</button>
      </div>
      <RunGraph dag={campaign.steps} edges={campaign.edges} events={events} showDetails={showDetails} />
      <RunCards campaign={campaign} showDetails={showDetails} />
      {(campaign.status === "sent" || campaign.status === "finished") && (
        <p>
          A/B result: <span data-testid="ab-result">{abResultText(campaign.ab_result)}</span>
        </p>
      )}
      <RunWorkflow campaign={campaign} showDetails={showDetails} />
      {campaign.receipt && (
        <p>
          Receipt: <code data-testid="receipt">{campaign.receipt}</code>
        </p>
      )}
    </>
  );
}
