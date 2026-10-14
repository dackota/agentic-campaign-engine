import type { Rejection } from "./builderApi";
import type { WorkflowStep } from "./workflow.gen";

export interface Problem {
  /** The step the message is about; null when it is about the whole workflow. */
  stepId: string | null;
  text: string;
}

const EMPTY_WORKFLOW = "Add at least one step";
const APPROVAL_FIRST = "An approval step needs a step before it";

const GENERAL = "Something is wrong with this workflow. Check each step.";
const WHOLE_WORKFLOW: Record<string, string> = {
  too_large: "This workflow is too big. Remove some steps.",
  not_json: "This workflow could not be read. Reload the page and try again.",
  dangling_edge: "A connection points to a step that is not there. Remove the steps around it and add them again.",
  cycle: "The steps loop back on themselves. Put each step after the steps it depends on.",
};

const quotedId = (message: string): string | null => /'([^']*)'/.exec(message)?.[1] ?? null;
const stepAtPath = (steps: WorkflowStep[], message: string): string | null => {
  const index = /^steps\.(\d+)/.exec(message)?.[1];
  return index === undefined ? null : (steps[Number(index)]?.id ?? null);
};

function shapeProblem(steps: WorkflowStep[], message: string): Problem {
  const stepId = stepAtPath(steps, message);
  return stepId === null
    ? { stepId, text: GENERAL }
    : { stepId, text: "Something is wrong with this step's settings. Check the numbers you entered." };
}

function problemOf(steps: WorkflowStep[], { rule, message }: Rejection): Problem {
  switch (rule) {
    case "unknown_step_kind":
      return {
        stepId: stepAtPath(steps, message),
        text: "This step has a type the builder does not know. Remove it and add one from the palette.",
      };
    case "invalid_shape":
      if (/^steps: \[\]/.test(message)) return { stepId: null, text: EMPTY_WORKFLOW };
      return shapeProblem(steps, message);
    case "duplicate_step_id":
      return { stepId: quotedId(message), text: "Two steps share a name. Remove one of them." };
    case "publish_without_approval":
      return {
        stepId: quotedId(message),
        text: "A publish step needs an approval step before it, so nothing goes out without a person's yes.",
      };
    case "publish_without_content":
      return {
        stepId: quotedId(message),
        text: "A publish step needs an AI step before it to write what it publishes.",
      };
    default:
      return {
        stepId: null,
        text: WHOLE_WORKFLOW[rule] ?? GENERAL,
      };
  }
}

/** Plain-word messages for the API's rejections, plus the checks the builder makes itself. */
export function problemsOf(steps: WorkflowStep[], rejections: Rejection[]): Problem[] {
  const own: Problem[] =
    steps[0]?.kind === "approval" ? [{ stepId: steps[0].id, text: APPROVAL_FIRST }] : [];
  return [...own, ...rejections.map((r) => problemOf(steps, r))];
}
