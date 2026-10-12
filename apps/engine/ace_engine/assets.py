"""Assets: what a writer step produced and an approver approves one by one.

Every agent step is an asset except the two that prepare the writers' work (strategy and
research). A saved workflow's own agent steps all write, so they are assets too."""

import uuid

from ace_engine import dag as graph

NOT_ASSETS = frozenset({"strategist", "research"})
EMAIL_PREVIEW = "preview"
# Asset step -> the brand-rendered preview route that shows it; the email's preview is the
# draft itself.
_RENDERED_PREVIEWS = {
    "landing_page": "preview/landing-page",
    "social": "preview/social",
    "design": "preview/cards",
    "one_pager": "preview/graphic",
}


def asset_steps(dag: graph.Dag) -> list[str]:
    """The step ids of the DAG's assets, in run order."""
    return [
        s["id"]
        for s in graph.ordered(dag)
        if s["kind"] == graph.AGENT and s["id"] not in NOT_ASSETS
    ]


def preview_path(campaign_id: uuid.UUID | str, step_id: str) -> str:
    """The API path that renders the asset."""
    return f"/campaigns/{campaign_id}/{_RENDERED_PREVIEWS.get(step_id, EMAIL_PREVIEW)}"
