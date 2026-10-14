import { useEffect, useState, type FormEvent } from "react";
import { listWorkflows } from "./api";
import { DEFAULT_WORKFLOW, dollarsOf, workflowLabel } from "./labels";

/** Short enough that the budget box and Create button show without scrolling at 720 px. */
const REPORT_ROWS = 7;
/** The built-in one-email pipeline: no saved workflow, so the API gets an empty name. */
const QUICK_DRAFT_LABEL = "Quick email draft";

interface NewCampaignFormProps {
  onCreate: (report: string, workflow: string, budgetUsd: number | null) => void;
}


/** The saved workflows by name; the standard one is chosen to start with. */
function WorkflowPicker({ value, onChange }: { value: string; onChange: (name: string) => void }) {
  const [workflows, setWorkflows] = useState([DEFAULT_WORKFLOW]);
  const [hasListError, setHasListError] = useState(false);

  useEffect(() => {
    listWorkflows()
      .then((names) => setWorkflows(names.includes(DEFAULT_WORKFLOW) ? names : [DEFAULT_WORKFLOW, ...names]))
      .catch((e: unknown) => {
        console.error("could not list saved workflows", e);
        setHasListError(true);
      });
  }, []);

  return (
    <>
      {/* The select sits beside its label, not inside: the label's text must stay "Workflow". */}
      <label htmlFor="workflow-picker">Workflow</label>
      <select id="workflow-picker" value={value} onChange={(e) => onChange(e.target.value)}>
        {workflows.map((name) => (
          <option key={name} value={name}>
            {workflowLabel(name)}
          </option>
        ))}
        <option value="">{QUICK_DRAFT_LABEL}</option>
      </select>
      {hasListError && <p>Could not load your saved workflows, so only the standard one is offered.</p>}
    </>
  );
}

/** The optional spend limit, with what it does in words. */
function BudgetField({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  return (
    <>
      <label>
        Budget (USD)
        <input
          type="number"
          min="0"
          step="any"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="no limit"
          aria-describedby="budget-hint"
        />
      </label>
      <p id="budget-hint" className="hint">
        Optional. The campaign pauses if it reaches this amount.
      </p>
    </>
  );
}

export function NewCampaignForm({ onCreate }: NewCampaignFormProps) {
  const [report, setReport] = useState("");
  const [workflow, setWorkflow] = useState(DEFAULT_WORKFLOW);
  const [budget, setBudget] = useState("");
  const hasReport = report.trim() !== "";

  function submit(event: FormEvent) {
    event.preventDefault();
    onCreate(report, workflow, dollarsOf(budget));
  }

  return (
    <>
      <h1>New campaign</h1>
      <form onSubmit={submit} className="new-campaign">
        <label>
          Threat report
          <textarea
            value={report}
            onChange={(e) => setReport(e.target.value)}
            rows={REPORT_ROWS}
            aria-describedby="report-hint"
          />
        </label>
        <p id="report-hint" className="hint">
          Paste the threat report or advisory. The first line becomes the campaign title.
        </p>
        <WorkflowPicker value={workflow} onChange={setWorkflow} />
        <BudgetField value={budget} onChange={setBudget} />
        <button
          type="submit"
          className="btn btn-primary"
          disabled={!hasReport}
          aria-describedby={hasReport ? undefined : "create-reason"}
        >
          Create campaign
        </button>
        {!hasReport && (
          <p id="create-reason" className="hint">
            Add your threat report to start the campaign.
          </p>
        )}
      </form>
    </>
  );
}
