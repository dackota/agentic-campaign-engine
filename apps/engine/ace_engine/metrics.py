"""The metrics the alert rules and dashboards read (manifests/observability/grafana).

Prometheus sees them as `ace_runs_total{outcome}`, `ace_cost_dollars_total`, and
`ace_eval_score_{sum,count,bucket}`. They are exported over OTLP when
`OTEL_EXPORTER_OTLP_ENDPOINT` is set (`telemetry.configure`); with it unset they cost almost
nothing. The eval score is the brand reviewer's verdict on a draft: 1 for a pass, 0 for a fix.
Scores from the evals suite record to the same histogram.
"""

from opentelemetry import metrics

_meter = metrics.get_meter("ace")
_runs = _meter.create_counter("ace.runs", description="Runs that ended, by outcome")
_cost = _meter.create_counter("ace.cost.dollars", description="Model cost of agent steps")
_eval_score = _meter.create_histogram("ace.eval.score", description="Eval score, 0 to 1")

PASS_SCORE = 1.0
FIX_SCORE = 0.0


def run_ended(outcome: str) -> None:
    """A run reached `outcome`: failed, sent, or finished."""
    _runs.add(1, {"outcome": outcome})


def step_cost(dollars: float, model: str) -> None:
    if dollars > 0:
        _cost.add(dollars, {"model": model})


def eval_score(score: float, source: str) -> None:
    _eval_score.record(score, {"source": source})
